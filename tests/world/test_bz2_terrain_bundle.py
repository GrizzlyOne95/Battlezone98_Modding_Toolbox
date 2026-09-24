import json
import struct
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from bztoolbox.modules.world.bz2_terrain_bundle import build_bz2_terrain_bundle
from bztoolbox.modules.world.mat_codec import decode_entry, read_mat


def ter_fixture():
    version = 5
    cluster = 16
    count = cluster * cluster
    info = 0x1111
    out = bytearray(b"TERR" + struct.pack("<Ihhhh", version, 0, 0, cluster, cluster))
    out.append(0x3F)
    out += struct.pack("<" + "f" * count, *([12.5] * count))
    out += bytes((10, 20, 30)) * count
    out += bytes([0]) * count
    out += bytes([0]) * count
    out += bytes([0]) * count
    out += bytes([0]) * count
    out += struct.pack("<I", info)
    return bytes(out)


class BZ2TerrainBundleTests(unittest.TestCase):
    def test_builds_resolved_candidate_trn_mat_and_atlas(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source"
            source.mkdir()
            ter = source / "map.ter"
            ter.write_bytes(ter_fixture())
            trn = source / "map.trn"
            trn.write_text(
                "[Size]\nMinX=0\nMinZ=0\nWidth=32\nDepth=32\nHeight=150\n\n"
                "[NormalView]\nTime=1200\nFogStart=100\n\n"
                "[Texture]\nTileTexture1=grass.png\n",
                encoding="cp1252",
            )
            Image.new("RGBA", (8, 8), (40, 160, 40, 255)).save(source / "grass.png")

            out = root / "out"
            report = build_bz2_terrain_bundle(
                ter, trn, source, out, "PORTTEST",
                tile_res=8, export_dds=False, export_png=True,
            )

            self.assertEqual(
                report["status"],
                "resolved_terrain_bundle_candidate_requires_in_game_validation",
            )
            self.assertTrue((out / "PORTTEST.hg2").is_file())
            self.assertTrue((out / "PORTTEST.mat").is_file())
            self.assertFalse((out / "PORTTEST_reduced.MAT").exists())
            self.assertTrue((out / "porttest_detail_atlas.csv").is_file())
            self.assertTrue((out / "porttest_detail_atlas.material").is_file())
            self.assertTrue((out / "porttest_neutral.png").is_file())
            self.assertTrue((out / "PORTTEST_CONFIG.TRN").is_file())
            full = (out / "PORTTEST.trn").read_text(encoding="cp1252")
            self.assertIn("[Size]\nMinX=0\nMinZ=0\nWidth=1280\nDepth=1280\nHeight=150", full)
            self.assertIn("[NormalView]\nTime=1200\nFogStart=100", full)
            self.assertNotIn("[Texture]\n", full)
            self.assertIn("[Atlases]\nMaterialName = PORTTEST_DETAIL_ATLAS", full)
            self.assertIn("[TextureType0]\n", full)
            self.assertNotIn("[TextureType1]\n", full)
            entries = read_mat(out / "PORTTEST.mat", 1, 1)
            self.assertEqual({decode_entry(int(value)).base for value in entries.flat}, {0})
            manifest = json.loads((out / "PORTTEST_source_manifest.json").read_text())
            self.assertTrue(manifest["ready_for_atlas"])
            self.assertEqual(manifest["resolved_used_slots"], [1])
            self.assertEqual(manifest["slots"][1]["redux_material"], 0)
            self.assertEqual(report["source_to_redux_material"], {"1": 0})
            self.assertEqual(report["atlas"]["full_trn"], "PORTTEST.trn")


    def test_missing_texture_fails_before_creating_output_folder(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source"
            source.mkdir()
            ter = source / "map.ter"
            ter.write_bytes(ter_fixture())
            trn = source / "map.trn"
            trn.write_text(
                "[Size]\nMinX=0\nMinZ=0\nWidth=32\nDepth=32\nHeight=150\n\n"
                "[Texture]\nTileTexture1=missing.png\n",
                encoding="cp1252",
            )
            out = root / "out"

            with self.assertRaisesRegex(ValueError, "resolution is incomplete"):
                build_bz2_terrain_bundle(
                    ter, trn, source, out, "PORTTEST",
                    tile_res=8, export_dds=False, export_png=True,
                )

            self.assertFalse(out.exists())

    def test_rehomes_bundle_and_reports_object_offset(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            ter = root / "map.ter"
            ter.write_bytes(ter_fixture())
            trn = root / "map.trn"
            trn.write_text("[Texture]\nTileTexture1=grass.png\n", encoding="cp1252")
            Image.new("RGBA", (8, 8), (40, 160, 40, 255)).save(root / "grass.png")
            out = root / "out"
            report = build_bz2_terrain_bundle(
                ter, trn, root, out, "PORTTEST", tile_res=8,
                export_dds=False, export_png=True,
                target_min_x=2560, target_min_z=1280,
            )
            self.assertEqual(report["object_offset_m"], [2560, 0.0, 1280])
            full = (out / "PORTTEST.trn").read_text(encoding="cp1252")
            self.assertIn("[Size]\nMinX=2560\nMinZ=1280", full)



if __name__ == "__main__":
    unittest.main()
