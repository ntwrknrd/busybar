// BUSY Bar 1.2.4 / JerryScript. No browser, Node, or host process required.
const APP_ID = "app.ntwrknrd.weather";
const CACHE_KEY = "forecast-v4-46032";
const REFRESH_MS = 15 * 60 * 1000;
const SOURCE_MAX_AGE_MS = 30 * 60 * 1000;
// Explicit prototype tradeoff: 1.2.4 fails this provider's TLS handshake.
// Only public, fixed-location weather is requested; no credentials are sent.
const WEATHER_URL = "http://api.open-meteo.com/v1/forecast" +
    "?latitude=39.9712&longitude=-86.1245" +
    "&current=temperature_2m,weather_code,is_day,wind_speed_10m,relative_humidity_2m" +
    "&minutely_15=precipitation&forecast_minutely_15=98" +
    "&daily=temperature_2m_max,temperature_2m_min,precipitation_probability_max,precipitation_sum" +
    "&temperature_unit=fahrenheit&wind_speed_unit=mph&precipitation_unit=inch&forecast_days=1&timeformat=unixtime" +
    "&timezone=America%2FIndiana%2FIndianapolis";

let reading = null;
let stale = true;
let refreshing = false;
let drawing = false;
let nextRefresh = 0;
const startedAt = Date.now();

function validReading(value) {
    return value && value.zip === "46032" && validPrecipSeries(value) &&
        [value.temperature, value.code, value.high, value.low,
        value.fetchedAt, value.sourceTime, value.dayTime, value.utcOffset,
        value.isDay, value.wind, value.humidity, value.precipChance, value.precipTotal].every(function (n) {
        return typeof n === "number" && isFinite(n);
    }) && value.fetchedAt > 0 && value.sourceTime > 0 && value.dayTime > 0 &&
        value.wind >= 0 && value.humidity >= 0 && value.humidity <= 100 &&
        value.precipChance >= 0 && value.precipChance <= 100 && value.precipTotal >= 0 &&
        value.low <= value.high && (value.isDay === 0 || value.isDay === 1);
}

// Each precipitation amount covers the 15 minutes ENDING at its timestamp.
function validPrecipSeries(value) {
    const times = value.precipTimes, amounts = value.precipAmounts;
    return Array.isArray(times) && Array.isArray(amounts) && times.length >= 2 &&
        times.length <= 100 && times.length === amounts.length &&
        times.every(function (t, i) {
            return typeof t === "number" && isFinite(t) && t > 0 &&
                (i === 0 || t - times[i-1] === 900) &&
                (amounts[i] === null || (typeof amounts[i] === "number" &&
                    isFinite(amounts[i]) && amounts[i] >= 0));
        });
}

function precipitationTiming(now, old) {
    if (old) return "UNAVAILABLE";
    const seconds = now / 1000;
    const times = reading.precipTimes;
    if (times[0] - 900 > seconds || times[times.length-1] <= seconds) {
        return "UNAVAILABLE";
    }
    for (let i = 0; i < times.length; i++) {
        if (times[i] <= seconds) continue;
        const start = times[i] - 900;
        if (start >= seconds + 86400) break;
        if (reading.precipAmounts[i] === null) return "UNAVAILABLE";
        if (reading.precipAmounts[i] > 0) {
            if (start <= seconds) return "NOW";
            const minutes = Math.ceil((start - seconds) / 60);
            return minutes < 60 ? "~" + minutes + " MIN" :
                "~" + (Math.round(minutes / 6) / 10) + " HR";
        }
    }
    return times[times.length-1] >= seconds + 86400 ? "NONE 24H" : "UNAVAILABLE";
}

function conditions(code) {
    if (code === 0) return "CLEAR";
    if (code === 1) return "MAINLY CLR";
    if (code === 2) return "PART CLOUD";
    if (code === 3) return "OVERCAST";
    if (code === 45 || code === 48) return "FOG";
    if (code >= 51 && code <= 57) return "DRIZZLE";
    if ((code >= 61 && code <= 67) || (code >= 80 && code <= 82)) return "RAIN";
    if ((code >= 71 && code <= 77) || code === 85 || code === 86) return "SNOW";
    if (code >= 95 && code <= 99) return "STORM";
    return "UNKNOWN";
}

