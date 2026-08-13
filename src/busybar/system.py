from __future__ import annotations

import argparse
import contextlib
import json
import math
import os
import re
import shutil
import signal
import subprocess
import time
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from threading import Event

import psutil
from busylib import BusyBar, types

from busybar.device import (
    BETTER_CONNECTION_POLL_SECONDS,
    Candidate,
    display_is_busy,
    is_better,
    reconnect_delay,
    resolve,
    same_route,
)
from busybar.output import status
from busybar.system_animation import build_alert_animation

APP_NAME = "macos-system-monitor"
ALERT_ASSET_FILENAME = "system-alerts.anim"
SECONDARY_INTERVAL_SECONDS = 5
PING_TARGET = "1.1.1.1"
GREEN = "#32D17CFF"
YELLOW = "#FFD43BFF"
RED = "#FF3030FF"
WHITE = "#FFFFFFFF"
BACKGROUND = "#101722FF"


@dataclass(frozen=True)
class SecondaryMetrics:
    temperature: float | None
    ping_ms: float | None


@dataclass
class MetricTracker:
    alpha: float
    values: deque[float] = field(default_factory=lambda: deque(maxlen=30))
    smoothed: float | None = None

    def update(self, value: float | None) -> None:
        if value is None:
            return
        self.smoothed = (
            value
            if self.smoothed is None
            else self.alpha * value + (1 - self.alpha) * self.smoothed
        )
        self.values.append(self.smoothed)

    @property
    def peak(self) -> float | None:
        return max(self.values) if self.values else None

    def trend(self, threshold: float) -> str:
        if self.smoothed is None or len(self.values) < 4:
            return "-"
        difference = self.smoothed - self.values[-4]
        if difference >= threshold:
            return "^"
        if difference <= -threshold:
            return "v"
        return "-"


@dataclass
class ThresholdTracker:
    warning: float
    critical: float
    hysteresis: float
    level: int | None = None

    def update(self, value: float | None) -> int | None:
        if value is None:
            return None
        previous = self.level
        if previous is None:
            self.level = (
                2 if value >= self.critical else 1 if value >= self.warning else 0
            )
            return None
        if previous == 2:
            self.level = 1 if value < self.critical - self.hysteresis else 2
        elif previous == 1:
            if value >= self.critical:
                self.level = 2
            elif value < self.warning - self.hysteresis:
                self.level = 0
        elif value >= self.critical:
            self.level = 2
        elif value >= self.warning:
            self.level = 1
        return self.level if self.level > previous else None


@dataclass
class SystemState:
    cpu: MetricTracker = field(default_factory=lambda: MetricTracker(0.35))
    memory: MetricTracker = field(default_factory=lambda: MetricTracker(0.5))
    temperature: MetricTracker = field(default_factory=lambda: MetricTracker(0.35))
    ping: MetricTracker = field(default_factory=lambda: MetricTracker(0.35))
    levels: dict[str, ThresholdTracker] = field(
        default_factory=lambda: {
            "cpu": ThresholdTracker(65, 85, 3),
            "memory": ThresholdTracker(65, 85, 3),
            "temperature": ThresholdTracker(70, 85, 2),
            "ping": ThresholdTracker(30, 80, 5),
        }
    )

    def update(
        self,
        cpu: float | None = None,
        memory: float | None = None,
        secondary: SecondaryMetrics | None = None,
    ) -> tuple[str, int] | None:
        samples = {"cpu": cpu, "memory": memory}
        if secondary is not None:
            samples.update(
                temperature=secondary.temperature,
                ping=secondary.ping_ms,
            )
        alert: tuple[str, int] | None = None
        for name, value in samples.items():
            tracker = getattr(self, name)
            tracker.update(value)
            raised = self.levels[name].update(tracker.smoothed)
            if raised is not None and (alert is None or raised > alert[1]):
                alert = (name, raised)
        return alert


def level_color(level: int | None) -> str:
    return RED if level == 2 else YELLOW if level == 1 else GREEN


def normalized(value: float | None, low: float, high: float) -> float:
    if value is None:
        return 0
    return max(0, min(1, (value - low) / (high - low)))


def format_ping(value: float | None) -> str:
    if value is None:
        return "--ms"
    if value >= 1000:
        return f"{value / 1000:.1f}s"
    return f"{value:.0f}ms"


