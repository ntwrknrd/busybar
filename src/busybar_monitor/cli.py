from __future__ import annotations

import argparse
import contextlib
import json
import math
import os
import signal
import sys
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from threading import Event
from typing import Iterator

import psutil
from busylib import BusyBar, BusyBarDevices, exceptions, types

APP_NAME = "macos-system-monitor"
USB_ADDRESS = "10.0.4.20"
ANIMATION_FPS = 10
ANIMATION_SECONDS = 0.5
BETTER_CONNECTION_POLL_SECONDS = 30
RECONNECT_DELAYS = (1, 2, 5, 10, 30)


@dataclass(frozen=True)
class Candidate:
    name: str
    address: str | None
    token: str | None
    rank: int

    def connect(self) -> BusyBar:
        if self.name == "cloud":
            return BusyBar(token=self.token, timeout=3, max_retries=0)
        return BusyBar(self.address, token=self.token, timeout=2, max_retries=0)


def candidates() -> Iterator[Candidate]:
    lan_token = os.getenv("BUSYBAR_LAN_TOKEN") or None
    seen: set[str] = set()
    found: list[Candidate] = []

    try:
        devices = BusyBarDevices.discover()
    except Exception:
        devices = []

    for device in devices:
        for affinity, token, rank in (
            ("over_usb", None, 0),
            ("over_wifi", lan_token, 1),
        ):
            address = device.get_address(affinity)
            if address and address not in seen:
                seen.add(address)
                found.append(
                    Candidate(
                        f"mDNS {affinity.removeprefix('over_')}", address, token, rank
                    )
                )

    if USB_ADDRESS not in seen:
        seen.add(USB_ADDRESS)
        found.append(Candidate("USB", USB_ADDRESS, None, 0))

    home_address = os.getenv("BUSYBAR_HOME_IP")
    if home_address and home_address not in seen:
        seen.add(home_address)
        found.append(Candidate("home LAN", home_address, lan_token, 1))

    cloud_token = os.getenv("BUSYBAR_CLOUD_TOKEN")
    if cloud_token:
        found.append(Candidate("cloud", None, cloud_token, 2))

    yield from sorted(found, key=lambda candidate: candidate.rank)


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


def reconnect_delay(attempt: int) -> int:
    return RECONNECT_DELAYS[min(attempt, len(RECONNECT_DELAYS) - 1)]


def same_route(left: Candidate, right: Candidate) -> bool:
    return left.address == right.address and left.rank == right.rank


def is_better(new: Candidate, current: Candidate) -> bool:
    return new.rank < current.rank


