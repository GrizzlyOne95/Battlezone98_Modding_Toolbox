import struct
import sys
import unittest
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from bztoolbox.modules.textures.makemap_compat import (
    MapFormat, MakeMapOptions, apply_chroma_key, apply_remap, colorize,
    decode_map_bytes, desaturate, encode_map_bytes, recover_alpha,
    undo_premultiplied_alpha,
)


class MapCodecTests(unittest.TestCase):
    def test_header_and_type3_bgra(self):
        img = Image.new("RGBA", (1, 1), (10, 20, 30, 40))
        data = encode_map_bytes(img, MakeMapOptions(map_format=MapFormat.ARGB8888))
        self.assertEqual(struct.unpack_from("<HHI", data), (4, 3, 1))
        self.assertEqual(data[8:], bytes((30, 20, 10, 40)))
        self.assertEqual(decode_map_bytes(data).getpixel((0, 0)), (10, 20, 30, 40))

    def test_argb4444_round_trip(self):
        img = Image.new("RGBA", (1, 1), (0xAB, 0x34, 0xFE, 0x71))
        data = encode_map_bytes(img, MakeMapOptions(map_format=MapFormat.ARGB4444))
        self.assertEqual(struct.unpack_from("<H", data, 8)[0], 0x7A3F)
        self.assertEqual(decode_map_bytes(data).getpixel((0, 0)), (0xAA, 0x33, 0xFF, 0x77))

    def test_rgb565_round_trip(self):
        img = Image.new("RGBA", (1, 1), (255, 129, 7, 3))
        data = encode_map_bytes(img, MakeMapOptions(map_format=MapFormat.RGB565))
        px = decode_map_bytes(data).getpixel((0, 0))
        self.assertEqual(px[3], 255)
        self.assertGreaterEqual(px[0], 248)
        self.assertTrue(128 <= px[1] <= 132)
        self.assertLessEqual(px[2], 8)

    def test_xrgb8888_is_opaque_on_read(self):
        img = Image.new("RGBA", (1, 1), (1, 2, 3, 4))
        data = encode_map_bytes(img, MakeMapOptions(map_format=MapFormat.XRGB8888))
        self.assertEqual(data[8:], bytes((3, 2, 1, 0)))
        self.assertEqual(decode_map_bytes(data).getpixel((0, 0)), (1, 2, 3, 255))

    def test_indexed_and_transparent_index(self):
        palette = [(255, 0, 0), (0, 255, 0), (0, 0, 255)] + [(0, 0, 0)] * 253
        img = Image.new("RGBA", (2, 1))
        img.putdata([(250, 4, 4, 255), (0, 0, 0, 0)])
        opts = MakeMapOptions(map_format=MapFormat.INDEXED, palette=palette, transparent_index=2)
        data = encode_map_bytes(img, opts)
        self.assertEqual(data[8:], bytes((0, 2)))


class TransformTests(unittest.TestCase):
    def test_recover_alpha_uses_max_rgb(self):
        img = Image.new("RGBA", (1, 1), (10, 80, 20, 1))
        self.assertEqual(recover_alpha(img).getpixel((0, 0)), (10, 80, 20, 80))

    def test_chromakey_zeroes_entire_pixel(self):
        img = Image.new("RGBA", (1, 1), (1, 2, 3, 200))
        self.assertEqual(apply_chroma_key(img, (1, 2, 3)).getpixel((0, 0)), (0, 0, 0, 0))

    def test_undo_pma(self):
        img = Image.new("RGBA", (1, 1), (50, 25, 0, 100))
        self.assertEqual(undo_premultiplied_alpha(img).getpixel((0, 0)), (127, 63, 0, 100))

    def test_desat_reference_luma_weights(self):
        img = Image.new("RGBA", (1, 1), (255, 0, 0, 77))
        self.assertEqual(desaturate(img, 100).getpixel((0, 0)), (76, 76, 76, 77))

    def test_remap_maps_each_channel_independently(self):
        table = Image.new("RGBA", (2, 1))
        table.putdata([(10, 20, 30, 40), (110, 120, 130, 140)])
        img = Image.new("RGBA", (1, 1), (255, 0, 255, 0))
        self.assertEqual(apply_remap(img, table).getpixel((0, 0)), (110, 20, 130, 40))

    def test_colorize_identity_defaults(self):
        img = Image.new("RGBA", (1, 1), (12, 34, 56, 78))
        out = colorize(img, (1,1,1,1), (255,255,255,255), (0,0,0,0))
        self.assertEqual(out.getpixel((0, 0)), (12, 34, 56, 78))


if __name__ == "__main__":
    unittest.main()
