# On-device weather prototype

`app.ntwrknrd.weather` runs directly on official BUSY Bar firmware 1.2.4.
It fetches Carmel, Indiana ZIP 46032 weather from Open-Meteo over the Bar's Wi-Fi
connection, using the ZIP lookup coordinates 39.9712, -86.1245.
The Mac is needed only for installation. No API keys or custom firmware are used.

This prototype uses plain HTTP for Open-Meteo, explicitly accepted for public,
fixed-location weather after the Bar's TLS handshake failed on firmware 1.2.4.
Weather responses therefore are not authenticated or encrypted. It sends no
credentials or personal location. Display requests use `127.0.0.1`; the official
example's USB address did not work with USB networking unavailable.

The front display rotates through current temperature/conditions, high/low,
wind speed (mph), relative humidity (%), and the next precipitation forecast.
Each view lasts 10 seconds. ZIP 46032 sits beneath the compact weather icon
in the left column of every page. Values use nearly the full display height,
with compact descriptions and units to their right. Fahrenheit remains beside
the temperature digits. A yellow question mark replaces the icon on stale pages
while the ZIP remains visible.
Each front view is a single XPM bitmap, so text and icons update together; the
renderer reuses this repository's pixel alphabet.

The precipitation page estimates time until the first nonzero 15-minute
precipitation interval within the next 24 hours. Amounts represent the preceding
15 minutes, so the countdown targets the interval's start, not its end. It shows
approximate minutes below one hour, then hours; `NOW` means the current interval
has forecast precipitation. `NONE 24H` requires complete, dry forecast coverage;
stale, missing, or insufficient data shows `UNAVAILABLE`. These are model estimates,
not radar-based minute-by-minute predictions. The rear screen retains the day's
forecast total in inches (including rain and snow water equivalent).

Successful forecasts refresh every 15 minutes and persist in `localStorage`,
in a versioned ZIP-specific cache; older caches without the new fields are ignored. Current conditions are
Open-Meteo model estimates, not thermometer observations. High/low values are
today's forecast extrema, not the day's observed extrema. Newly fetched model
data older than 30 minutes is rejected; yesterday's high/low is never shown as
today's; the same guard hides yesterday's precipitation total. Cached readings
get a yellow question-mark icon until a fresh request succeeds;
the rear timestamp retains an `OLD` label.
Failures retry after one minute. This prototype omits forecast graphs.

## Install and launch

From the repository root, with the usual `BUSYBAR_SERIAL_NUMBER` and local
connection environment configured:

```sh
uv sync --locked
uv run scripts/install_device_weather.py
```

The installer verifies the device serial and firmware version, uploads and reads
back the two app files, and enables the experimental JavaScript Apps menu using
`/ext/apps_data/apps_menu/js_apps_enabled`. It preserves existing files and refuses
to replace a different weather installation. Firmware-provided fallback icons are
used. The app's own `debug` flag is false, so Developer Mode is not required.

Reload the Apps menu by moving the mode switch away from Apps and back. Select
**Carmel Weather**, then **Start**. The prototype uses fixed ZIP 46032 coordinates;
there is no setup screen yet.

Move the mode switch away from Apps to stop the app. Firmware 1.2.4 consumes the
Back key while a JavaScript app is running. Display elements expire after ten
seconds without a redraw, so stopped scripts cannot leave permanent overlays.

## Verification

```sh
node --test tests/test_device_weather.cjs
uv run python -m unittest discover -s tests
```

The JavaScript tests run the shipped script with a simulated firmware environment,
including responses without browser-style `ok` or `status` properties. They cover
refresh cadence, offline cache/recovery, invalid responses, and storage failure.
Hardware checks are needed for rendering, firmware heap limits, networking, and
launch/exit behavior; host tests do not establish those properties.

On September 19, 2026, the prototype was installed and launched on firmware
1.2.4 over Wi-Fi. Live fetch, persistent cache, front-display rendering, stopping
by mode switch, and relaunch were verified. A temporary closed-loopback-port
forecast endpoint verified that cached values remain visible in yellow with
`OLD`; the normal endpoint was then restored. No Mac weather process was running.
An actual Wi-Fi outage and an extended 15-minute-refresh soak remain untested.

On September 20 the location was corrected from downtown Indianapolis to ZIP
46032, with a separate cache and the revised icon-led display verified on both
screens. The live Carmel response was 79 F with forecast high 82 and low 67,
compared with approximately 82/87/70 for the old downtown coordinates.

## Firmware references

- [Release 1.2.3: experimental JavaScript support](https://github.com/busy-app/busybar-firmware/releases/tag/1.2.3)
- [1.2.4 app loader](https://github.com/busy-app/busybar-firmware/blob/1.2.4/lib/js_app/js_app.c)
- [1.2.4 JavaScript fetch](https://github.com/busy-app/busybar-firmware/blob/1.2.4/applications/services/js_runner/js_fetch.c)
- [Open-Meteo model data and condition codes](https://open-meteo.com/en/docs)
- [ZIP 46032 location lookup](https://api.zippopotam.us/us/46032)
- [Weather Forecast design inspiration](https://github.com/maxswinkels/busybar-apps/tree/main/apps/weather-forecast)

The icon-led arrangement takes inspiration from the community Weather Forecast
app; the JavaScript renderer and pixel artwork here are original. That reference
is a host-run Python app, while this app continues to run directly on the Bar.

The September 20 detail-page update was installed and read back on firmware
1.2.4. A full rotation captured on both displays verified wind speed, humidity,
and daily precipitation probability/total alongside the original two views.
The live response showed 8.2 mph wind, 79% relative humidity, 43% peak hourly
precipitation probability, and 1.094 inches forecast for the whole day. Thirteen
JavaScript tests and 53 Python tests pass, including new field validation and
hiding previous-day precipitation.

The subsequent timing/layout revision replaces the front daily precipitation
summary with an approximate next-event countdown. Hardware captures verified
ZIP placement, Fahrenheit spacing, and the live countdown. Sixteen JavaScript
tests cover forecast interval boundaries, missing data, midnight, stale icons,
and pixel placement. Loading also uses the same bitmap ID as live weather to
avoid startup text overlapping the first forecast.