def metric_elements(
    *,
    prefix: str,
    label: str,
    value_text: str,
    value: float | None,
    peak: float | None,
    low: float,
    high: float,
    trend: str,
    level: int | None,
    x: int,
    y: int,
    timeout: int | None,
) -> list[types.DisplayElement]:
    width = 35
    color = level_color(level)
    value_width = max(1, round(width * normalized(value, low, high)))
    peak_x = x + round((width - 1) * normalized(peak, low, high))
    return [
        types.TextElement(
            id=f"{prefix}-label",
            text=label,
            font="tiny",
            x=x,
            y=y,
            color=WHITE,
            timeout=timeout,
        ),
        types.TextElement(
            id=f"{prefix}-value-text",
            text=value_text,
            font="tiny",
            x=x + 14,
            y=y,
            color=color,
            timeout=timeout,
        ),
        types.TextElement(
            id=f"{prefix}-trend",
            text=trend,
            font="tiny",
            x=x + 31,
            y=y,
            color=color,
            timeout=timeout,
        ),
        types.RectangleElement(
            id=f"{prefix}-background",
            x=x,
            y=y + 6,
            width=width,
            height=1,
            fill="solid",
            fill_colors=[BACKGROUND],
            border_width=0,
            timeout=timeout,
        ),
        types.RectangleElement(
            id=f"{prefix}-value",
            x=x,
            y=y + 6,
            width=value_width,
            height=1,
            fill="solid",
            fill_colors=[color],
            border_width=0,
            timeout=timeout,
        ),
        types.RectangleElement(
            id=f"{prefix}-peak",
            x=peak_x,
            y=y + 6,
            width=1,
            height=1,
            fill="solid",
            fill_colors=[WHITE if peak is not None else BACKGROUND],
            border_width=0,
            timeout=timeout,
        ),
    ]


