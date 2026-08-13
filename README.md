# BUSY Bar applications

The `busybar` CLI runs separate applications on a Flipper BUSY Bar:

- `busybar system` displays live CPU, memory, CPU temperature, and ping latency.
- `busybar stocks` rotates through intraday changes and charts.

The system application keeps CPU, memory, CPU temperature, and ping latency
visible together in a stable four-cell overview. Each cell includes a compact
value, direction indicator, utilization meter, and recent peak marker. Samples
are smoothed, and warning colors use hysteresis so noisy values do not flicker
between states. CPU and memory update at the configured interval; temperature
and ping are sampled independently every five seconds.

Crossing a warning or critical threshold briefly displays a preloaded on-device
alert. Asset upload failure does not stop the monitor; it continues without
alerts. Every metric update sends a complete overview, so the monitor can
redraw itself after the physical mode selector temporarily gives the display to
another application. The monitor removes only its own display elements when it
exits. Elements also expire automatically if the process crashes, allowing the
Bar to return to its previous mode without a global display reset.

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

The stock application defaults to the symbols in the Apple Stocks watchlist
used when it was created. Set a persistent default with a space-separated
`BUSYBAR_STOCK_SYMBOLS` value or pass symbols on the command line. It uses Yahoo
Finance's unofficial chart endpoint without an account or API key. Quotes
refresh once per minute and are cached under `~/Library/Caches/busybar/`, so
temporary throttling or outages retain the last successful chart.

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
cadence with `--rotate` and `--refresh`. Percentage change is shown by default;
use `--change points` to show the absolute price change instead. The CLI renders
every stock page into a cached, continuously looping animation asset. The BUSY
Bar plays the 24 FPS vertical page swipes and chart reveals locally, without
clearing the display or making an HTTP request for each frame. Quote refreshes
rebuild the inactive asset slot before switching to it at a cycle boundary.
Failed Yahoo refreshes retain the previous asset, use exponential backoff, and mark data
older than three refresh intervals in yellow.

The connection order is mDNS discovery, USB at `10.0.4.20`, the configured
home LAN address, then BUSY Cloud. Every candidate must report the configured
serial number before the monitor writes to it. The monitor reconnects with
bounded backoff after a connection fails and checks every 30 seconds for a
better transport in the background, preferring USB over LAN and LAN over BUSY
Cloud. Pass `--verbose` to report those periodic health checks. Stop the monitor
with `Ctrl-C`.