// Original pixel artwork, generated in memory; no asset uploads on refresh.
function weatherIcon(code, isDay) {
    const pixels = [];
    for (let i = 0; i < 256; i++) pixels.push(".");
    function dot(x, y, color) {
        if (x >= 0 && x < 16 && y >= 0 && y < 16) pixels[y * 16 + x] = color;
    }
    function disk(cx, cy, radius, color) {
        for (let y = 0; y < 16; y++) {
            for (let x = 0; x < 16; x++) {
                if ((x-cx)*(x-cx) + (y-cy)*(y-cy) <= radius*radius) dot(x,y,color);
            }
        }
    }
    if (code <= 2) {
        if (isDay) {
            disk(7,7,3,"Y");
            [[7,1],[7,2],[7,12],[7,13],[1,7],[2,7],[12,7],[13,7],
                [3,3],[11,3],[3,11],[11,11]].forEach(function (p) {dot(p[0],p[1],"Y");});
        } else {
            disk(7,7,5,"M");
            disk(10,4,5,".");
            dot(13,3,"W");
        }
    }
    if (code >= 2 && code !== 45 && code !== 48) {
        disk(5,7,3,"C");
        disk(9,6,4,"W");
        disk(12,8,2,"C");
        for (let x = 2; x < 15; x++) {dot(x,9,"C"); dot(x,10,"C");}
    }
    const kind = conditions(code);
    if (kind === "RAIN" || kind === "DRIZZLE") {
        [4,8,12].forEach(function (x) {dot(x,12,"B"); dot(x-1,13,"B"); dot(x-1,14,"B");});
    } else if (kind === "SNOW") {
        [4,10].forEach(function (x) {dot(x,12,"M"); dot(x-1,13,"M"); dot(x,14,"M"); dot(x+1,13,"M");});
    } else if (kind === "STORM") {
        [[8,11],[7,12],[6,13],[7,13],[8,13],[7,14],[6,15]].forEach(function (p) {dot(p[0],p[1],"Y");});
    } else if (kind === "FOG") {
        for (let y = 5; y <= 11; y += 3) for (let x = 2; x < 14; x++) dot(x,y,"C");
    }
    let data = "! XPM2\n16 16 7 1\n. c #000000\nY c #FFD43B\nC c #899BAD\n" +
        "W c #DBE7EE\nB c #429FFF\nM c #B6DEFF\nR c #FF7B66\n";
    for (let y = 0; y < 16; y++) data += pixels.slice(y*16,y*16+16).join("") + "\n";
    return data;
}

function text(id, value, x, y, font, color, display) {
    return {id: id, type: "text", text: value || " ", x: x, y: y, font: font,
        color: color, align: "top_left", display: display || "front", timeout: 10};
}

function sameForecastDay(now, value) {
    return Math.floor((now / 1000 + value.utcOffset) / 86400) ===
        Math.floor((value.dayTime + value.utcOffset) / 86400);
}

function pageIndex(now) {
    return Math.floor((now - startedAt) / 10000) % 5;
}

const PIXEL_FONT = {"A":"010101111101101","B":"110101110101110","C":"011100100100011","D":"110101101101110","E":"111100110100111","F":"111100110100100","G":"011100101101011","H":"101101111101101","I":"111010010010111","J":"001001001101010","K":"101101110101101","L":"100100100100111","M":"101111111101101","N":"101111111111101","O":"010101101101010","P":"110101110100100","Q":"010101101111011","R":"110101110101101","S":"011100010001110","T":"111010010010010","U":"101101101101111","V":"101101101101010","W":"101101111111101","X":"101101010101101","Y":"101101010010010","Z":"111001010100111","0":"111101101101111","1":"010110010010111","2":"110001010100111","3":"110001010001110","4":"101101111001001","5":"111100110001110","6":"011100111101111","7":"111001010010010","8":"111101111101111","9":"111101111001110","+":"000010111010000","-":"000000111000000",".":"000000000000010","^":"010101000000000","/":"001001010100100","~":"000000010101000","%":"101001010100101","?":"110001010000010"," ":"000000000000000"};

