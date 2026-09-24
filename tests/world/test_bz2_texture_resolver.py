import tempfile
import unittest
from pathlib import Path

import numpy as np

from bztoolbox.modules.world.bz2_ter_codec import SourceTerrain
from bztoolbox.modules.world.bz2_texture_resolver import (
    build_texture_slot_manifest,
    extract_trn_texture_slots,
    find_loose_texture_root,
    resolve_named_texture_slots,
    resolve_trn_texture_slots,
)


def source_with_slots(*slots):
    info = 0
    for layer, slot in enumerate(slots):
        info |= int(slot) << (4 * layer)
    return SourceTerrain(
        version=5,
        grid_min_x=0,
        grid_min_z=0,
        grid_max_x=16,
        grid_max_z=16,
        heights_m=np.zeros((16, 16), dtype=np.float32),
        colors=np.zeros((16, 16, 3), dtype=np.uint8),
        alphas=np.zeros((3, 16, 16), dtype=np.uint8),
        cells=np.zeros((16, 16), dtype=np.uint8),
        info=np.array([[info]], dtype=np.uint32),
    )


class BZ2TextureResolverTests(unittest.TestCase):
    def test_extracts_direct_tile_texture_numbers_from_companion_trn(self):
        with tempfile.TemporaryDirectory() as folder:
            trn = Path(folder) / "map.trn"
            trn.write_text(
                '[Size]\nWidth=2560\n\n'
                '[Texture] // BZ2 legacy section\n'
                'TileTexture1 = "terrain/pluto.tga"\n'
                'TileTexture8=terrain\\pluto9.tga\n\n'
                '[World]\nMusicTrack=1\n',
                encoding="cp1252",
            )
            self.assertEqual(
                extract_trn_texture_slots(trn),
                {1: "terrain/pluto.tga", 8: r"terrain\pluto9.tga"},
            )

    def test_companion_trn_resolution_keeps_missing_slots_blocking(self):
        source = source_with_slots(1, 2, 8, 0)
        manifest = build_texture_slot_manifest(source)

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "pluto.tga").write_bytes(b"one")
            (root / "pluto2.tga").write_bytes(b"two")
            trn = root / "map.trn"
            trn.write_text(
                "[Texture]\n"
                'TileTexture1="pluto.tga"\n'
                'TileTexture2="pluto2.tga"\n',
                encoding="cp1252",
            )

            resolved = resolve_trn_texture_slots(manifest, trn, root)
            self.assertEqual(resolved["resolved_used_slots"], [1, 2])
            self.assertEqual(resolved["empty_used_slots"], [0])
            self.assertEqual(resolved["unresolved_used_slots"], [8])
            self.assertFalse(resolved["ready_for_atlas"])
            self.assertEqual(resolved["slots"][0]["status"], "empty")
            self.assertEqual(resolved["material_index_offset"], -1)
            self.assertEqual(resolved["slots"][1]["redux_material"], 0)
            self.assertEqual(resolved["slots"][2]["redux_material"], 1)

    def test_explicit_tile_texture_zero_preserves_material_numbers(self):
        source = source_with_slots(0, 1, 1, 0)
        manifest = build_texture_slot_manifest(source)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "zero.png").write_bytes(b"zero")
            (root / "one.png").write_bytes(b"one")
            trn = root / "map.trn"
            trn.write_text("[Texture]\nTileTexture0=zero.png\nTileTexture1=one.png\n",
                           encoding="cp1252")
            resolved = resolve_trn_texture_slots(manifest, trn, root)
            self.assertTrue(resolved["ready_for_atlas"])
            self.assertEqual(resolved["material_index_offset"], 0)
            self.assertEqual(resolved["slots"][0]["redux_material"], 0)
            self.assertEqual(resolved["slots"][1]["redux_material"], 1)

    def test_finds_only_a_complete_loose_texture_root(self):
        manifest = build_texture_slot_manifest(source_with_slots(1, 1, 1, 1))
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            packed = root / "game"
            packed.mkdir()
            (packed / "lgtex.pak").write_bytes(b"packed")
            loose = root / "extracted"
            loose.mkdir()
            (loose / "pluto.tga").write_bytes(b"loose")
            trn = root / "map.trn"
            trn.write_text("[Texture]\nTileTexture1=pluto.tga\n", encoding="cp1252")
            self.assertEqual(find_loose_texture_root(manifest, trn, [packed, loose]), loose.resolve())
            self.assertIsNone(find_loose_texture_root(manifest, trn, [packed]))

    def test_resolves_exact_names_case_insensitively_without_renumbering(self):
        source = source_with_slots(1, 2, 3, 4)
        manifest = build_texture_slot_manifest(source)

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            terrain = root / "Terrain"
            terrain.mkdir()
            (terrain / "Rock.DDS").write_bytes(b"rock")
            (terrain / "Sand.tga").write_bytes(b"sand")
            (terrain / "Mud.PNG").write_bytes(b"mud")
            (terrain / "Ice.dds").write_bytes(b"ice")

            resolved = resolve_named_texture_slots(
                manifest,
                {
                    1: "terrain/rock.dds",
                    2: "TERRAIN\\SAND.TGA",
                    3: "Terrain/mud.png",
                    4: "terrain/ICE.DDS",
                },
                root,
            )

            self.assertEqual(resolved["resolved_used_slots"], [1, 2, 3, 4])
            self.assertEqual(resolved["unresolved_used_slots"], [])
            self.assertTrue(resolved["ready_for_atlas"])
            for slot in (1, 2, 3, 4):
                self.assertEqual(resolved["slots"][slot]["redux_material"], slot)
                self.assertEqual(resolved["slots"][slot]["status"], "resolved")
                self.assertTrue(Path(resolved["slots"][slot]["source_path"]).is_file())

    def test_missing_used_name_stays_blocking(self):
        source = source_with_slots(1, 2, 3, 4)
        manifest = build_texture_slot_manifest(source)

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / "rock.dds").write_bytes(b"rock")

            resolved = resolve_named_texture_slots(
                manifest,
                {1: "rock.dds", 2: "missing.dds"},
                root,
            )

            self.assertEqual(resolved["resolved_used_slots"], [1])
            self.assertEqual(resolved["unresolved_used_slots"], [2, 3, 4])
            self.assertFalse(resolved["ready_for_atlas"])
            self.assertEqual(resolved["slots"][2]["status"], "missing")
            self.assertIsNone(resolved["slots"][2]["source_path"])

    def test_rejects_paths_outside_asset_root(self):
        source = source_with_slots(1, 1, 1, 1)
        manifest = build_texture_slot_manifest(source)

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name in ("../rock.dds", "/tmp/rock.dds", r"C:\\rock.dds"):
                with self.subTest(name=name):
                    with self.assertRaisesRegex(ValueError, "below asset root"):
                        resolve_named_texture_slots(manifest, {1: name}, root)


if __name__ == "__main__":
    unittest.main()
