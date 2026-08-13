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
from itertools import pairwise
from pathlib import Path
from threading import Event
from typing import Any

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

APP_NAME = "stocks"
BACKGROUND = "#101722FF"
GREEN = "#32D17CFF"
RED = "#FF5964FF"
STALE = "#FFD43BFF"
DEFAULT_SYMBOLS = ("AAPL", "MSFT", "NVDA")
DEFAULT_REFRESH_SECONDS = 60
DEFAULT_ROTATE_SECONDS = 10
GRAPH_Y = 8
GRAPH_HEIGHT = 8
GRAPH_POINTS = 36
ANIMATION_FPS = 8
ANIMATION_SECONDS = 0.75
YAHOO_URL = "https://query2.finance.yahoo.com/v8/finance/chart/{symbol}"


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


def cache_path() -> Path:
    root = os.getenv("XDG_CACHE_HOME")
    if root:
        return Path(root) / "busybar" / "stocks.json"
    return Path.home() / "Library" / "Caches" / "busybar" / "stocks.json"


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
    payload: dict[str, Any], fetched_at: float | None = None
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


def fetch_symbol(symbol: str, timeout: float = 8) -> MarketSeries:
    encoded = urllib.parse.quote(symbol, safe=".-^")
    query = urllib.parse.urlencode({"interval": "5m", "range": "1d"})
    request = urllib.request.Request(
        f"{YAHOO_URL.format(symbol=encoded)}?{query}",
        headers={"Accept": "application/json", "User-Agent": "busybar/0.1"},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return parse_chart(json.load(response))


def refresh_series(
    symbols: list[str], existing: dict[str, MarketSeries]
) -> tuple[dict[str, MarketSeries], list[str]]:
    updated = dict(existing)
    failures: list[str] = []
    for symbol in symbols:
        try:
            updated[symbol] = fetch_symbol(symbol)
        except (OSError, ValueError, KeyError, TypeError, urllib.error.URLError) as exc:
            failures.append(f"{symbol}: {type(exc).__name__}")
    if updated != existing:
        with contextlib.suppress(OSError):
            save_cache(cache_path(), updated)
    return updated, failures


def sample_values(values: list[float], count: int = GRAPH_POINTS) -> list[float]:
    if len(values) <= count:
        return values
    return [
        values[round(index * (len(values) - 1) / (count - 1))] for index in range(count)
    ]


def graph_segments(values: list[float]) -> list[tuple[int, int, int]]:
    sampled = sample_values(values)
    if len(sampled) < 2:
        return []
    low, high = min(sampled), max(sampled)
    spread = high - low

    def ordinate(value: float) -> int:
        if spread == 0:
            return GRAPH_Y + GRAPH_HEIGHT // 2
        return (
            GRAPH_Y
            + GRAPH_HEIGHT
            - 1
            - round((value - low) / spread * (GRAPH_HEIGHT - 1))
        )

    ordinates = [ordinate(value) for value in sampled]
    width = max(1, 72 // (len(ordinates) - 1))
    return [
        (index * width, min(left, right), abs(right - left) + 1)
        for index, (left, right) in enumerate(pairwise(ordinates))
    ]


def format_price(price: float) -> str:
    if price >= 1000:
        return f"{price:.0f}"
    if price >= 100:
        return f"{price:.1f}"
    return f"{price:.2f}"


def stock_frame(
    series: MarketSeries,
    timeout: int,
    *,
    reveal: float = 1,
    x_offset: int = 0,
    stale_after: float = DEFAULT_REFRESH_SECONDS * 3,
) -> types.DisplayElements:
    change = series.change_percent
    color = GREEN if change >= 0 else RED
    if time.time() - series.fetched_at > stale_after:
        color = STALE
    segments = graph_segments(series.closes)
    visible = round(len(segments) * max(0, min(1, reveal)))
    elements: list[types.DisplayElement] = [
        types.RectangleElement(
            id="stocks-background",
            x=0,
            y=GRAPH_Y,
            width=72,
            height=GRAPH_HEIGHT,
            fill="solid",
            fill_colors=[BACKGROUND],
            border_width=0,
            timeout=timeout,
        ),
        types.TextElement(
            id="stocks-symbol",
            text=series.symbol[:6],
            font="tiny",
            x=x_offset,
            y=0,
            color="#FFFFFFFF",
            timeout=timeout,
        ),
        types.TextElement(
            id="stocks-price",
            text=format_price(series.price),
            font="tiny",
            x=25 + x_offset,
            y=0,
            color="#FFFFFFFF",
            timeout=timeout,
        ),
        types.TextElement(
            id="stocks-change",
            text=f"{change:+.1f}%",
            font="tiny",
            x=51 + x_offset,
            y=0,
            color=color,
            timeout=timeout,
        ),
    ]
    for index, (x, y, height) in enumerate(segments):
        elements.append(
            types.RectangleElement(
                id=f"stocks-graph-{index}",
                x=x,
                y=y,
                width=2,
                height=height,
                fill="solid",
                fill_colors=[color if index < visible else BACKGROUND],
                border_width=0,
                timeout=timeout,
            )
        )
    return types.DisplayElements(
        application_name=APP_NAME, priority=50, elements=elements
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
        default=DEFAULT_REFRESH_SECONDS,
        help="quote refresh seconds",
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


def main(argv: list[str] | None = None) -> None:
    args = parser().parse_args(argv)
    if args.rotate < 2:
        parser().error("--rotate must be at least 2 seconds")
    if args.refresh < 15:
        parser().error("--refresh must be at least 15 seconds")
    symbols = configured_symbols(args.symbols)
    market, failures = refresh_series(symbols, load_cache(cache_path()))
    available = [symbol for symbol in symbols if symbol in market]
    if not available:
        parser().error(f"no market data available ({'; '.join(failures)})")
    if failures:
        print(
            f"Yahoo refresh incomplete ({'; '.join(failures)}); using cache",
            file=sys.stderr,
        )

    element_timeout = max(15, math.ceil(args.rotate * 3))
    if args.dry_run:
        payload = stock_frame(market[available[0]], element_timeout)
        print(json.dumps(payload.model_dump(mode="json", exclude_none=True), indent=2))
        return

    stop_event = Event()

    def stop(_signum: int, _frame: object) -> None:
        stop_event.set()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    index = 0
    bar: BusyBar | None = None
    candidate: Candidate | None = None
    reconnect_attempt = 0
    display_suppressed = False
    refresh_failures = 0
    next_refresh = time.monotonic() + args.refresh
    next_probe = 0.0
    refresh_future: Future[tuple[dict[str, MarketSeries], list[str]]] | None = None
    probe_future: Future[tuple[BusyBar, Candidate]] | None = None
    refresh_executor = ThreadPoolExecutor(
        max_workers=1, thread_name_prefix="stocks-data"
    )
    probe_executor = ThreadPoolExecutor(
        max_workers=1, thread_name_prefix="busybar-probe"
    )

    try:
        while not stop_event.is_set():
            if bar is None:
                try:
                    bar, candidate = resolve()
                except Exception as exc:
                    delay = reconnect_delay(reconnect_attempt)
                    reconnect_attempt += 1
                    print(
                        f"BUSY Bar unavailable ({exc}); retrying in {delay}s",
                        file=sys.stderr,
                    )
                    stop_event.wait(delay)
                    continue
                print(f"Connected via {candidate.name}", file=sys.stderr)
                reconnect_attempt = 0
                next_probe = time.monotonic() + BETTER_CONNECTION_POLL_SECONDS

            series = market[available[index]]
            steps = 1 if args.once else max(1, round(ANIMATION_FPS * ANIMATION_SECONDS))
            animation_started = time.monotonic()
            try:
                for step in range(1, steps + 1):
                    progress = smoothstep(step / steps)
                    try:
                        bar.display_draw(
                            stock_frame(
                                series,
                                element_timeout,
                                reveal=progress,
                                x_offset=round(12 * (1 - progress)),
                                stale_after=args.refresh * 3,
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
                            print("Display available; stocks resumed", file=sys.stderr)
                        display_suppressed = False
                    deadline = animation_started + step / ANIMATION_FPS
                    if stop_event.wait(max(0, deadline - time.monotonic())):
                        break
            except Exception as exc:
                print(
                    f"Lost {candidate.name} connection ({type(exc).__name__}); reconnecting",
                    file=sys.stderr,
                )
                bar.close()
                bar = None
                candidate = None
                display_suppressed = False
                continue

            if args.once:
                break

            wait_until = time.monotonic() + args.rotate
            while not stop_event.is_set() and time.monotonic() < wait_until:
                if refresh_future is not None and refresh_future.done():
                    refreshed, refresh_errors = refresh_future.result()
                    market = refreshed
                    available = [symbol for symbol in symbols if symbol in market]
                    refresh_future = None
                    if refresh_errors:
                        refresh_failures += 1
                        delay = min(300, args.refresh * (2 ** min(refresh_failures, 3)))
                        next_refresh = time.monotonic() + delay
                        print(
                            f"Yahoo refresh failed ({'; '.join(refresh_errors)}); retrying in {delay:.0f}s",
                            file=sys.stderr,
                        )
                    else:
                        refresh_failures = 0
                        next_refresh = time.monotonic() + args.refresh
                        if args.verbose:
                            print("Yahoo quotes refreshed", file=sys.stderr)

                if probe_future is not None and probe_future.done():
                    try:
                        probe_bar, probe_candidate = probe_future.result()
                    except RuntimeError as exc:
                        if args.verbose:
                            print(f"Transport check failed: {exc}", file=sys.stderr)
                    else:
                        if same_route(probe_candidate, candidate):
                            probe_bar.close()
                        elif is_better(probe_candidate, candidate):
                            old_bar = bar
                            bar = probe_bar
                            candidate = probe_candidate
                            old_bar.close()
                            print(f"Switched to {candidate.name}", file=sys.stderr)
                        else:
                            probe_bar.close()
                    probe_future = None

                now = time.monotonic()
                if refresh_future is None and now >= next_refresh:
                    refresh_future = refresh_executor.submit(
                        refresh_series, symbols, market
                    )
                    next_refresh = math.inf
                if probe_future is None and now >= next_probe:
                    probe_future = probe_executor.submit(resolve)
                    next_probe = now + BETTER_CONNECTION_POLL_SECONDS
                stop_event.wait(min(0.25, max(0, wait_until - now)))

            index = (index + 1) % len(available)
    finally:
        probe_executor.shutdown(wait=True, cancel_futures=True)
        refresh_executor.shutdown(wait=True, cancel_futures=True)
        if bar is not None:
            with contextlib.suppress(Exception):
                bar.display_clear(application_name=APP_NAME)
            bar.close()
