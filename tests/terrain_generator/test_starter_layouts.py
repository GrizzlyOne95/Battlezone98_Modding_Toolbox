import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage

from bztoolbox.modules import terrain_generator as hmg
from bztoolbox.modules.terrain_generator.height_import import load_height_file
from bztoolbox.modules.terrain_generator.starter_layouts import LAYOUT_CONTROLS, STARTER_LAYOUTS


class StarterLayoutTests(unittest.TestCase):
    def test_starter_layouts_head_the_style_list(self):
        self.assertEqual(list(hmg.RECIPES)[: len(STARTER_LAYOUTS)], list(STARTER_LAYOUTS))
        self.assertEqual(set(LAYOUT_CONTROLS), set(STARTER_LAYOUTS))

    def test_single_plateau_is_flat_and_rises_by_plateau_height(self):
        settings = hmg.GeneratorSettings(zones_x=2, zones_z=2, seed=5, plateaus=1, plateau_height=300.0)
        heights = hmg.generate("Simple Arena", settings).heights.astype(int)
        top = heights[252:261, 252:261]
        self.assertEqual(int(top.min()), int(top.max()))
        self.assertAlmostEqual(int(top[4, 4]) - int(heights.min()), 300, delta=20)

    def test_plateau_count_changes_the_map(self):
        base = hmg.GeneratorSettings(zones_x=1, zones_z=1, seed=7)
        maps = [hmg.generate("Simple Arena", replace(base, plateaus=n)).heights for n in (0, 2, 4)]
        self.assertFalse(np.array_equal(maps[0], maps[1]))
        self.assertFalse(np.array_equal(maps[1], maps[2]))


    def test_mirrored_arena_keeps_whole_plateaus(self):
        for symmetry, flip in (("Mirror X", np.fliplr), ("Mirror Z", np.flipud)):
            settings = hmg.GeneratorSettings(zones_x=2, zones_z=2, seed=9, plateaus=3, symmetry=symmetry)
            heights = hmg.generate("Simple Arena", settings).heights.astype(int)
            self.assertTrue(np.array_equal(heights, flip(heights)), symmetry)
            yy, xx = np.mgrid[0:512, 0:512]
            inside_wall = np.hypot(xx - 255.5, yy - 255.5) < 0.7 * 256
            tops = (heights > int(heights[256, 256]) + 200) & inside_wall
            self.assertEqual(ndimage.label(tops)[1], 3, symmetry)


class HeightImportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_hg2_round_trip(self):
        source = hmg.generate("Two Bases", hmg.GeneratorSettings(zones_x=2, zones_z=1, seed=3))
        path = self.dir / "map.hg2"
        source.write(path)
        loaded = load_height_file(path, 5, 5)
        self.assertEqual((loaded.zones_x, loaded.zones_z), (2, 1))
        self.assertTrue(np.array_equal(loaded.heights, source.heights))

    def test_16bit_png_is_lossless_and_keeps_its_zones(self):
        source = hmg.generate("Flat Field", hmg.GeneratorSettings(zones_x=1, zones_z=2, seed=3))
        path = self.dir / "map.png"
        source.write_png16(path)
        loaded = load_height_file(path, 4, 4)
        self.assertEqual((loaded.zones_x, loaded.zones_z), (1, 2))
        self.assertTrue(np.array_equal(loaded.heights, source.heights))

    def test_8bit_image_is_one_metre_per_level_and_resized_to_zones(self):
        grey = np.zeros((100, 150), dtype=np.uint8)
        grey[:, 75:] = 200
        path = self.dir / "drawn.png"
        Image.fromarray(grey, mode="L").save(path)
        loaded = load_height_file(path, 3, 2)
        self.assertEqual(loaded.heights.shape, (2 * 256, 3 * 256))
        self.assertEqual(int(loaded.heights[:, 0].max()), 0)
        self.assertEqual(int(loaded.heights[:, -1].min()), 2000)


if __name__ == "__main__":
    unittest.main()
