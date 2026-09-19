# On-device weather prototype

`app.ntwrknrd.weather` runs directly on official BUSY Bar firmware 1.2.4.
It fetches Indianapolis weather from Open-Meteo over the Bar's Wi-Fi connection.
The Mac is needed only for installation. No API keys or custom firmware are used.

This prototype uses plain HTTP for Open-Meteo, explicitly accepted for public,
fixed-location weather after the Bar's TLS handshake failed on firmware 1.2.4.
Weather responses therefore are not authenticated or encrypted. It sends no
credentials or personal location. Display requests use `127.0.0.1`; the official
example's USB address did not work with USB networking unavailable.

The front display shows Fahrenheit temperature, conditions, and today's high/low.
Successful forecasts refresh every 15 minutes and persist in `localStorage`.
Cached readings appear in yellow with `OLD` until a fresh request succeeds.
Failures retry after one minute. With no cache, the display shows
`WAITING FOR WIFI`. This first prototype omits forecast graphs and animations.

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
**Indy Weather**, then **Start**. The prototype uses fixed Indianapolis coordinates;
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

## Firmware references

- [Release 1.2.3: experimental JavaScript support](https://github.com/busy-app/busybar-firmware/releases/tag/1.2.3)
- [1.2.4 app loader](https://github.com/busy-app/busybar-firmware/blob/1.2.4/lib/js_app/js_app.c)
- [1.2.4 JavaScript fetch](https://github.com/busy-app/busybar-firmware/blob/1.2.4/applications/services/js_runner/js_fetch.c)
- [Open-Meteo weather data](https://open-meteo.com/)
