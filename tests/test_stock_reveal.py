import importlib.util
import struct
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('stock_reveal', ROOT / 'scripts/build_stock_reveal.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class StockRevealTests(unittest.TestCase):
    def test_asset_decodes_to_progressively_transparent_chart_columns(self):
        data = builder.build_reveal()
        self.assertEqual(data, (ROOT / 'device-apps/app.ntwrknrd.stocks/scripts/reveal.anim').read_bytes())
        header = struct.unpack('<8sBBBBBHBIIIII', data[:36])
        self.assertEqual(header[:6], (b'bicycle0', 0, 44, 16, 2, 24))
        self.assertEqual(header[10:], (1, 23, 23))
        offset = 36 + header[8]
        for visible in range(0, 45, 2):
            encoding, duration, size = struct.unpack('<BBH', data[offset:offset+4])
            self.assertEqual((encoding, duration), (1, 1))
            offset += 4
            encoded = data[offset:offset+size]
            pixels = []
            for i in range(0, len(encoded), 5):
                count = encoded[i]
                self.assertTrue(0 < count < 128)
                pixels.extend([tuple(encoded[i+1:i+5])] * count)
            self.assertEqual(len(pixels), 44*16)
            for y in range(16):
                self.assertEqual(pixels[y*44:(y+1)*44],
                                 [(0, 0, 0, 0)]*visible + [(0, 0, 0, 255)]*(44-visible))
            offset += size
        self.assertEqual(offset, len(data))
