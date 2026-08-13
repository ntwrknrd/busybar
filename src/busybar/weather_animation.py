from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from itertools import pairwise

from busybar.anim import AnimSection, encode_anim
from busybar.animation import smoothstep
from busybar.stock_animation import FONT

WIDTH = 72
HEIGHT = 16
FPS = 24
SWIPE_FRAMES = 10
BLUE = (65, 151, 255)
CYAN = (64, 220, 230)
GRAY = (120, 135, 155)
GREEN = (50, 209, 124)
RED = (255, 89, 100)
WHITE = (255, 255, 255)
YELLOW = (255, 212, 59)
WEATHER_FONT = {
    **FONT,
    "/": ("001", "001", "010", "100", "100"),
    ":": ("000", "010", "000", "010", "000"),
}


@dataclass(frozen=True)
class HourForecast:
    time: str
    temperature: float
    precipitation_probability: float


@dataclass(frozen=True)
class DayForecast:
    date: str
    weather_code: int
    high: float
    low: float


@dataclass(frozen=True)
class WeatherSnapshot:
    location: str
    temperature: float
    apparent_temperature: float
    weather_code: int
    hourly: list[HourForecast]
    daily: list[DayForecast]
    temperature_suffix: str


@dataclass(frozen=True)
class WeatherAnimation:
    data: bytes
    cycle_seconds: float


def condition_name(code: int) -> str:
    if code == 0:
        return "CLEAR"
    if code <= 3:
        return "CLOUD"
    if code in (45, 48):
        return "FOG"
    if code in range(51, 68) or code in range(80, 83):
        return "RAIN"
    if code in range(71, 78) or code in (85, 86):
        return "SNOW"
    if code >= 95:
        return "STORM"
    return "WX"


def _set_pixel(frame: bytearray, x: int, y: int, color: tuple[int, int, int]) -> None:
    if not 0 <= x < WIDTH or not 0 <= y < HEIGHT:
        return
    offset = (y * WIDTH + x) * 3
    frame[offset : offset + 3] = bytes(color)


def _draw_text(
    frame: bytearray,
    text: str,
    x: int,
    y: int,
    color: tuple[int, int, int],
    scale: int = 1,
) -> None:
    cursor = x
    for character in text.upper():
        glyph = WEATHER_FONT.get(character, WEATHER_FONT["?"])
        for row, pixels in enumerate(glyph):
            for column, pixel in enumerate(pixels):
                if pixel == "1":
                    for dy in range(scale):
                        for dx in range(scale):
                            _set_pixel(
                                frame,
                                cursor + column * scale + dx,
                                y + row * scale + dy,
                                color,
                            )
        cursor += (len(glyph[0]) + 1) * scale


def _text_width(text: str) -> int:
    return (
        sum(
            len(WEATHER_FONT.get(character, WEATHER_FONT["?"])[0]) + 1
            for character in text
        )
        - 1
    )


