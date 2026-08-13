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

    def test_builds_local_sections_for_each_page(self) -> None:
        pages = [
            StockPage("AAPL", -0.4, [100, 99, 101]),
            StockPage("MSFT", 1.2, [200, 202, 203]),
        ]
        animation = build_stock_animation(pages)
        self.assertTrue(animation.data.startswith(SIGNATURE))
        self.assertEqual(
            animation.section_seconds["initial_0"], REVEAL_FRAMES / ANIMATION_FPS
        )
        self.assertEqual(
            animation.section_seconds["to_1"],
            (SWIPE_FRAMES + REVEAL_FRAMES) / ANIMATION_FPS,
        )
        for section in ("show_0", "show_1", "initial_0", "to_0", "to_1"):
            self.assertIn(f"{section}\0".encode(), animation.data)

    def test_change_format_fits_left_column(self) -> None:
        self.assertEqual(format_change(-0.4), "-0.4%")
        self.assertEqual(format_change(12.3), "+12%")


if __name__ == "__main__":
    unittest.main()
