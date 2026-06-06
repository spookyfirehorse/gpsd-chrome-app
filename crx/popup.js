async function updatePopup() {
    try {
        const res = await chrome.runtime.sendMessage({type: "GET_LAST_GPS"});

        if (res) {
            document.getElementById('no-data').style.display = 'none';
            document.getElementById('gps-grid').style.display = 'grid';

            const lat = res.location?.lat || res.lat || 0;
            const lng = res.location?.lng || res.lng || 0;
            const alt = res.location?.alt || res.altitude || res.alt || 0;
            const head = res.location?.heading || res.heading || 0;

            // Da das Python-Skript im Feld 'speed' bereits km/h liefert,
            // lesen wir den Wert hier direkt ohne erneute Multiplikation aus!
            const speedKmh = res.speed || res.location?.speed || 0;

            // HTML Felder füllen
            document.getElementById('lat').innerText = lat.toFixed(5);
            document.getElementById('lng').innerText = lng.toFixed(5);
            document.getElementById('alt').innerText = alt.toFixed(1) + " m";
            document.getElementById('head').innerText = head.toFixed(1) + "°";
            document.getElementById('speed').innerText = speedKmh.toFixed(1) + " km/h";
        }
    } catch(e) {
        console.error("Popup Error:", e);
    }
}

setInterval(updatePopup, 1000);
updatePopup();
