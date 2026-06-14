chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    if (message.action === "improve") {
        fetch("https://prowrite-backend-ds5o.onrender.com/improve", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(message.data)
        })
        .then(res => res.json())
        .then(data => sendResponse({ data }))
        .catch(err => sendResponse({ error: "No se pudo conectar al servidor." }));
        return true;
    }
});