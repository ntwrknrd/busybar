from __future__ import annotations

from dataclasses import dataclass

from busybar.anim import AnimSection, encode_anim
from busybar.animation import smoothstep

WIDTH = 72
HEIGHT = 16
CHART_X = 22
CHART_WIDTH = WIDTH - CHART_X
ANIMATION_FPS = 24
SWIPE_FRAMES = 10
REVEAL_FRAMES = 12
BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
CHART_BACKGROUND = (16, 23, 34)
GREEN = (50, 209, 124)
RED = (255, 89, 100)
STALE = (255, 212, 59)

FONT: dict[str, tuple[str, ...]] = {
    "A": ("010", "101", "111", "101", "101"),
    "B": ("110", "101", "110", "101", "110"),
    "C": ("011", "100", "100", "100", "011"),
    "D": ("110", "101", "101", "101", "110"),
    "E": ("111", "100", "110", "100", "111"),
    "F": ("111", "100", "110", "100", "100"),
    "G": ("011", "100", "101", "101", "011"),
    "H": ("101", "101", "111", "101", "101"),
    "I": ("111", "010", "010", "010", "111"),
    "J": ("001", "001", "001", "101", "010"),
    "K": ("101", "101", "110", "101", "101"),
    "L": ("100", "100", "100", "100", "111"),
    "M": ("101", "111", "111", "101", "101"),
    "N": ("101", "111", "111", "111", "101"),
    "O": ("010", "101", "101", "101", "010"),
    "P": ("110", "101", "110", "100", "100"),
    "Q": ("010", "101", "101", "111", "011"),
    "R": ("110", "101", "110", "101", "101"),
    "S": ("011", "100", "010", "001", "110"),
    "T": ("111", "010", "010", "010", "010"),
    "U": ("101", "101", "101", "101", "111"),
    "V": ("101", "101", "101", "101", "010"),
    "W": ("101", "101", "111", "111", "101"),
    "X": ("101", "101", "010", "101", "101"),
    "Y": ("101", "101", "010", "010", "010"),
    "Z": ("111", "001", "010", "100", "111"),
    "0": ("111", "101", "101", "101", "111"),
    "1": ("010", "110", "010", "010", "111"),
    "2": ("110", "001", "010", "100", "111"),
    "3": ("110", "001", "010", "001", "110"),
    "4": ("101", "101", "111", "001", "001"),
    "5": ("111", "100", "110", "001", "110"),
    "6": ("011", "100", "111", "101", "111"),
    "7": ("111", "001", "010", "010", "010"),
    "8": ("111", "101", "111", "101", "111"),
    "9": ("111", "101", "111", "001", "110"),
    "+": ("000", "010", "111", "010", "000"),
    "-": ("000", "000", "111", "000", "000"),
    ".": ("000", "000", "000", "000", "010"),
    "%": ("110", "110", "010", "011", "011"),
    "^": ("010", "101", "000", "000", "000"),
    "?": ("110", "001", "010", "000", "010"),
}


@dataclass(frozen=True)
class StockPage:
    symbol: str
    change_percent: float
    closes: list[float]
    stale: bool = False
    change_points: float = 0
    change_mode: str = "percent"


@dataclass(frozen=True)
class StockAnimation:
    data: bytes
    section_seconds: dict[str, float]


def _set_pixel(frame: bytearray, x: int, y: int, color: tuple[int, int, int]) -> None:
    if not 0 <= x < WIDTH or not 0 <= y < HEIGHT:
        return
    offset = (y * WIDTH + x) * 3
    frame[offset : offset + 3] = bytes(color)


def _fill_rect(
    frame: bytearray,
    x: int,
    y: int,
    width: int,
    height: int,
    color: tuple[int, int, int],
) -> None:
    for row in range(max(0, y), min(HEIGHT, y + height)):
        for column in range(max(0, x), min(WIDTH, x + width)):
            _set_pixel(frame, column, row, color)


def _draw_text(
    frame: bytearray, text: str, x: int, y: int, color: tuple[int, int, int]
) -> None:
    cursor = x
    for character in text.upper():
        glyph = FONT.get(character, FONT["?"])
        for row, pixels in enumerate(glyph):
            for column, pixel in enumerate(pixels):
                if pixel == "1":
                    _set_pixel(frame, cursor + column, y + row, color)
        cursor += 4


def _display_change(change: float, mode: str) -> float:
    threshold = 0.005 if mode == "points" else 0.05
    return 0 if abs(change) < threshold else change


def format_change(change: float, mode: str = "percent") -> str:
    displayed = _display_change(change, mode)
    if mode == "points":
        if displayed == 0:
            return "0.00"
        if abs(displayed) >= 1000:
            return f"{displayed / 1000:+.1f}K"
        if abs(displayed) >= 100:
            return f"{displayed:+.0f}"
        if abs(displayed) >= 10:
            return f"{displayed:+.1f}"
        return f"{displayed:+.2f}"
    if displayed == 0:
        return "0.0%"
    if abs(displayed) >= 10:
        return f"{displayed:+.0f}%"
    return f"{displayed:+.1f}%"


