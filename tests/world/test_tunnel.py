import contextlib
import io
import tempfile
import unittest
from pathlib import Path

import numpy as np

from battlezone.terrain.hg2 import HG2Map
from battlezone.terrain.lgt import read_lgt, write_lgt
from battlezone.terrain.tunnel import (
    carve_trench, path_distance, shade_path, shade_polygon, shade_rect, trench_cells,
)

GROUND = 1000                     # 100 m in 0.1 m units


def flat_map(zones=1, height=GROUND) -> HG2Map:
    return HG2Map(np.full((256 * zones, 256 * zones), height, np.uint16), zones, zones)


class CarveTests(unittest.TestCase):
    def test_depth_trench_with_ramps(self):
        hg2 = flat_map()
        result = carve_trench(hg2, [(100, 640), (1100, 640)], 20, depth_m=10, ramp_length_m=100)
        h = hg2.heights * 0.1
        row = 128                                         # z = 640
        self.assertAlmostEqual(h[row, 120], 90.0)         # x = 600: full depth
        self.assertAlmostEqual(h[row, 20], 100.0)         # x = 100: the ramp starts at ground level
        self.assertAlmostEqual(h[row, 30], 95.0, delta=0.11)   # x = 150: half way down the ramp
        ramp = h[row, 20:41]
        self.assertTrue(np.all(np.diff(ramp) <= 1e-9))    # descends steadily
        # 20 m floor: z = 630..650 are floor samples, 625/655 are outside it.
        self.assertTrue(np.allclose(h[126:131, 120], 90.0))
        self.assertEqual(h[125, 120], 100.0)              # a 2:1 wall reaches ground within one sample
        self.assertEqual(result.length_m, 1000.0)
        self.assertAlmostEqual(result.deepest_m, 10.0)
        self.assertEqual(result.clipped, 0)
        self.assertTrue(result.carved[128, 120] and not result.carved[100, 120])

    def test_gentle_walls_and_level_floor(self):
        hg2 = flat_map()
        carve_trench(hg2, [(200, 400), (800, 400)], 10, floor_height_m=90, wall_slope=0.5)
        h = hg2.heights[:, 100] * 0.1                     # x = 500
        self.assertAlmostEqual(h[80], 90.0)               # z = 400
        self.assertAlmostEqual(h[82], 92.5)               # z = 410: 5 m past the 5 m half width, 0.5 per m
        self.assertAlmostEqual(h[84], 97.5)
        self.assertEqual(h[86], 100.0)

    def test_never_raises_and_origin_shift(self):
        rng = np.random.default_rng(3)
        heights = rng.integers(500, 1500, (256, 256)).astype(np.uint16)
        a = HG2Map(heights.copy(), 1, 1)
        carve_trench(a, [(300, 300), (700, 900), (1000, 900)], 15, floor_height_m=80, ramp_length_m=50)
        self.assertTrue(np.all(a.heights <= heights))
        b = HG2Map(heights.copy(), 1, 1)
        carve_trench(b, [(300, 98860), (700, 99460), (1000, 99460)], 15, floor_height_m=80, ramp_length_m=50,
                     origin=(0, 98560))
        np.testing.assert_array_equal(a.heights, b.heights)

    def test_clips_at_zero_and_errors(self):
        hg2 = flat_map(height=20)                           # 2 m ground
        result = carve_trench(hg2, [(100, 100), (300, 100)], 10, depth_m=5)
        self.assertGreater(result.clipped, 0)
        self.assertEqual(hg2.heights.min(), 0)
        with self.assertRaises(ValueError):
            carve_trench(flat_map(), [(0, 0), (10, 0)], 10)                        # neither depth nor floor
        with self.assertRaises(ValueError):
            carve_trench(flat_map(), [(0, 0), (10, 0)], 10, depth_m=1, floor_height_m=1)
        with self.assertRaises(ValueError):
            carve_trench(flat_map(), [(5, 5)], 10, depth_m=1)
        with self.assertRaises(ValueError):
            carve_trench(flat_map(), [(9000, 9000), (9500, 9000)], 10, depth_m=1)    # outside the map

    def test_path_distance(self):
        pts = np.array([[0.0, 0.0], [10.0, 0.0], [10.0, 10.0]])
        d, s = path_distance(np.array([5.0, 12.0, 10.0]), np.array([3.0, 5.0, 15.0]), pts)
        np.testing.assert_allclose(d, [3.0, 2.0, 5.0])
        np.testing.assert_allclose(s, [5.0, 15.0, 20.0])


