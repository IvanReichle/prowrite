const API_BASE = "https://prowrite-backend-ds5o.onrender.com";

chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    if (message.action === "improve") {
        fetch(`${API_BASE}/improve`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(message.data),
        })
        .then(async res => {
            const body = await res.json().catch(() => ({}));
            if (!res.ok) {
                sendResponse({ error: body.detail || `Error ${res.status}` });
            } else {
                sendResponse({ data: body });
            }
        })
        .catch(() => sendResponse({ error: "No se pudo conectar al servidor. Comprueba tu conexión." }));
        return true;
    }

    if (message.action === "usage") {
        fetch(`${API_BASE}/usage/${encodeURIComponent(message.userId)}`)
        .then(async res => {
            const body = await res.json().catch(() => ({}));
            sendResponse(res.ok ? body : { error: body.detail || `Error ${res.status}` });
        })
        .catch(() => sendResponse({ error: "Sin conexión" }));
        return true;
    }
});