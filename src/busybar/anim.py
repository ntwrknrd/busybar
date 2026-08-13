"""Minimal encoder for the BUSY Bar's bicycle0 animation format."""

from __future__ import annotations

import struct
from dataclasses import dataclass

SIGNATURE = b"bicycle0"
HEADER_SIZE = 36
COLOR_MODE_BGR888 = 0
PIXEL_SIZE = 3
MAX_RUN_PIXELS = 127


@dataclass(frozen=True)
class AnimSection:
    name: str
    start: int
    end: int


@dataclass
class _FileFrame:
    source: bytes
    encoding: int
    duration: int
    data: bytes


def _pack_bgr(rgb: bytes) -> bytes:
    bgr = bytearray(len(rgb))
    for offset in range(0, len(rgb), PIXEL_SIZE):
        bgr[offset] = rgb[offset + 2]
        bgr[offset + 1] = rgb[offset + 1]
        bgr[offset + 2] = rgb[offset]
    return bytes(bgr)


def _rle_compress(pixels: bytes) -> bytes:
    blocks = [
        pixels[offset : offset + PIXEL_SIZE]
        for offset in range(0, len(pixels), PIXEL_SIZE)
    ]
    encoded = bytearray()
    index = 0
    while index < len(blocks):
        repeat = 1
        while (
            index + repeat < len(blocks)
            and repeat < MAX_RUN_PIXELS
            and blocks[index + repeat] == blocks[index]
        ):
            repeat += 1
        if repeat >= 3:
            encoded.append(repeat)
            encoded.extend(blocks[index])
            index += repeat
            continue

        literal_start = index
        literal_count = 0
        while index < len(blocks) and literal_count < MAX_RUN_PIXELS:
            repeat = 1
            while (
                index + repeat < len(blocks)
                and repeat < MAX_RUN_PIXELS
                and blocks[index + repeat] == blocks[index]
            ):
                repeat += 1
            if repeat >= 3:
                break
            take = min(repeat, MAX_RUN_PIXELS - literal_count)
            literal_count += take
            index += take
        encoded.append(0x80 | literal_count)
        encoded.extend(
            b"".join(blocks[literal_start : literal_start + literal_count])
        )
    return bytes(encoded)


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
    encoded_frames: list[_FileFrame] = []
    for frame in frames:
        if (
            encoded_frames
            and encoded_frames[-1].source == frame
            and encoded_frames[-1].duration < 255
        ):
            encoded_frames[-1].duration += 1
            continue
        packed = _pack_bgr(frame)
        compressed = _rle_compress(packed)
        if len(compressed) < len(packed):
            encoded_frames.append(_FileFrame(frame, 1, 1, compressed))
        else:
            encoded_frames.append(_FileFrame(frame, 0, 1, packed))

    max_encoded_size = max(len(frame.data) for frame in encoded_frames)
    frames_size = sum(4 + len(frame.data) for frame in encoded_frames)
    header = struct.pack(
        "<8sBBBBBHBIIIII",
        SIGNATURE,
        0,
        width,
        height,
        COLOR_MODE_BGR888,
        fps,
        max_encoded_size,
        0,
        sections_size,
        frames_size,
        len(all_sections),
        len(encoded_frames),
        len(frames),
    )
    if len(header) != HEADER_SIZE:
        raise AssertionError("invalid animation header size")

    section_data = bytearray()
    display_frame_starts: list[tuple[int, int]] = []
    frame_offset = HEADER_SIZE + sections_size
    for frame in encoded_frames:
        display_frame_starts.extend(
            (frame_offset, remaining)
            for remaining in range(frame.duration, 0, -1)
        )
        frame_offset += 4 + len(frame.data)
    for section in all_sections:
        frame_offset, duration_override = display_frame_starts[section.start]
        section_data.extend(
            struct.pack(
                "<IIIB",
                section.start,
                section.end,
                frame_offset,
                duration_override,
            )
        )
        section_data.extend(section.name.encode("ascii"))
        section_data.append(0)

    frame_data = bytearray()
    for frame in encoded_frames:
        frame_data.extend(
            struct.pack(
                "<BBH", frame.encoding, frame.duration, len(frame.data)
            )
        )
        frame_data.extend(frame.data)

    return bytes(header + section_data + frame_data)
