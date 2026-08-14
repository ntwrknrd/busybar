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
from busybar.stock_animation import StockAnimation, StockPage, build_stock_animation

APP_NAME = "stocks"
DEFAULT_SYMBOLS = (
    "AAPL",
    "AMZN",
    "AMD",
    "ANET",
    "AVGO",
    "CCJ",
    "CEG",
    "CSCO",
    "DBRG",
    "DELL",
    "DLR",
    "^DJI",
    "EQIX",
    "GOOG",
    "HPE",
    "IBM",
    "INTC",
    "LRCX",
    "META",
    "MU",
    "NVDA",
    "QTUM",
    "SMR",
    "^GSPC",
    "TSM",
    "VFIAX",
    "VIGAX",
    "VLXVX",
    "VWUAX",
    "VBTLX",
    "VWILX",
)
DEFAULT_REFRESH_SECONDS = 60
DEFAULT_ROTATE_SECONDS = 10
YAHOO_URL = "https://query2.finance.yahoo.com/v8/finance/chart/{symbol}"
ASSET_FILENAMES = ("stocks-a.anim", "stocks-b.anim")


@dataclass(frozen=True)
class HistoryProfile:
    yahoo_range: str
    yahoo_interval: str
    refresh_seconds: int


HISTORY_PROFILES = {
    "daily": HistoryProfile("1d", "5m", DEFAULT_REFRESH_SECONDS),
    "weekly": HistoryProfile("5d", "15m", 5 * 60),
    "monthly": HistoryProfile("1mo", "1h", 15 * 60),
    "yearly": HistoryProfile("1y", "1d", 60 * 60),
}


@dataclass(frozen=True)
class MarketSeries:
    symbol: str
    currency: str
    price: float
    previous_close: float
    timestamps: list[int]
    closes: list[float]
    fetched_at: float

    @property
    def change_percent(self) -> float:
        if not self.previous_close:
            return 0
        return (self.price - self.previous_close) / self.previous_close * 100

    @property
    def change_points(self) -> float:
        return self.price - self.previous_close


def cache_path(history: str = "daily") -> Path:
    root = os.getenv("XDG_CACHE_HOME")
    filename = "stocks.json" if history == "daily" else f"stocks-{history}.json"
    if root:
        return Path(root) / "busybar" / filename
    return Path.home() / "Library" / "Caches" / "busybar" / filename


def load_cache(path: Path) -> dict[str, MarketSeries]:
    try:
        payload = json.loads(path.read_text())
        return {symbol: MarketSeries(**series) for symbol, series in payload.items()}
    except (OSError, TypeError, ValueError, json.JSONDecodeError):
        return {}


def save_cache(path: Path, series: dict[str, MarketSeries]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps({key: asdict(value) for key, value in series.items()})
    )
    temporary.replace(path)


def parse_chart(
    payload: dict[str, Any],
    fetched_at: float | None = None,
    history: str = "daily",
) -> MarketSeries:
    chart = payload["chart"]
    if chart.get("error"):
        raise ValueError(str(chart["error"]))
    result = chart["result"][0]
    meta = result["meta"]
    timestamps = result.get("timestamp", [])
    raw_closes = result["indicators"]["quote"][0]["close"]
    points = [
        (int(timestamp), float(close))
        for timestamp, close in zip(timestamps, raw_closes, strict=False)
        if close is not None
    ]
    if not points:
        raise ValueError("Yahoo returned no price points")
    previous_close = meta.get("previousClose") or meta.get("chartPreviousClose")
    if history != "daily":
        previous_close = points[0][1]
    price = meta.get("regularMarketPrice") or points[-1][1]
    if previous_close is None:
        previous_close = points[0][1]
    return MarketSeries(
        symbol=str(meta["symbol"]).upper(),
        currency=str(meta.get("currency", "")),
        price=float(price),
        previous_close=float(previous_close),
        timestamps=[point[0] for point in points],
        closes=[point[1] for point in points],
        fetched_at=fetched_at if fetched_at is not None else time.time(),
    )