def overview_frame(
    state: SystemState,
    timeout: int | None = None,
    alert: tuple[str, int] | None = None,
) -> types.DisplayElements:
    specs = (
        ("cpu", "CPU", state.cpu, 0, 100, 2, lambda value: f"{value:.0f}"),
        (
            "temperature",
            "TMP",
            state.temperature,
            30,
            100,
            1,
            lambda value: f"{value:.0f}C",
        ),
        ("memory", "RAM", state.memory, 0, 100, 2, lambda value: f"{value:.0f}"),
        ("ping", "NET", state.ping, 0, 200, 5, format_ping),
    )
    elements: list[types.DisplayElement] = []
    for index, (name, label, tracker, low, high, delta, formatter) in enumerate(specs):
        value = tracker.smoothed
        elements.extend(
            metric_elements(
                prefix=name,
                label=label,
                value_text=formatter(value) if value is not None else "--",
                value=value,
                peak=tracker.peak,
                low=low,
                high=high,
                trend=tracker.trend(delta),
                level=state.levels[name].level,
                x=37 if index % 2 else 0,
                y=8 if index >= 2 else 0,
                timeout=timeout,
            )
        )
    if alert is not None:
        name, level = alert
        elements.append(
            types.AnimationElement(
                id="system-alert",
                path=ALERT_ASSET_FILENAME,
                section=f"{name}-{'critical' if level == 2 else 'warning'}",
                timeout=1,
            )
        )
    return types.DisplayElements(
        application_name=APP_NAME, priority=50, elements=elements
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

    cpu = psutil.cpu_percent(interval=None)
    memory = psutil.virtual_memory().percent
    initial_secondary = (
        sample_secondary_metrics()
        if args.dry_run or args.once
        else SecondaryMetrics(None, None)
    )
    state = SystemState()
    state.update(cpu=cpu, memory=memory, secondary=initial_secondary)

    if args.dry_run:
        payload = overview_frame(state)
        print(json.dumps(payload.model_dump(mode="json", exclude_none=True), indent=2))
        return

    stop_event = Event()

    def stop(_signum: int, _frame: object) -> None:
        stop_event.set()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    element_timeout = max(10, math.ceil(args.interval * 5))
    alert_animation = build_alert_animation()
    bar: BusyBar | None = None
    candidate: Candidate | None = None
    reconnect_attempt = 0
    next_better_connection_poll = 0.0
    display_suppressed = False
    alert_asset_ready = False
    next_secondary_sample = time.monotonic() + SECONDARY_INTERVAL_SECONDS
    probe_future: Future[tuple[BusyBar, Candidate]] | None = None
    probe_executor = ThreadPoolExecutor(
        max_workers=1, thread_name_prefix="busybar-probe"
    )
    sensor_executor = ThreadPoolExecutor(
        max_workers=1, thread_name_prefix="busybar-sensors"
    )
    sensor_future: Future[SecondaryMetrics] | None = (
        None if args.once else sensor_executor.submit(sample_secondary_metrics)
    )

    def draw(alert: tuple[str, int] | None = None) -> bool:
        nonlocal display_suppressed
        if bar is None:
            raise RuntimeError("BUSY Bar is not connected")
        try:
            bar.display_draw(
                overview_frame(
                    state,
                    element_timeout,
                    alert if alert_asset_ready else None,
                )
            )
        except Exception as exc:
            if not display_is_busy(exc):
                raise
            if not display_suppressed:
                status(
                    "Display is owned by a higher-priority mode; waiting",
                    timestamp=args.verbose,
                )
            display_suppressed = True
            return False
        if display_suppressed:
            status("Display available; monitor resumed", timestamp=args.verbose)
        display_suppressed = False
        return True

    def disconnect(exc: Exception) -> None:
        nonlocal bar, candidate, display_suppressed
        route = candidate.name if candidate is not None else "BUSY Bar"
        status(
            f"Lost {route} connection ({type(exc).__name__}); reconnecting",
            timestamp=args.verbose,
        )
        if bar is not None:
            bar.close()
        bar = None
        candidate = None
        display_suppressed = False

    try:
        while not stop_event.is_set():
            if bar is None:
                try:
                    bar, candidate = resolve()
                    try:
                        if not alert_asset_ready:
                            bar.assets_upload(
                                APP_NAME,
                                ALERT_ASSET_FILENAME,
                                alert_animation.data,
                            )
                            alert_asset_ready = True
                    except Exception as exc:
                        if args.verbose:
                            status(
                                f"Alert animation unavailable ({type(exc).__name__}); continuing without alerts",
                                timestamp=True,
                            )
                    draw()
                except Exception as exc:
                    if bar is not None:
                        bar.close()
                    bar = None
                    candidate = None
                    delay = reconnect_delay(reconnect_attempt)
                    reconnect_attempt += 1
                    status(
                        f"BUSY Bar unavailable ({exc}); retrying in {delay}s",
                        timestamp=args.verbose,
                    )
                    stop_event.wait(delay)
                    continue

                status(f"Connected via {candidate.name}", timestamp=args.verbose)
                reconnect_attempt = 0
                next_better_connection_poll = (
                    time.monotonic() + BETTER_CONNECTION_POLL_SECONDS
                )
                if args.once:
                    break

            if stop_event.wait(args.interval):
                break

            try:
                alert = state.update(
                    cpu=psutil.cpu_percent(interval=None),
                    memory=psutil.virtual_memory().percent,
                )
                if sensor_future is not None and sensor_future.done():
                    try:
                        secondary_alert = state.update(secondary=sensor_future.result())
                    except Exception as exc:
                        if args.verbose:
                            status(
                                f"Sensor sample failed ({type(exc).__name__})",
                                timestamp=True,
                            )
                    else:
                        if secondary_alert is not None and (
                            alert is None or secondary_alert[1] > alert[1]
                        ):
                            alert = secondary_alert
                    sensor_future = None

                if probe_future is not None and probe_future.done():
                    try:
                        probe_bar, probe_candidate = probe_future.result()
                    except RuntimeError as exc:
                        if args.verbose:
                            status(f"Transport check failed: {exc}", timestamp=True)
                    else:
                        if same_route(probe_candidate, candidate):
                            probe_bar.close()
                            if args.verbose:
                                status(
                                    f"Connection healthy via {candidate.name}",
                                    timestamp=True,
                                )
                        elif is_better(probe_candidate, candidate):
                            old_bar = bar
                            bar = probe_bar
                            candidate = probe_candidate
                            old_bar.close()
                            draw()
                            status(
                                f"Switched to {candidate.name}",
                                timestamp=args.verbose,
                            )
                        else:
                            probe_bar.close()
                    probe_future = None

                now = time.monotonic()
                if probe_future is None and now >= next_better_connection_poll:
                    if args.verbose:
                        status("Checking for a better connection", timestamp=True)
                    probe_future = probe_executor.submit(resolve)
                    next_better_connection_poll = now + BETTER_CONNECTION_POLL_SECONDS
                if sensor_future is None and now >= next_secondary_sample:
                    sensor_future = sensor_executor.submit(sample_secondary_metrics)
                    next_secondary_sample = now + SECONDARY_INTERVAL_SECONDS

                draw(alert)
            except Exception as exc:
                disconnect(exc)
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
