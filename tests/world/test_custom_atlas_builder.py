import tempfile
import unittest
from pathlib import Path

from PIL import Image

from bztoolbox.modules.world.custom_atlas_builder import build_custom_atlas, generate_transition_mask


class CustomAtlasBuilderTests(unittest.TestCase):
    def test_headless_build_preserves_existing_two_material_matrix_contract(self):
        red = Image.new("RGBA", (8, 8), (255, 0, 0, 255))
        blue = Image.new("RGBA", (8, 8), (0, 0, 255, 255))

        with tempfile.TemporaryDirectory() as folder:
            cfg = {
                "res": 8,
                "prfx": "bz",
                "mode": "Matrix",
                "out_dir": folder,
                "exp_dds": False,
                "exp_png": True,
                "exp_normal": False,
                "exp_specular": False,
                "exp_emissive": False,
                "exp_csv": True,
                "exp_trn": True,
                "exp_mat": True,
                "style": "Square/Blocky",
                "seed": 123,
                "depth": 0.1,
                "teeth": 4,
                "jitter": 0.0,
                "softness": 0,
                "groups": {0: {"A": red}, 1: {"A": blue}},
            }

            result = build_custom_atlas(cfg)
            root = Path(folder)

            self.assertEqual(result["prefix"], "BZ")
            self.assertEqual(result["grid"], 2)
            self.assertEqual(result["atlas_size"], [16, 16])
            self.assertEqual(result["tile_count"], 4)
            self.assertEqual(
                (root / "bz_mapping.csv").read_text(),
                "\n".join([
                    ",0,0,0.5,0.5",
                    "BZ00SA0.MAP,0,0,0.5,0.5",
                    "BZ11SA0.MAP,0.5,0,0.5,0.5",
                    "BZ01CA0.MAP,0,0.5,0.5,0.5",
                    "BZ01DA0.MAP,0.5,0.5,0.5,0.5",
                ]),
            )

            self.assertEqual(
                (root / "BZ_CONFIG.TRN").read_text(),
                "[Atlases]\n"
                "MaterialName = BZ_DETAIL_ATLAS\n\n"
                "[TextureType0]\n"
                "FlatColor= 128\n"
                "SolidA0 = BZ00SA0.MAP\n"
                "CapTo1_A0 = BZ01CA0.MAP\n"
                "DiagonalTo1_A0 = BZ01DA0.MAP\n"
                "[TextureType1]\n"
                "FlatColor= 128\n"
                "SolidA0 = BZ11SA0.MAP\n",
            )

            self.assertEqual(
                (root / "bz_detail_atlas.material").read_text(),
                'import * from "BZTerrainBase.material"\n\n'
                "material BZ_DETAIL_ATLAS : BZTerrainBase\n"
                "{\n"
                "\tset_texture_alias DiffuseMap bz_atlas_d.png\n"
                "\tset_texture_alias EmissiveMap black.dds\n"
                "\tset_texture_alias DetailMap bz_detail.dds\n"
                '\n\tset $diffuse "1 1 1"\n'
                '\tset $ambient "1 1 1"\n'
                '\tset $specular ".25 .25 .25"\n'
                '\tset $shininess "63"\n'
                "}\n",
            )

            atlas = Image.open(root / "bz_atlas_d.png").convert("RGBA")
            self.assertEqual(atlas.size, (16, 16))
            self.assertEqual(atlas.getpixel((1, 1)), (255, 0, 0, 255))
            self.assertEqual(atlas.getpixel((9, 1)), (0, 0, 255, 255))

    def test_explicit_pairs_emit_only_requested_transition_kinds(self):
        red = Image.new("RGBA", (8, 8), (255, 0, 0, 255))
        blue = Image.new("RGBA", (8, 8), (0, 0, 255, 255))
        green = Image.new("RGBA", (8, 8), (0, 255, 0, 255))
        with tempfile.TemporaryDirectory() as folder:
            cfg = {
                "res": 8, "prfx": "bz", "mode": "ExplicitPairs",
                "out_dir": folder, "exp_dds": False, "exp_png": True,
                "exp_normal": False, "exp_specular": False,
                "exp_emissive": False, "exp_csv": True, "exp_trn": True,
                "exp_mat": True, "style": "Square/Blocky", "seed": 0,
                "depth": 0.0, "teeth": 1, "jitter": 0.0, "softness": 0,
                "groups": {0: {"A": red}, 1: {"A": blue}, 2: {"A": green}},
                "cap_pairs": {(0, 1)},
                "diagonal_pairs": {(1, 2)},
            }
            result = build_custom_atlas(cfg)
            self.assertEqual(result["tile_count"], 5)
            trn = (Path(folder) / "BZ_CONFIG.TRN").read_text()
            self.assertIn("CapTo1_A0 = BZ01CA0.MAP", trn)
            self.assertNotIn("DiagonalTo1_A0", trn)
            self.assertIn("DiagonalTo2_A0 = BZ12DA0.MAP", trn)
            self.assertNotIn("CapTo2_A0", trn)
            mapping = (Path(folder) / "bz_mapping.csv").read_text()
            self.assertIn("BZ01CA0.MAP", mapping)
            self.assertIn("BZ12DA0.MAP", mapping)
            self.assertNotIn("BZ01DA0.MAP", mapping)
            self.assertNotIn("BZ12CA0.MAP", mapping)

    def test_mask_service_is_deterministic_for_existing_geometric_style(self):
        cfg = {
            "res": 16,
            "style": "Sawtooth",
            "seed": 42,
            "depth": 0.15,
            "teeth": 5,
            "jitter": 2.0,
            "softness": 0,
        }
        first = generate_transition_mask("cap", cfg)
        second = generate_transition_mask("cap", cfg)
        self.assertEqual(first.tobytes(), second.tobytes())


if __name__ == "__main__":
    unittest.main()
