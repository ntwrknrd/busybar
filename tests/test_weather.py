import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from busybar.anim import SIGNATURE
from busybar.app import main as app_main
from busybar.weather import (
    Location,
    WeatherRecord,
    animation_frame,
    geocode,
    load_cache,
    parse_forecast,
    save_cache,
)
from busybar.weather_animation import (
    DayForecast,
    HourForecast,
    WeatherSnapshot,
    build_weather_animation,
    condition_name,
    render_current,
    render_daily,
    render_hourly,
)


def forecast_payload() -> dict:
    return {
        "current": {
            "time": "2026-08-13T10:00",
            "temperature_2m": 72.4,
            "apparent_temperature": 74.1,
            "weather_code": 2,
        },
        "hourly": {
            "time": [
                "2026-08-13T09:00",
                "2026-08-13T10:00",
                "2026-08-13T11:00",
            ],
            "temperature_2m": [70, 72, 74],
            "precipitation_probability": [10, 20, 30],
        },
        "daily": {
            "time": ["2026-08-13", "2026-08-14", "2026-08-15"],
            "weather_code": [2, 61, 0],
            "temperature_2m_max": [81, 79, 84],
            "temperature_2m_min": [64, 63, 65],
        },
    }


def snapshot() -> WeatherSnapshot:
    return WeatherSnapshot(
        location="Indianapolis",
        temperature=72,
        apparent_temperature=74,
        weather_code=2,
        hourly=[
            HourForecast(f"2026-08-13T{hour:02}:00", 70 + hour % 5, hour * 5)
            for hour in range(10, 22)
        ],
        daily=[
            DayForecast("2026-08-13", 2, 81, 64),
            DayForecast("2026-08-14", 61, 79, 63),
            DayForecast("2026-08-15", 0, 84, 65),
        ],
        temperature_suffix="F",
    )


class WeatherTests(unittest.TestCase):
    @patch("busybar.weather._get_json")
    def test_geocodes_first_result(self, get_json: object) -> None:
        get_json.return_value = {
            "results": [
                {
                    "name": "Indianapolis",
                    "admin1": "Indiana",
                    "latitude": 39.77,
                    "longitude": -86.16,
                    "timezone": "America/Indiana/Indianapolis",
                }
            ]
        }
        location = geocode("Indianapolis")
        self.assertEqual(location.name, "Indianapolis, Indiana")
        self.assertEqual(location.longitude, -86.16)

    def test_parses_current_hourly_and_daily_forecast(self) -> None:
        location = Location(
            "Indianapolis, Indiana", 39.77, -86.16, "America/Indiana/Indianapolis"
        )
        result = parse_forecast(forecast_payload(), location, "fahrenheit")
        self.assertEqual(result.location, "Indianapolis")
        self.assertEqual(result.temperature, 72.4)
        self.assertEqual(result.temperature_suffix, "F")
        self.assertEqual([hour.temperature for hour in result.hourly], [72, 74])
        self.assertEqual(result.daily[1].weather_code, 61)

    def test_cache_round_trip(self) -> None:
        location = Location(
            "Indianapolis, Indiana", 39.77, -86.16, "America/Indiana/Indianapolis"
        )
        record = WeatherRecord("Indianapolis", "fahrenheit", location, snapshot(), 123)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "weather.json"
            save_cache(path, record)
            self.assertEqual(load_cache(path), record)
            self.assertEqual(
                json.loads(path.read_text())["snapshot"]["temperature"], 72
            )

    def test_renders_three_complete_pages(self) -> None:
        weather = snapshot()
        self.assertEqual(len(render_current(weather)), 72 * 16 * 3)
        self.assertEqual(len(render_hourly(weather)), 72 * 16 * 3)
        self.assertEqual(len(render_daily(weather)), 72 * 16 * 3)

    def test_builds_continuously_looping_animation(self) -> None:
        animation = build_weather_animation(snapshot(), dwell_seconds=2)
        self.assertTrue(animation.data.startswith(SIGNATURE))
        self.assertIn(b"cycle\0", animation.data)
        self.assertGreater(animation.cycle_seconds, 6)

    def test_condition_code_groups(self) -> None:
        self.assertEqual(condition_name(0), "CLEAR")
        self.assertEqual(condition_name(2), "CLOUD")
        self.assertEqual(condition_name(61), "RAIN")
        self.assertEqual(condition_name(71), "SNOW")
        self.assertEqual(condition_name(95), "STORM")

    def test_animation_payload_loops_uploaded_asset(self) -> None:
        payload = animation_frame("weather-a.anim", 1800)
        element = payload.elements[0]
        self.assertEqual(element.path, "weather-a.anim")
        self.assertEqual(element.section, "cycle")
        self.assertTrue(element.loop)

    @patch("busybar.app.weather.main")
    def test_cli_dispatches_weather_arguments(self, weather_main: object) -> None:
        app_main(["weather", "Indianapolis", "--once"])
        weather_main.assert_called_once_with(["Indianapolis", "--once"])


if __name__ == "__main__":
    unittest.main()
