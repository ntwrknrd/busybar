const assert = require('node:assert/strict');
const {test} = require('node:test');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');

const root = path.join(__dirname, '../device-apps/app.ntwrknrd.weather');
const source = fs.readFileSync(path.join(root, 'scripts/main.js'), 'utf8');
const epoch = 1800000000000;
const good = {current: {temperature_2m: 78.2, weather_code: 0, is_day: 1, wind_speed_10m: 6.4, relative_humidity_2m: 65, time: epoch / 1000},
    utc_offset_seconds: -14400,
    minutely_15_units: {precipitation: 'inch'},
    minutely_15: {
        time: Array.from({length: 98}, (_, i) => Math.floor(epoch / 900000) * 900 + i * 900),
        precipitation: Array(98).fill(0)
    },
    current_units: {temperature_2m: '\u00b0F', wind_speed_10m: 'mp/h', relative_humidity_2m: '%'},
    daily_units: {temperature_2m_max: '\u00b0F', temperature_2m_min: '\u00b0F', precipitation_probability_max: '%', precipitation_sum: 'inch'},
    daily: {precipitation_probability_max: [40], precipitation_sum: [0.12], temperature_2m_max: [82.5], temperature_2m_min: [64.1],
        time: [Math.floor((epoch / 1000 - 14400) / 86400) * 86400 + 14400]}};
const settle = () => new Promise(resolve => setImmediate(resolve));
const element = (s, id) => s.draws.at(-1).elements.find(e => e.id === id);

function boot({cached = null, failure = false, storageFailure = false} = {}) {
    const state = {now: epoch, draws: [], requests: 0, cached,
        failure, storageFailure, payload: JSON.parse(JSON.stringify(good))};
    class Clock extends Date { static now() {return state.now;} }
    const context = vm.createContext({
        Date: Clock,
        console: {info() {}, error() {}},
        localStorage: {
            getItem: key => {state.cacheKey = key; return state.cached;},
            setItem: (_, value) => {
                if (state.storageFailure) throw new Error('disk full');
                state.cached = value;
            }
        },
        setInterval: callback => {state.tick = callback;},
        fetch: (url, options) => {
            if (options) {
                state.draws.push(JSON.parse(options.body));
                return Promise.resolve({json: () => Promise.resolve({result: 'OK'})});
            }
            state.requests++;
            state.url = url;
            return state.failure ? Promise.reject(new Error('offline')) :
                Promise.resolve({json: () => Promise.resolve(state.payload)});
        }
    });
    vm.runInContext(source, context);
    state.context = context;
    return state;
}

test('manifest fits firmware limit and matches directory', () => {
    const text = fs.readFileSync(path.join(root, 'appmeta/manifest.json'));
    assert.ok(text.length <= 512);
    assert.equal(JSON.parse(text).id, path.basename(root));
});

test('fetches without Response.ok/status, renders values, refreshes at 15 minutes', async () => {
    const s = boot();
    await settle();
    assert.equal(JSON.parse(s.cached).temperature, 78.2);
    assert.match(element(s, 'front').data, /^! XPM2\n72 16 7 1/);
    assert.match(s.url, /latitude=39.9712&longitude=-86.1245/);
    assert.equal(s.cacheKey, 'forecast-v4-46032');
    assert.equal(JSON.parse(s.cached).temperature, 78.2);
    s.now += 899999;
    s.tick();
    await settle();
    assert.equal(s.requests, 1);
    s.now++;
    s.tick();
    await settle();
    assert.equal(s.requests, 2);
    assert.ok(s.draws.every(d => d.application_name === 'app.ntwrknrd.weather' &&
        d.elements.every(e => e.timeout === 10)));
});

test('offline restart keeps cached values marked OLD, retries, then recovers', async () => {
    const first = boot();
    await settle();
    const s = boot({cached: first.cached, failure: true});
    await settle();
    assert.match(element(s, 'back-time').text, /OLD/);
    assert.equal(JSON.parse(s.cached).temperature, 78.2);
    s.failure = false;
    s.now += 60000;
    s.tick();
    await settle();
    assert.equal(s.requests, 2);
    assert.doesNotMatch(element(s, 'back-time').text, /OLD/);
});

test('invalid API response cannot replace good cache', async () => {
    const s = boot();
    await settle();
    const saved = s.cached;
    s.payload = {error: true, reason: 'rate limited'};
    s.now += 900000;
    s.tick();
    await settle();
    assert.equal(s.cached, saved);
    assert.match(element(s, 'back-time').text, /OLD/);
});

test('corrupt cache and network failure show waiting screen', async () => {
    const s = boot({cached: '{broken', failure: true});
    await settle();
    assert.equal(s.draws.at(-1).elements.length, 1);
    assert.equal(element(s, 'front').type, 'xpmbitmap');
});

