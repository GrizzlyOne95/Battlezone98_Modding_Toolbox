import os
import tempfile
import unittest

from bztoolbox.modules.world.legacy_preflight import emit_resolved_palette, is_legacy_terrain_map_name
from bztoolbox.modules.world.legacy_preflight_hook import _copy_runtime_support_files


class LegacyPreflightTests(unittest.TestCase):
    def test_emits_embedded_stock_palette_requested_by_trn(self):
        with tempfile.TemporaryDirectory() as root:
            source = os.path.join(root, "source")
            output = os.path.join(root, "output")
            os.makedirs(source)
            os.makedirs(output)
            with open(os.path.join(source, "map.trn"), "w", encoding="cp1252") as stream:
                stream.write("[Color]\nPalette=MARS.ACT\n")

            path, check = emit_resolved_palette(source, output)
            self.assertEqual(check.level, "pass")
            self.assertIsNotNone(path)
            self.assertEqual(os.path.basename(path).lower(), "mars.act")
            self.assertEqual(os.path.getsize(path), 768)

    def test_terrain_map_filter_only_matches_atlas_tiles(self):
        self.assertTrue(is_legacy_terrain_map_name("EG00SA0.MAP"))
        self.assertTrue(is_legacy_terrain_map_name("mg12dc3.map"))
        self.assertFalse(is_legacy_terrain_map_name("BLUSKY.MAP"))
        self.assertFalse(is_legacy_terrain_map_name("custom.map"))

    def test_runtime_copy_excludes_all_legacy_map_sources(self):
        with tempfile.TemporaryDirectory() as root:
            source = os.path.join(root, "source")
            output = os.path.join(root, "output")
            os.makedirs(source)
            os.makedirs(output)

            for name, payload in (
                ("EG00SA0.MAP", b"terrain"),
                ("BLUSKY.MAP", b"sky"),
                ("custom.map", b"custom"),
                ("sbshlde0.wav", b"audio"),
                ("mission.bzn", b"bzn"),
            ):
                with open(os.path.join(source, name), "wb") as stream:
                    stream.write(payload)

            copied = _copy_runtime_support_files(source, output)
            self.assertEqual(copied, 2)
            self.assertFalse(os.path.exists(os.path.join(output, "EG00SA0.MAP")))
            self.assertFalse(os.path.exists(os.path.join(output, "BLUSKY.MAP")))
            self.assertFalse(os.path.exists(os.path.join(output, "custom.map")))
            self.assertTrue(os.path.isfile(os.path.join(output, "sbshlde0.wav")))
            self.assertTrue(os.path.isfile(os.path.join(output, "mission.bzn")))


if __name__ == "__main__":
    unittest.main()
