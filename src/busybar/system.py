from __future__ import annotations

import argparse
import contextlib
import json
import logging
import math
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from threading import Event

import psutil
from busylib import BusyBar, types

from busybar.animation import smoothstep
from busybar.device import (
    BETTER_CONNECTION_POLL_SECONDS,
    Candidate,
    display_is_busy,
    is_better,
    reconnect_delay,
    resolve,
    same_route,
)

APP_NAME = "macos-system-monitor"
ANIMATION_FPS = 12
ANIMATION_SECONDS = 0.75
PAGE_SECONDS = 5
PING_TARGET = "1.1.1.1"

# Slide transitions intentionally position elements beyond the display edge.
logging.getLogger("busylib.client.display").setLevel(logging.ERROR)


@dataclass(frozen=True)
class SecondaryMetrics:
    temperature: float | None
    ping_ms: float | None


def color_for(percent: float) -> str:
    if percent >= 85:
        return "#FF3030FF"
    if percent >= 65:
        return "#FFD43BFF"
    return "#32D17CFF"


def static_bar_elements(
    label: str,
    y: int,
    prefix: str,
    timeout: int | None = None,
    x_offset: int = 0,
) -> list[types.DisplayElement]:
    return [
        types.TextElement(
            id=f"{prefix}-label",
            text=label,
            font="tiny",
            x=x_offset,
            y=y,
            timeout=timeout,
        ),
        types.RectangleElement(
            id=f"{prefix}-background",
            x=17 + x_offset,
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
    percent: float,
    y: int,
    prefix: str,
    timeout: int | None = None,
    *,
    text: str | None = None,
    color: str | None = None,
    x_offset: int = 0,
) -> list[types.DisplayElement]:
    value = max(0.0, min(100.0, percent))
    width = max(1, round(36 * value / 100))
    return [
        types.RectangleElement(
            id=f"{prefix}-value",
            x=17 + x_offset,
            y=y,
            width=width,
            height=5,
            fill="solid",
            fill_colors=[color or color_for(value)],
            border_width=0,
            timeout=timeout,
        ),
        types.TextElement(
            id=f"{prefix}-percent",
            text=text or f"{value:2.0f}%",
            font="tiny",
            x=55 + x_offset,
            y=y,
            color=color or color_for(value),
            timeout=timeout,
        ),
    ]


def static_frame(timeout: int | None = None) -> types.DisplayElements:
    elements = static_bar_elements("CPU", 1, "cpu", timeout)
    elements.extend(static_bar_elements("RAM", 9, "ram", timeout))
    return types.DisplayElements(
        application_name=APP_NAME, priority=50, elements=elements
    )


def dynamic_frame(
    cpu: float, memory: float, timeout: int | None = None
) -> types.DisplayElements:
    elements = dynamic_bar_elements(cpu, 1, "cpu", timeout)
    elements.extend(dynamic_bar_elements(memory, 9, "ram", timeout))
    return types.DisplayElements(
        application_name=APP_NAME, priority=50, elements=elements
    )


def frame(
    cpu: float,
    memory: float,
    timeout: int | None = None,
    x_offset: int = 0,
) -> types.DisplayElements:
    elements = static_bar_elements("CPU", 1, "cpu", timeout, x_offset)
    elements.extend(dynamic_bar_elements(cpu, 1, "cpu", timeout, x_offset=x_offset))
    elements.extend(static_bar_elements("RAM", 9, "ram", timeout, x_offset))
    elements.extend(dynamic_bar_elements(memory, 9, "ram", timeout, x_offset=x_offset))
    return types.DisplayElements(
        application_name=APP_NAME, priority=50, elements=elements
    )


def temperature_color(value: float) -> str:
    if value >= 85:
        return "#FF3030FF"
    if value >= 70:
        return "#FFD43BFF"
    return "#32D17CFF"


def ping_color(value: float) -> str:
    if value > 80:
        return "#FF3030FF"
    if value >= 30:
        return "#FFD43BFF"
    return "#32D17CFF"


def secondary_frame(
    metrics: SecondaryMetrics,
    timeout: int | None = None,
    x_offset: int = 0,
) -> types.DisplayElements:
    temperature = metrics.temperature
    ping_ms = metrics.ping_ms
    temp_value = temperature if temperature is not None else 0
    ping_value = ping_ms if ping_ms is not None else 0
    temp_percent = max(0, min(100, (temp_value - 30) / 70 * 100))
    ping_percent = max(0, min(100, ping_value / 200 * 100))
    elements = static_bar_elements("TMP", 1, "temp", timeout, x_offset)
    elements.extend(
        dynamic_bar_elements(
            temp_percent,
            1,
            "temp",
            timeout,
            text=f"{temperature:.0f}C" if temperature is not None else "--C",
            color=temperature_color(temp_value),
            x_offset=x_offset,
        )
    )
    elements.extend(static_bar_elements("NET", 9, "ping", timeout, x_offset))
    elements.extend(
        dynamic_bar_elements(
            ping_percent,
            9,
            "ping",
            timeout,
            text=f"{ping_ms:.0f}ms" if ping_ms is not None else "--ms",
            color=ping_color(ping_value),
            x_offset=x_offset,
        )
    )
    return types.DisplayElements(
        application_name=APP_NAME, priority=50, elements=elements
    )


def page_frame(
    page: int,
    cpu: float,
    memory: float,
    secondary: SecondaryMetrics,
    timeout: int,
    x_offset: int = 0,
) -> types.DisplayElements:
    if page == 0:
        return frame(cpu, memory, timeout, x_offset)
    return secondary_frame(secondary, timeout, x_offset)


def transition_frame(
    page: int,
    progress: float,
    cpu: float,
    memory: float,
    secondary: SecondaryMetrics,
    timeout: int,
) -> types.DisplayElements:
    outgoing = page_frame(page, cpu, memory, secondary, timeout, -round(72 * progress))
    incoming = page_frame(
        1 - page, cpu, memory, secondary, timeout, round(72 * (1 - progress))
    )
    return types.DisplayElements(
        application_name=APP_NAME,
        priority=50,
        elements=outgoing.elements + incoming.elements,
    )


def sample_secondary_metrics() -> SecondaryMetrics:
    temperature: float | None = None
    ping_ms: float | None = None
    macmon = shutil.which("macmon")
    if macmon:
        try:
            result = subprocess.run(
                [macmon, "pipe", "--samples", "1", "--interval", "250"],
                check=True,
                capture_output=True,
                text=True,
                timeout=3,
            )
            temperature = float(json.loads(result.stdout)["temp"]["cpu_temp_avg"])
        except (
            OSError,
            ValueError,
            KeyError,
            subprocess.SubprocessError,
            json.JSONDecodeError,
        ):
            pass

    target = os.getenv("BUSYBAR_PING_TARGET", PING_TARGET)
    try:
        result = subprocess.run(
            ["/sbin/ping", "-n", "-c", "1", "-W", "1000", target],
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        )
        match = re.search(r"time[=<]([0-9.]+) ms", result.stdout)
        if match:
            ping_ms = float(match.group(1))
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    return SecondaryMetrics(temperature=temperature, ping_ms=ping_ms)


def interpolate(start: float, end: float, progress: float) -> float:
    return start + (end - start) * progress


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Show macOS system metrics on BUSY Bar"
    )
    result.add_argument(
        "--interval", type=float, default=2.0, help="refresh interval in seconds"
    )
    result.add_argument("--once", action="store_true", help="draw one frame and exit")
    result.add_argument(
        "--dry-run",
        action="store_true",
        help="print one frame without contacting the Bar",
    )
    result.add_argument(
        "--verbose", action="store_true", help="report periodic transport health checks"
    )
    return result