test('cache write failure does not discard live weather', async () => {
    const s = boot({storageFailure: true});
    await settle();
    assert.ok(element(s, 'front'));
    assert.doesNotMatch(element(s, 'back-time').text, /OLD/);
});

test('separates current conditions from ZIP-specific forecast high/low', async () => {
    const s = boot();
    await settle();
    const current = element(s, 'front').data;
    s.now += 10000;
    s.tick();
    await settle();
    assert.notEqual(element(s, 'front').data, current);
    assert.match(element(s, 'back-day').text, /today/);
    assert.equal(s.draws.at(-1).elements.filter(e => e.display !== 'back').length, 1);
    assert.equal(element(s, 'back-location').text, 'Carmel 46032');
    assert.equal(element(s, 'front').type, 'xpmbitmap');
    assert.ok(s.draws.at(-1).elements.every(e => e.align === 'top_left'));
});

test('WMO mainly clear is distinct from partly cloudy, with night icons', async () => {
    const s = boot();
    await settle();
    assert.equal(vm.runInContext('conditions(1)', s.context), 'MAINLY CLR');
    assert.equal(vm.runInContext('conditions(2)', s.context), 'PART CLOUD');
    assert.notEqual(vm.runInContext('weatherIcon(0, 1)', s.context),
        vm.runInContext('weatherIcon(0, 0)', s.context));
    for (const code of [0,1,2,3,45,61,71,95]) {
        const lines = vm.runInContext(`weatherIcon(${code}, 1)`, s.context).trimEnd().split('\n');
        assert.equal(lines[1], '16 16 7 1');
        assert.equal(lines.slice(9).length, 16);
        assert.ok(lines.slice(9).every(row => row.length === 16));
    }
});

test('old model timestamps and wrong units cannot replace a good reading', async () => {
    const s = boot();
    await settle();
    const saved = s.cached;
    s.now += 31 * 60000;
    s.tick();
    await settle();
    assert.equal(s.cached, saved);
    assert.match(element(s, 'back-time').text, /OLD/);
    s.payload.current.time = s.now / 1000;
    s.payload.current_units.temperature_2m = '\u00b0C';
    s.now += 60000;
    s.tick();
    await settle();
    assert.equal(s.cached, saved);
});

test('wrong-location cache is discarded and yesterday highs/lows are hidden', async () => {
    const s = boot({cached: JSON.stringify({temperature: 99, code: 1,
        high: 101, low: 85, fetchedAt: epoch}), failure: true});
    await settle();
    assert.equal(s.draws.at(-1).elements.length, 1);
    assert.equal(element(s, 'front').type, 'xpmbitmap');
    const live = boot();
    await settle();
    live.failure = true;
    live.now += 86400000 + 10000;
    live.tick();
    await settle();
    assert.match(element(live, 'back-day').text, /unavailable/);
    assert.match(element(live, 'back-time').text, /OLD/);
});


test('rotates wind, humidity and whole-day precipitation with explicit units', async () => {
    const s = boot();
    await settle();
    assert.match(s.url, /wind_speed_unit=mph&precipitation_unit=inch/);
    const cached = JSON.parse(s.cached);
    assert.equal(cached.wind, 6.4);
    assert.equal(cached.humidity, 65);
    assert.equal(cached.precipChance, 40);
    assert.equal(cached.precipTotal, 0.12);
    const frames = new Set([element(s, 'front').data]);
    for (const [seconds, expected] of [[10, /today/], [20, /Wind: 6 mph/],
        [30, /Rel. humidity: 65%/], [40, /Next: NONE 24H/]]) {
        s.now = epoch + seconds * 1000;
        s.tick();
        await settle();
        assert.match(element(s, 'back-day').text, expected);
        frames.add(element(s, 'front').data);
    }
    assert.equal(frames.size, 5);
    assert.equal(element(s, 'back-total').text, 'Today total: 0.12 in');
    s.failure = true;
    s.now = epoch + 86440000;
    s.tick();
    await settle();
    assert.equal(element(s, 'back-day').text, 'Next: UNAVAILABLE');
    assert.equal(element(s, 'back-total').text, ' ');
});

test('rejects missing, out-of-range and wrong-unit detail fields without losing cache', async () => {
    for (const mutate of [
        p => {p.current.relative_humidity_2m = null;},
        p => {p.current.relative_humidity_2m = 101;},
        p => {p.current.wind_speed_10m = -1;},
        p => {p.daily.precipitation_probability_max[0] = 101;},
        p => {p.daily.precipitation_sum[0] = -0.1;},
        p => {p.daily.precipitation_sum[0] = null;},
        p => {p.current_units.wind_speed_10m = 'km/h';},
        p => {p.daily_units.precipitation_sum = 'mm';}
    ]) {
        const s = boot();
        await settle();
        const saved = s.cached;
        mutate(s.payload);
        s.now += 900000;
        s.tick();
        await settle();
        assert.equal(s.cached, saved);
        assert.match(element(s, 'back-time').text, /OLD/);
    }
});

