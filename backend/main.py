import asyncio
import logging
import os
import time
from datetime import date

import google.genai as genai
import psycopg2
import psycopg2.extras
import stripe
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request, Header
from pydantic import BaseModel, field_validator
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

load_dotenv()

# ──────────────────────────────────────────────
#  Arranque: validar variables de entorno
# ──────────────────────────────────────────────

_REQUIRED = ["GEMINI_API_KEY", "DATABASE_URL", "STRIPE_SECRET_KEY", "STRIPE_WEBHOOK_SECRET"]
_missing  = [v for v in _REQUIRED if not os.getenv(v)]
if _missing:
    raise RuntimeError(f"Variables de entorno faltantes: {', '.join(_missing)}")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)
log = logging.getLogger("prowrite")

# ──────────────────────────────────────────────
#  Constantes
# ──────────────────────────────────────────────

FREE_LIMIT        = 10
MAX_TEXT_FREE     = 5_000    # caracteres máx para plan Free
MAX_TEXT_PRO      = 20_000   # caracteres máx para plan Pro
MODELOS_FALLBACK  = ["gemini-2.5-flash", "gemini-2.0-flash", "gemini-1.5-flash"]

stripe.api_key        = os.getenv("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")

# ──────────────────────────────────────────────
#  CORS manual (sin depender de fastapi.middleware.cors)
# ──────────────────────────────────────────────

_CORS_HEADERS = {
    "Access-Control-Allow-Origin":  "*",
    "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type, Authorization, X-Requested-With",
    "Access-Control-Max-Age":       "86400",
}


class CORSMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method == "OPTIONS":
            return Response(headers=_CORS_HEADERS)
        response = await call_next(request)
        response.headers.update(_CORS_HEADERS)
        return response


# ──────────────────────────────────────────────
#  App
# ──────────────────────────────────────────────

limiter = Limiter(key_func=get_remote_address)
app = FastAPI(title="ProWrite API", version="1.2.0")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(CORSMiddleware)

# ──────────────────────────────────────────────
#  Base de datos (PostgreSQL)
# ──────────────────────────────────────────────

def get_db() -> psycopg2.extensions.connection:
    return psycopg2.connect(
        os.getenv("DATABASE_URL"),
        cursor_factory=psycopg2.extras.RealDictCursor,
    )


