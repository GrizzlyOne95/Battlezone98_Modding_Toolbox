import tempfile
import unittest
from pathlib import Path

from PIL import Image

from bztoolbox.modules.world.bz2_atlas_port import build_bz2_direct_atlas


def resolved_manifest(root: Path):
    slots = []
    used = {0: "grass.png", 10: "rock.png", 15: "snow.png"}
    colors = {
        0: (20, 160, 20, 255),
        10: (120, 100, 80, 255),
        15: (240, 240, 255, 255),
    }
    for slot, filename in used.items():
        Image.new("RGBA", (6, 6), colors[slot]).save(root / filename)

    for slot in range(16):
        is_used = slot in used
        slots.append({
            "slot": slot,
            "used": is_used,
            "usage_count": 1 if is_used else 0,
            "status": "resolved" if is_used else "unused",
            "source_name": used.get(slot),
            "source_path": str((root / used[slot]).resolve()) if is_used else None,
            "redux_material": slot,
            "atlas_tile": None,
        })

    return {
        "schema_version": 1,
        "slots": slots,
        "unresolved_used_slots": [],
        "resolved_used_slots": [0, 10, 15],
        "ready_for_atlas": True,
    }


class BZ2DirectAtlasTests(unittest.TestCase):
    def test_sparse_high_slots_preserve_texture_type_ids(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            manifest = resolved_manifest(root)
            out = root / "out"

            result = build_bz2_direct_atlas(
                manifest, out, "P", tile_res=8, export_dds=False, export_png=True
            )

            self.assertEqual(sorted(result["source_slots"]), [0, 10, 15])
            self.assertEqual(
                result["slot_to_atlas_alias"],
                {
                    0: "P00SA0.MAP",
                    10: "PAASA0.MAP",
                    15: "PFFSA0.MAP",
                },
            )
            self.assertEqual(result["tile_count"], 3)
            self.assertEqual(result["transition_policy"],
                             "none_until_MAT_reduction_proves_required_pairs")

            trn = (out / "P_CONFIG.TRN").read_text()
            self.assertIn("[TextureType0]\n", trn)
            self.assertIn("[TextureType10]\n", trn)
            self.assertIn("[TextureType15]\n", trn)
            self.assertNotIn("[TextureType1]\n", trn)
            self.assertNotIn("CapTo", trn)
            self.assertNotIn("DiagonalTo", trn)
            self.assertIn("SolidA0 = P00SA0.MAP", trn)
            self.assertIn("SolidA0 = PAASA0.MAP", trn)
            self.assertIn("SolidA0 = PFFSA0.MAP", trn)

            mapping = (out / "p_detail_atlas.csv").read_text()
            self.assertIn("P00SA0.MAP", mapping)
            self.assertIn("PAASA0.MAP", mapping)
            self.assertIn("PFFSA0.MAP", mapping)
            self.assertTrue((out / "p_neutral.png").is_file())
            material = (out / "p_detail_atlas.material").read_text()
            self.assertIn("set_texture_alias DetailMap p_neutral.png", material)
            self.assertIn("set_texture_alias SpecularMap p_neutral.png", material)

    def test_exact_mat_pairs_generate_only_required_transitions(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            manifest = resolved_manifest(root)
            result = build_bz2_direct_atlas(
                manifest, root / "out", "P", tile_res=8,
                export_dds=False, export_png=True,
                cap_pairs={(0, 10)}, diagonal_pairs={(10, 15)},
            )

            self.assertEqual(result["transition_policy"], "exact_pairs_from_encoded_MAT")
            self.assertEqual(result["cap_pairs"], [(0, 10)])
            self.assertEqual(result["diagonal_pairs"], [(10, 15)])
            self.assertEqual(result["tile_count"], 5)
            trn = (root / "out" / "P_CONFIG.TRN").read_text()
            self.assertIn("CapTo10_A0 = P0ACA0.MAP", trn)
            self.assertNotIn("DiagonalTo10_A0", trn)
            self.assertIn("DiagonalTo15_A0 = PAFDA0.MAP", trn)
            self.assertNotIn("CapTo15_A0", trn)

    def test_unresolved_manifest_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            manifest = resolved_manifest(root)
            manifest["ready_for_atlas"] = False
            manifest["unresolved_used_slots"] = [10]
            with self.assertRaisesRegex(ValueError, "unresolved texture slots"):
                build_bz2_direct_atlas(
                    manifest, root / "out", "P",
                    tile_res=8, export_dds=False, export_png=True,
                )

    def test_material_remap_updates_texture_type_and_alias(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            manifest = resolved_manifest(root)
            manifest["slots"][10]["redux_material"] = 3
            result = build_bz2_direct_atlas(
                manifest, root / "out", "P",
                tile_res=8, export_dds=False, export_png=True,
            )
            self.assertEqual(result["source_to_redux_material"][10], 3)
            self.assertIn("[TextureType3]\n", (root / "out" / "P_CONFIG.TRN").read_text())
            self.assertNotIn("[TextureType10]\n", (root / "out" / "P_CONFIG.TRN").read_text())

    def test_duplicate_redux_material_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            manifest = resolved_manifest(root)
            manifest["slots"][10]["redux_material"] = 0
            with self.assertRaisesRegex(ValueError, "same Redux material 0"):
                build_bz2_direct_atlas(
                    manifest, root / "out", "P",
                    tile_res=8, export_dds=False, export_png=True,
                )

    def test_companion_trn_empty_zero_slot_is_skipped(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            Image.new("RGBA", (6, 6), (120, 100, 80, 255)).save(root / "rock.png")
            manifest = {
                "ready_for_atlas": True,
                "unresolved_used_slots": [],
                "slots": [
                    {"slot": 0, "used": True, "status": "empty", "source_path": None,
                     "redux_material": 0},
                    {"slot": 1, "used": True, "status": "resolved",
                     "source_path": str((root / "rock.png").resolve()), "redux_material": 1},
                ],
            }
            result = build_bz2_direct_atlas(
                manifest, root / "out", "P", tile_res=8,
                export_dds=False, export_png=True,
            )
            self.assertEqual(sorted(result["source_slots"]), [1])


if __name__ == "__main__":
    unittest.main()
