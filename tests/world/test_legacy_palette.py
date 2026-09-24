import hashlib
import os
import tempfile
import unittest

from bztoolbox.modules.world.legacy_palette import (
    read_trn_palette_reference,
    resolve_legacy_palette,
    scan_trn_palette_references,
)


class LegacyPaletteTests(unittest.TestCase):
    def _write_trn(self, root, name, palette=None):
        path = os.path.join(root, name)
        with open(path, "w", encoding="cp1252") as stream:
            stream.write("[Size]\nWidth=1280\nDepth=1280\n\n")
            if palette is not None:
                stream.write(f"[Color]\nPalette={palette}\nLuma=MARS.LUM\n")
        return path

    def test_reads_palette_from_color_section(self):
        with tempfile.TemporaryDirectory() as root:
            path = self._write_trn(root, "legends.trn", "MARS.ACT")
            self.assertEqual(read_trn_palette_reference(path), "MARS.ACT")

    def test_legends_style_missing_mars_uses_embedded_stock_palette(self):
        with tempfile.TemporaryDirectory() as root:
            self._write_trn(root, "legends.trn", "MARS.ACT")
            result = resolve_legacy_palette(root)
            self.assertTrue(result.ok)
            self.assertEqual(result.status, "embedded")
            self.assertEqual(result.requested, "mars.act")
            self.assertTrue(os.path.isfile(result.path))
            with open(result.path, "rb") as stream:
                raw = stream.read()
            self.assertEqual(len(raw), 768)
            self.assertEqual(
                hashlib.sha256(raw).hexdigest(),
                "2ef0015d676ca0678d825d3041df2acbef49181797d41a9e7ffa215b625d8be4",
            )

    def test_map_supplied_palette_wins_over_embedded_stock(self):
        with tempfile.TemporaryDirectory() as root:
            self._write_trn(root, "map.trn", "MARS.ACT")
            local = os.path.join(root, "mars.act")
            with open(local, "wb") as stream:
                stream.write(bytes([17]) * 768)
            result = resolve_legacy_palette(root)
            self.assertEqual(result.status, "source")
            self.assertEqual(os.path.normcase(result.path), os.path.normcase(local))

    def test_explicit_palette_override_wins(self):
        with tempfile.TemporaryDirectory() as root:
            self._write_trn(root, "map.trn", "MARS.ACT")
            explicit = os.path.join(root, "custom.act")
            with open(explicit, "wb") as stream:
                stream.write(bytes([33]) * 768)
            result = resolve_legacy_palette(root, explicit)
            self.assertEqual(result.status, "explicit")
            self.assertEqual(os.path.normcase(result.path), os.path.normcase(explicit))

    def test_mixed_trn_palettes_are_rejected_for_shared_atlas(self):
        with tempfile.TemporaryDirectory() as root:
            self._write_trn(root, "marsmap.trn", "MARS.ACT")
            self._write_trn(root, "moonmap.trn", "MOON.ACT")
            result = resolve_legacy_palette(root)
            self.assertFalse(result.ok)
            self.assertEqual(result.status, "mixed")
            self.assertIn("multiple TRN palettes", result.message)

    def test_unknown_declared_palette_is_not_silently_moon(self):
        with tempfile.TemporaryDirectory() as root:
            self._write_trn(root, "custom.trn", "CUSTOM.ACT")
            result = resolve_legacy_palette(root)
            self.assertFalse(result.ok)
            self.assertEqual(result.status, "missing")
            self.assertIn("CUSTOM.ACT", result.message)

    def test_no_declared_palette_uses_explicitly_reported_moon_default(self):
        with tempfile.TemporaryDirectory() as root:
            self._write_trn(root, "oldmap.trn", None)
            result = resolve_legacy_palette(root)
            self.assertTrue(result.ok)
            self.assertEqual(result.status, "default")
            self.assertEqual(result.requested, "moon.act")

    def test_scan_reports_each_trn(self):
        with tempfile.TemporaryDirectory() as root:
            self._write_trn(root, "a.trn", "MARS.ACT")
            self._write_trn(root, "b.trn", None)
            refs = scan_trn_palette_references(root)
            self.assertEqual(refs["a.trn"], "MARS.ACT")
            self.assertIsNone(refs["b.trn"])


if __name__ == "__main__":
    unittest.main()
