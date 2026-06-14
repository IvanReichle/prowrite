// ── Configuración ──────────────────────────────────────────────────────────
const API_BASE = "https://prowrite-backend-ds5o.onrender.com";
const STRIPE_PAYMENT_LINK = "https://buy.stripe.com/5kQ00lgN54ENfxidNQa3u00";

// ── Estado ─────────────────────────────────────────────────────────────────
let selectedTone = "Formal";
let userId = null;

// ── Elementos del DOM ──────────────────────────────────────────────────────
const inputText    = document.getElementById("inputText");
const improveBtn   = document.getElementById("improveBtn");
const btnText      = document.getElementById("btnText");
const btnLoader    = document.getElementById("btnLoader");
const outputSection = document.getElementById("outputSection");
const outputText   = document.getElementById("outputText");
const copyBtn      = document.getElementById("copyBtn");
const errorMsg     = document.getElementById("errorMsg");
const usageText    = document.getElementById("usageText");
const proBanner    = document.getElementById("proBanner");
const proBtn       = document.getElementById("proBtn");

// ── Inicialización ─────────────────────────────────────────────────────────
async function init() {
  const stored = await chrome.storage.local.get("user_id");
  if (stored.user_id) {
    userId = stored.user_id;
  } else {
    userId = crypto.randomUUID();
    await chrome.storage.local.set({ user_id: userId });
  }
  await refreshUsage();
}

async function refreshUsage() {
  try {
    const res = await fetch(`${API_BASE}/usage/${userId}`);
    if (!res.ok) throw new Error();
    const data = await res.json();
    updateUsageBadge(data);
  } catch {
    usageText.textContent = "Sin conexión";
  }
}

function updateUsageBadge(data) {
  if (data.is_pro) {
    usageText.textContent = "⚡ Pro — Ilimitado";
    proBanner.style.display = "none";
  } else {
    const rem = data.remaining;
    usageText.textContent = `${rem}/10 usos hoy`;
    proBanner.style.display = rem === 0 ? "flex" : "none";
  }
}

// ── Selector de tono ───────────────────────────────────────────────────────
document.querySelectorAll(".tone-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tone-btn").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    selectedTone = btn.dataset.tone;
  });
});

// ── Mejorar texto ──────────────────────────────────────────────────────────
improveBtn.addEventListener("click", async () => {
  const text = inputText.value.trim();
  if (!text) { showError("Por favor escribe o pega un texto."); return; }

  setLoading(true);
  hideError();
  outputSection.style.display = "none";

  try {
    const response = await chrome.runtime.sendMessage({
        action: "improve",
        data: { user_id: userId, text: text, tone: selectedTone }
    });
    
    if (response.error) {
        showError(response.error);
        return;
    }
    
    const data = response.data;

    outputText.textContent = data.improved_text;  
    outputSection.style.display = "flex";
    updateUsageBadge(data);

  } catch (err) {
    showError("No se pudo conectar al servidor. ¿Está el backend corriendo?");
  } finally {
    setLoading(false);
  }
});

// ── Copiar resultado ───────────────────────────────────────────────────────
copyBtn.addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(outputText.textContent);
    copyBtn.textContent = "✓ Copiado";
    setTimeout(() => (copyBtn.textContent = "Copiar"), 1500);
  } catch {
    copyBtn.textContent = "Error";
  }
});

// ── Botón Pro ──────────────────────────────────────────────────────────────
proBtn.addEventListener("click", () => {
  chrome.tabs.create({ url: `${STRIPE_PAYMENT_LINK}?client_reference_id=${userId}` });
});

// ── Helpers ────────────────────────────────────────────────────────────────
function setLoading(state) {
  improveBtn.disabled = state;
  btnText.classList.toggle("hidden", state);
  btnLoader.classList.toggle("hidden", !state);
}

function showError(msg) {
  errorMsg.textContent = msg;
  errorMsg.classList.remove("hidden");
}

function hideError() {
  errorMsg.classList.add("hidden");
}

// ── Arranque ───────────────────────────────────────────────────────────────
init();
