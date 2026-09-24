import struct
import tempfile
import unittest
from pathlib import Path

import numpy as np

from bztoolbox.modules.world.hg2_codec import (
    DEFAULT_ZONE_BITS,
    HG2_MAP_VERSION,
    HG2_STORAGE_MAX_HEIGHT,
    HG2_STRUCTURE_VERSION,
    hg2_to_png16_array,
    png16_to_hg2_array,
    read_hg2,
    write_hg2,
)


class HG2CodecTests(unittest.TestCase):
    def test_default_redux_zone_size_is_256(self):
        self.assertEqual(1 << DEFAULT_ZONE_BITS, 256)

    def test_header_and_zone_major_payload_are_canonical(self):
        zone_bits = 2
        zone_size = 1 << zone_bits
        heights = np.zeros((zone_size * 2, zone_size * 2), dtype=np.uint16)
        heights[0:zone_size, 0:zone_size] = 100
        heights[0:zone_size, zone_size:] = 200
        heights[zone_size:, 0:zone_size] = 300
        heights[zone_size:, zone_size:] = 400

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "layout.hg2"
            write_hg2(path, heights, 2, 2, zone_bits=zone_bits)
            data = path.read_bytes()

        self.assertEqual(
            struct.unpack("<HHHHI", data[:12]),
            (HG2_STRUCTURE_VERSION, zone_bits, 2, 2, HG2_MAP_VERSION),
        )
        raw = np.frombuffer(data[12:], dtype="<u2")
        block = zone_size * zone_size
        self.assertTrue(np.all(raw[0 * block : 1 * block] == 100))
        self.assertTrue(np.all(raw[1 * block : 2 * block] == 200))
        self.assertTrue(np.all(raw[2 * block : 3 * block] == 300))
        self.assertTrue(np.all(raw[3 * block : 4 * block] == 400))

    def test_full_13_bit_round_trip(self):
        heights = np.array([[0, 4095], [4096, HG2_STORAGE_MAX_HEIGHT]], dtype=np.uint16)
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "range.hg2"
            write_hg2(path, heights, 1, 1, zone_bits=1)
            header, loaded = read_hg2(path)

        self.assertEqual(header.shape, (2, 2))
        self.assertTrue(np.array_equal(loaded, heights))

    def test_reader_masks_non_height_high_bits_like_bzmapio(self):
        zone_bits = 1
        header = struct.pack(
            "<HHHHI",
            HG2_STRUCTURE_VERSION,
            zone_bits,
            1,
            1,
            HG2_MAP_VERSION,
        )
        raw_words = np.array([0xE123, 0xAABC, 0x3FFF, 0x2001], dtype="<u2")
        expected = raw_words & 0x1FFF

        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "masked.hg2"
            path.write_bytes(header + raw_words.tobytes())
            _, loaded = read_hg2(path)

        np.testing.assert_array_equal(loaded.reshape(-1), expected)

    def test_png16_interchange_is_height_times_eight(self):
        heights = np.array([[0, 1], [4095, HG2_STORAGE_MAX_HEIGHT]], dtype=np.uint16)
        png16 = hg2_to_png16_array(heights)
        self.assertEqual(int(png16[1, 0]), 32760)
        self.assertEqual(int(png16[1, 1]), 65528)
        self.assertTrue(np.array_equal(png16_to_hg2_array(png16), heights))

    def test_truncated_and_extra_payloads_are_rejected(self):
        zone_bits = 2
        sample_count = (1 << zone_bits) ** 2
        header = struct.pack(
            "<HHHHI",
            HG2_STRUCTURE_VERSION,
            zone_bits,
            1,
            1,
            HG2_MAP_VERSION,
        )

        for suffix, count in (("short", sample_count - 1), ("extra", sample_count + 1)):
            with self.subTest(suffix=suffix):
                payload = np.arange(count, dtype="<u2").tobytes()
                with tempfile.TemporaryDirectory() as temp_dir:
                    path = Path(temp_dir) / f"{suffix}.hg2"
                    path.write_bytes(header + payload)
                    with self.assertRaisesRegex(ValueError, "payload size mismatch"):
                        read_hg2(path)


if __name__ == "__main__":
    unittest.main()