def display_is_busy(exc: Exception) -> bool:
    return isinstance(exc, exceptions.BusyBarAPIError) and exc.status_code == 409


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Show macOS CPU and RAM usage on BUSY Bar")
    result.add_argument("--interval", type=float, default=2.0, help="refresh interval in seconds")
    result.add_argument("--once", action="store_true", help="draw one frame and exit")
    result.add_argument("--dry-run", action="store_true", help="print one frame without contacting the Bar")
    result.add_argument(
        "--verbose", action="store_true", help="report periodic transport health checks"
    )
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

    stop_event = Event()

    def stop(_signum: int, _frame: object) -> None:
        stop_event.set()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    cpu = psutil.cpu_percent(interval=None)
    memory = psutil.virtual_memory().percent
    element_timeout = max(10, math.ceil(args.interval * 5))
    bar: BusyBar | None = None
    candidate: Candidate | None = None
    reconnect_attempt = 0
    next_better_connection_poll = 0.0
    display_suppressed = False
    probe_future: Future[tuple[BusyBar, Candidate]] | None = None
    probe_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="busybar-probe")

    try:
        while not stop_event.is_set():
            if bar is None:
                try:
                    bar, candidate = resolve()
                    try:
                        bar.display_draw(frame(cpu, memory, element_timeout))
                    except Exception as exc:
                        if not display_is_busy(exc):
                            raise
                        display_suppressed = True
                except Exception as exc:
                    if bar is not None:
                        bar.close()
                    bar = None
                    candidate = None
                    delay = reconnect_delay(reconnect_attempt)
                    reconnect_attempt += 1
                    print(
                        f"BUSY Bar unavailable ({exc}); retrying in {delay}s",
                        file=sys.stderr,
                    )
                    stop_event.wait(delay)
                    continue

                print(f"Connected via {candidate.name}", file=sys.stderr)
                if display_suppressed:
                    print(
                        "Display is owned by a higher-priority mode; waiting",
                        file=sys.stderr,
                    )
                reconnect_attempt = 0
                next_better_connection_poll = (
                    time.monotonic() + BETTER_CONNECTION_POLL_SECONDS
                )
                if args.once:
                    break

            try:
                if probe_future is not None and probe_future.done():
                    try:
                        probe_bar, probe_candidate = probe_future.result()
                    except RuntimeError as exc:
                        if args.verbose:
                            print(f"Transport check failed: {exc}", file=sys.stderr)
                    else:
                        if same_route(probe_candidate, candidate):
                            probe_bar.close()
                            if args.verbose:
                                print(
                                    f"Connection healthy via {candidate.name}",
                                    file=sys.stderr,
                                )
                        elif is_better(probe_candidate, candidate):
                            old_bar = bar
                            bar = probe_bar
                            candidate = probe_candidate
                            old_bar.close()
                            try:
                                bar.display_draw(frame(cpu, memory, element_timeout))
                            except Exception as exc:
                                if not display_is_busy(exc):
                                    raise
                                display_suppressed = True
                            print(f"Switched to {candidate.name}", file=sys.stderr)
                        else:
                            probe_bar.close()
                    probe_future = None

                if (
                    probe_future is None
                    and time.monotonic() >= next_better_connection_poll
                ):
                    if args.verbose:
                        print("Checking for a better connection", file=sys.stderr)
                    probe_future = probe_executor.submit(resolve)
                    next_better_connection_poll = (
                        time.monotonic() + BETTER_CONNECTION_POLL_SECONDS
                    )

                if stop_event.wait(args.interval):
                    break
                target_cpu = psutil.cpu_percent(interval=None)
                target_memory = psutil.virtual_memory().percent
                steps = max(
                    1, round(ANIMATION_FPS * min(ANIMATION_SECONDS, args.interval))
                )
                for step in range(1, steps + 1):
                    if stop_event.is_set():
                        break
                    progress = step / steps
                    try:
                        bar.display_draw(
                            frame(
                                interpolate(cpu, target_cpu, progress),
                                interpolate(memory, target_memory, progress),
                                element_timeout,
                            )
                        )
                    except Exception as exc:
                        if not display_is_busy(exc):
                            raise
                        if not display_suppressed:
                            print(
                                "Display is owned by a higher-priority mode; waiting",
                                file=sys.stderr,
                            )
                        display_suppressed = True
                        break
                    else:
                        if display_suppressed:
                            print("Display available; monitor resumed", file=sys.stderr)
                        display_suppressed = False
                    if stop_event.wait(1 / ANIMATION_FPS):
                        break
                cpu, memory = target_cpu, target_memory
            except Exception as exc:
                print(
                    f"Lost {candidate.name} connection ({type(exc).__name__}); reconnecting",
                    file=sys.stderr,
                )
                bar.close()
                bar = None
                candidate = None
                display_suppressed = False
    finally:
        if probe_future is not None and probe_future.done():
            with contextlib.suppress(Exception):
                probe_bar, _probe_candidate = probe_future.result()
                probe_bar.close()
        probe_executor.shutdown(wait=True, cancel_futures=True)
        if bar is not None:
            with contextlib.suppress(Exception):
                bar.display_clear(application_name=APP_NAME)
            bar.close()