test('zero wind, humidity and precipitation are valid, legacy cache is rejected', async () => {
    const s = boot();
    s.payload.current.wind_speed_10m = 0;
    s.payload.current.relative_humidity_2m = 0;
    s.payload.daily.precipitation_probability_max[0] = 0;
    s.payload.daily.precipitation_sum[0] = 0;
    await settle();
    assert.equal(JSON.parse(s.cached).precipTotal, 0);
    const legacy = JSON.parse(s.cached);
    delete legacy.humidity;
    const restarted = boot({cached: JSON.stringify(legacy), failure: true});
    await settle();
    assert.equal(restarted.draws.at(-1).elements.length, 1);
    assert.equal(element(restarted, 'front').type, 'xpmbitmap');
});


test('precipitation timing respects interval ends and counts down across midnight', async () => {
    const s = boot();
    await settle();
    const set = code => vm.runInContext(code, s.context);
    const start = Math.floor(epoch / 900000) * 900;
    set('reading.precipAmounts[3] = 0.01');
    assert.equal(set(`precipitationTiming(${(start + 900) * 1000}, false)`), '~15 MIN');
    assert.equal(set(`precipitationTiming(${(start + 1800) * 1000}, false)`), 'NOW');
    // A wet interval that has ended must not be called current precipitation.
    assert.equal(set(`precipitationTiming(${(start + 2700) * 1000}, false)`), 'UNAVAILABLE');
    set('reading.precipAmounts[3] = 0; reading.precipAmounts[7] = 0.01');
    assert.equal(set(`precipitationTiming(${start * 1000}, false)`), '~1.5 HR');
    assert.equal(set(`precipitationTiming(${start * 1000}, true)`), 'UNAVAILABLE');
    set('reading.precipAmounts[1] = null');
    assert.equal(set(`precipitationTiming(${start * 1000}, false)`), 'UNAVAILABLE');
    set('reading.precipAmounts[1] = 0; reading.precipTimes = reading.precipTimes.map(function(t) {return t + 7200;})');
    assert.equal(set(`precipitationTiming(${start * 1000}, false)`), 'UNAVAILABLE');
    // Move a complete series across the local midnight boundary.
    set('reading.precipTimes = reading.precipTimes.map(function(t, i) {return reading.dayTime + 85500 + i * 900;})');
    assert.equal(set('precipitationTiming((reading.dayTime + 85500) * 1000, false)'), '~1.5 HR');
});

test('rejects malformed forecast series and wrong precipitation units', async () => {
    for (const mutate of [
        p => {p.minutely_15.time[2] += 60;},
        p => {p.minutely_15.precipitation.pop();},
        p => {p.minutely_15.precipitation[1] = -1;},
        p => {p.minutely_15_units.precipitation = 'mm';}
    ]) {
        const s = boot();
        await settle();
        const saved = s.cached;
        mutate(s.payload);
        s.now += 900000;
        s.tick();
        await settle();
        assert.equal(s.cached, saved);
        assert.match(element(s, 'back-time').text, /OLD/);
    }
});

test('ZIP sits below the icon, tall values and right labels remain clear when stale', async () => {
    const s = boot();
    await settle();
    const bitmap = (page, old) => vm.runInContext(
        `frontBitmap(${epoch + page * 10000}, ${old}, true)`, s.context).trimEnd().split('\n').slice(9);
    const region = (rows, x, y, w, h) => rows.slice(y,y+h).map(row => row.slice(x,x+w)).join('');
    const current = bitmap(0, false);
    assert.match(region(current,0,12,19,4), /C/);
    assert.match(region(current,37,0,3,5), /C/);
    assert.doesNotMatch(region(current,44,0,4,16), /[WCB]/);
    for (let page = 0; page < 5; page++) {
        const fresh = bitmap(page, false), old = bitmap(page, true);
        assert.notEqual(region(fresh,0,0,19,10), region(old,0,0,19,10));
        assert.match(region(old,0,0,19,10), /Y/);
        assert.equal(region(fresh,0,12,19,4), region(old,0,12,19,4));
        assert.doesNotMatch(region(old,0,0,19,10), /[WCBMR]/);
        if (page !== 4) assert.equal(region(fresh,20,0,52,16), region(old,20,0,52,16));
    }
});