def _line(
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
        if (x0, y0) == (x1, y1):
            return
        doubled = 2 * error
        if doubled >= dy:
            error += dy
            x0 += sx
        if doubled <= dx:
            error += dx
            y0 += sy


def _weather_icon(frame: bytearray, code: int, x: int, y: int) -> None:
    condition = condition_name(code)
    if condition == "CLEAR":
        for px, py in (
            (7, 0),
            (7, 14),
            (0, 7),
            (14, 7),
            (2, 2),
            (12, 2),
            (2, 12),
            (12, 12),
        ):
            _set_pixel(frame, x + px, y + py, YELLOW)
        for py in range(4, 11):
            for px in range(4, 11):
                if (px - 7) ** 2 + (py - 7) ** 2 <= 11:
                    _set_pixel(frame, x + px, y + py, YELLOW)
        return
    cloud = WHITE if condition in ("SNOW", "STORM") else GRAY
    for py in range(5, 11):
        for px in range(1, 15):
            if (
                py >= 8
                or (px - 5) ** 2 + (py - 7) ** 2 <= 10
                or (px - 10) ** 2 + (py - 6) ** 2 <= 12
            ):
                _set_pixel(frame, x + px, y + py, cloud)
    if condition == "RAIN":
        for px in (3, 7, 11):
            _set_pixel(frame, x + px, y + 13, BLUE)
            _set_pixel(frame, x + px - 1, y + 14, BLUE)
    elif condition == "SNOW":
        for px in (3, 8, 13):
            _set_pixel(frame, x + px, y + 14, CYAN)
    elif condition == "STORM":
        for px, py in ((8, 11), (7, 12), (9, 12), (8, 13), (7, 14)):
            _set_pixel(frame, x + px, y + py, YELLOW)
    elif condition == "FOG":
        for py in (12, 14):
            for px in range(2, 14):
                _set_pixel(frame, x + px, y + py, GRAY)


def _mini_icon(frame: bytearray, code: int, x: int, y: int) -> None:
    condition = condition_name(code)
    if condition == "CLEAR":
        for px, py in (
            (3, 0),
            (1, 1),
            (3, 1),
            (5, 1),
            (0, 3),
            (2, 3),
            (3, 3),
            (4, 3),
            (6, 3),
            (1, 5),
            (3, 5),
            (5, 5),
        ):
            _set_pixel(frame, x + px, y + py, YELLOW)
        return
    for px, py in ((2, 1), (3, 0), (4, 1), (1, 2), (2, 2), (3, 2), (4, 2), (5, 2)):
        _set_pixel(frame, x + px, y + py, WHITE if condition == "SNOW" else GRAY)
    if condition == "RAIN":
        for px in (1, 3, 5):
            _set_pixel(frame, x + px, y + 4, BLUE)
    elif condition == "SNOW":
        for px in (1, 3, 5):
            _set_pixel(frame, x + px, y + 4, CYAN)
    elif condition == "STORM":
        _set_pixel(frame, x + 3, y + 3, YELLOW)
        _set_pixel(frame, x + 2, y + 4, YELLOW)
    elif condition == "FOG":
        for px in range(1, 6):
            _set_pixel(frame, x + px, y + 4, GRAY)


def render_current(snapshot: WeatherSnapshot) -> bytes:
    frame = bytearray(WIDTH * HEIGHT * 3)
    _weather_icon(frame, snapshot.weather_code, 0, 0)
    _draw_text(frame, snapshot.location[:13], 18, 0, WHITE)
    temperature = f"{round(snapshot.temperature)}{snapshot.temperature_suffix}"
    _draw_text(frame, temperature, 18, 6, GREEN, scale=2)
    _draw_text(frame, condition_name(snapshot.weather_code)[:5], 51, 6, CYAN)
    _draw_text(frame, f"FL{round(snapshot.apparent_temperature)}", 51, 11, GRAY)
    return bytes(frame)


def render_hourly(snapshot: WeatherSnapshot) -> bytes:
    frame = bytearray(WIDTH * HEIGHT * 3)
    hours = snapshot.hourly[:12]
    if not hours:
        return bytes(frame)
    _draw_text(frame, "NEXT12H", 0, 0, WHITE)
    first = datetime.fromisoformat(hours[0].time)
    last = datetime.fromisoformat(hours[-1].time)
    _draw_text(frame, first.strftime("%I%p").lstrip("0")[:3], 32, 0, GRAY)
    _draw_text(frame, last.strftime("%I%p").lstrip("0")[:3], 60, 0, GRAY)
    temperatures = [hour.temperature for hour in hours]
    low, high = min(temperatures), max(temperatures)
    spread = max(1, high - low)
    points: list[tuple[int, int]] = []
    for index, hour in enumerate(hours):
        x = round(index * 71 / max(1, len(hours) - 1))
        probability_height = round(
            max(0, min(100, hour.precipitation_probability)) / 100 * 5
        )
        for py in range(HEIGHT - probability_height, HEIGHT):
            _set_pixel(frame, x, py, BLUE)
        y = 12 - round((hour.temperature - low) / spread * 6)
        points.append((x, y))
    for start, end in pairwise(points):
        _line(frame, start, end, YELLOW)
    return bytes(frame)


def render_daily(snapshot: WeatherSnapshot) -> bytes:
    frame = bytearray(WIDTH * HEIGHT * 3)
    for index, day in enumerate(snapshot.daily[:3]):
        x = index * 24
        label = datetime.fromisoformat(day.date).strftime("%a").upper()
        _draw_text(frame, label, x + 6, 0, WHITE)
        _mini_icon(frame, day.weather_code, x + 9, 5)
        high = str(round(day.high))
        low = str(round(day.low))
        total_width = _text_width(high) + _text_width("/") + _text_width(low) + 2
        cursor = x + max(0, (24 - total_width) // 2)
        _draw_text(frame, high, cursor, 11, RED)
        cursor += _text_width(high) + 1
        _draw_text(frame, "/", cursor, 11, GRAY)
        cursor += _text_width("/") + 1
        _draw_text(frame, low, cursor, 11, BLUE)
    return bytes(frame)


def _vertical_swipe(outgoing: bytes, incoming: bytes, offset: int) -> bytes:
    row_size = WIDTH * 3
    frame = bytearray(len(outgoing))
    for target_y in range(HEIGHT):
        stacked_y = target_y + offset
        source = outgoing if stacked_y < HEIGHT else incoming
        source_y = stacked_y if stacked_y < HEIGHT else stacked_y - HEIGHT
        frame[target_y * row_size : (target_y + 1) * row_size] = source[
            source_y * row_size : (source_y + 1) * row_size
        ]
    return bytes(frame)


def build_weather_animation(
    snapshot: WeatherSnapshot, dwell_seconds: float = 8
) -> WeatherAnimation:
    pages = [render_current(snapshot), render_hourly(snapshot), render_daily(snapshot)]
    dwell_frames = max(1, round(dwell_seconds * FPS))
    frames: list[bytes] = []
    for index, page in enumerate(pages):
        frames.extend([page] * dwell_frames)
        incoming = pages[(index + 1) % len(pages)]
        frames.extend(
            _vertical_swipe(
                page,
                incoming,
                round(HEIGHT * smoothstep(step / SWIPE_FRAMES)),
            )
            for step in range(1, SWIPE_FRAMES + 1)
        )
    return WeatherAnimation(
        data=encode_anim(
            frames,
            width=WIDTH,
            height=HEIGHT,
            fps=FPS,
            sections=[AnimSection("cycle", 0, len(frames) - 1)],
        ),
        cycle_seconds=len(frames) / FPS,
    )
