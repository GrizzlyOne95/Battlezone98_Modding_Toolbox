import tempfile
import unittest
from pathlib import Path

import numpy as np

from bztoolbox.modules.world import maketrn_compat
from bztoolbox.modules.world.hg2_codec import read_hg2


class MakeTRNCompatTests(unittest.TestCase):
    def test_dimensions_match_binary_normalization(self):
        self.assertEqual(maketrn_compat.normalize_make_trn_dimension(1280), 1280)
        self.assertEqual(maketrn_compat.normalize_make_trn_dimension(2560), 2560)
        self.assertEqual(maketrn_compat.normalize_make_trn_dimension(1281), 1280)
        self.assertEqual(maketrn_compat.normalize_make_trn_dimension(1285), 2560)
        self.assertEqual(maketrn_compat.normalize_make_trn_dimension(2000), 2560)

    def test_zero_sample_dimensions_are_rejected(self):
        for value in (1, 2, 3, 4):
            with self.assertRaises(ValueError):
                maketrn_compat.normalize_make_trn_dimension(value)

    def test_rectangular_geometry(self):
        geom = maketrn_compat.make_stock_geometry(2560, 5120)
        self.assertEqual((geom.width_meters, geom.depth_meters), (2560, 5120))
        self.assertEqual((geom.zones_x, geom.zones_z), (2, 4))

    def test_empty_elevation_uses_binary_range(self):
        self.assertEqual(maketrn_compat.validate_empty_elevation(0), 0)
        self.assertEqual(maketrn_compat.validate_empty_elevation(4094), 4094)
        with self.assertRaises(ValueError):
            maketrn_compat.validate_empty_elevation(4095)

    def test_stock_trn_height_matches_blank_create(self):
        self.assertAlmostEqual(maketrn_compat.stock_trn_height(1234), 123.4)

    def test_hgt_triangle_interpolation_without_smoothing(self):
        source = np.array([[0, 10], [20, 40]], dtype=np.uint16)
        up = maketrn_compat.interpolate_hgt_to_hg2(source)
        expected = np.array(
            [
                [0, 5, 10, 10],
                [10, 20, 25, 25],
                [20, 30, 40, 40],
                [20, 30, 40, 40],
            ],
            dtype=np.uint16,
        )
        np.testing.assert_array_equal(up, expected)

    def test_hgt_triangle_upsample_includes_make_trn_smoothing(self):
        source = np.array([[0, 10], [20, 40]], dtype=np.uint16)
        up = maketrn_compat.upsample_hgt_to_hg2(source)
        expected = np.array(
            [
                [9, 12, 16, 18],
                [14, 18, 23, 25],
                [22, 26, 32, 35],
                [25, 30, 37, 40],
            ],
            dtype=np.uint16,
        )
        np.testing.assert_array_equal(up, expected)

    def test_make_trn_smoothing_uses_valid_neighbors_and_half_up_rounding(self):
        source = np.array(
            [
                [0, 1, 2],
                [3, 4, 5],
                [6, 7, 8],
            ],
            dtype=np.uint16,
        )
        smoothed = maketrn_compat.smooth_make_trn_hg2(source)
        expected = np.array(
            [
                [2, 3, 3],
                [4, 4, 5],
                [5, 6, 6],
            ],
            dtype=np.uint16,
        )
        np.testing.assert_array_equal(smoothed, expected)

    def test_hgt_constant_surface_stays_constant_after_conversion(self):
        source = np.full((4, 4), 1234, dtype=np.uint16)
        up = maketrn_compat.upsample_hgt_to_hg2(source)
        raw = maketrn_compat.interpolate_hgt_to_hg2(source)
        self.assertEqual(up.shape, (8, 8))
        self.assertTrue(np.all(up == 1234))
        self.assertTrue(np.all(raw == 1234))

    def test_hgt_zone_unpack_masks_12_bits_and_preserves_zone_order(self):
        zone_samples = maketrn_compat.HGT_SAMPLES_PER_ZONE ** 2
        left = np.full(zone_samples, 0xF123, dtype='<u2')
        right = np.full(zone_samples, 0x0456, dtype='<u2')
        raster = maketrn_compat.unpack_hgt_zones(left.tobytes() + right.tobytes(), 2, 1)
        self.assertEqual(raster.shape, (128, 256))
        self.assertTrue(np.all(raster[:, :128] == 0x0123))
        self.assertTrue(np.all(raster[:, 128:] == 0x0456))

    def test_no_smoothing_file_conversion_writes_redux_hg2(self):
        zone_size = maketrn_compat.HGT_SAMPLES_PER_ZONE
        legacy = np.arange(zone_size * zone_size, dtype=np.uint16).reshape(zone_size, zone_size)
        legacy &= 0x0FFF

        with tempfile.TemporaryDirectory() as tmp:
            hgt_path = Path(tmp) / "legacy.hgt"
            hg2_path = Path(tmp) / "legacy.hg2"
            hgt_path.write_bytes(legacy.astype('<u2').tobytes())

            expected = maketrn_compat.interpolate_hgt_to_hg2(legacy)
            written = maketrn_compat.convert_hgt_to_hg2_no_smoothing(
                hgt_path, hg2_path, 1, 1
            )
            header, actual = read_hg2(hg2_path)

        self.assertEqual((header.zones_x, header.zones_z, header.zone_bits), (1, 1, 8))
        np.testing.assert_array_equal(written, expected)
        np.testing.assert_array_equal(actual, expected)

    def test_read_hgt_smooth_switch_changes_nonflat_terrain(self):
        zone_size = maketrn_compat.HGT_SAMPLES_PER_ZONE
        legacy = np.zeros((zone_size, zone_size), dtype=np.uint16)
        legacy[32:96, 32:96] = 3000

        with tempfile.TemporaryDirectory() as tmp:
            hgt_path = Path(tmp) / "legacy.hgt"
            hgt_path.write_bytes(legacy.astype('<u2').tobytes())
            raw = maketrn_compat.read_hgt_as_hg2(hgt_path, 1, 1, smooth=False)
            smoothed = maketrn_compat.read_hgt_as_hg2(hgt_path, 1, 1, smooth=True)

        np.testing.assert_array_equal(raw, maketrn_compat.interpolate_hgt_to_hg2(legacy))
        self.assertFalse(np.array_equal(raw, smoothed))

    def test_bulk_folder_conversion_pairs_same_stem_trns(self):
        zone_size = maketrn_compat.HGT_SAMPLES_PER_ZONE
        a = np.full((zone_size, zone_size), 111, dtype=np.uint16)
        b = np.full((zone_size, zone_size), 222, dtype=np.uint16)

        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "source"
            out = Path(tmp) / "output"
            src.mkdir()
            (src / "mission01.hgt").write_bytes(a.astype('<u2').tobytes())
            (src / "mission02.hgt").write_bytes(b.astype('<u2').tobytes())
            (src / "mission01.trn").write_text("[Size]\nWidth=1280\nDepth=1280\n", encoding="ascii")
            (src / "mission02.trn").write_text("[Size]\nWidth=1280\nDepth=1280\n", encoding="ascii")

            results = maketrn_compat.convert_legacy_hgt_folder_no_smoothing(src, out)
            _, hg2_a = read_hg2(out / "mission01.hg2")
            _, hg2_b = read_hg2(out / "mission02.hg2")

        self.assertEqual([Path(result.hgt_path).stem for result in results], ["mission01", "mission02"])
        self.assertTrue(np.all(hg2_a == 111))
        self.assertTrue(np.all(hg2_b == 222))

    def test_bulk_pairing_rejects_ambiguous_trn_without_same_stem(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp)
            (src / "mission.hgt").write_bytes(b"\x00\x00")
            (src / "alpha.trn").write_text("[Size]\nWidth=1280\nDepth=1280\n", encoding="ascii")
            (src / "beta.trn").write_text("[Size]\nWidth=1280\nDepth=1280\n", encoding="ascii")
            with self.assertRaisesRegex(ValueError, "Multiple TRNs"):
                maketrn_compat.resolve_legacy_hgt_trn(src / "mission.hgt", src)


if __name__ == '__main__':
    unittest.main()
