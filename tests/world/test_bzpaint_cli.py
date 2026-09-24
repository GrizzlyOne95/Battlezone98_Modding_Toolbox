import tempfile
import unittest
from pathlib import Path

import numpy as np

from bztoolbox.modules.world import bzpaint
from bztoolbox.modules.world.hg2_codec import write_hg2
from bztoolbox.modules.world.mat_codec import decode_entry, read_mat


class BZPaintCliTests(unittest.TestCase):
    def test_legacy_make_trn_switches_are_accepted(self):
        self.assertEqual(
            bzpaint._normalize_legacy_args(["moon.trn", "/p=moon.ini", "/e=-25", "--seed", "7"]),
            ["moon.trn", "--params", "moon.ini", "--empty-elevation", "-25", "--seed", "7"],
        )

    def test_unrelated_absolute_paths_are_not_rewritten(self):
        self.assertEqual(
            bzpaint._normalize_legacy_args(["/tmp/world.trn", "/tmp/params.ini"]),
            ["/tmp/world.trn", "/tmp/params.ini"],
        )

    def test_end_to_end_legacy_parameter_paint(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            trn = root / "moon.trn"
            hg2 = root / "moon.hg2"
            ini = root / "moon.ini"
            mat = root / "moon.mat"

            trn.write_text(
                "[Size]\nMinX=0\nMinZ=0\nWidth=1280\nDepth=1280\n"
                "[TextureType2]\nSolidA0=dummy.map\n",
                encoding="cp1252",
            )
            ini.write_text(
                "[Layer0]\n"
                "ElevationStart=0\nElevationEnd=4095\n"
                "SlopeStart=0\nSlopeEnd=90\nMaterial=2\n",
                encoding="cp1252",
            )
            write_hg2(
                hg2,
                np.full((256, 256), 100, dtype=np.uint16),
                zones_x=1,
                zones_z=1,
            )

            result = bzpaint.paint_trn(trn, parameter_path=ini, seed=1)
            self.assertTrue(result.wrote_file)
            self.assertEqual((result.entries_x, result.entries_z), (64, 64))
            self.assertEqual(result.parameters, str(ini))
            self.assertTrue(mat.exists())
            self.assertEqual(mat.stat().st_size, 8192)

            entries = read_mat(mat, 1, 1)
            first = decode_entry(int(entries[0, 0]))
            self.assertEqual((first.base, first.next), (2, 2))
            self.assertIn(first.variant, (0, 1, 2, 3))

    def test_dry_run_does_not_write_output(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            trn = root / "flat.trn"
            hg2 = root / "flat.hg2"
            output = root / "should_not_exist.mat"
            trn.write_text("[Size]\nWidth=1280\nDepth=1280\n", encoding="cp1252")
            write_hg2(hg2, np.zeros((256, 256), dtype=np.uint16), 1, 1)

            result = bzpaint.paint_trn(trn, output_path=output, dry_run=True)
            self.assertFalse(result.wrote_file)
            self.assertFalse(output.exists())
            self.assertEqual((result.entries_x, result.entries_z), (64, 64))

    def test_parameter_file_requires_valid_layers(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            trn = root / "bad.trn"
            hg2 = root / "bad.hg2"
            ini = root / "bad.ini"
            trn.write_text("[Size]\nWidth=1280\nDepth=1280\n", encoding="cp1252")
            ini.write_text("[Other]\nValue=1\n", encoding="cp1252")
            write_hg2(hg2, np.zeros((256, 256), dtype=np.uint16), 1, 1)

            with self.assertRaisesRegex(ValueError, "no valid .*Layer0"):
                bzpaint.paint_trn(trn, parameter_path=ini)


if __name__ == "__main__":
    unittest.main()
