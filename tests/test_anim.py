import struct
import unittest

from busybar.anim import HEADER_SIZE, SIGNATURE, AnimSection, encode_anim


class AnimationEncoderTests(unittest.TestCase):
    def test_encodes_bicycle_header_sections_and_bgr_frame(self) -> None:
        data = encode_anim(
            [bytes((1, 2, 3, 4, 5, 6))],
            width=2,
            height=1,
            fps=24,
            sections=[AnimSection("show", 0, 0)],
        )
        header = struct.unpack("<8sBBBBBHBIIIII", data[:HEADER_SIZE])
        self.assertEqual(header[0], SIGNATURE)
        self.assertEqual(header[2:6], (2, 1, 0, 24))
        self.assertEqual(header[6], 6)
        self.assertEqual(header[10:], (2, 1, 1))
        self.assertIn(b"default\0", data)
        self.assertIn(b"show\0", data)
        self.assertTrue(data.endswith(bytes((3, 2, 1, 6, 5, 4))))

    def test_rejects_invalid_frames_and_sections(self) -> None:
        with self.assertRaises(ValueError):
            encode_anim([], width=72, height=16, fps=24, sections=[])
        with self.assertRaises(ValueError):
            encode_anim(
                [b"short"],
                width=72,
                height=16,
                fps=24,
                sections=[],
            )
        with self.assertRaises(ValueError):
            encode_anim(
                [bytes(3)],
                width=1,
                height=1,
                fps=24,
                sections=[AnimSection("bad name", 0, 0)],
            )

    def test_folds_identical_frames_into_duration(self) -> None:
        frame = bytes((1, 2, 3))
        data = encode_anim(
            [frame, frame, frame],
            width=1,
            height=1,
            fps=24,
            sections=[AnimSection("tail", 2, 2)],
        )
        header = struct.unpack("<8sBBBBBHBIIIII", data[:HEADER_SIZE])
        self.assertEqual(header[11:], (1, 3))
        sections_size = header[8]
        frame_offset = HEADER_SIZE + sections_size
        self.assertEqual(data[frame_offset : frame_offset + 2], bytes((0, 3)))

    def test_compresses_repeated_pixels_with_rle(self) -> None:
        data = encode_anim(
            [bytes((1, 2, 3)) * 4],
            width=4,
            height=1,
            fps=24,
            sections=[],
        )
        header = struct.unpack("<8sBBBBBHBIIIII", data[:HEADER_SIZE])
        frame_offset = HEADER_SIZE + header[8]
        encoding, duration, encoded_size = struct.unpack(
            "<BBH", data[frame_offset : frame_offset + 4]
        )
        self.assertEqual((encoding, duration, encoded_size), (1, 1, 4))
        self.assertEqual(data[frame_offset + 4 :], bytes((4, 3, 2, 1)))
