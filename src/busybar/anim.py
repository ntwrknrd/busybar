"""Minimal encoder for the BUSY Bar's bicycle0 animation format."""

from __future__ import annotations

import struct
from dataclasses import dataclass

SIGNATURE = b"bicycle0"
HEADER_SIZE = 36
COLOR_MODE_BGR888 = 0


@dataclass(frozen=True)
class AnimSection:
    name: str
    start: int
    end: int


def encode_anim(
    frames: list[bytes],
    *,
    width: int,
    height: int,
    fps: int,
    sections: list[AnimSection],
) -> bytes:
    if not frames:
        raise ValueError("animation requires at least one frame")
    if not 1 <= width <= 255 or not 1 <= height <= 255:
        raise ValueError("animation dimensions must fit in one byte")
    if not 1 <= fps <= 255:
        raise ValueError("animation FPS must fit in one byte")

    frame_size = width * height * 3
    if frame_size > 0xFFFF:
        raise ValueError("animation frame is too large")
    if any(len(frame) != frame_size for frame in frames):
        raise ValueError(f"every RGB frame must contain {frame_size} bytes")

    all_sections = [AnimSection("default", 0, len(frames) - 1), *sections]
    names: set[str] = set()
    for section in all_sections:
        if not section.name or not all(
            character.isascii() and (character.isalnum() or character in "_.-")
            for character in section.name
        ):
            raise ValueError(f"invalid animation section name: {section.name!r}")
        if section.name in names:
            raise ValueError(f"duplicate animation section: {section.name}")
        if (
            section.start < 0
            or section.end < section.start
            or section.end >= len(frames)
        ):
            raise ValueError(
                f"animation section is outside frame range: {section.name}"
            )
        names.add(section.name)

    sections_size = sum(
        14 + len(section.name.encode("ascii")) for section in all_sections
    )
    encoded_frame_size = 4 + frame_size
    frames_size = encoded_frame_size * len(frames)
    header = struct.pack(
        "<8sBBBBBHBIIIII",
        SIGNATURE,
        0,
        width,
        height,
        COLOR_MODE_BGR888,
        fps,
        frame_size,
        0,
        sections_size,
        frames_size,
        len(all_sections),
        len(frames),
        len(frames),
    )
    if len(header) != HEADER_SIZE:
        raise AssertionError("invalid animation header size")

    section_data = bytearray()
    frames_offset = HEADER_SIZE + sections_size
    for section in all_sections:
        frame_offset = frames_offset + section.start * encoded_frame_size
        section_data.extend(
            struct.pack("<IIIB", section.start, section.end, frame_offset, 1)
        )
        section_data.extend(section.name.encode("ascii"))
        section_data.append(0)

    frame_data = bytearray()
    for rgb in frames:
        bgr = bytearray(frame_size)
        for offset in range(0, frame_size, 3):
            bgr[offset] = rgb[offset + 2]
            bgr[offset + 1] = rgb[offset + 1]
            bgr[offset + 2] = rgb[offset]
        frame_data.extend(struct.pack("<BBH", 0, 1, frame_size))
        frame_data.extend(bgr)

    return bytes(header + section_data + frame_data)