def init_db() -> None:
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id           TEXT PRIMARY KEY,
            is_pro            INTEGER NOT NULL DEFAULT 0,
            stripe_customer_id TEXT,
            created_at        TIMESTAMP DEFAULT NOW()
        );
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS usage (
            user_id TEXT    NOT NULL,
            day     TEXT    NOT NULL,
            count   INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (user_id, day)
        );
    """)
    conn.commit()
    cur.close()
    conn.close()
    log.info("Base de datos inicializada.")


init_db()

# ──────────────────────────────────────────────
#  Helpers BD
# ──────────────────────────────────────────────

def ensure_user(user_id: str, conn) -> None:
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO users (user_id) VALUES (%s) ON CONFLICT (user_id) DO NOTHING",
        (user_id,),
    )
    conn.commit()
    cur.close()


def get_usage_today(user_id: str, conn) -> int:
    today = str(date.today())
    cur   = conn.cursor()
    cur.execute(
        "SELECT count FROM usage WHERE user_id = %s AND day = %s",
        (user_id, today),
    )
    row = cur.fetchone()
    cur.close()
    return row["count"] if row else 0


def increment_usage(user_id: str, conn) -> None:
    today = str(date.today())
    cur   = conn.cursor()
    cur.execute(
        """
        INSERT INTO usage (user_id, day, count) VALUES (%s, %s, 1)
        ON CONFLICT (user_id, day) DO UPDATE SET count = usage.count + 1
        """,
        (user_id, today),
    )
    conn.commit()
    cur.close()


def is_pro(user_id: str, conn) -> bool:
    cur = conn.cursor()
    cur.execute("SELECT is_pro FROM users WHERE user_id = %s", (user_id,))
    row = cur.fetchone()
    cur.close()
    return bool(row["is_pro"]) if row else False


def _set_pro(user_id: str, value: int, customer_id: str | None, conn) -> None:
    cur = conn.cursor()
    if customer_id:
        cur.execute(
            "UPDATE users SET is_pro = %s, stripe_customer_id = %s WHERE user_id = %s",
            (value, customer_id, user_id),
        )
    else:
        cur.execute("UPDATE users SET is_pro = %s WHERE user_id = %s", (value, user_id))
    conn.commit()
    cur.close()


def _set_pro_by_customer(customer_id: str, value: int, conn) -> None:
    cur = conn.cursor()
    cur.execute(
        "UPDATE users SET is_pro = %s WHERE stripe_customer_id = %s",
        (value, customer_id),
    )
    conn.commit()
    cur.close()


# ──────────────────────────────────────────────
#  Schemas
# ──────────────────────────────────────────────

IDIOMAS = {
    "es": "Spanish",  "en": "English",  "fr": "French",
    "de": "German",   "pt": "Portuguese", "it": "Italian",
    "nl": "Dutch",    "pl": "Polish",   "ru": "Russian",
    "ja": "Japanese", "zh": "Chinese",  "ar": "Arabic",
}

TONE_MAP = {
    "Formal":      "formal and professional",
    "Directo":     "direct and concise",
    "Direct":      "direct and concise",
    "Persuasivo":  "persuasive and convincing",
    "Persuasive":  "persuasive and convincing",
    "Amigable":    "friendly and approachable",
    "Friendly":    "friendly and approachable",
}


class ImproveRequest(BaseModel):
    user_id:  str
    text:     str
    tone:     str
    language: str = "es"

    @field_validator("user_id")
    @classmethod
    def validate_user_id(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("user_id no puede estar vacío")
        if len(v) > 128:
            raise ValueError("user_id demasiado largo")
        return v

    @field_validator("text")
    @classmethod
    def validate_text(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("El texto no puede estar vacío")
        return v

    @field_validator("tone")
    @classmethod
    def validate_tone(cls, v: str) -> str:
        if v not in TONE_MAP:
            return "Formal"
        return v

    @field_validator("language")
    @classmethod
    def validate_language(cls, v: str) -> str:
        return v if v in IDIOMAS else "en"


# ──────────────────────────────────────────────
#  Endpoints
# ──────────────────────────────────────────────

@app.get("/")
async def health():
    """Health check para Render / Railway."""
    return {"status": "ok", "version": app.version}


@app.get("/health")
async def health_detailed():
    return {"status": "ok", "version": app.version, "time": time.time()}


@app.post("/improve")
@limiter.limit("30/minute")
async def improve_text(request: Request, body: ImproveRequest):
    conn = get_db()
    try:
        ensure_user(body.user_id, conn)

        pro   = is_pro(body.user_id, conn)
        usage = get_usage_today(body.user_id, conn)

        if not pro and usage >= FREE_LIMIT:
            raise HTTPException(
                status_code=429,
                detail="Límite diario alcanzado. Hazte Pro para usos ilimitados.",
            )

        # Validar longitud de texto según plan
        max_chars = MAX_TEXT_PRO if pro else MAX_TEXT_FREE
        if len(body.text) > max_chars:
            raise HTTPException(
                status_code=400,
                detail=f"Texto demasiado largo. Máximo {max_chars:,} caracteres para tu plan.",
            )

        lang_name = IDIOMAS.get(body.language, "English")
        tone_en   = TONE_MAP.get(body.tone, "clear and professional")

        client_genai = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
        prompt = (
            f"Improve the following text in {lang_name} with a {tone_en} tone. "
            f"Return ONLY the improved text with no explanations, comments, or formatting markers.\n\n"
            f"Original text:\n{body.text}"
        )

        def _llamar_gemini() -> str | None:
            for modelo in MODELOS_FALLBACK:
                for intento in range(3):
                    try:
                        resp = client_genai.models.generate_content(
                            model=modelo, contents=prompt
                        )
                        return resp.text
                    except Exception as exc:
                        if any(k in str(exc) for k in ("503", "UNAVAILABLE", "429")):
                            time.sleep(2 ** intento)
                            continue
                        log.error("Gemini %s intento %d: %s", modelo, intento, exc)
                        raise
            return None

        improved = await asyncio.get_running_loop().run_in_executor(None, _llamar_gemini)

        if not improved:
            raise HTTPException(
                status_code=503,
                detail="Servicio de IA no disponible. Inténtalo en unos segundos.",
            )

        increment_usage(body.user_id, conn)
        remaining = FREE_LIMIT - (usage + 1) if not pro else -1
        log.info("Mejora OK user=%s lang=%s tone=%s remaining=%s", body.user_id[:8], body.language, body.tone, remaining)
        return {"improved_text": improved, "remaining": remaining, "is_pro": pro}

    finally:
        conn.close()


@app.get("/usage/{user_id}")
async def get_usage(user_id: str):
    if not user_id.strip():
        raise HTTPException(status_code=400, detail="user_id inválido")
    conn = get_db()
    try:
        ensure_user(user_id, conn)
        usage     = get_usage_today(user_id, conn)
        pro       = is_pro(user_id, conn)
        remaining = -1 if pro else max(0, FREE_LIMIT - usage)
        return {"user_id": user_id, "remaining": remaining, "is_pro": pro, "used_today": usage}
    finally:
        conn.close()


@app.get("/languages")
async def list_languages():
    """Devuelve los idiomas soportados."""
    return {"languages": IDIOMAS}


@app.post("/stripe/webhook")
async def stripe_webhook(request: Request, stripe_signature: str = Header(None)):
    payload = await request.body()
    try:
        event = stripe.Webhook.construct_event(
            payload, stripe_signature, STRIPE_WEBHOOK_SECRET
        )
    except (stripe.error.SignatureVerificationError, stripe.SignatureVerificationError):
        log.warning("Firma de webhook de Stripe inválida")
        raise HTTPException(status_code=400, detail="Firma de webhook inválida")

    ev_type = event["type"]
    log.info("Stripe webhook: %s", ev_type)

    if ev_type == "checkout.session.completed":
        session     = event["data"]["object"]
        user_id     = session.get("client_reference_id") or session.get("metadata", {}).get("user_id")
        customer_id = session.get("customer")
        if user_id:
            conn = get_db()
            try:
                ensure_user(user_id, conn)
                _set_pro(user_id, 1, customer_id, conn)
                log.info("Usuario %s actualizado a Pro (checkout)", user_id[:8])
            finally:
                conn.close()

    elif ev_type in (
        "customer.subscription.deleted",
        "customer.subscription.paused",
    ):
        customer_id = event["data"]["object"].get("customer")
        if customer_id:
            conn = get_db()
            try:
                _set_pro_by_customer(customer_id, 0, conn)
                log.info("Suscripción cancelada/pausada customer=%s", customer_id)
            finally:
                conn.close()

    elif ev_type == "customer.subscription.updated":
        sub         = event["data"]["object"]
        customer_id = sub.get("customer")
        status      = sub.get("status")
        if customer_id and status:
            is_active = status in ("active", "trialing")
            conn = get_db()
            try:
                _set_pro_by_customer(customer_id, 1 if is_active else 0, conn)
                log.info("Suscripción actualizada customer=%s status=%s", customer_id, status)
            finally:
                conn.close()

    elif ev_type == "invoice.payment_failed":
        customer_id = event["data"]["object"].get("customer")
        if customer_id:
            log.warning("Pago fallido para customer=%s", customer_id)

    return {"status": "ok"}
