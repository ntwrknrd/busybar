from __future__ import annotations

import math
from dataclasses import dataclass

from busybar.anim import AnimSection, encode_anim
from busybar.stock_animation import FONT

WIDTH = 72
HEIGHT = 16
FPS = 12
BLACK = (0, 0, 0)
WARNING = (255, 212, 59)
CRITICAL = (255, 48, 48)
LABELS = {
    "cpu": "CPU",
    "memory": "RAM",
    "temperature": "TMP",
    "ping": "NET",
}


@dataclass(frozen=True)
class AlertAnimation:
    data: bytes
    sections: tuple[str, ...]


def _set_pixel(frame: bytearray, x: int, y: int, color: tuple[int, int, int]) -> None:
    offset = (y * WIDTH + x) * 3
    frame[offset : offset + 3] = bytes(color)


def _draw_text(
    frame: bytearray, text: str, y: int, color: tuple[int, int, int]
) -> None:
    width = len(text) * 4 - 1
    cursor = (WIDTH - width) // 2
    for character in text:
        glyph = FONT[character]
        for row, pixels in enumerate(glyph):
            for column, pixel in enumerate(pixels):
                if pixel == "1":
                    _set_pixel(frame, cursor + column, y + row, color)
        cursor += 4


def _alert_frame(
    label: str, base_color: tuple[int, int, int], brightness: float
) -> bytes:
    color = tuple(round(channel * brightness) for channel in base_color)
    frame = bytearray(WIDTH * HEIGHT * 3)
    for x in range(WIDTH):
        _set_pixel(frame, x, 0, color)
        _set_pixel(frame, x, HEIGHT - 1, color)
    for y in range(HEIGHT):
        _set_pixel(frame, 0, y, color)
        _set_pixel(frame, WIDTH - 1, y, color)
    _draw_text(frame, label, 2, color)
    _draw_text(frame, "HIGH", 9, color)
    return bytes(frame)


def build_alert_animation() -> AlertAnimation:
    frames: list[bytes] = []
    sections: list[AnimSection] = []
    names: list[str] = []
    for metric, label in LABELS.items():
        for severity, color in (("warning", WARNING), ("critical", CRITICAL)):
            name = f"{metric}-{severity}"
            start = len(frames)
            frames.extend(
                _alert_frame(
                    label,
                    color,
                    0.25 + 0.75 * math.sin(math.pi * step / (FPS - 1)),
                )
                for step in range(FPS)
            )
            sections.append(AnimSection(name, start, len(frames) - 1))
            names.append(name)
    return AlertAnimation(
        data=encode_anim(
            frames,
            width=WIDTH,
            height=HEIGHT,
            fps=FPS,
            sections=sections,
        ),
        sections=tuple(names),
    )
