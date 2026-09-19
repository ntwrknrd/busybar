// BUSY Bar 1.2.4 / JerryScript. No browser, Node, or host process required.
const APP_ID = "app.ntwrknrd.weather";
const CACHE_KEY = "forecast-v1";
const REFRESH_MS = 15 * 60 * 1000;
// Explicit prototype tradeoff: 1.2.4 fails this provider's TLS handshake.
// Only public, fixed-location weather is requested; no credentials are sent.
const WEATHER_URL = "http://api.open-meteo.com/v1/forecast" +
    "?latitude=39.7684&longitude=-86.1581" +
    "&current=temperature_2m,weather_code" +
    "&daily=temperature_2m_max,temperature_2m_min" +
    "&temperature_unit=fahrenheit&forecast_days=1" +
    "&timezone=America%2FIndiana%2FIndianapolis";

let reading = null;
let stale = true;
let refreshing = false;
let drawing = false;
let nextRefresh = 0;

function validReading(value) {
    return value && [value.temperature, value.code, value.high, value.low,
        value.fetchedAt].every(function (n) {
        return typeof n === "number" && isFinite(n);
    }) && value.fetchedAt > 0;
}

function conditions(code) {
    if (code === 0) return "CLEAR";
    if (code === 1 || code === 2) return "PT CLOUD";
    if (code === 3) return "CLOUDY";
    if (code === 45 || code === 48) return "FOG";
    if (code >= 51 && code <= 57) return "DRIZZLE";
    if ((code >= 61 && code <= 67) || (code >= 80 && code <= 82)) return "RAIN";
    if ((code >= 71 && code <= 77) || code === 85 || code === 86) return "SNOW";
    if (code >= 95 && code <= 99) return "STORM";
    return "UNKNOWN";
}

function draw() {
    if (drawing) return;
    const now = Date.now();
    const old = stale || !reading || now < reading.fetchedAt ||
        now - reading.fetchedAt >= REFRESH_MS;
    const top = reading ? Math.round(reading.temperature) + "F " +
        conditions(reading.code) : "INDY WEATHER";
    const bottom = reading ? "H" + Math.round(reading.high) + " L" +
        Math.round(reading.low) + (old ? " OLD" : "") : "WAITING FOR WIFI";
    const color = old ? "#FFD43BFF" : "#FFFFFFFF";
    drawing = true;
    fetch("http://127.0.0.1/api/display/draw", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
            application_name: APP_ID,
            priority: 50,
            elements: [
                {id: "current", type: "text", x: 0, y: 1, font: "tiny",
                    text: top, color: color, timeout: 10},
                {id: "range", type: "text", x: 0, y: 9, font: "tiny",
                    text: bottom, color: color, timeout: 10}
            ]
        })
    }).then(function (response) {
        return response.json();
    }).then(function (body) {
        if (body.result !== "OK") console.error("Weather display unavailable");
        drawing = false;
    }).catch(function (error) {
        drawing = false;
        console.error("Weather display request failed: " + error);
    });
}

function refresh() {
    if (refreshing) return;
    refreshing = true;
    fetch(WEATHER_URL).then(function (response) {
        // Firmware 1.2.4 does not expose Response.ok or Response.status.
        return response.json();
    }).then(function (body) {
        const candidate = {
            temperature: body.current.temperature_2m,
            code: body.current.weather_code,
            high: body.daily.temperature_2m_max[0],
            low: body.daily.temperature_2m_min[0],
            fetchedAt: Date.now()
        };
        if (!validReading(candidate)) throw new Error("Invalid forecast");
        reading = candidate;
        stale = false;
        try {
            localStorage.setItem(CACHE_KEY, JSON.stringify(reading));
        } catch (_) {
            console.error("Weather cache write failed");
        }
        console.info("Weather refreshed");
    }).catch(function (error) {
        stale = true;
        console.error("Weather refresh failed; retaining cache: " + error);
    }).then(function () {
        refreshing = false;
        nextRefresh = Date.now() + (stale ? 60000 : REFRESH_MS);
        draw();
    });
}

try {
    const cached = JSON.parse(localStorage.getItem(CACHE_KEY));
    if (validReading(cached)) reading = cached;
} catch (_) {
    console.error("Weather cache unavailable");
}

draw();
refresh();
setInterval(function () {
    if (Date.now() >= nextRefresh) refresh();
    draw();
}, 5000);