def main(argv: list[str] | None = None) -> None:
    args = parser().parse_args(argv)
    if args.interval < 0.25:
        parser().error("--interval must be at least 0.25 seconds")

    psutil.cpu_percent(interval=None)
    time.sleep(min(args.interval, 0.5))

    if args.dry_run:
        payload = secondary_frame(sample_secondary_metrics())
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
    page = 0
    secondary = SecondaryMetrics(None, None)
    next_page_switch = time.monotonic() + PAGE_SECONDS
    probe_future: Future[tuple[BusyBar, Candidate]] | None = None
    probe_executor = ThreadPoolExecutor(
        max_workers=1, thread_name_prefix="busybar-probe"
    )
    sensor_executor = ThreadPoolExecutor(
        max_workers=1, thread_name_prefix="busybar-sensors"
    )
    sensor_future: Future[SecondaryMetrics] | None = sensor_executor.submit(
        sample_secondary_metrics
    )

    try:
        while not stop_event.is_set():
            if bar is None:
                try:
                    bar, candidate = resolve()
                    try:
                        bar.display_draw(
                            page_frame(page, cpu, memory, secondary, element_timeout)
                        )
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
                if sensor_future is not None and sensor_future.done():
                    with contextlib.suppress(Exception):
                        secondary = sensor_future.result()
                    sensor_future = None

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
                                bar.display_draw(
                                    page_frame(
                                        page,
                                        cpu,
                                        memory,
                                        secondary,
                                        element_timeout,
                                    )
                                )
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
                switching_page = time.monotonic() >= next_page_switch
                steps = max(
                    1, round(ANIMATION_FPS * min(ANIMATION_SECONDS, args.interval))
                )
                animation_started = time.monotonic()
                for step in range(1, steps + 1):
                    if stop_event.is_set():
                        break
                    linear_progress = step / steps
                    progress = (
                        smoothstep(linear_progress)
                        if switching_page
                        else linear_progress
                    )
                    try:
                        payload = (
                            transition_frame(
                                page,
                                progress,
                                interpolate(cpu, target_cpu, progress),
                                interpolate(memory, target_memory, progress),
                                secondary,
                                element_timeout,
                            )
                            if switching_page
                            else page_frame(
                                page,
                                interpolate(cpu, target_cpu, progress),
                                interpolate(memory, target_memory, progress),
                                secondary,
                                element_timeout,
                            )
                        )
                        bar.display_draw(payload)
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
                    frame_deadline = animation_started + step / ANIMATION_FPS
                    if stop_event.wait(max(0, frame_deadline - time.monotonic())):
                        break
                cpu, memory = target_cpu, target_memory
                if switching_page:
                    page = 1 - page
                    next_page_switch = time.monotonic() + PAGE_SECONDS
                    if page == 1 and sensor_future is None:
                        sensor_future = sensor_executor.submit(sample_secondary_metrics)
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
        sensor_executor.shutdown(wait=True, cancel_futures=True)
        if bar is not None:
            with contextlib.suppress(Exception):
                bar.display_clear(application_name=APP_NAME)
            bar.close()
