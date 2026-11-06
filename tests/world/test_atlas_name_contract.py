import importlib.util
import tempfile
import unittest
from pathlib import Path

from PIL import Image
import numpy as np

from battlezone.terrain.atlas import validate_tile_name
from bztoolbox.modules.world.custom_atlas_builder import build_custom_atlas

ROOT = Path(__file__).resolve().parents[2]


def script(name):
    spec = importlib.util.spec_from_file_location(
        "cc_atlas_" + name, ROOT / "scripts/world/cc_atlas" / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AtlasNameContractTests(unittest.TestCase):
    def test_numeric_prefix_transitions_are_checked_and_bad_edges_rejected(self):
        checker = script("verify_atlas")
        builder = script("build_world")
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            names = ("i4c00s1", "i4c11s1", "i4c01c1", "i4c01d1")
            (root / "test.csv").write_text("\n".join(
                f"{name}.map,{(i % 2)/2},{(i // 2)/2},0.5,0.5" for i, name in enumerate(names)))
            solid_a = np.full((16, 16, 3), (32, 64, 96), np.uint8)
            solid_b = np.full((16, 16, 3), (192, 160, 128), np.uint8)
            cap = solid_a.copy(); cap[12:, 4:12] = solid_b[12:, 4:12]
            diagonal = solid_a.copy(); diagonal[8:, 8:] = solid_b[8:, 8:]
            diagonal[-1, 1:] = solid_b[-1, 1:]
            diagonal[1:, -1] = solid_b[1:, -1]
            def write(cap_image):
                image = np.concatenate((np.concatenate((solid_a, solid_b), 1),
                                        np.concatenate((cap_image, diagonal), 1)), 0)
                levels = [builder.bc1.encode_bc1(np.asarray(Image.fromarray(image).resize((n,n), Image.Resampling.BOX)))
                          for n in (32,16,8)]
                builder.write_dxt1(root / "TEST_ATLAS_D.dds", 32, 32, levels)
            # Deliberately wrong cap must fail; the old alphabetic-only regex
            # silently checked zero transitions and accepted this fixture.
            write(solid_b)
            count, failures = checker.verify(str(root))
            self.assertEqual(count, 2)
            self.assertTrue(any("i4c01c1: N edge" in f for f in failures), failures)
            cap[-1, 2:14] = solid_b[-1, 2:14]
            write(cap)
            count, failures = checker.verify(str(root))
            self.assertEqual(count, 2)
            self.assertEqual(failures, [])
            # Authored intact/damaged variants may share their entire border.
            # A nearest-solid vote is meaningless there, despite their distinct
            # interiors. The matching edge should pass; foreign colours should
            # still be rejected.
            solid_b[[0, -1], :] = solid_a[[0, -1], :]
            solid_b[:, [0, -1]] = solid_a[:, [0, -1]]
            cap = solid_a.copy(); diagonal[:] = solid_a
            write(cap)
            self.assertEqual(checker.verify(str(root)), (2, []))
            cap[-1] = (255, 0, 0)
            write(cap)
            count, failures = checker.verify(str(root))
            self.assertEqual(count, 2)
            self.assertTrue(any("i4c01c1: S edge" in f for f in failures), failures)

    def test_name_boundary_includes_extension_and_terminator(self):
        validate_tile_name("quarryx00s1.map")
        with self.assertRaisesRegex(ValueError, "15 bytes"):
            validate_tile_name("jvquarry00s1.map")

    def test_custom_builder_rejects_long_alias_before_writing(self):
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder) / "atlas"
            with self.assertRaisesRegex(ValueError, "shorter tile prefix"):
                build_custom_atlas(dict(res=8, prfx="jvquarry", mode="SolidsOnly",
                                        out_dir=str(out), groups={0: {"A": Image.new("RGBA", (8, 8))}}))
            self.assertFalse(out.exists())

    def test_cc_planner_rejects_long_prefix(self):
        builder = script("build2")
        cfg = dict(tile="jvquarry", types={0: "source.tga"}, blend=[0], pool=[])
        with self.assertRaisesRegex(ValueError, "15 bytes"):
            builder.plan_tiles("quarry_detail_atlas", cfg, [])
        with tempfile.TemporaryDirectory() as folder:
            out = Path(folder) / "atlas"
            with self.assertRaisesRegex(ValueError, "15 bytes"):
                builder.build("quarry_detail_atlas", cfg, str(out), [])
            self.assertFalse(out.exists())
        cfg["tile"] = "jq"
        tiles, _ = builder.plan_tiles("quarry_detail_atlas", cfg, [])
        self.assertEqual(tiles[0]["name"], "jq00s1")

    def test_trn_checker_uses_first_section_and_checks_lookup_name_length(self):
        checker = script("check_trn")
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            new = root / "trns"; new.mkdir()
            atlas = root / "atlases" / "quarry_detail_atlas"; atlas.mkdir(parents=True)
            path = new / "quarry.trn"
            csv = atlas / "quarry_detail_atlas.csv"
            valid = ("; comment mentioning [Atlases]\n[Atlases]\n"
                     "MaterialName=QUARRY_DETAIL_ATLAS\n[TextureType0]\nSolidA0=jq00s1.map\n")
            path.write_text(valid)
            csv.write_text(",0,0,1,1\njq00s1.map,0,0,1,1\n")
            self.assertEqual(checker.main(new, root / "atlases", root / "no_originals"), 0)
            path.write_text("[Atlases]\n" + valid)
            self.assertEqual(checker.main(new, root / "atlases", root / "no_originals"), 1)
            path.write_text(valid.replace("jq00s1", "jvquarry00s1"))
            csv.write_text(",0,0,1,1\njvquarry00s1.map,0,0,1,1\n")
            self.assertEqual(checker.main(new, root / "atlases", root / "no_originals"), 1)