def fetch_symbol(
    symbol: str, history: str = "daily", timeout: float = 8
) -> MarketSeries:
    profile = HISTORY_PROFILES[history]
    encoded = urllib.parse.quote(symbol, safe=".-^")
    query = urllib.parse.urlencode(
        {"interval": profile.yahoo_interval, "range": profile.yahoo_range}
    )
    request = urllib.request.Request(
        f"{YAHOO_URL.format(symbol=encoded)}?{query}",
        headers={"Accept": "application/json", "User-Agent": "busybar/0.1"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return parse_chart(json.load(response), history=history)


def refresh_series(
    symbols: list[str],
    existing: dict[str, MarketSeries],
    history: str = "daily",
) -> tuple[dict[str, MarketSeries], list[str]]:
    updated = dict(existing)
    failures: list[str] = []
    for symbol in symbols:
        try:
            updated[symbol] = fetch_symbol(symbol, history)
        except (OSError, ValueError, KeyError, TypeError, urllib.error.URLError) as exc:
            failures.append(f"{symbol}: {type(exc).__name__}")
    if updated != existing:
        with contextlib.suppress(OSError):
            save_cache(cache_path(history), updated)
    return updated, failures


def animation_pages(
    market: dict[str, MarketSeries],
    symbols: list[str],
    stale_after: float,
    change_mode: str = "percent",
) -> list[StockPage]:
    now = time.time()
    return [
        StockPage(
            symbol=market[symbol].symbol,
            change_percent=market[symbol].change_percent,
            change_points=market[symbol].change_points,
            change_mode=change_mode,
            closes=[market[symbol].previous_close, *market[symbol].closes],
            stale=now - market[symbol].fetched_at > stale_after,
        )
        for symbol in symbols
    ]


def animation_frame(
    filename: str, section: str, timeout: int, *, loop: bool = False
) -> types.DisplayElements:
    return types.DisplayElements(
        application_name=APP_NAME,
        priority=50,
        elements=[
            types.AnimationElement(
                id="stocks-page-animation",
                path=filename,
                section=section,
                loop=loop,
                timeout=timeout,
            )
        ],
    )


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Show rotating stock charts on BUSY Bar"
    )
    result.add_argument("symbols", nargs="*", help="ticker symbols")
    result.add_argument(
        "--rotate",
        type=float,
        default=DEFAULT_ROTATE_SECONDS,
        help="seconds per symbol",
    )
    result.add_argument(
        "--refresh",
        type=float,
        help="quote refresh seconds (default: based on --history)",
    )
    result.add_argument(
        "--history",
        choices=tuple(HISTORY_PROFILES),
        default="daily",
        help="chart history range (default: daily)",
    )
    result.add_argument(
        "--change",
        choices=("percent", "points"),
        default="percent",
        help="change value to display (default: percent)",
    )
    result.add_argument("--once", action="store_true", help="draw one symbol and exit")
    result.add_argument(
        "--dry-run", action="store_true", help="print one frame as JSON"
    )
    result.add_argument(
        "--verbose", action="store_true", help="report refresh and transport checks"
    )
    return result


def configured_symbols(arguments: list[str]) -> list[str]:
    values = arguments
    if not values:
        values = os.getenv("BUSYBAR_STOCK_SYMBOLS", "").split()
    if not values:
        values = list(DEFAULT_SYMBOLS)
    return list(
        dict.fromkeys(value.strip().upper() for value in values if value.strip())
    )


def refresh_seconds(history: str, override: float | None = None) -> float:
    if override is not None:
        return override
    return HISTORY_PROFILES[history].refresh_seconds


def main(argv: list[str] | None = None) -> None:
    args = parser().parse_args(argv)
    data_refresh_seconds = refresh_seconds(args.history, args.refresh)
    if args.rotate < 2:
        parser().error("--rotate must be at least 2 seconds")
    if data_refresh_seconds < 15:
        parser().error("--refresh must be at least 15 seconds")
    if args.verbose:
        profile = HISTORY_PROFILES[args.history]
        status(
            f"Using {args.history} history "
            f"({profile.yahoo_range}/{profile.yahoo_interval}); "
            f"refreshing every {data_refresh_seconds:g}s",
            timestamp=True,
        )
    symbols = configured_symbols(args.symbols)
    market, failures = refresh_series(
        symbols, load_cache(cache_path(args.history)), args.history
    )
    available = [symbol for symbol in symbols if symbol in market]
    if not available:
        parser().error(f"no market data available ({'; '.join(failures)})")
    if failures:
        status(
            f"Yahoo refresh incomplete ({'; '.join(failures)}); using cache",
            timestamp=args.verbose,
        )

    stale_after = data_refresh_seconds * 3
    animation = build_stock_animation(
        animation_pages(market, available, stale_after, args.change), args.rotate
    )
    asset_slot = 0
    asset_filename = ASSET_FILENAMES[asset_slot]
    element_timeout = max(
        120,
        math.ceil(data_refresh_seconds + animation.section_seconds["cycle"] * 2),
    )
    if args.dry_run:
        payload = animation_frame(
            asset_filename, "cycle", element_timeout, loop=True
        )
        print(json.dumps(payload.model_dump(mode="json", exclude_none=True), indent=2))
        print(
            f"animation_asset_bytes={len(animation.data)} sections={len(animation.section_seconds)}",
            file=sys.stderr,
        )
        return

    stop_event = Event()

    def stop(_signum: int, _frame: object) -> None:
        stop_event.set()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    index = 0
    bar: BusyBar | None = None
    candidate: Candidate | None = None
    asset_uploaded = False
    reconnect_attempt = 0
    display_suppressed = False
    refresh_failures = 0
    next_refresh = time.monotonic() + data_refresh_seconds
    next_probe = 0.0
    refresh_future: Future[tuple[dict[str, MarketSeries], list[str]]] | None = None
    probe_future: Future[tuple[BusyBar, Candidate]] | None = None
    pending_update: tuple[
        dict[str, MarketSeries], list[str], StockAnimation, int, str
    ] | None = None
    refresh_executor = ThreadPoolExecutor(
        max_workers=1, thread_name_prefix="stocks-data"
    )
    probe_executor = ThreadPoolExecutor(
        max_workers=1, thread_name_prefix="busybar-probe"
    )

    def draw(payload: types.DisplayElements) -> bool:
        nonlocal display_suppressed
        if bar is None:
            raise RuntimeError("BUSY Bar is not connected")
        try:
            bar.display_draw(payload)
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
            status("Display available; stocks resumed", timestamp=args.verbose)
        display_suppressed = False
        return True

    def start_animation() -> bool:
        return draw(
            animation_frame(
                asset_filename, "cycle", element_timeout, loop=True
            )
        )

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
                try:
                    start_animation()
                except Exception as exc:
                    disconnect(exc)
                    continue

            if args.once:
                break

            wait_until = time.monotonic() + args.rotate
            while not stop_event.is_set() and time.monotonic() < wait_until:
                if refresh_future is not None and refresh_future.done():
                    refreshed, refresh_errors = refresh_future.result()
                    refresh_future = None
                    refreshed_available = [
                        symbol for symbol in symbols if symbol in refreshed
                    ]
                    refreshed_animation = build_stock_animation(
                        animation_pages(
                            refreshed,
                            refreshed_available,
                            stale_after,
                            args.change,
                        ),
                        args.rotate,
                    )
                    refreshed_slot = 1 - asset_slot
                    refreshed_filename = ASSET_FILENAMES[refreshed_slot]
                    try:
                        bar.assets_upload(
                            APP_NAME,
                            refreshed_filename,
                            refreshed_animation.data,
                        )
                    except Exception as exc:
                        status(
                            f"Animation asset refresh failed ({type(exc).__name__}); keeping previous data",
                            timestamp=args.verbose,
                        )
                        next_refresh = time.monotonic() + data_refresh_seconds
                    else:
                        pending_update = (
                            refreshed,
                            refreshed_available,
                            refreshed_animation,
                            refreshed_slot,
                            refreshed_filename,
                        )
                    if refresh_errors:
                        refresh_failures += 1
                        delay = min(
                            max(300, data_refresh_seconds * 4),
                            data_refresh_seconds * (2 ** min(refresh_failures, 3)),
                        )
                        next_refresh = time.monotonic() + delay
                        status(
                            f"Yahoo refresh failed ({'; '.join(refresh_errors)}); retrying in {delay:.0f}s",
                            timestamp=args.verbose,
                        )
                    else:
                        refresh_failures = 0
                        next_refresh = time.monotonic() + data_refresh_seconds
                        if args.verbose:
                            status("Yahoo quotes refreshed", timestamp=True)

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
                            status(
                                f"Switched to {candidate.name}",
                                timestamp=args.verbose,
                            )
                        else:
                            probe_bar.close()
                    probe_future = None

                now = time.monotonic()
                if refresh_future is None and now >= next_refresh:
                    refresh_future = refresh_executor.submit(
                        refresh_series, symbols, market, args.history
                    )
                    next_refresh = math.inf
                if probe_future is None and now >= next_probe:
                    probe_future = probe_executor.submit(resolve)
                    next_probe = now + BETTER_CONNECTION_POLL_SECONDS
                stop_event.wait(min(0.25, max(0, wait_until - now)))

            if stop_event.is_set():
                break
            if bar is None:
                continue
            if len(available) == 1:
                continue
            target = (index + 1) % len(available)
            try:
                if args.verbose:
                    status(f"Showing {available[target]}", timestamp=True)
                stop_event.wait(animation.section_seconds[f"to_{target}"])
                if target == 0 and pending_update is not None:
                    (
                        market,
                        available,
                        animation,
                        asset_slot,
                        asset_filename,
                    ) = pending_update
                    pending_update = None
                    element_timeout = max(
                        120,
                        math.ceil(
                            data_refresh_seconds
                            + animation.section_seconds["cycle"] * 2
                        ),
                    )
                    start_animation()
            except Exception as exc:
                disconnect(exc)
                continue
            index = target
    finally:
        probe_executor.shutdown(wait=True, cancel_futures=True)
        refresh_executor.shutdown(wait=True, cancel_futures=True)
        if bar is not None:
            with contextlib.suppress(Exception):
                bar.display_clear(application_name=APP_NAME)
            bar.close()