def _sample(values: list[float], count: int = 26) -> list[float]:
    if len(values) <= count:
        return values
    return [
        values[round(index * (len(values) - 1) / (count - 1))] for index in range(count)
    ]


def _graph_points(values: list[float]) -> list[tuple[int, int]]:
    sampled = _sample(values)
    if not sampled:
        return []
    low, high = min(sampled), max(sampled)
    spread = high - low
    points: list[tuple[int, int]] = []
    for index, value in enumerate(sampled):
        x = CHART_X + round(index * (CHART_WIDTH - 2) / max(1, len(sampled) - 1))
        y = (
            HEIGHT // 2
            if spread == 0
            else HEIGHT - 1 - round((value - low) / spread * 15)
        )
        points.append((x, y))
    return points


def _draw_line(
    frame: bytearray,
    start: tuple[int, int],
    end: tuple[int, int],
    color: tuple[int, int, int],
) -> None:
    x0, y0 = start
    x1, y1 = end
    dx = abs(x1 - x0)
    sx = 1 if x0 < x1 else -1
    dy = -abs(y1 - y0)
    sy = 1 if y0 < y1 else -1
    error = dx + dy
    while True:
        _set_pixel(frame, x0, y0, color)
        if x0 == x1 and y0 == y1:
            break
        doubled = 2 * error
        if doubled >= dy:
            error += dy
            x0 += sx
        if doubled <= dx:
            error += dx
            y0 += sy


def render_page(page: StockPage, reveal: float = 1) -> bytes:
    frame = bytearray(WIDTH * HEIGHT * 3)
    _fill_rect(frame, CHART_X, 0, CHART_WIDTH, HEIGHT, CHART_BACKGROUND)
    change = page.change_points if page.change_mode == "points" else page.change_percent
    displayed_change = _display_change(change, page.change_mode)
    color = (
        STALE
        if page.stale
        else WHITE
        if displayed_change == 0
        else GREEN
        if displayed_change > 0
        else RED
    )
    _draw_text(frame, page.symbol[:5], 0, 0, WHITE)
    _draw_text(frame, format_change(change, page.change_mode), 0, 9, color)
    points = _graph_points(page.closes)
    visible = round(max(0, min(1, reveal)) * max(0, len(points) - 1))
    for index in range(visible):
        _draw_line(frame, points[index], points[index + 1], color)
    return bytes(frame)


def _vertical_swipe(outgoing: bytes, incoming: bytes, offset: int) -> bytes:
    row_size = WIDTH * 3
    frame = bytearray(len(outgoing))
    for target_y in range(HEIGHT):
        stacked_y = target_y + offset
        source = outgoing if stacked_y < HEIGHT else incoming
        source_y = stacked_y if stacked_y < HEIGHT else stacked_y - HEIGHT
        start = source_y * row_size
        target = target_y * row_size
        frame[target : target + row_size] = source[start : start + row_size]
    return bytes(frame)


def _transition_frames(outgoing_page: StockPage, incoming_page: StockPage) -> list[bytes]:
    outgoing = render_page(outgoing_page)
    incoming_empty = render_page(incoming_page, 0)
    frames = [
        _vertical_swipe(
            outgoing,
            incoming_empty,
            round(HEIGHT * smoothstep(step / SWIPE_FRAMES)),
        )
        for step in range(1, SWIPE_FRAMES + 1)
    ]
    frames.extend(
        render_page(incoming_page, smoothstep(step / REVEAL_FRAMES))
        for step in range(1, REVEAL_FRAMES + 1)
    )
    return frames


def build_stock_animation(
    pages: list[StockPage], dwell_seconds: float = 10
) -> StockAnimation:
    if not pages:
        raise ValueError("stock animation requires at least one page")
    frames: list[bytes] = []
    sections: list[AnimSection] = []
    durations: dict[str, float] = {}

    def add_section(name: str, section_frames: list[bytes]) -> None:
        start = len(frames)
        frames.extend(section_frames)
        sections.append(AnimSection(name, start, len(frames) - 1))
        durations[name] = len(section_frames) / ANIMATION_FPS

    dwell_frames = max(1, round(dwell_seconds * ANIMATION_FPS))
    cycle_frames: list[bytes] = []
    for index, page in enumerate(pages):
        cycle_frames.extend([render_page(page)] * dwell_frames)
        if len(pages) == 1:
            continue
        target = (index + 1) % len(pages)
        transition = _transition_frames(page, pages[target])
        cycle_frames.extend(transition)
        durations[f"to_{target}"] = len(transition) / ANIMATION_FPS
    add_section("cycle", cycle_frames)

    return StockAnimation(
        data=encode_anim(
            frames,
            width=WIDTH,
            height=HEIGHT,
            fps=ANIMATION_FPS,
            sections=sections,
        ),
        section_seconds=durations,
    )
