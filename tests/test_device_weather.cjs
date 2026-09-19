const assert = require('node:assert/strict');
const {test} = require('node:test');
const vm = require('node:vm');
const fs = require('node:fs');
const path = require('node:path');

const root = path.join(__dirname, '../device-apps/app.ntwrknrd.weather');
const source = fs.readFileSync(path.join(root, 'scripts/main.js'), 'utf8');
const good = {current: {temperature_2m: 78.2, weather_code: 0},
    daily: {temperature_2m_max: [82.5], temperature_2m_min: [64.1]}};
const settle = () => new Promise(resolve => setImmediate(resolve));

function boot({cached = null, failure = false, storageFailure = false} = {}) {
    const state = {now: 1800000000000, draws: [], requests: 0, cached,
        failure, storageFailure, payload: good};
    const context = vm.createContext({
        Date: {now: () => state.now},
        console: {info() {}, error() {}},
        localStorage: {
            getItem: () => state.cached,
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
            return state.failure ? Promise.reject(new Error('offline')) :
                Promise.resolve({json: () => Promise.resolve(state.payload)});
        }
    });
    vm.runInContext(source, context);
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
    assert.match(s.draws.at(-1).elements[0].text, /78F CLEAR/);
    assert.equal(s.draws.at(-1).elements[1].text, 'H83 L64');
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
    assert.match(s.draws.at(-1).elements[1].text, /OLD/);
    assert.match(s.draws.at(-1).elements[0].text, /78F/);
    s.failure = false;
    s.now += 60000;
    s.tick();
    await settle();
    assert.equal(s.requests, 2);
    assert.doesNotMatch(s.draws.at(-1).elements[1].text, /OLD/);
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
    assert.match(s.draws.at(-1).elements[1].text, /OLD/);
});

test('corrupt cache and network failure show waiting screen', async () => {
    const s = boot({cached: '{broken', failure: true});
    await settle();
    assert.equal(s.draws.at(-1).elements[1].text, 'WAITING FOR WIFI');
});

test('cache write failure does not discard live weather', async () => {
    const s = boot({storageFailure: true});
    await settle();
    assert.equal(s.draws.at(-1).elements[1].text, 'H83 L64');
});
