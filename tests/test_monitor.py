import os
import unittest
from unittest.mock import patch

from busybar_monitor.cli import (
    USB_ADDRESS,
    candidates,
    color_for,
    dynamic_frame,
    frame,
    interpolate,
    static_frame,
)


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


if __name__ == "__main__":
    unittest.main()
