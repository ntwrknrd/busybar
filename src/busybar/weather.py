from __future__ import annotations

import argparse
import contextlib
import json
import math
import os
import signal
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import Event
from typing import Any

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
from busybar.weather_animation import (
    DayForecast,
    HourForecast,
    WeatherAnimation,
    WeatherSnapshot,
    build_weather_animation,
)

APP_NAME = "weather"
DEFAULT_LOCATION = "Indianapolis, Indiana"
DEFAULT_REFRESH_SECONDS = 900
DEFAULT_DWELL_SECONDS = 8
GEOCODING_URL = "https://geocoding-api.open-meteo.com/v1/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ASSET_FILENAMES = ("weather-a.anim", "weather-b.anim")


@dataclass(frozen=True)
class Location:
    name: str
    latitude: float
    longitude: float
    timezone: str


@dataclass(frozen=True)
class WeatherRecord:
    query: str
    units: str
    location: Location
    snapshot: WeatherSnapshot
    fetched_at: float


def cache_path() -> Path:
    root = os.getenv("XDG_CACHE_HOME")
    if root:
        return Path(root) / "busybar" / "weather.json"
    return Path.home() / "Library" / "Caches" / "busybar" / "weather.json"


def load_cache(path: Path) -> WeatherRecord | None:
    try:
        payload = json.loads(path.read_text())
        snapshot = payload["snapshot"]
        return WeatherRecord(
            query=payload["query"],
            units=payload["units"],
            location=Location(**payload["location"]),
            snapshot=WeatherSnapshot(
                location=snapshot["location"],
                temperature=snapshot["temperature"],
                apparent_temperature=snapshot["apparent_temperature"],
                weather_code=snapshot["weather_code"],
                hourly=[HourForecast(**hour) for hour in snapshot["hourly"]],
                daily=[DayForecast(**day) for day in snapshot["daily"]],
                temperature_suffix=snapshot["temperature_suffix"],
            ),
            fetched_at=payload["fetched_at"],
        )
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def save_cache(path: Path, record: WeatherRecord) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(asdict(record)))
    temporary.replace(path)