function frontBitmap(now, old, today) {
    const pixels = [];
    for (let i = 0; i < 72 * 16; i++) pixels.push(".");
    function dot(x, y, color) {
        if (x >= 0 && x < 72 && y >= 0 && y < 16) pixels[y * 72 + x] = color;
    }
    function label(value, x, y, color, scale, height) {
        height = height || scale;
        for (let n = 0; n < value.length; n++) {
            const glyph = PIXEL_FONT[value[n]] || PIXEL_FONT["?"];
            for (let row = 0; row < 5; row++) for (let col = 0; col < 3; col++) {
                if (glyph[row * 3 + col] === "1") {
                    for (let dy = 0; dy < height; dy++) for (let dx = 0; dx < scale; dx++) {
                        dot(x + n * 4 * scale + col * scale + dx, y + row * height + dy, color);
                    }
                }
            }
        }
    }
    if (!reading) {
        label("CARMEL",1,1,"W",1);
        label("46032 LOADING",1,10,"B",1);
    } else {
        // Left column: 11-pixel icon, one-pixel gap, four-pixel ZIP.
        if (old) {
            label("?",6,0,"Y",2);
        } else {
            const iconRows = weatherIcon(reading.code, reading.isDay).split("\n").slice(9,25);
            for (let y = 0; y < 11; y++) for (let x = 0; x < 18; x++) {
                dot(x,y,iconRows[Math.floor(y*16/11)][Math.floor(x*16/18)]);
            }
        }
        // Compact four-row digits keep ZIP readable without crowding the icon.
        const zipDigits = ["101101111001", "100111101111", "111101101111",
            "111011001111", "110011100111"];
        for (let n = 0; n < zipDigits.length; n++) {
            for (let y = 0; y < 4; y++) for (let x = 0; x < 3; x++) {
                if (zipDigits[n][y*3+x] === "1") dot(n*4+x,y+12,"C");
            }
        }
        function value(number, color) {
            label(number,22,0,color,number.length <= 3 ? 2 : 1,3);
        }
        function description(top, bottom) {
            label(top,48,1,"B",1);
            label(bottom,48,10,"B",1);
        }
        const page = pageIndex(now);
        if (page === 1) {
            const high = today ? String(Math.round(reading.high)) : "--";
            const low = today ? String(Math.round(reading.low)) : "--";
            label(high,22,0,"R",high.length <= 2 ? 2 : 1,3);
            label("H",38,5,"R",1);
            label(low,47,0,"B",low.length <= 2 ? 2 : 1,3);
            label("L",63,5,"B",1);
        } else if (page === 2) {
            value(String(Math.round(reading.wind)),"W");
            description("WIND","MPH");
        } else if (page === 3) {
            label("HUMIDITY",21,5,"B",1);
            const humidity = String(Math.round(reading.humidity)) + " %";
            label(humidity,73 - humidity.length*4,5,"W",1);
        } else if (page === 4) {
            const timing = precipitationTiming(now, old);
            if (timing[0] === "~") {
                const parts = timing.slice(1).split(" ");
                value(parts[0],"W");
                description("PRECIP","~" + parts[1]);
            } else {
                value(timing === "UNAVAILABLE" ? "?" : timing === "NONE 24H" ? "NONE" : "NOW","W");
                description("PRECIP",timing === "NONE 24H" ? "24H" : timing === "UNAVAILABLE" ? "N/A" : "");
            }
        } else {
            const temperature = String(Math.round(reading.temperature));
            value(temperature,"W");
            label("F",21 + temperature.length * (temperature.length <= 3 ? 8 : 4),0,"C",1);
            const condition = conditions(reading.code);
            if (condition === "PART CLOUD") description("PARTLY","CLOUDY");
            else if (condition === "MAINLY CLR") description("MAINLY","CLEAR");
            else if (condition === "OVERCAST") description("OVER","CAST");
            else description(condition.slice(0,6),condition.slice(6));
        }
    }
    let data = "! XPM2\n72 16 7 1\n. c #000000\nY c #FFD43B\nC c #899BAD\n" +
        "W c #FFFFFF\nB c #74BFFF\nM c #B6DEFF\nR c #FFB47A\n";
    for (let y = 0; y < 16; y++) data += pixels.slice(y*72,y*72+72).join("") + "\n";
    return data;
}

