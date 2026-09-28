import tempfile
import unittest
from pathlib import Path

from PIL import Image

from battlezone.images.sprites import (
    SpriteEntry, StaDocument, StaEntry, format_sta_entry, read_sta, read_stb, validate_sta_entry,
)

TABLE = ('# Custom sprites\r\n'
         '\r\n'
         '"ttsun"      ttsunmat     0   0   512  512   512  512 0x00000000  # the sun\r\n'
         '# explosions\r\n'
         '"ttfx.0"     ttfxmat      0   0   256  256   512  256 0x00000000\r\n'
         'garbage line kept as is\r\n'
         '"ttfx.1"     ttfxmat    256   0   256  256   512  256\r\n')

MATERIALS = ("material ttsunmat\n{\n technique\n {\n  pass\n  {\n   texture_unit\n   {\n    texture ttsun.png\n"
             "   }\n  }\n }\n}\nmaterial ttfxmat\n{\n technique\n {\n  pass\n  {\n   texture_unit\n   {\n"
             "    texture ttfx.png\n   }\n  }\n }\n}\n")


class StaDocumentTests(unittest.TestCase):
    def test_unedited_text_is_unchanged(self):
        doc = StaDocument(TABLE)
        self.assertEqual(doc.text(), TABLE)
        self.assertEqual(doc.entries, read_sta(TABLE))
        for index, entry in enumerate(doc.entries):
            doc.replace(index, entry)                  # the same values do not reformat the line
        self.assertEqual(doc.text(), TABLE)

    def test_edit_add_delete_keep_comments(self):
        doc = StaDocument(TABLE)
        doc.replace(0, StaEntry("ttsun", "ttsunmat", 0, 0, 256, 256, 512, 512, 0x10))
        self.assertEqual(doc.add(StaEntry("new", "ttfxmat", 1, 2, 3, 4, 512, 256, 3)), 3)
        doc.delete(1)
        text = doc.text()
        self.assertIn("# Custom sprites\r\n", text)
        self.assertIn("# explosions\r\n", text)
        self.assertIn("garbage line kept as is\r\n", text)
        self.assertIn("0x00000010  # the sun\r\n", text)            # trailing comment survives an edit
        self.assertTrue(text.endswith('0x00000003\r\n'))           # new entry after the last one
        self.assertEqual([e.name for e in read_sta(text)], ["ttsun", "ttfx.1", "new"])
        self.assertEqual(read_sta(text)[0].width, 256)
        with self.assertRaises(IndexError):
            doc.delete(5)

    def test_empty_document(self):
        doc = StaDocument()
        self.assertEqual(doc.add(StaEntry("a", "m", 0, 0, 8, 8, 8, 8)), 0)
        self.assertEqual(read_sta(doc.text())[0].name, "a")
        self.assertTrue(doc.text().endswith("\n"))

    def test_format_matches_stock_columns(self):
        line = format_sta_entry(StaEntry("status_left", "scrncut", 0, 0, 63, 84, 1024, 1024))
        self.assertEqual(line, '"status_left"                      scrncut              0     0    63    84  '
                               '1024  1024 0x00000000')

    def test_validation(self):
        self.assertEqual(validate_sta_entry(StaEntry("ok", "mat", 0, 0, 1, 1, 8, 8)), [])
        self.assertTrue(validate_sta_entry(StaEntry('bad"name', "mat", 0, 0, 1, 1, 8, 8)))
        self.assertTrue(validate_sta_entry(StaEntry("x", "two words", 0, 0, 1, 1, 8, 8)))
        self.assertTrue(validate_sta_entry(StaEntry("x", "mat", 0, 0, 1, 1, 0, 8)))
        self.assertTrue(validate_sta_entry(StaEntry("x", "mat", -1, 0, 1, 1, 8, 8)))


