import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from busybar.app import main as app_main
from busybar.stocks import (
    MarketSeries,
    animation_frame,
    animation_pages,
    load_cache,
    parse_chart,
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
    def test_yahoo_chart_parsing_filters_missing_points(self) -> None:
        series = parse_chart(yahoo_payload(), fetched_at=123)
        self.assertEqual(series.symbol, "AAPL")
        self.assertEqual(series.timestamps, [1, 3, 4])
        self.assertEqual(series.closes, [100.0, 101.0, 102.0])
        self.assertEqual(series.change_percent, 2.0)

    @patch("busybar.stocks.time.time", return_value=100)
    def test_builds_animation_pages_from_cached_market_data(
        self, _time: object
    ) -> None:
        series = MarketSeries("AAPL", "USD", 102, 100, [1, 2], [100, 102], 100)
        page = animation_pages({"AAPL": series}, ["AAPL"], stale_after=30)[0]
        self.assertEqual(page.symbol, "AAPL")
        self.assertEqual(page.change_percent, 2)
        self.assertEqual(page.closes, [100, 102])
        self.assertFalse(page.stale)

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
