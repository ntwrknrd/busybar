import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from busybar.app import main as app_main
from busybar.stocks import (
    BACKGROUND,
    GRAPH_X,
    GREEN,
    MarketSeries,
    graph_segments,
    load_cache,
    parse_chart,
    refresh_series,
    sample_values,
    save_cache,
    stock_delta_frame,
    stock_frame,
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

    def test_graph_is_scaled_and_downsampled(self) -> None:
        values = [float(value) for value in range(100)]
        self.assertEqual(len(sample_values(values)), 36)
        segments = graph_segments(values)
        self.assertEqual(len(segments), 35)
        self.assertTrue(all(GRAPH_X <= x <= 70 for x, _y, _height in segments))
        self.assertTrue(all(0 <= y <= 15 for _x, y, _height in segments))

    @patch("busybar.stocks.time.time", return_value=100)
    def test_reveal_hides_unfinished_graph_segments(self, _time: object) -> None:
        series = MarketSeries("AAPL", "USD", 102, 100, [1, 2, 3], [100, 101, 102], 100)
        payload = stock_frame(series, 30, reveal=0)
        graph = [
            element
            for element in payload.elements
            if element.id.startswith("stocks-graph-")
        ]
        self.assertTrue(graph)
        self.assertTrue(all(element.fill_colors == [BACKGROUND] for element in graph))

        payload = stock_frame(series, 30, reveal=1)
        graph = [
            element
            for element in payload.elements
            if element.id.startswith("stocks-graph-")
        ]
        self.assertTrue(all(element.fill_colors == [GREEN] for element in graph))

    @patch("busybar.stocks.time.time", return_value=100)
    def test_text_uses_left_column_and_chart_uses_remaining_height(
        self, _time: object
    ) -> None:
        series = MarketSeries("AAPL", "USD", 102, 100, [1, 2], [100, 102], 100)
        payload = stock_frame(series, 30)
        elements = {element.id: element for element in payload.elements}
        self.assertNotIn("stocks-price", elements)
        self.assertEqual(
            (elements["stocks-symbol"].x, elements["stocks-symbol"].y), (0, 0)
        )
        self.assertEqual(
            (elements["stocks-change"].x, elements["stocks-change"].y), (0, 9)
        )
        self.assertEqual(
            (
                elements["stocks-background"].x,
                elements["stocks-background"].y,
                elements["stocks-background"].width,
                elements["stocks-background"].height,
            ),
            (22, 0, 50, 16),
        )

    def test_cache_round_trip(self) -> None:
        series = MarketSeries("AAPL", "USD", 102, 100, [1, 2], [100, 102], 123)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "stocks.json"
            save_cache(path, {"AAPL": series})
            self.assertEqual(load_cache(path), {"AAPL": series})
            self.assertEqual(json.loads(path.read_text())["AAPL"]["price"], 102)

    @patch("busybar.stocks.time.time", return_value=100)
    def test_delta_frame_contains_only_new_graph_segments(self, _time: object) -> None:
        values = [float(value) for value in range(36)]
        series = MarketSeries("AAPL", "USD", 102, 100, list(range(36)), values, 100)
        payload = stock_delta_frame(
            series,
            30,
            previous_reveal=0.25,
            reveal=0.5,
        )
        graph = [
            element
            for element in payload.elements
            if element.id.startswith("stocks-graph-")
        ]
        self.assertEqual(len(payload.elements), 9)
        self.assertEqual(len(graph), 9)
        self.assertTrue(
            all(element.type == "rectangle" for element in payload.elements)
        )
        self.assertNotIn(
            "stocks-background", {element.id for element in payload.elements}
        )

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
