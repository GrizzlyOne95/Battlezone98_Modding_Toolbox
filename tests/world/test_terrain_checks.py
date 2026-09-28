import tempfile
import unittest
from pathlib import Path

import numpy as np

from battlezone.terrain.hg2 import HG2Map
from battlezone.terrain.lgt import bake_redux_lgt, read_lgt, write_lgt
from battlezone.validation import validate_project
from battlezone.validation.fixes import apply_fixes
from bztoolbox.modules.terrain_generator.relight import relight


def _terrain(seed: int) -> np.ndarray:
    y, x = np.mgrid[0:256, 0:256]
    return (1500 + 400 * np.sin(x / (15.0 + seed)) + 300 * np.cos(y / (11.0 + seed))).astype(np.uint16)


def _map(root: Path, stem: str, seed: int, light=None) -> None:
    heights = _terrain(seed)
    HG2Map(heights, 1, 1).write(root / f"{stem}.hg2")
    if light is not None:
        write_lgt(root / f"{stem}.lgt", light, 1, 1, border=56)


class LightMapCheckTests(unittest.TestCase):
    def rules(self, root):
        return sorted((i.rule_id, Path(i.path).name) for i in validate_project(root, ["lgt"]).issues)

    def test_good_flat_mismatched_missing_and_shared(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            _map(root, "good", 1, bake_redux_lgt(_terrain(1), 1, 1))
            _map(root, "flat", 2, np.full((256, 256), 56, np.uint8))
            _map(root, "wrong", 3, bake_redux_lgt(_terrain(9), 1, 1).T.copy())
            _map(root, "bare", 4)
            shared = bake_redux_lgt(_terrain(5), 1, 1)
            _map(root, "sharea", 5, shared)
            _map(root, "shareb", 6, shared)
            self.assertEqual(self.rules(root), [
                ("lgt-flat", "flat.lgt"), ("lgt-mismatch", "wrong.lgt"),
                ("lgt-missing", "bare.hg2"), ("lgt-shared", "sharea.lgt"), ("lgt-shared", "shareb.lgt")])

            report = validate_project(root, ["lgt"])
            fixes = [(i.path, i.line, i.fix) for i in report.issues if i.fix]
            backup = root.parent / (root.name + "-backup")
            changed = apply_fixes(root, fixes, backup)
            self.assertIn("bare.lgt", changed)
            self.assertTrue((backup / "flat.lgt").is_file())
            self.assertEqual(self.rules(root), [])
            light = read_lgt(root / "flat.lgt", 1, 1)[0]
            np.testing.assert_array_equal(light, bake_redux_lgt(_terrain(2), 1, 1))

    def test_relight_only_broken(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "maps"
            root.mkdir()
            good = bake_redux_lgt(_terrain(1), 1, 1)
            _map(root, "good", 1, good)
            _map(root, "flat", 2, np.full((256, 256), 56, np.uint8))
            result = relight([root], only_broken=True, backup_dir=Path(tmp) / "bak")
            self.assertEqual([Path(p).name for p in result.rebaked], ["flat.lgt"])
            self.assertTrue((Path(tmp) / "bak" / "maps" / "flat.lgt").is_file())
            dry = relight([root / "good.hg2"], dry_run=True)
            self.assertEqual([Path(p).name for p in dry.rebaked], ["good.lgt"])


class TileAndSpriteCheckTests(unittest.TestCase):
    TRN = "[Sky]\r\nSunTexture={sun}\r\n{atlas}[TextureType0]\r\nSolidA0 = XX00SA0.MAP\r\n"

    def _project(self, root: Path, sun="sun.0", atlas=True) -> None:
        text = self.TRN.format(sun=sun, atlas="[Atlases]\r\nMaterialName = xx_detail_atlas\r\n" if atlas else "")
        (root / "m.trn").write_bytes(text.encode("cp1252"))
        entries = np.zeros(64 * 64, dtype="<u2")
        entries[:7] = (7 << 12) | (7 << 8)
        entries.tofile(root / "m.mat")

    def test_undefined_tiles(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._project(Path(tmp))
            (issue,) = validate_project(tmp, ["tiles"]).issues
            self.assertEqual((issue.severity, issue.rule_id), ("info", "trn-undefined-tiles"))
            self.assertIn("7 cell(s)", issue.message)
        with tempfile.TemporaryDirectory() as tmp:
            self._project(Path(tmp), atlas=False)
            (issue,) = validate_project(tmp, ["tiles"]).issues
            self.assertEqual(issue.severity, "warning")

    def test_sun_sprites(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._project(Path(tmp))
            self.assertEqual(validate_project(tmp, ["sprites"]).issues, [])
        with tempfile.TemporaryDirectory() as tmp:
            self._project(Path(tmp), sun="sunblue")
            (issue,) = validate_project(tmp, ["sprites"]).issues
            self.assertEqual((issue.rule_id, issue.line), ("trn-unknown-sprite", 2))
            (Path(tmp) / "spritea.sta").write_text('"sunblue"  bluesun  0 0 512 512 512 512 0x00000000\n')
            self.assertEqual(validate_project(tmp, ["sprites"]).issues, [])


if __name__ == "__main__":
    unittest.main()
