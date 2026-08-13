# BUSY Bar applications

The `busybar` CLI runs separate applications on a Flipper BUSY Bar:

- `busybar system` displays live CPU, memory, CPU temperature, and ping latency.
- `busybar stocks` rotates through intraday stock prices and charts.

The system application's two dashboard pages rotate every five seconds with a
horizontal slide transition.
Transitions use latency-aware frame pacing and eased motion to remain smooth
over Wi-Fi without delaying each frame by the API round-trip time.
Values animate smoothly in place without clearing the display between samples.
Every update sends a complete frame, so the monitor can redraw itself after the
physical mode selector temporarily gives the display to another application.
The monitor removes only its own display elements when it exits. Elements also
expire automatically if the process crashes, allowing the Bar to return to its
previous mode without a global display reset.

## Setup

Both applications read these environment variables:

- `BUSYBAR_SERIAL_NUMBER`: required; prevents drawing to the wrong device.
- `BUSYBAR_LAN_TOKEN`: password for the local Wi-Fi HTTP API.
- `BUSYBAR_HOME_IP`: optional reserved home address.
- `BUSYBAR_CLOUD_TOKEN`: optional BUSY Account API token.

Install dependencies:

```sh
uv sync
```

CPU temperature requires `macmon` on Apple Silicon:

```sh
brew install macmon
```

Ping targets `1.1.1.1` by default. Override it with `BUSYBAR_PING_TARGET`.

The stock application defaults to `AAPL`, `MSFT`, and `NVDA`. Set a persistent
default with a space-separated `BUSYBAR_STOCK_SYMBOLS` value or pass symbols on
the command line. It uses Yahoo Finance's unofficial chart endpoint without an
account or API key. Quotes refresh once per minute and are cached under
`~/Library/Caches/busybar/`, so temporary throttling or outages retain the last
successful chart.

Preview the generated display payload without contacting the device:

```sh
uv run busybar system --dry-run
uv run busybar stocks AAPL MSFT --dry-run
```

Draw once:

```sh
uv run busybar system --once
uv run busybar stocks AAPL --once
```

Run continuously with a two-second refresh interval:

```sh
uv run busybar system
uv run busybar stocks AAPL MSFT NVDA
```

Stock symbols rotate every ten seconds. Override the display and market-data
cadence with `--rotate` and `--refresh`. The graph reveals from left to right as
each new symbol slides into place. Failed Yahoo refreshes use exponential
backoff and mark data older than three refresh intervals in yellow.

The connection order is mDNS discovery, USB at `10.0.4.20`, the configured
home LAN address, then BUSY Cloud. Every candidate must report the configured
serial number before the monitor writes to it. The monitor reconnects with
bounded backoff after a connection fails and checks every 30 seconds for a
better transport in the background, preferring USB over LAN and LAN over BUSY
Cloud. Pass `--verbose` to report those periodic health checks. Stop the monitor
with `Ctrl-C`.
