# BUSY Bar macOS system monitor

Displays live CPU, memory, CPU temperature, and ping latency from macOS on a
Flipper BUSY Bar. The two dashboard pages rotate every five seconds with a
horizontal slide transition.
Values animate smoothly in place without clearing the display between samples.
Every update sends a complete frame, so the monitor can redraw itself after the
physical mode selector temporarily gives the display to another application.
The monitor removes only its own display elements when it exits. Elements also
expire automatically if the process crashes, allowing the Bar to return to its
previous mode without a global display reset.

## Setup

The monitor reads these environment variables:

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

Preview the generated display payload without contacting the device:

```sh
uv run busybar-monitor --dry-run
```

Draw once:

```sh
uv run busybar-monitor --once
```

Run continuously with a two-second refresh interval:

```sh
uv run busybar-monitor
```

The connection order is mDNS discovery, USB at `10.0.4.20`, the configured
home LAN address, then BUSY Cloud. Every candidate must report the configured
serial number before the monitor writes to it. The monitor reconnects with
bounded backoff after a connection fails and checks every 30 seconds for a
better transport in the background, preferring USB over LAN and LAN over BUSY
Cloud. Pass `--verbose` to report those periodic health checks. Stop the monitor
with `Ctrl-C`.
