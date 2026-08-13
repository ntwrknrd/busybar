from __future__ import annotations

import argparse
import json
import math
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
ANIMATION_FPS = 10
ANIMATION_SECONDS = 0.5


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


def static_bar_elements(
    label: str, y: int, prefix: str, timeout: int | None = None
) -> list[types.DisplayElement]:
    return [
        types.TextElement(
            id=f"{prefix}-label", text=label, font="tiny", x=0, y=y, timeout=timeout
        ),
        types.RectangleElement(
            id=f"{prefix}-background",
            x=17,
            y=y,
            width=36,
            height=5,
            fill="solid",
            fill_colors=["#202838FF"],
            border_width=0,
            timeout=timeout,
        ),
    ]


def dynamic_bar_elements(
    percent: float, y: int, prefix: str, timeout: int | None = None
) -> list[types.DisplayElement]:
    value = max(0.0, min(100.0, percent))
    width = max(1, round(36 * value / 100))
    return [
        types.RectangleElement(
            id=f"{prefix}-value",
            x=17,
            y=y,
            width=width,
            height=5,
            fill="solid",
            fill_colors=[color_for(value)],
            border_width=0,
            timeout=timeout,
        ),
        types.TextElement(
            id=f"{prefix}-percent",
            text=f"{value:2.0f}%",
            font="tiny",
            x=55,
            y=y,
            color=color_for(value),
            timeout=timeout,
        ),
    ]


def static_frame(timeout: int | None = None) -> types.DisplayElements:
    elements = static_bar_elements("CPU", 1, "cpu", timeout)
    elements.extend(static_bar_elements("RAM", 9, "ram", timeout))
    return types.DisplayElements(application_name=APP_NAME, priority=50, elements=elements)


def dynamic_frame(
    cpu: float, memory: float, timeout: int | None = None
) -> types.DisplayElements:
    elements = dynamic_bar_elements(cpu, 1, "cpu", timeout)
    elements.extend(dynamic_bar_elements(memory, 9, "ram", timeout))
    return types.DisplayElements(application_name=APP_NAME, priority=50, elements=elements)


def frame(
    cpu: float, memory: float, timeout: int | None = None
) -> types.DisplayElements:
    elements = static_frame(timeout).elements + dynamic_frame(cpu, memory, timeout).elements
    return types.DisplayElements(application_name=APP_NAME, priority=50, elements=elements)


def interpolate(start: float, end: float, progress: float) -> float:
    return start + (end - start) * progress


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

    cpu = psutil.cpu_percent(interval=None)
    memory = psutil.virtual_memory().percent
    element_timeout = max(5, math.ceil(args.interval * 3))

    try:
        bar.display_draw(frame(cpu, memory, element_timeout))
        while not stopping and not args.once:
            time.sleep(args.interval)
            target_cpu = psutil.cpu_percent(interval=None)
            target_memory = psutil.virtual_memory().percent
            steps = max(1, round(ANIMATION_FPS * min(ANIMATION_SECONDS, args.interval)))
            for step in range(1, steps + 1):
                if stopping:
                    break
                progress = step / steps
                bar.display_draw(
                    frame(
                        interpolate(cpu, target_cpu, progress),
                        interpolate(memory, target_memory, progress),
                        element_timeout,
                    )
                )
                time.sleep(1 / ANIMATION_FPS)
            cpu, memory = target_cpu, target_memory
    finally:
        try:
            bar.display_clear(application_name=APP_NAME)
        finally:
            bar.close()
