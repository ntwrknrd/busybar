import io
import json
import tempfile
import unittest
import urllib.error
import urllib.parse
from pathlib import Path
from unittest.mock import patch

from busybar.app import main as app_main
from busybar.stocks import (
    DEFAULT_SYMBOLS,
    HISTORY_PROFILES,
    MarketSeries,
    animation_frame,
    animation_pages,
    cache_path,
    fetch_symbol,
    load_cache,
    parse_chart,
    parser,
    refresh_seconds,
    refresh_series,
    save_cache,
)


def yahoo_payload() -> dict:
    return {
        "chart": {
            "error": None,
            "result": [
                {
                    "meta": {
                        "symbol": "AAPL",
                        "currency": "USD",
                        "regularMarketPrice": 102.0,
                        "previousClose": 100.0,
                    },
                    "timestamp": [1, 2, 3, 4],
                    "indicators": {"quote": [{"close": [100.0, None, 101.0, 102.0]}]},
                }
            ],
        }
    }


class StockTests(unittest.TestCase):
    def test_history_defaults_to_daily(self) -> None:
        args = parser().parse_args([])
        self.assertEqual(args.history, "daily")
        self.assertIsNone(args.refresh)

    def test_history_accepts_supported_ranges(self) -> None:
        for history in HISTORY_PROFILES:
            with self.subTest(history=history):
                self.assertEqual(
                    parser().parse_args(["--history", history]).history, history
                )

    def test_history_uses_range_specific_refresh_defaults(self) -> None:
        self.assertEqual(refresh_seconds("daily"), 60)
        self.assertEqual(refresh_seconds("weekly"), 300)
        self.assertEqual(refresh_seconds("monthly"), 900)
        self.assertEqual(refresh_seconds("yearly"), 3600)
        self.assertEqual(refresh_seconds("yearly", 45), 45)

    def test_change_display_defaults_to_percent(self) -> None:
        self.assertEqual(parser().parse_args([]).change, "percent")

    def test_change_display_accepts_points(self) -> None:
        self.assertEqual(parser().parse_args(["--change", "points"]).change, "points")

    def test_defaults_match_apple_stocks_watchlist(self) -> None:
        self.assertEqual(
            DEFAULT_SYMBOLS,
            (
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
            ),
        )

    def test_yahoo_chart_parsing_filters_missing_points(self) -> None:
        series = parse_chart(yahoo_payload(), fetched_at=123)
        self.assertEqual(series.symbol, "AAPL")
        self.assertEqual(series.timestamps, [1, 3, 4])
        self.assertEqual(series.closes, [100.0, 101.0, 102.0])
        self.assertEqual(series.change_percent, 2.0)
        self.assertEqual(series.change_points, 2.0)

    def test_longer_history_uses_first_chart_point_as_change_baseline(self) -> None:
        payload = yahoo_payload()
        payload["chart"]["result"][0]["meta"]["previousClose"] = 90.0
        series = parse_chart(payload, fetched_at=123, history="monthly")
        self.assertEqual(series.previous_close, 100.0)
        self.assertEqual(series.change_percent, 2.0)

    def test_yahoo_request_uses_history_profile(self) -> None:
        with patch("busybar.stocks.urllib.request.urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value = io.BytesIO(
                json.dumps(yahoo_payload()).encode()
            )
            fetch_symbol("AAPL", "yearly")

        request = urlopen.call_args.args[0]
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(request.full_url).query)
        self.assertEqual(query, {"interval": ["1d"], "range": ["1y"]})

    def test_history_ranges_have_separate_cache_files(self) -> None:
        with patch.dict("os.environ", {"XDG_CACHE_HOME": "/tmp/cache"}):
            self.assertEqual(cache_path("daily").name, "stocks.json")
            self.assertEqual(cache_path("weekly").name, "stocks-weekly.json")
            self.assertEqual(cache_path("monthly").name, "stocks-monthly.json")
            self.assertEqual(cache_path("yearly").name, "stocks-yearly.json")

    @patch("busybar.stocks.time.time", return_value=100)
    def test_builds_animation_pages_from_cached_market_data(
        self, _time: object
    ) -> None:
        series = MarketSeries("AAPL", "USD", 102, 100, [1, 2], [100, 102], 100)
        page = animation_pages({"AAPL": series}, ["AAPL"], stale_after=30)[0]
        self.assertEqual(page.symbol, "AAPL")
        self.assertEqual(page.change_percent, 2)
        self.assertEqual(page.change_points, 2)
        self.assertEqual(page.change_mode, "percent")
        self.assertEqual(page.closes, [100, 100, 102])
        self.assertFalse(page.stale)

    @patch("busybar.stocks.time.time", return_value=100)
    def test_builds_points_animation_pages(self, _time: object) -> None:
        series = MarketSeries("AAPL", "USD", 102, 100, [1, 2], [100, 102], 100)
        page = animation_pages(
            {"AAPL": series}, ["AAPL"], stale_after=30, change_mode="points"
        )[0]
        self.assertEqual(page.change_points, 2)
        self.assertEqual(page.change_mode, "points")

    def test_cache_round_trip(self) -> None:
        series = MarketSeries("AAPL", "USD", 102, 100, [1, 2], [100, 102], 123)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "stocks.json"
            save_cache(path, {"AAPL": series})
            self.assertEqual(load_cache(path), {"AAPL": series})
            self.assertEqual(json.loads(path.read_text())["AAPL"]["price"], 102)

    def test_animation_frame_plays_uploaded_section(self) -> None:
        payload = animation_frame("stocks-a.anim", "to_1", 30)
        self.assertEqual(len(payload.elements), 1)
        element = payload.elements[0]
        self.assertEqual(element.type, "animation")
        self.assertEqual(element.path, "stocks-a.anim")
        self.assertEqual(element.section, "to_1")

    def test_animation_frame_can_loop_on_device(self) -> None:
        payload = animation_frame("stocks-a.anim", "cycle", 60, loop=True)
        self.assertTrue(payload.elements[0].loop)

    @patch("busybar.stocks.fetch_symbol")
    def test_refresh_keeps_cached_data_when_yahoo_throttles(
        self, fetch: object
    ) -> None:
        series = MarketSeries("AAPL", "USD", 102, 100, [1, 2], [100, 102], 123)
        fetch.side_effect = urllib.error.HTTPError(
            "https://query2.finance.yahoo.com", 429, "throttled", {}, None
        )
        refreshed, failures = refresh_series(["AAPL"], {"AAPL": series})
        self.assertEqual(refreshed["AAPL"], series)
        self.assertEqual(failures, ["AAPL: HTTPError"])

    @patch("busybar.app.stocks.main")
    def test_cli_dispatches_stock_arguments(self, stocks_main: object) -> None:
        app_main(["stocks", "AAPL", "--once"])
        stocks_main.assert_called_once_with(["AAPL", "--once"])


if __name__ == "__main__":
    unittest.main()