function displayElements(now) {
    const white = "#FFFFFFFF";
    if (!reading) return [{id: "front", type: "xpmbitmap", x: 0, y: 0,
        align: "top_left", data: frontBitmap(now, true, false), timeout: 10}];
    const old = stale || now < reading.sourceTime ||
        now - reading.sourceTime > SOURCE_MAX_AGE_MS;
    const today = sameForecastDay(now, reading);
    const elements = [{id: "front", type: "xpmbitmap", x: 0, y: 0,
        align: "top_left", data: frontBitmap(now, old, today), timeout: 10}];
    const source = new Date(reading.sourceTime + reading.utcOffset * 1000);
    const hours = source.getUTCHours();
    const minutes = source.getUTCMinutes();
    const stamp = (hours % 12 || 12) + ":" + (minutes < 10 ? "0" : "") + minutes +
        (hours < 12 ? " AM" : " PM");
    elements.push(text("back-location", "Carmel 46032", 4, 4, "small", white, "back"));
    elements.push(text("back-source", "Open-Meteo model", 4, 20, "small", white, "back"));
    elements.push(text("back-time", "As of " + stamp + (old ? " - OLD" : ""),
        4, 36, "small", white, "back"));
    let detail = "H/L: " + (today ? "today's forecast" : "unavailable");
    const page = pageIndex(now);
    if (page === 2) detail = "Wind: " + Math.round(reading.wind) + " mph";
    if (page === 3) detail = "Rel. humidity: " + Math.round(reading.humidity) + "%";
    if (page === 4) detail = "Next: " + precipitationTiming(now, old);
    elements.push(text("back-day", detail, 4, 52, "small", white, "back"));
    elements.push(text("back-total", page === 4 && today ?
        "Today total: " + reading.precipTotal.toFixed(2) + " in" : " ",
        4, 66, "small", white, "back"));
    return elements;
}

function draw() {
    if (drawing) return;
    drawing = true;
    fetch("http://127.0.0.1/api/display/draw", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
            application_name: APP_ID,
            priority: 50,
            elements: displayElements(Date.now())
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
        if (body.current_units.temperature_2m !== "\u00b0F" ||
            body.daily_units.temperature_2m_max !== "\u00b0F" ||
            body.daily_units.temperature_2m_min !== "\u00b0F" ||
            body.current_units.wind_speed_10m !== "mp/h" ||
            body.current_units.relative_humidity_2m !== "%" ||
            body.daily_units.precipitation_probability_max !== "%" ||
            body.daily_units.precipitation_sum !== "inch" ||
            body.minutely_15_units.precipitation !== "inch") throw new Error("Wrong weather units");
        const candidate = {
            zip: "46032",
            temperature: body.current.temperature_2m,
            code: body.current.weather_code,
            high: body.daily.temperature_2m_max[0],
            low: body.daily.temperature_2m_min[0],
            fetchedAt: Date.now(),
            sourceTime: body.current.time * 1000,
            dayTime: body.daily.time[0],
            utcOffset: body.utc_offset_seconds,
            isDay: body.current.is_day,
            wind: body.current.wind_speed_10m,
            humidity: body.current.relative_humidity_2m,
            precipChance: body.daily.precipitation_probability_max[0],
            precipTotal: body.daily.precipitation_sum[0],
            precipTimes: body.minutely_15.time,
            precipAmounts: body.minutely_15.precipitation
        };
        if (!validReading(candidate)) throw new Error("Invalid forecast");
        if (candidate.sourceTime > candidate.fetchedAt + 300000 ||
            candidate.fetchedAt - candidate.sourceTime > SOURCE_MAX_AGE_MS ||
            !sameForecastDay(candidate.fetchedAt, candidate)) throw new Error("Outdated forecast");
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