class ShadeTests(unittest.TestCase):
    def test_rect_with_soft_edge(self):
        lgt = np.full((256, 256), 200, np.uint8)
        out = shade_rect(lgt, 300, 620, 900, 660, value=60, feather_m=5)
        self.assertEqual(out[128, 120], 60)               # inside
        self.assertEqual(out[124, 120], 130)              # on the edge: half way
        self.assertEqual(out[123, 120], 200)              # outside the soft edge
        self.assertEqual(lgt[128, 120], 200)              # the input is not changed

    def test_never_brightens_and_hard_edge(self):
        lgt = np.full((256, 256), 200, np.uint8)
        lgt[128, 120] = 10
        out = shade_polygon(lgt, [(500, 600), (700, 600), (600, 700)], value=60, feather_m=0)
        self.assertEqual(out[128, 120], 10)
        self.assertEqual(out[125, 120], 60)               # (600, 625) is inside the triangle
        self.assertEqual(out[125, 100], 200)              # (500, 625) is outside
        with self.assertRaises(ValueError):
            shade_polygon(lgt, [(0, 0), (1, 1)])

    def test_path_band_and_legacy_cells(self):
        lgt = np.full((128, 128), 255, np.uint8)            # 1.5 layout: 10 m cells
        out = shade_path(lgt, [(100, 640), (1100, 640)], 20, cell_size_m=10, value=56, feather_m=0)
        # cell row r is centred at z = 10 r + 2.5
        self.assertEqual(out[63, 60], 56)                 # z = 632.5
        self.assertEqual(out[64, 60], 56)                 # z = 642.5
        self.assertEqual(out[62, 60], 255)                # z = 622.5

    def test_trench_cells(self):
        carved = np.zeros((256, 256), bool)
        carved[100, 100] = True
        cells = trench_cells(carved, (128, 128))
        self.assertEqual(int(cells.sum()), 9)
        self.assertTrue(cells[49:52, 49:52].all())


class TunnelCliTests(unittest.TestCase):
    def _map(self, folder: Path) -> Path:
        hg2 = flat_map()
        hg2.write(folder / "tt.hg2")
        write_lgt(folder / "tt.lgt", np.full((256, 256), 180, np.uint8), 1, 1, border=56)
        (folder / "tt.trn").write_text("[Size]\nMinX=-640\nMinZ=0\nWidth=1280\nDepth=1280\n")
        return folder / "tt.hg2"

    def _run(self, argv):
        from bztoolbox.modules.terrain_generator.tunnel import main

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(io.StringIO()):
            code = main(argv)
        return code, stdout.getvalue()

    def test_out_folder_leaves_the_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = self._map(Path(tmp))
            before = source.read_bytes()
            code, text = self._run([str(source), "--path", "100,640", "1100,640", "--width", "20", "--depth", "10",
                                    "--ramp", "50", "--roof-shade", "300,620,900,660", "--out", str(Path(tmp) / "o"),
                                    "--preview", str(Path(tmp) / "p.png")])
            self.assertEqual(code, 0, text)
            self.assertEqual(source.read_bytes(), before)
            carved = HG2Map.read(Path(tmp) / "o" / "tt.hg2")
            self.assertAlmostEqual(carved.heights[128, 120] * 0.1, 90.0)
            light, _zx, _zz, cells = read_lgt(Path(tmp) / "o" / "tt.lgt", 1, 1)
            self.assertEqual(cells, 256)
            self.assertEqual(light[128, 120], 64)          # under the roof
            self.assertGreater(light[128, 20], 240)        # ramp top, open sky: rebaked, not the old 180
            self.assertEqual(light[10, 10], 180)           # untouched away from the trench
            self.assertTrue((Path(tmp) / "p.png").is_file())

    def test_overwrite_backs_up_and_world_coordinates(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = self._map(Path(tmp))
            before = source.read_bytes()
            backup = Path(tmp) / "backup"
            code, text = self._run([str(source), "--trn", str(Path(tmp) / "tt.trn"), "--path", "-540,640", "460,640",
                                    "--width", "20", "--floor", "95", "--backup", str(backup)])
            self.assertEqual(code, 0, text)
            self.assertEqual((backup / "tt.hg2").read_bytes(), before)
            self.assertTrue((backup / "tt.lgt").is_file())
            self.assertAlmostEqual(HG2Map.read(source).heights[128, 120] * 0.1, 95.0)
            # Running it again carves nothing more and writes nothing.
            again = source.read_bytes()
            code, text = self._run([str(source), "--trn", str(Path(tmp) / "tt.trn"), "--path", "-540,640",
                                    "460,640", "--width", "20", "--floor", "95", "--backup", str(Path(tmp) / "b2"),
                                    "--no-lgt"])
            self.assertEqual(code, 0, text)
            self.assertIn("carved 0", text)
            self.assertEqual(source.read_bytes(), again)

    def test_dry_run_and_bad_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = self._map(Path(tmp))
            before = source.read_bytes()
            code, _text = self._run([str(source), "--path", "100,640", "1100,640", "--width", "20", "--depth", "5",
                                     "--dry-run"])
            self.assertEqual(code, 0)
            self.assertEqual(source.read_bytes(), before)
            code, _text = self._run([str(source), "--path", "100", "--width", "20", "--depth", "5"])
            self.assertEqual(code, 1)

    def test_page_form(self):
        from bztoolbox.app.pages.tunnel import spec_from_form

        form = dict(path="100,640 1100,640", width="20", mode="floor", amount="90", ramp="", ramps="start",
                    wall_slope="0", roofs="1,2,3,4", shade="60", feather="5", shade_path=True, coords="world",
                    trn="", origin="-640,0")
        spec = spec_from_form(form)
        self.assertEqual((spec.floor, spec.depth, spec.ramp, spec.wall_slope), (90.0, None, 0.0, None))
        self.assertEqual((spec.origin, spec.roof_rects, spec.shade), ((-640.0, 0.0), [(1, 2, 3, 4)], 60))
        for key, bad in (("path", "100,640"), ("width", "wide"), ("roofs", "1,2,3"), ("origin", "")):
            with self.assertRaises(ValueError):
                spec_from_form(dict(form, **{key: bad}))


if __name__ == "__main__":
    unittest.main()