def _get_json(url: str, params: dict[str, object], timeout: float = 8) -> Any:
    query = urllib.parse.urlencode(params)
    request = urllib.request.Request(
        f"{url}?{query}",
        headers={"Accept": "application/json", "User-Agent": "busybar/0.1"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def geocode(query: str) -> Location:
    payload = _get_json(GEOCODING_URL, {"name": query, "count": 1, "language": "en"})
    results = payload.get("results", [])
    if not results:
        raise ValueError(f"location not found: {query}")
    result = results[0]
    label = str(result["name"])
    admin = result.get("admin1")
    if admin and str(admin).casefold() != label.casefold():
        label = f"{label}, {admin}"
    return Location(
        name=label,
        latitude=float(result["latitude"]),
        longitude=float(result["longitude"]),
        timezone=str(result["timezone"]),
    )


def parse_forecast(
    payload: dict[str, Any], location: Location, units: str
) -> WeatherSnapshot:
    current = payload["current"]
    hourly = payload["hourly"]
    daily = payload["daily"]
    current_time = str(current["time"])
    hours = [
        HourForecast(str(timestamp), float(temperature), float(probability or 0))
        for timestamp, temperature, probability in zip(
            hourly["time"],
            hourly["temperature_2m"],
            hourly["precipitation_probability"],
            strict=False,
        )
        if str(timestamp) >= current_time
    ][:12]
    days = [
        DayForecast(str(date), int(code), float(high), float(low))
        for date, code, high, low in zip(
            daily["time"],
            daily["weather_code"],
            daily["temperature_2m_max"],
            daily["temperature_2m_min"],
            strict=False,
        )
    ][:3]
    return WeatherSnapshot(
        location=location.name.split(",", 1)[0],
        temperature=float(current["temperature_2m"]),
        apparent_temperature=float(current["apparent_temperature"]),
        weather_code=int(current["weather_code"]),
        hourly=hours,
        daily=days,
        temperature_suffix="F" if units == "fahrenheit" else "C",
    )


def fetch_forecast(location: Location, units: str) -> WeatherSnapshot:
    temperature_unit = "fahrenheit" if units == "fahrenheit" else "celsius"
    payload = _get_json(
        FORECAST_URL,
        {
            "latitude": location.latitude,
            "longitude": location.longitude,
            "timezone": location.timezone,
            "temperature_unit": temperature_unit,
            "wind_speed_unit": "mph" if units == "fahrenheit" else "kmh",
            "current": "temperature_2m,apparent_temperature,weather_code",
            "hourly": "temperature_2m,precipitation_probability",
            "daily": "weather_code,temperature_2m_max,temperature_2m_min",
            "forecast_days": 4,
        },
    )
    return parse_forecast(payload, location, units)


def refresh_weather(
    query: str, units: str, existing: WeatherRecord | None
) -> WeatherRecord:
    location = (
        existing.location
        if existing is not None
        and existing.query.casefold() == query.casefold()
        and existing.units == units
        else geocode(query)
    )
    record = WeatherRecord(
        query=query,
        units=units,
        location=location,
        snapshot=fetch_forecast(location, units),
        fetched_at=time.time(),
    )
    with contextlib.suppress(OSError):
        save_cache(cache_path(), record)
    return record


def animation_frame(filename: str, timeout: int) -> types.DisplayElements:
    return types.DisplayElements(
        application_name=APP_NAME,
        priority=50,
        elements=[
            types.AnimationElement(
                id="weather-cycle",
                path=filename,
                section="cycle",
                loop=True,
                timeout=timeout,
            )
        ],
    )


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Show current conditions and forecasts on BUSY Bar"
    )
    result.add_argument(
        "location",
        nargs="?",
        help=f"city or postal code (default: {DEFAULT_LOCATION})",
    )
    result.add_argument(
        "--units",
        choices=("fahrenheit", "celsius"),
        default=os.getenv("BUSYBAR_WEATHER_UNITS", "fahrenheit"),
    )
    result.add_argument(
        "--refresh",
        type=float,
        default=DEFAULT_REFRESH_SECONDS,
        help="forecast refresh seconds",
    )
    result.add_argument(
        "--dwell",
        type=float,
        default=DEFAULT_DWELL_SECONDS,
        help="seconds per weather page",
    )
    result.add_argument("--once", action="store_true", help="draw once and exit")
    result.add_argument(
        "--dry-run", action="store_true", help="build without contacting the Bar"
    )
    result.add_argument("--verbose", action="store_true", help="report diagnostics")
    return result


def main(argv: list[str] | None = None) -> None:
    args = parser().parse_args(argv)
    if args.refresh < 300:
        parser().error("--refresh must be at least 300 seconds")
    if args.dwell < 2:
        parser().error("--dwell must be at least 2 seconds")
    query = args.location or os.getenv("BUSYBAR_WEATHER_LOCATION") or DEFAULT_LOCATION
    cached = load_cache(cache_path())
    try:
        record = refresh_weather(query, args.units, cached)
    except (OSError, KeyError, TypeError, ValueError, urllib.error.URLError) as exc:
        if (
            cached is None
            or cached.query.casefold() != query.casefold()
            or cached.units != args.units
        ):
            parser().error(f"weather unavailable ({type(exc).__name__}: {exc})")
        record = cached
        status(
            f"Weather refresh failed ({type(exc).__name__}); using cache",
            timestamp=args.verbose,
        )

    animation = build_weather_animation(record.snapshot, args.dwell)
    asset_slot = 0
    asset_filename = ASSET_FILENAMES[asset_slot]
    element_timeout = max(1800, math.ceil(args.refresh + animation.cycle_seconds * 2))
    if args.dry_run:
        print(
            json.dumps(
                animation_frame(asset_filename, element_timeout).model_dump(
                    mode="json", exclude_none=True
                ),
                indent=2,
            )
        )
        print(
            f"location={record.location.name} animation_asset_bytes={len(animation.data)}",
            file=sys.stderr,
        )
        return

    stop_event = Event()

    def stop(_signum: int, _frame: object) -> None:
        stop_event.set()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    bar: BusyBar | None = None
    candidate: Candidate | None = None
    asset_uploaded = False
    display_suppressed = False
    reconnect_attempt = 0
    next_refresh = time.monotonic() + args.refresh
    next_probe = 0.0
    next_cycle = time.monotonic() + animation.cycle_seconds
    refresh_future: Future[WeatherRecord] | None = None
    probe_future: Future[tuple[BusyBar, Candidate]] | None = None
    pending: tuple[WeatherRecord, WeatherAnimation, int, str] | None = None
    refresh_executor = ThreadPoolExecutor(
        max_workers=1, thread_name_prefix="weather-data"
    )
    probe_executor = ThreadPoolExecutor(
        max_workers=1, thread_name_prefix="busybar-probe"
    )

    def draw() -> bool:
        nonlocal display_suppressed
        if bar is None:
            raise RuntimeError("BUSY Bar is not connected")
        try:
            bar.display_draw(animation_frame(asset_filename, element_timeout))
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
            status("Display available; weather resumed", timestamp=args.verbose)
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
                    if not asset_uploaded:
                        bar.assets_upload(APP_NAME, asset_filename, animation.data)
                        asset_uploaded = True
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
                next_probe = time.monotonic() + BETTER_CONNECTION_POLL_SECONDS
                next_cycle = time.monotonic() + animation.cycle_seconds
                if args.once:
                    break

            if stop_event.wait(0.25):
                break
            now = time.monotonic()
            try:
                if refresh_future is not None and refresh_future.done():
                    try:
                        refreshed = refresh_future.result()
                    except Exception as exc:
                        status(
                            f"Weather refresh failed ({type(exc).__name__}); keeping cache",
                            timestamp=args.verbose,
                        )
                    else:
                        refreshed_animation = build_weather_animation(
                            refreshed.snapshot, args.dwell
                        )
                        refreshed_slot = 1 - asset_slot
                        refreshed_filename = ASSET_FILENAMES[refreshed_slot]
                        try:
                            bar.assets_upload(
                                APP_NAME, refreshed_filename, refreshed_animation.data
                            )
                        except Exception as exc:
                            status(
                                f"Weather asset refresh failed ({type(exc).__name__}); keeping previous forecast",
                                timestamp=args.verbose,
                            )
                        else:
                            pending = (
                                refreshed,
                                refreshed_animation,
                                refreshed_slot,
                                refreshed_filename,
                            )
                            if args.verbose:
                                status("Weather forecast refreshed", timestamp=True)
                    refresh_future = None
                    next_refresh = now + args.refresh

                if probe_future is not None and probe_future.done():
                    try:
                        probe_bar, probe_candidate = probe_future.result()
                    except RuntimeError as exc:
                        if args.verbose:
                            status(f"Transport check failed: {exc}", timestamp=True)
                    else:
                        if same_route(probe_candidate, candidate):
                            probe_bar.close()
                        elif is_better(probe_candidate, candidate):
                            old_bar = bar
                            bar = probe_bar
                            candidate = probe_candidate
                            old_bar.close()
                            draw()
                            status(
                                f"Switched to {candidate.name}", timestamp=args.verbose
                            )
                        else:
                            probe_bar.close()
                    probe_future = None

                if pending is not None and now >= next_cycle:
                    record, animation, asset_slot, asset_filename = pending
                    pending = None
                    element_timeout = max(
                        1800, math.ceil(args.refresh + animation.cycle_seconds * 2)
                    )
                    draw()
                    next_cycle = now + animation.cycle_seconds
                elif now >= next_cycle:
                    next_cycle += animation.cycle_seconds

                if refresh_future is None and now >= next_refresh:
                    refresh_future = refresh_executor.submit(
                        refresh_weather, query, args.units, record
                    )
                    next_refresh = math.inf
                if probe_future is None and now >= next_probe:
                    probe_future = probe_executor.submit(resolve)
                    next_probe = now + BETTER_CONNECTION_POLL_SECONDS
            except Exception as exc:
                disconnect(exc)
    finally:
        probe_executor.shutdown(wait=True, cancel_futures=True)
        refresh_executor.shutdown(wait=True, cancel_futures=True)
        if bar is not None:
            with contextlib.suppress(Exception):
                bar.display_clear(application_name=APP_NAME)
            bar.close()
