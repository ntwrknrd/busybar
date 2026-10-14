"""Build a reusable BGRA curtain for native, host-independent chart reveals."""
import struct
from pathlib import Path


def build_reveal() -> bytes:
    frames = []
    # Firmware bicycle0 supports BGRA8888 (color mode 2), including alpha.
    # Transparent pixels expose the live chart underneath; opaque black hides it.
    for visible in range(0, 45, 2):
        data = bytearray()
        for _ in range(16):
            for count, alpha in ((visible, 0), (44 - visible, 255)):
                if count:
                    data.extend((count, 0, 0, 0, alpha))
        frames.append(struct.pack('<BBH', 1, 1, len(data)) + data)
    section_size = 21
    header = struct.pack('<8sBBBBBHBIIIII', b'bicycle0', 0, 44, 16, 2, 24,
                         max(len(f)-4 for f in frames), 0, section_size,
                         sum(map(len, frames)), 1, len(frames), len(frames))
    section = struct.pack('<IIIB', 0, len(frames)-1, 36+section_size, 1) + b'default\0'
    return header + section + b''.join(frames)


if __name__ == '__main__':
    target = Path(__file__).resolve().parents[1] / 'device-apps/app.ntwrknrd.stocks/scripts/reveal.anim'
    target.write_bytes(build_reveal())
