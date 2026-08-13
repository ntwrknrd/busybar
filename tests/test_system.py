import os
import unittest
from unittest.mock import patch

from busylib import exceptions

from busybar.anim import SIGNATURE
from busybar.device import (
    USB_ADDRESS,
    candidates,
    display_is_busy,
    is_better,
    reconnect_delay,
    same_route,
)
from busybar.system import (
    ALERT_ASSET_FILENAME,
    MetricTracker,
    SecondaryMetrics,
    SystemState,
    ThresholdTracker,
    format_ping,
    overview_frame,
)
from busybar.system_animation import build_alert_animation


def candidates_without_discovery():
    with (
        patch("busybar.device.BusyBarDevices.discover", return_value=[]),
        patch.dict(os.environ, {}, clear=True),
    ):
        return list(candidates())


class SystemTests(unittest.TestCase):
    @patch("busybar.device.BusyBarDevices.discover", return_value=[])
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

    def test_metric_tracker_smooths_and_tracks_peak_and_trend(self) -> None:
        tracker = MetricTracker(alpha=0.5)
        for value in (10, 20, 30, 40):
            tracker.update(value)
        self.assertAlmostEqual(tracker.smoothed or 0, 31.25)
        self.assertEqual(tracker.peak, 31.25)
        self.assertEqual(tracker.trend(2), "^")

    def test_trend_is_blank_until_ready_and_dot_when_stable(self) -> None:
        tracker = MetricTracker(alpha=1)
        tracker.update(10)
        self.assertEqual(tracker.trend(2), "")
        for value in (10, 10, 10):
            tracker.update(value)
        self.assertEqual(tracker.trend(2), ".")

    def test_thresholds_use_hysteresis_and_report_only_increases(self) -> None:
        tracker = ThresholdTracker(warning=65, critical=85, hysteresis=3)
        self.assertIsNone(tracker.update(60))
        self.assertEqual(tracker.update(66), 1)
        self.assertIsNone(tracker.update(64))
        self.assertEqual(tracker.level, 1)
        self.assertIsNone(tracker.update(61))
        self.assertEqual(tracker.level, 0)
        self.assertEqual(tracker.update(90), 2)
        self.assertIsNone(tracker.update(83))
        self.assertEqual(tracker.level, 2)
        self.assertIsNone(tracker.update(81))
        self.assertEqual(tracker.level, 1)

    def test_overview_shows_all_metrics_without_percent_glyphs(self) -> None:
        state = SystemState()
        state.update(cpu=42, memory=76, secondary=SecondaryMetrics(67, 12))
        payload = overview_frame(state, timeout=7)
        text = {
            element.id: getattr(element, "text", None) for element in payload.elements
        }
        self.assertEqual(text["cpu-value-text"], "42")
        self.assertEqual(text["memory-value-text"], "76")
        self.assertEqual(text["temperature-value-text"], "67C")
        self.assertEqual(text["ping-value-text"], "12ms")
        self.assertNotIn("%", "".join(value for value in text.values() if value))
        self.assertEqual(len(payload.elements), 24)
        self.assertTrue(all(element.timeout == 7 for element in payload.elements))

    def test_overview_clamps_meter_widths(self) -> None:
        state = SystemState()
        state.update(cpu=-4, memory=140, secondary=SecondaryMetrics(20, 400))
        payload = overview_frame(state)
        elements = {element.id: element for element in payload.elements}
        self.assertEqual(elements["cpu-value"].width, 1)
        self.assertEqual(elements["memory-value"].width, 35)
        self.assertEqual(elements["ping-value"].width, 35)

    def test_overview_can_overlay_preloaded_alert_section(self) -> None:
        state = SystemState()
        state.update(cpu=20, memory=30, secondary=SecondaryMetrics(50, 10))
        payload = overview_frame(state, alert=("temperature", 2))
        alert = next(
            element for element in payload.elements if element.id == "system-alert"
        )
        self.assertEqual(alert.path, ALERT_ASSET_FILENAME)
        self.assertEqual(alert.section, "temperature-critical")

    def test_alert_animation_contains_every_threshold_section(self) -> None:
        animation = build_alert_animation()
        self.assertTrue(animation.data.startswith(SIGNATURE))
        self.assertEqual(len(animation.sections), 8)
        self.assertIn("cpu-warning", animation.sections)
        self.assertIn(b"temperature-critical\0", animation.data)

    def test_ping_format_is_compact(self) -> None:
        self.assertEqual(format_ping(None), "--")
        self.assertEqual(format_ping(12.4), "12ms")
        self.assertEqual(format_ping(123), "0.1s")
        self.assertEqual(format_ping(1200), "1.2s")
        self.assertEqual(format_ping(12000), "12s")


if __name__ == "__main__":
    unittest.main()
