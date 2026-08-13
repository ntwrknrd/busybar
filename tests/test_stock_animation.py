import unittest

from busybar.anim import SIGNATURE
from busybar.stock_animation import (
    ANIMATION_FPS,
    HEIGHT,
    REVEAL_FRAMES,
    SWIPE_FRAMES,
    WIDTH,
    StockPage,
    build_stock_animation,
    format_change,
    render_page,
)


class StockAnimationTests(unittest.TestCase):
    def test_renders_complete_rgb_page(self) -> None:
        page = StockPage("AAPL", -0.4, [100, 99, 101])
        empty = render_page(page, 0)
        full = render_page(page, 1)
        self.assertEqual(len(full), WIDTH * HEIGHT * 3)
        self.assertNotEqual(empty, full)

    def test_builds_continuously_looping_stock_cycle(self) -> None:
        pages = [
            StockPage("AAPL", -0.4, [100, 99, 101]),
            StockPage("MSFT", 1.2, [200, 202, 203]),
        ]
        animation = build_stock_animation(pages, dwell_seconds=2)
        self.assertTrue(animation.data.startswith(SIGNATURE))
        self.assertEqual(
            animation.section_seconds["to_1"],
            (SWIPE_FRAMES + REVEAL_FRAMES) / ANIMATION_FPS,
        )
        self.assertEqual(
            animation.section_seconds["cycle"],
            2 * (2 + (SWIPE_FRAMES + REVEAL_FRAMES) / ANIMATION_FPS),
        )
        self.assertIn(b"cycle\0", animation.data)

    def test_change_format_fits_left_column(self) -> None:
        self.assertEqual(format_change(-0.4), "-0.4%")
        self.assertEqual(format_change(12.3), "+12%")
        self.assertEqual(format_change(-0.0072), "0.0%")
        self.assertEqual(format_change(0.0072), "0.0%")

    def test_effectively_flat_change_uses_neutral_color(self) -> None:
        frame = render_page(StockPage("AVGO", -0.0072, [416.08, 421.67, 416.05]))
        pixels = {frame[offset : offset + 3] for offset in range(0, len(frame), 3)}
        self.assertNotIn(bytes((255, 89, 100)), pixels)
        self.assertNotIn(bytes((50, 209, 124)), pixels)


if __name__ == "__main__":
    unittest.main()
