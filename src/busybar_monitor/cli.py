from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import time
from dataclasses import dataclass
from typing import Iterator

import psutil
from busylib import BusyBar, BusyBarDevices, types

APP_NAME = "macos-system-monitor"
USB_ADDRESS = "10.0.4.20"


@dataclass(frozen=True)
class Candidate:
    name: str
    address: str | None
    token: str | None

    def connect(self) -> BusyBar:
        if self.name == "cloud":
            return BusyBar(token=self.token, timeout=3)
        return BusyBar(self.address, token=self.token, timeout=2)


def candidates() -> Iterator[Candidate]:
    lan_token = os.getenv("BUSYBAR_LAN_TOKEN") or None
    seen: set[str] = set()

    try:
        devices = BusyBarDevices.discover()
    except Exception:
        devices = []

    for device in devices:
        for affinity, token in (("over_wifi", lan_token), ("over_usb", None)):
            address = device.get_address(affinity)
            if address and address not in seen:
                seen.add(address)
                yield Candidate(f"mDNS {affinity.removeprefix('over_')}", address, token)

    if USB_ADDRESS not in seen:
        seen.add(USB_ADDRESS)
        yield Candidate("USB", USB_ADDRESS, None)

    home_address = os.getenv("BUSYBAR_HOME_IP")
    if home_address and home_address not in seen:
        seen.add(home_address)
        yield Candidate("home LAN", home_address, lan_token)

    cloud_token = os.getenv("BUSYBAR_CLOUD_TOKEN")
    if cloud_token:
        yield Candidate("cloud", None, cloud_token)


def resolve() -> tuple[BusyBar, Candidate]:
    expected_serial = os.getenv("BUSYBAR_SERIAL_NUMBER")
    if not expected_serial:
        raise RuntimeError("BUSYBAR_SERIAL_NUMBER is not set")

    failures: list[str] = []
    for candidate in candidates():
        bar = candidate.connect()
        try:
            status = bar.status()
            serial = status.device.serial_number if status.device else None
            if serial != expected_serial:
                failures.append(f"{candidate.name}: serial mismatch")
                bar.close()
                continue
            return bar, candidate
        except Exception as exc:
            failures.append(f"{candidate.name}: {type(exc).__name__}")
            bar.close()

    detail = "; ".join(failures) or "no connection candidates"
    raise RuntimeError(f"BUSY Bar not reachable ({detail})")


def color_for(percent: float) -> str:
    if percent >= 85:
        return "#FF3030FF"
    if percent >= 65:
        return "#FFD43BFF"
    return "#32D17CFF"


def bar_elements(label: str, percent: float, y: int, prefix: str) -> list[types.DisplayElement]:
    value = max(0.0, min(100.0, percent))
    width = max(1, round(36 * value / 100))
    return [
        types.TextElement(id=f"{prefix}-label", text=label, font="tiny", x=0, y=y),
        types.RectangleElement(
            id=f"{prefix}-background",
            x=17,
            y=y,
            width=36,
            height=5,
            fill="solid",
            fill_colors=["#202838FF"],
            border_width=0,
        ),
        types.RectangleElement(
            id=f"{prefix}-value",
            x=17,
            y=y,
            width=width,
            height=5,
            fill="solid",
            fill_colors=[color_for(value)],
            border_width=0,
        ),
        types.TextElement(
            id=f"{prefix}-percent",
            text=f"{value:2.0f}%",
            font="tiny",
            x=55,
            y=y,
            color=color_for(value),
        ),
    ]


def frame(cpu: float, memory: float) -> types.DisplayElements:
    elements = bar_elements("CPU", cpu, 1, "cpu")
    elements.extend(bar_elements("RAM", memory, 9, "ram"))
    return types.DisplayElements(application_name=APP_NAME, priority=50, elements=elements)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Show macOS CPU and RAM usage on BUSY Bar")
    result.add_argument("--interval", type=float, default=2.0, help="refresh interval in seconds")
    result.add_argument("--once", action="store_true", help="draw one frame and exit")
    result.add_argument("--dry-run", action="store_true", help="print one frame without contacting the Bar")
    return result


def main() -> None:
    args = parser().parse_args()
    if args.interval < 0.25:
        parser().error("--interval must be at least 0.25 seconds")

    psutil.cpu_percent(interval=None)
    time.sleep(min(args.interval, 0.5))

    if args.dry_run:
        payload = frame(psutil.cpu_percent(interval=None), psutil.virtual_memory().percent)
        print(json.dumps(payload.model_dump(mode="json", exclude_none=True), indent=2))
        return

    try:
        bar, candidate = resolve()
    except RuntimeError as exc:
        print(f"busybar-monitor: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    print(f"Connected via {candidate.name}", file=sys.stderr)
    stopping = False

    def stop(_signum: int, _frame: object) -> None:
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    try:
        while not stopping:
            payload = frame(psutil.cpu_percent(interval=None), psutil.virtual_memory().percent)
            bar.display_draw(payload, clear_before_draw=True)
            if args.once:
                break
            time.sleep(args.interval)
    finally:
        bar.close()
