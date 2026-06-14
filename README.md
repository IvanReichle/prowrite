# ✨ ProWrite AI

> Mejora cualquier texto con IA en segundos — extensión de Chrome + API en producción.

ProWrite es una herramienta de mejora de texto impulsada por **Gemini AI**. Consta de un backend FastAPI desplegado en Render y una extensión de Chrome (v1) con popup integrado y soporte de pagos Pro vía Stripe.

---

## 🚀 Demo en producción

- **API:** `https://prowrite-backend-ds5o.onrender.com`
- **Extensión Chrome v2 (con botón flotante):** [prowrite-extension](https://github.com/IvanReichle/prowrite-extension)

---

## 🏗️ Arquitectura

```
prowrite/
├── backend/
│   ├── main.py           # FastAPI — endpoints, Stripe webhooks, Gemini AI
│   └── requirements.txt  # Dependencias Python
├── extension/            # Extensión Chrome v1 (popup)
│   ├── manifest.json
│   ├── popup.html
│   ├── popup.js
│   ├── popup.css
│   └── background.js
└── vercel.json           # Configuración de deploy
```

---

## 🔌 API — Endpoints

| Método | Ruta | Descripción |
|--------|------|-------------|
| `GET` | `/` | Health check |
| `GET` | `/health` | Health check con timestamp |
| `POST` | `/improve` | Mejorar texto con IA |
| `GET` | `/usage/{user_id}` | Consultar uso diario |
| `GET` | `/languages` | Idiomas soportados |
| `POST` | `/stripe/webhook` | Webhook de pagos Stripe |

### POST `/improve` — Body

```json
{
  "user_id": "uuid",
  "text": "texto a mejorar",
  "tone": "Formal",
  "language": "es"
}
```

**Tonos disponibles:** `Formal`, `Direct`, `Persuasive`, `Friendly`

**Idiomas:** `es`, `en`, `fr`, `de`, `pt`, `it`, `nl`, `pl`, `ru`, `ja`, `zh`, `ar`

### Respuesta

```json
{
  "improved_text": "...",
  "remaining": 7,
  "is_pro": false
}
```

> `remaining: -1` indica plan Pro (ilimitado).

---

## 🤖 Gemini AI — Fallback chain

El backend intenta los modelos en orden hasta obtener respuesta:

1. `gemini-2.5-flash`
2. `gemini-2.0-flash`
3. `gemini-1.5-flash`

Con reintentos exponenciales ante errores 503/429.

---

## 💳 Planes

| Plan | Límite diario | Caracteres máx. |
|------|--------------|-----------------|
| Free | 10 mejoras/día | 5.000 caracteres |
| Pro | Ilimitado | 20.000 caracteres |

Los usuarios Pro se gestionan automáticamente via webhooks de Stripe:
- `checkout.session.completed` → activa Pro
- `customer.subscription.updated` → sincroniza estado
- `customer.subscription.deleted/paused` → desactiva Pro

---

## 🛠️ Tecnologías

- **FastAPI 0.115** + **Uvicorn** — servidor ASGI
- **Pydantic v2** — validación con `@field_validator`
- **google-genai 2.8** — SDK oficial de Gemini
- **psycopg2** — PostgreSQL con `RealDictCursor`
- **slowapi** — rate limiting (30 req/min por IP)
- **Stripe 11** — pagos y suscripciones
- **python-dotenv** — gestión de variables de entorno

---

## ⚙️ Variables de entorno

```env
GEMINI_API_KEY=...
DATABASE_URL=postgresql://...
STRIPE_SECRET_KEY=sk_...
STRIPE_WEBHOOK_SECRET=whsec_...
```

---

## 🚀 Instalación local

```bash
git clone https://github.com/IvanReichle/prowrite.git
cd prowrite/backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
# Crea .env con las variables de arriba
uvicorn main:app --reload
```

---

## 🌐 Despliegue en Render

1. Conecta el repositorio en [render.com](https://render.com)
2. Tipo: **Web Service** — Python
3. Build: `pip install -r backend/requirements.txt`
4. Start: `uvicorn backend.main:app --host 0.0.0.0 --port $PORT`
5. Añade las variables de entorno en el dashboard

---

## 📦 Extensión Chrome v1

La carpeta `extension/` contiene la versión 1 del popup. Para instalarla en Chrome:

1. Abre `chrome://extensions/`
2. Activa **Modo desarrollador**
3. Clic en **Cargar sin empaquetar** → selecciona `extension/`

> Para la versión completa con botón flotante en toda página, usa [prowrite-extension](https://github.com/IvanReichle/prowrite-extension).
