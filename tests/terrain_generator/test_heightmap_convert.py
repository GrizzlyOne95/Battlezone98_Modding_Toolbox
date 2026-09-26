import contextlib
import io
import tempfile
import unittest
from pathlib import Path

import numpy as np

from battlezone.terrain.hg2 import HG2Map
from bztoolbox.modules.terrain_generator.heightmap_convert import (
    convert_heightmap, convert_hg2_to_hgt, convert_hgt_to_hg2, main,
)
from bztoolbox.modules.terrain_generator.hgt import (
    HGTFormatError, HGTMap, LEGACY_ZONE_SIZE, legacy_residual,
)


def random_hgt(zones_x=2, zones_z=1, seed=3, flags=True) -> HGTMap:
    rng = np.random.default_rng(seed)
    shape = (zones_z * LEGACY_ZONE_SIZE, zones_x * LEGACY_ZONE_SIZE)
    heights = rng.integers(0, 4096, size=shape).astype(np.uint16)
    nibble = rng.integers(0, 16, size=shape).astype(np.uint16) if flags else 0
    return HGTMap((heights | (nibble << 12)).astype(np.uint16), zones_x, zones_z)


class FromHg2Tests(unittest.TestCase):
    def test_inverse_of_the_cook(self):
        hgt = random_hgt()
        for rounding in ("engine", "half-up"):
            for smoothing in (False,):
                back = HGTMap.from_hg2(hgt.to_hg2(rounding=rounding, smoothing=smoothing))
                self.assertTrue(np.array_equal(back.heights, hgt.heights), rounding)
                self.assertFalse(back.flags.any())

    def test_flags_are_carried_when_given(self):
        hgt = random_hgt()
        back = HGTMap.from_hg2(hgt.to_hg2(), flags=hgt.flags)
        self.assertTrue(np.array_equal(back.raw, hgt.raw))

    def test_thirteen_bit_heights_are_refused_or_clamped(self):
        hg2 = HG2Map(np.full((256, 256), 5000, dtype=np.uint16), 1, 1)
        with self.assertRaises(HGTFormatError):
            HGTMap.from_hg2(hg2)
        self.assertEqual(int(HGTMap.from_hg2(hg2, overflow="clamp").heights.max()), 4095)

    def test_128_sample_zones_map_one_to_one(self):
        heights = np.arange(128 * 128, dtype=np.uint16).reshape(128, 128) % 4096
        hg2 = HG2Map(heights, 1, 1, zone_bits=7)
        self.assertTrue(np.array_equal(HGTMap.from_hg2(hg2).heights, heights))

    def test_residual_measures_detail_between_vertices(self):
        hgt = random_hgt(flags=False)
        hg2 = hgt.to_hg2(rounding="half-up")
        self.assertEqual(legacy_residual(hg2, HGTMap.from_hg2(hg2))["differing"], 0)
        bumpy = HG2Map(hg2.heights.copy(), hg2.zones_x, hg2.zones_z)
        original = int(bumpy.heights[1, 1])
        bumpy.heights[1, 1] = 4095 if original < 2048 else 0
        residual = legacy_residual(bumpy, HGTMap.from_hg2(bumpy))
        self.assertEqual(residual["differing"], 1)
        self.assertEqual(residual["max_difference"], abs(int(bumpy.heights[1, 1]) - original))


class FileConversionTests(unittest.TestCase):
    def test_round_trip_through_files_is_byte_exact(self):
        hgt = random_hgt(zones_x=2, zones_z=3)
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp, "m.hgt")
            hgt.write(src)
            Path(tmp, "m.trn").write_text("[Size]\nMinX=0\nMinZ=0\nWidth=2560\nDepth=3840\nHeight=0\n")
            report = convert_hgt_to_hg2(src, Path(tmp, "m.hg2"))
            self.assertEqual(report.zones, (2, 3))
            self.assertIn("m.trn", report.zone_source)
            back = convert_hg2_to_hgt(Path(tmp, "m.hg2"), Path(tmp, "back.hgt"), flags_from=src)
            self.assertEqual(Path(tmp, "back.hgt").read_bytes(), src.read_bytes())
            self.assertTrue(any("lossless" in note for note in back.notes))
            # without the reference HGT only the flag nibble differs
            convert_hg2_to_hgt(Path(tmp, "m.hg2"), Path(tmp, "plain.hgt"))
            plain = np.fromfile(Path(tmp, "plain.hgt"), dtype="<u2")
            original = np.fromfile(src, dtype="<u2")
            self.assertTrue(np.array_equal(plain, original & 0x0FFF))

    def test_hg2_is_what_redux_ships(self):
        # half-up rounding, no smoothing, header 1/8/zones/10
        hgt = random_hgt(zones_x=1, zones_z=1, flags=False)
        with tempfile.TemporaryDirectory() as tmp:
            hgt.write(Path(tmp, "a.hgt"))
            convert_heightmap(Path(tmp, "a.hgt"), Path(tmp, "a.hg2"), zones=(1, 1))
            data = Path(tmp, "a.hg2").read_bytes()
            self.assertEqual(data[:12], bytes([1, 0, 8, 0, 1, 0, 1, 0, 10, 0, 0, 0]))
            expected = hgt.to_hg2(rounding="half-up").heights
            self.assertTrue(np.array_equal(HG2Map.read(Path(tmp, "a.hg2")).heights, expected))

    def test_lossy_hg2_is_reported(self):
        heights = np.zeros((256, 256), dtype=np.uint16)
        heights[101, 33] = 900          # an odd sample: between legacy vertices
        with tempfile.TemporaryDirectory() as tmp:
            HG2Map(heights, 1, 1).write(Path(tmp, "a.hg2"))
            report = convert_hg2_to_hgt(Path(tmp, "a.hg2"), Path(tmp, "a.hgt"))
        self.assertTrue(any("between legacy vertices" in w for w in report.warnings))

    def test_command_line_picks_direction_by_extension(self):
        hgt = random_hgt(zones_x=1, zones_z=1)
        with tempfile.TemporaryDirectory() as tmp:
            hgt.write(Path(tmp, "a.hgt"))
            out = io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
                self.assertEqual(main([str(Path(tmp, "a.hgt")), "--zones", "1x1"]), 0)
                self.assertEqual(main([str(Path(tmp, "a.hg2")), "-o", str(Path(tmp, "b.hgt")),
                                       "--flags-from", str(Path(tmp, "a.hgt"))]), 0)
                self.assertEqual(main([str(Path(tmp, "a.hgt")), "-o", str(Path(tmp, "a.hgt"))]), 1)
            self.assertEqual(Path(tmp, "b.hgt").read_bytes(), Path(tmp, "a.hgt").read_bytes())


if __name__ == "__main__":
    unittest.main()
