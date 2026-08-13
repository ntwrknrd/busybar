import os
import unittest
from unittest.mock import patch

from busylib import exceptions

from busybar_monitor.cli import (
    USB_ADDRESS,
    candidates,
    color_for,
    dynamic_frame,
    display_is_busy,
    frame,
    interpolate,
    is_better,
    reconnect_delay,
    same_route,
    SecondaryMetrics,
    secondary_frame,
    static_frame,
    temperature_color,
    ping_color,
    transition_frame,
)


def candidates_without_discovery():
    with patch("busybar_monitor.cli.BusyBarDevices.discover", return_value=[]):
        with patch.dict(os.environ, {}, clear=True):
            return list(candidates())


class MonitorTests(unittest.TestCase):
    def test_threshold_colors(self) -> None:
        self.assertEqual(color_for(64), "#32D17CFF")
        self.assertEqual(color_for(65), "#FFD43BFF")
        self.assertEqual(color_for(85), "#FF3030FF")

    @patch("busybar_monitor.cli.BusyBarDevices.discover", return_value=[])
    def test_fallback_order(self, _discover: object) -> None:
        environment = {
            "BUSYBAR_LAN_TOKEN": "lan-secret",
            "BUSYBAR_HOME_IP": "192.168.0.136",
            "BUSYBAR_CLOUD_TOKEN": "cloud-secret",
        }
        with patch.dict(os.environ, environment, clear=True):
            found = list(candidates())

        self.assertEqual([item.name for item in found], ["USB", "home LAN", "cloud"])
        self.assertEqual(found[0].address, USB_ADDRESS)
        self.assertIsNone(found[0].token)
        self.assertEqual(found[1].token, "lan-secret")
        self.assertEqual(found[2].token, "cloud-secret")

    def test_connection_preference_and_backoff(self) -> None:
        usb = next(
            candidate
            for candidate in candidates_without_discovery()
            if candidate.name == "USB"
        )
        cloud = type(usb)("cloud", None, "secret", 2)
        self.assertTrue(is_better(usb, cloud))
        self.assertFalse(is_better(cloud, usb))
        alternate_usb = type(usb)("other USB", USB_ADDRESS, None, 0)
        self.assertTrue(same_route(usb, alternate_usb))
        self.assertEqual(
            [reconnect_delay(i) for i in range(7)], [1, 2, 5, 10, 30, 30, 30]
        )

    def test_display_conflict_is_not_a_connection_failure(self) -> None:
        conflict = exceptions.BusyBarAPIError("busy", status_code=409)
        failure = exceptions.BusyBarAPIError("failed", status_code=500)
        self.assertTrue(display_is_busy(conflict))
        self.assertFalse(display_is_busy(failure))

    def test_frame_clamps_percentages(self) -> None:
        payload = frame(-4, 140)
        cpu_bar = next(element for element in payload.elements if element.id == "cpu-value")
        ram_bar = next(element for element in payload.elements if element.id == "ram-value")
        self.assertEqual(cpu_bar.width, 1)
        self.assertEqual(ram_bar.width, 36)

    def test_static_and_dynamic_elements_are_separate(self) -> None:
        self.assertEqual(
            {element.id for element in static_frame().elements},
            {"cpu-label", "cpu-background", "ram-label", "ram-background"},
        )
        self.assertEqual(
            {element.id for element in dynamic_frame(20, 40).elements},
            {"cpu-value", "cpu-percent", "ram-value", "ram-percent"},
        )

    def test_interpolation(self) -> None:
        self.assertEqual(interpolate(20, 80, 0), 20)
        self.assertEqual(interpolate(20, 80, 0.5), 50)
        self.assertEqual(interpolate(20, 80, 1), 80)

    def test_elements_can_expire_after_a_crash(self) -> None:
        payload = frame(20, 40, timeout=7)
        self.assertTrue(all(element.timeout == 7 for element in payload.elements))

    def test_each_frame_is_complete(self) -> None:
        payload = frame(20, 40)
        self.assertEqual(
            {element.id for element in payload.elements},
            {
                "cpu-label",
                "cpu-background",
                "cpu-value",
                "cpu-percent",
                "ram-label",
                "ram-background",
                "ram-value",
                "ram-percent",
            },
        )

    def test_secondary_page_formats_temperature_and_ping(self) -> None:
        payload = secondary_frame(SecondaryMetrics(67.4, 12.2))
        values = {element.id: getattr(element, "text", None) for element in payload.elements}
        self.assertEqual(values["temp-percent"], "67C")
        self.assertEqual(values["ping-percent"], "12ms")
        self.assertEqual(temperature_color(70), "#FFD43BFF")
        self.assertEqual(ping_color(81), "#FF3030FF")

    def test_transition_contains_both_pages(self) -> None:
        payload = transition_frame(0, 0.5, 20, 40, SecondaryMetrics(60, 10), 10)
        ids = {element.id for element in payload.elements}
        self.assertIn("cpu-label", ids)
        self.assertIn("temp-label", ids)


if __name__ == "__main__":
    unittest.main()
