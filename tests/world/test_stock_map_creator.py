import os
import tempfile
import unittest

import numpy as np

from bztoolbox.modules.world.hg2_codec import read_hg2
from bztoolbox.modules.world.maketrn_compat import make_stock_geometry
from bztoolbox.modules.world.mat_codec import default_make_trn_rules, expected_mat_bytes, read_mat
from bztoolbox.modules.world.stock_map_creator import StockBuildConfig, build_stock_map, build_stock_trn_text


class StockMapCreatorTests(unittest.TestCase):
    def make_config(self, out_dir, *, width=1280, depth=1280, empty=0, seed=1, **kwargs):
        return StockBuildConfig(
            name="TEST01",
            out_dir=out_dir,
            geometry=make_stock_geometry(width, depth),
            empty_elevation=empty,
            time_of_day=1100,
            music_track=27,
            music_loop_first=27,
            music_loop_last=27,
            music_loop_skip=-1,
            ambient=(1.0, 1.0, 1.0),
            diffuse=(1.0, 1.0, 1.0),
            specular=(1.0, 1.0, 1.0),
            normal_view="[NormalView]\nTime=900\nFogStart=175",
            static_trn="[TextureType0]\nSolidA0=MN00SA0.MAP\n\n[TextureType3]\nSolidA0=MN33SA0.MAP",
            paint_rules=default_make_trn_rules(),
            legacy_seed=seed,
            **kwargs,
        )

    def test_trn_uses_rectangular_dimensions_and_empty_height(self):
        cfg = self.make_config("unused", width=2560, depth=5120, empty=1234)
        text = build_stock_trn_text(cfg)
        self.assertIn("Width=2560", text)
        self.assertIn("Depth=5120", text)
        self.assertIn("Height=123.400000", text)
        self.assertIn("Time=1100", text)

    def test_trn_preserves_nonzero_msn_origin(self):
        cfg = self.make_config("unused", min_x=3840, min_z=2560)
        text = build_stock_trn_text(cfg)
        self.assertIn("MinX=3840", text)
        self.assertIn("MinZ=2560", text)

    def test_build_emits_all_three_stock_files_with_canonical_geometry(self):
        with tempfile.TemporaryDirectory() as folder:
            cfg = self.make_config(folder)
            result = build_stock_map(cfg)
            self.assertTrue(os.path.isfile(result.trn_path))
            self.assertTrue(os.path.isfile(result.hg2_path))
            self.assertTrue(os.path.isfile(result.mat_path))

            header, heights = read_hg2(result.hg2_path)
            self.assertEqual((header.zone_bits, header.zones_x, header.zones_z), (8, 1, 1))
            self.assertEqual(heights.shape, (256, 256))
            self.assertEqual(os.path.getsize(result.mat_path), expected_mat_bytes(1, 1))
            self.assertEqual(read_mat(result.mat_path, 1, 1).shape, (64, 64))

    def test_empty_elevation_fills_hg2(self):
        with tempfile.TemporaryDirectory() as folder:
            cfg = self.make_config(folder, empty=1234)
            result = build_stock_map(cfg)
            _, heights = read_hg2(result.hg2_path)
            self.assertTrue((heights == 1234).all())

    def test_source_height_raster_replaces_blank_fill(self):
        with tempfile.TemporaryDirectory() as folder:
            source = np.full((256, 256), 100, dtype=np.uint16)
            source[128, 128] = 250
            cfg = self.make_config(folder, source_heights=source)
            result = build_stock_map(cfg)
            _, heights = read_hg2(result.hg2_path)
            np.testing.assert_array_equal(heights, source)

    def test_source_height_geometry_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            cfg = self.make_config(folder, source_heights=np.zeros((128, 128), dtype=np.uint16))
            with self.assertRaisesRegex(ValueError, "does not match terrain geometry"):
                build_stock_map(cfg)


if __name__ == '__main__':
    unittest.main()