class SpriteSheetTests(unittest.TestCase):
    def _folder(self, root: Path) -> Path:
        (root / "spritea.sta").write_bytes(TABLE.encode("cp1252"))
        (root / "sprites.material").write_text(MATERIALS)
        sun = Image.new("RGBA", (256, 256), (0, 0, 0, 0))     # half the table's 512 reference size
        sun.paste((255, 255, 0, 255), (64, 64, 192, 192))
        sun.save(root / "ttsun.png")
        fx = Image.new("RGBA", (512, 256), (255, 0, 0, 255))
        fx.paste((0, 0, 255, 255), (256, 0, 512, 256))
        fx.save(root / "ttfx.png")
        return root

    def test_crop_scales_the_reference_rectangle(self):
        from bztoolbox.modules.textures.sprite_sheets import SpriteSheets, crop_box, find_project_table

        self.assertEqual(crop_box(StaEntry("a", "m", 256, 0, 256, 256, 512, 512), 256, 256), (128, 0, 256, 128))
        with tempfile.TemporaryDirectory() as tmp:
            folder = self._folder(Path(tmp))
            self.assertEqual(find_project_table(tmp), folder / "spritea.sta")
            sheets = SpriteSheets(folder)
            entries = read_sta(TABLE)
            sun = sheets.crop(entries[0])
            self.assertEqual(sun.size, (256, 256))
            self.assertEqual(sun.getpixel((128, 128)), (255, 255, 0, 255))
            self.assertEqual(sheets.crop(entries[2]).getpixel((5, 5)), (0, 0, 255, 255))
            self.assertIsNone(sheets.crop(StaEntry("x", "nomaterial", 0, 0, 1, 1, 8, 8)))
            self.assertIn("no material", sheets.explain("nomaterial"))
        self.assertIsNone(find_project_table(None))

    def test_no_game_means_no_stock_table(self):
        from bztoolbox.modules.textures.sprite_sheets import stock_sta_text

        self.assertIsNone(stock_sta_text(None))
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(stock_sta_text(tmp))

    def test_stock_table_from_bzone_zfs(self):
        from battlezone.archives.zfs import write_zfs
        from bztoolbox.modules.textures.sprite_sheets import stock_sta_text

        with tempfile.TemporaryDirectory() as tmp:
            write_zfs(Path(tmp) / "bzone.zfs", [("spritea.st", TABLE.encode("cp1252"))])
            self.assertEqual(read_sta(stock_sta_text(tmp)), read_sta(TABLE))

    def test_legacy_tables_from_one_sta(self):
        from bztoolbox.modules.world import redux_to_legacy as module

        stock = [SpriteEntry("status_left", "scrncut", 0, 0, 63, 84, 0), SpriteEntry("sun.0", "sprite_a", 0, 0, 63, 63, 16)]
        original = module.stock_sprite_tables
        module.stock_sprite_tables = lambda _dir: {"spritea.stb": list(stock), "sprite8.stb": list(stock)}
        try:
            with tempfile.TemporaryDirectory() as tmp:
                (Path(tmp) / "src").mkdir()
                folder = self._folder(Path(tmp) / "src")
                out = Path(tmp) / "out"
                report = module.export_sprite_tables(folder / "spritea.sta", out, legacy_dir=tmp)
                self.assertTrue(report.ok, report.lines())
                table = read_stb((out / "spritea.stb").read_bytes())
                self.assertEqual(table[:2], stock)
                self.assertEqual([e.name for e in table[2:]], ["ttsun", "ttfx.0", "ttfx.1"])
                self.assertTrue((out / "TTSUN.MAP").is_file())
                self.assertTrue((out / "sprite8.stb").is_file())
        finally:
            module.stock_sprite_tables = original

    def test_legacy_tables_need_a_legacy_install(self):
        from bztoolbox.modules.world.redux_to_legacy import export_sprite_tables

        with tempfile.TemporaryDirectory() as tmp:
            folder = self._folder(Path(tmp))
            report = export_sprite_tables(folder / "spritea.sta", Path(tmp) / "out", legacy_dir=None)
            self.assertFalse(report.ok)
            self.assertFalse((Path(tmp) / "out").exists())


class SpriteFormTests(unittest.TestCase):
    def test_entry_from_form(self):
        from bztoolbox.app.pages.sprites import entry_from_form, entry_row

        values = dict(name=" boom.0 ", material="xplmat", u="0", v="16", width="32", height="32",
                      image_width="256", image_height="256", flags="0x10")
        entry = entry_from_form(values)
        self.assertEqual((entry.name, entry.v, entry.flags), ("boom.0", 16, 16))
        self.assertEqual(entry_row(entry)[4], "0x00000010")
        for key, bad in (("u", "x"), ("material", "two words"), ("image_width", "0")):
            with self.assertRaises(ValueError):
                entry_from_form(dict(values, **{key: bad}))


if __name__ == "__main__":
    unittest.main()
