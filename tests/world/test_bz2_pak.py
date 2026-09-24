import struct
import tempfile
import unittest
import zlib
from pathlib import Path

from bztoolbox.modules.world.bz2_pak import PakArchive
from bztoolbox.modules.world.bz2_texture_resolver import (build_texture_slot_manifest,
                                  find_texture_asset_root, resolve_trn_texture_slots)
from tests.world.test_bz2_texture_resolver import source_with_slots


def write_pak(path: Path, entries):
    data = bytearray(b"DOCP" + b"\0" * 52)
    records = bytearray()
    for name, payload, compressed in entries:
        stored = zlib.compress(payload) if compressed else payload
        offset = len(data)
        data.extend(stored)
        encoded = name.encode("cp1252")
        records.extend(struct.pack("<IB", 0, len(encoded)))
        records.extend(encoded)
        records.extend(struct.pack("<III", offset, len(stored), len(payload)))
    toc = len(data)
    data.extend(records)
    struct.pack_into("<IIIII", data, 4, 2, 0, len(data), len(entries), toc)
    path.write_bytes(data)


class PakTests(unittest.TestCase):
    def test_selective_read_extract_and_trn_resolution(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            write_pak(root / "smtex.pak", [("Pluto.TGA", b"texture", True),
                                            ("other.tga", b"other", False)])
            pak = PakArchive(root / "smtex.pak")
            self.assertEqual(pak.read("pluto.tga"), b"texture")
            self.assertEqual(pak.extract("PLUTO.tga", root / "out").read_bytes(), b"texture")
            with self.assertRaises(ValueError):
                pak.extract("../outside.tga", root / "out")
            trn = root / "map.trn"
            trn.write_text("[Texture]\nTileTexture1=pluto.tga\n", encoding="cp1252")
            manifest = build_texture_slot_manifest(source_with_slots(1, 1, 1, 1))
            self.assertEqual(find_texture_asset_root(manifest, trn, [root]), root)
            resolved = resolve_trn_texture_slots(manifest, trn, root)
            self.assertTrue(resolved["ready_for_atlas"])
            self.assertEqual(resolved["slots"][1]["source_member"], "Pluto.TGA")

    def test_baked_dds_fills_legacy_tga_missing_from_pak(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            baked = root / "bz2r_res" / "baked" / "Worlds" / "Pluto"
            baked.mkdir(parents=True)
            (baked / "pluto9.dds").write_bytes(b"baked")
            trn = root / "map.trn"
            trn.write_text("[Texture]\nTileTexture1=pluto9.tga\n", encoding="cp1252")
            manifest = build_texture_slot_manifest(source_with_slots(1, 1, 1, 1))
            resolved = resolve_trn_texture_slots(manifest, trn, root)
            self.assertTrue(resolved["ready_for_atlas"])
            self.assertEqual(resolved["slots"][1]["source_substitution"],
                             "baked_dds_same_stem")

    def test_rejects_damaged_member(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "bad.pak"
            write_pak(path, [("one.tga", b"large payload" * 10, True)])
            data = bytearray(path.read_bytes())
            data[56] ^= 0xff
            path.write_bytes(data)
            with self.assertRaises(ValueError):
                PakArchive(path).read("one.tga")


if __name__ == "__main__":
    unittest.main()
