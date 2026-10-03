import struct
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from battlezone.terrain import colortables as ct
from battlezone.terrain.atlas import parse_materials, read_atlas_csv, tile_family, tile_level
from battlezone.terrain.hg2 import HG2Map
from battlezone.terrain.lgt import write_lgt
from battlezone.terrain.palettes import get_stock_act_bytes
from bztoolbox.modules.textures.makemap_compat import decode_map_bytes
from battlezone.images.sprites import SpriteEntry, read_sta, read_stb, write_stb
from battlezone.terrain.trn import TRNDocument
from bztoolbox.modules.world.redux_to_legacy import (
    LegacyExportOptions, defined_slots, encode_indexed_map, encode_rgb_map, mat_slot_usage, port_redux_to_legacy,
    rewrite_trn_for_legacy, star_dome_values,
)

MARS = ct.palette_array(get_stock_act_bytes("mars.act"))

REDUX_TRN = """[NormalView]\r
Time=1800\r
\r
[Atlases]\r
MaterialName\t= tt_detail_atlas\r
\r
[Sky]\r
SkyTexture= ttsky.map\r
\r
[Clouds]\r
Texture0 = acloud2.map\r
\r
[Color]\r
Palette=ttworld.ACT\r
Luma=MARS.LUM\r
\r
[TextureType0] // Snow\r
FlatColor= 120\r
SolidA0        = TT00S0.MAP\r
\r
[TextureType1] // Rock\r
SolidA0        = TT11S0.MAP\r
SolidA1        = TT11S1.MAP\r
SolidA2        = TT11S2.MAP\r
SolidA3        = TT11S3.MAP\r
CapTo0_A0      = TT10C0.MAP\r
"""

TERRAIN_MATERIAL = """import * from "BZTerrainBase.material"

material TT_DETAIL_ATLAS : BZTerrainBase
{
\tset_texture_alias DiffuseMap tt_atlas.png
\tset_texture_alias NormalMap flat_n.dds
}
"""

SKY_MATERIAL = """material TTSKY.MAP
{
\ttechnique
\t{
\t\tpass
\t\t{
\t\t\ttexture_unit
\t\t\t{
\t\t\t\ttexture ttsky.png
\t\t\t}
\t\t}
\t}
}
"""

# Three cells of a 2x2 atlas, each one colour with a black band along its top edge.
CELL_COLOURS = {"TT00S0.MAP": (230, 235, 240), "TT11S0.MAP": (150, 70, 40), "TT10C0.MAP": (90, 90, 60)}


def _atlas() -> Image.Image:
    image = Image.new("RGB", (512, 512), (0, 0, 0))
    for (x, y), name in zip(((0, 0), (256, 0), (0, 256)), CELL_COLOURS):
        cell = Image.new("RGB", (256, 256), CELL_COLOURS[name])
        cell.paste((0, 0, 0), (0, 0, 256, 32))
        image.paste(cell, (x, y))
    return image


def _redux_folder(root: Path) -> Path:
    src = root / "redux"
    src.mkdir()
    (src / "ttworld.trn").write_bytes(REDUX_TRN.encode("cp1252"))
    (src / "tt_detail_atlas.material").write_text(TERRAIN_MATERIAL)
    (src / "ttsky.material").write_text(SKY_MATERIAL)
    (src / "tt_detail_atlas.csv").write_text(",0,0,0.5,0.5\nTT00S0.MAP,0,0,0.5,0.5\nTT11S0.MAP,0.5,0,0.5,0.5\n"
                                             "TT10C0.MAP,0,0.5,0.5,0.5\n")
    _atlas().save(src / "tt_atlas.png")
    Image.new("RGB", (64, 64), (200, 120, 90)).save(src / "ttsky.png")
    (src / "ttworld.act").write_bytes(bytes(768))            # a Redux placeholder
    heights = (np.arange(256 * 256, dtype=np.int64).reshape(256, 256) % 2000).astype(np.uint16)
    HG2Map(heights, 1, 1).write(src / "ttworld.hg2")
    write_lgt(src / "ttworld.lgt", np.full((256, 256), 200, np.uint8), 1, 1)
    (src / "ttworld.mat").write_bytes(bytes(64 * 64 * 2))
    (src / "ttworld.ini").write_text("[DESCRIPTION]\n")
    (src / "ttworld.lua").write_text("-- script\n")
    (src / "ttworld.des").write_text("A test world\n")
    return src


class ColourTableTests(unittest.TestCase):
    def test_nearest_prefers_the_lowest_index_and_respects_allowed(self):
        palette = np.zeros((256, 3))
        palette[5] = palette[9] = (100, 100, 100)
        self.assertEqual(ct.nearest_indices([[101, 100, 100]], palette, [5, 9, 30])[0], 5)
        self.assertEqual(ct.nearest_indices([[101, 100, 100]], palette, [9, 30])[0], 9)

    def test_quantize_keeps_transparent_index_for_clear_pixels_only(self):
        image = Image.new("RGBA", (2, 1))
        image.putpixel((0, 0), (0, 0, 0, 0))
        image.putpixel((1, 0), (0, 0, 0, 255))
        indices = ct.quantize(image, MARS, ct.TERRAIN_INDICES, transparent_index=0)
        self.assertEqual(indices[0, 0], 0)
        self.assertNotEqual(indices[0, 1], 0)

    def test_stock_palettes_are_safe_and_placeholders_are_not(self):
        moon = ct.palette_array(get_stock_act_bytes("moon.act"))
        self.assertTrue(ct.palette_is_legacy_safe(moon, MARS)[0])
        self.assertFalse(ct.palette_is_legacy_safe(ct.palette_array(bytes(768)), MARS)[0])

    def test_built_palette_keeps_the_shared_entries(self):
        rng = np.random.default_rng(3)
        samples = rng.integers(0, 256, (5000, 3)).astype(float)
        built = ct.build_world_palette(samples, MARS, iterations=3)
        np.testing.assert_array_equal(built[ct.SHARED_INDICES], MARS[ct.SHARED_INDICES])
        self.assertTrue(ct.palette_is_legacy_safe(built, MARS)[0])

    def test_transfer_onto_the_same_palette_keeps_every_colour(self):
        rng = np.random.default_rng(7)
        table = rng.integers(0, 256, (256, 256)).astype(np.uint8)
        for kind in ct.TABLE_KINDS:
            moved = ct.transfer_table(table, MARS, MARS, kind)
            np.testing.assert_array_equal(MARS[moved], MARS[table])


class AtlasTests(unittest.TestCase):
    def test_csv_skips_the_header_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.csv"
            path.write_text(",0,0,0.25,0.25\npm11s0.map,0.25,0.5,0.25,0.25\n")
            cells = read_atlas_csv(path)
        self.assertEqual(list(cells), ["PM11S0.MAP"])
        self.assertEqual(cells["PM11S0.MAP"].box(8192, 8192), (2048, 4096, 4096, 6144))

    def test_tile_names(self):
        self.assertEqual(tile_level("PM00S3.MAP"), 3)
        self.assertEqual(tile_family("pm00s3.map"), "PM00S")
        self.assertEqual(tile_family("ma00sA0.map"), "MA00SA")

    def test_materials(self):
        terrain = parse_materials(TERRAIN_MATERIAL)[0]
        self.assertEqual((terrain.name, terrain.parent, terrain.diffuse), ("TT_DETAIL_ATLAS", "BZTerrainBase",
                                                                          "tt_atlas.png"))
        sky = parse_materials(SKY_MATERIAL)[0]
        self.assertEqual((sky.name, sky.diffuse), ("TTSKY.MAP", "ttsky.png"))


class TRNRewriteTests(unittest.TestCase):
    def test_atlases_go_levels_are_added_and_colour_files_set(self):
        text, changes = rewrite_trn_for_legacy(REDUX_TRN, color={"Palette": "tt.act", "Luma": "tt.lum",
                                                                 "Alpha": "tt.alb"})
        self.assertNotIn("[Atlases]", text)
        self.assertNotIn("MaterialName", text)
        for level in (1, 2, 3):
            self.assertIn(f"SolidA{level}        = TT00S{level}.MAP", text)
            self.assertIn(f"CapTo0_A{level}      = TT10C{level}.MAP", text)
        self.assertEqual(text.count("SolidA1 "), 2)             # TT11 already had its levels
        self.assertIn("Palette=tt.act", text)
        self.assertIn("Luma=tt.lum", text)
        self.assertIn("Alpha=tt.alb", text)
        self.assertIn("[TextureType0] // Snow", text)
        self.assertIn("\r\n", text)
        self.assertTrue(any("removed [Atlases]" in c for c in changes))

    def test_cr_cr_lf_is_one_line_break(self):
        text, changes = rewrite_trn_for_legacy("[Size]\r\r\nWidth=1280\r\r\n\r\r\n[Sky]\r\r\n")
        self.assertEqual(text, "[Size]\r\nWidth=1280\r\n\r\n[Sky]\r\n")
        self.assertTrue(any("CR CR LF" in c for c in changes))

    def test_star_dome_is_scaled_to_stock_radius(self):
        text = "[Stars]\r\nRadius\t\t= 4096\r\nTexture05   = a.map\r\nSize05      = 8192\r\nSize01 = 100\r\n"
        values = star_dome_values(TRNDocument.parse(text))
        self.assertEqual(values, {("stars", "radius"): "1000", ("stars", "size05"): "2000",
                                  ("stars", "size01"): "24"})
        out, _ = rewrite_trn_for_legacy(text, values=values)
        self.assertIn("Radius\t\t= 1000", out)
        self.assertIn("Size05      = 2000", out)
        self.assertEqual(star_dome_values(TRNDocument.parse("[Stars]\nRadius=1000\nSize00=200\n")), {})

    def test_colour_section_is_added_when_missing(self):
        text, _ = rewrite_trn_for_legacy("[Size]\nWidth=1280\n", color={"Palette": "x.act"})
        self.assertTrue(text.rstrip().endswith("[Color]\nPalette=x.act"))


class MapEncodingTests(unittest.TestCase):
    def test_encoders_round_trip_through_the_makemap_reader(self):
        indices = np.array([[1, 2], [3, 4]], dtype=np.uint8)
        decoded = decode_map_bytes(encode_indexed_map(indices), [tuple(c) for c in MARS.astype(int)])
        self.assertEqual(decoded.getpixel((1, 1))[:3], tuple(MARS[4].astype(int)))
        image = Image.new("RGBA", (2, 2), (248, 252, 248, 255))
        data = encode_rgb_map(image)
        self.assertEqual(struct.unpack_from("<HHI", data), (4, 2, 2))
        self.assertEqual(decode_map_bytes(data).getpixel((0, 0)), (255, 255, 255, 255))
        self.assertEqual(struct.unpack_from("<HHI", encode_rgb_map(image, transparent=True))[1], 1)


class PortTests(unittest.TestCase):
    def test_redux_folder_becomes_a_legacy_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = _redux_folder(Path(tmp))
            out = Path(tmp) / "legacy"
            report = port_redux_to_legacy(src, out, LegacyExportOptions(game_dir=None))
            self.assertTrue(report.ok, report.lines())
            act = ct.palette_array((out / "ttworld.ACT").read_bytes())
            np.testing.assert_array_equal(act[ct.SHARED_INDICES], MARS[ct.SHARED_INDICES])
            palette = [tuple(c) for c in act.astype(int)]

            for level, side in enumerate((256, 128, 64, 32)):
                data = (out / f"TT00S{level}.MAP").read_bytes()
                self.assertEqual(struct.unpack_from("<HHI", data), (side, 0, side))
            self.assertEqual(report.tiles, 12)                     # 3 cells x 4 levels
            for name, colour in CELL_COLOURS.items():
                image = decode_map_bytes((out / name).read_bytes(), palette).convert("RGB")
                # MAP rows are bottom-up: the atlas cell's black top band is at the end of the file.
                self.assertLess(max(image.getpixel((128, 250))), 30)
                self.assertLess(max(abs(a - b) for a, b in zip(image.getpixel((128, 20)), colour)), 24)
                self.assertTrue(np.all(np.frombuffer((out / name).read_bytes()[8:], np.uint8) < 224))

            sky = (out / "ttsky.map").read_bytes()
            self.assertEqual(struct.unpack_from("<HHI", sky), (256, 0, 256))
            self.assertFalse((out / "acloud2.map").exists())         # stock 1.5 file

            trn = (out / "ttworld.trn").read_text(encoding="cp1252")
            self.assertNotIn("[Atlases]", trn)
            self.assertIn("TT00S3.MAP", trn)
            self.assertIn("Palette=ttworld.ACT", trn)
            self.assertIn("Luma=MARS.LUM", trn)                       # no game folder: kept, with a warning
            self.assertTrue(any("lum/.tbl/.alb" in w for w in report.warnings))

            self.assertEqual((out / "ttworld.hgt").stat().st_size, 0x8000)
            self.assertEqual((out / "ttworld.lgt").stat().st_size, 2 * 128 * 128)
            self.assertEqual((out / "ttworld.mat").read_bytes(), (src / "ttworld.mat").read_bytes())
            self.assertTrue((out / "ttworld.des").exists())
            for gone in ("ttworld.ini", "ttworld.lua", "tt_atlas.png", "tt_detail_atlas.csv"):
                self.assertFalse((out / gone).exists(), gone)
            self.assertTrue(any("Lua" in w for w in report.warnings))
            self.assertTrue((out / "redux_to_legacy_report.txt").exists())

    def test_colour_tables_come_from_the_game(self):
        from bztoolbox.modules.world import redux_to_legacy as module

        tables = {k: bytes(range(256)) * 256 for k in ct.TABLE_KINDS}
        original = module.stock_color_tables
        module.stock_color_tables = lambda game_dir, world: tables
        try:
            with tempfile.TemporaryDirectory() as tmp:
                src = _redux_folder(Path(tmp))
                out = Path(tmp) / "legacy"
                report = port_redux_to_legacy(src, out, LegacyExportOptions(game_dir=tmp))
                self.assertTrue(report.ok, report.lines())
                trn = (out / "ttworld.trn").read_text(encoding="cp1252")
                for key, ext in (("Luma", "lum"), ("Translucency", "tbl"), ("Alpha", "alb")):
                    self.assertIn(f"{key}=ttworld.{ext}", trn)
                    self.assertEqual((out / f"ttworld.{ext}").stat().st_size, 65536)
        finally:
            module.stock_color_tables = original

    @staticmethod
    def _mat_with_undefined_slots(src: Path) -> None:
        entries = np.zeros(64 * 64, dtype="<u2")
        entries[:10] = (7 << 12) | (7 << 8)                  # type 7: no [TextureType7]
        entries[10:15] = (1 << 12) | (0 << 8)                # 1 -> 0 cap: TextureType1 only has CapTo0
        entries[15:20] = (0 << 12) | (1 << 8)                # 0 -> 1 cap: not defined
        entries[20:25] = (1 << 12) | (1 << 8) | 3            # type 1 solid, variant D: covered by SolidA
        entries.tofile(src / "ttworld.mat")

    def test_undefined_mat_slots_get_redux_default_tile(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = _redux_folder(Path(tmp))
            self._mat_with_undefined_slots(src)
            out = Path(tmp) / "legacy"
            report = port_redux_to_legacy(src, out, LegacyExportOptions())
            self.assertTrue(report.ok, report.lines())
            doc = TRNDocument.read(out / "ttworld.trn")
            # The CSV's nameless row is cell (0,0), which is TT00S: reused, no new tiles.
            self.assertEqual(doc.get("TextureType7", "SolidA0"), "TT00S0.MAP")
            self.assertEqual(doc.get("TextureType7", "SolidA3"), "TT00S3.MAP")
            self.assertEqual(doc.get("TextureType0", "CapTo1_A2"), "TT00S2.MAP")
            self.assertIsNone(doc.get("TextureType1", "CapTo2_A0"))
            slots = defined_slots(doc)
            usage = mat_slot_usage(np.fromfile(out / "ttworld.mat", dtype="<u2"))
            for (t, kind, other, variant) in usage:
                self.assertTrue(any((t, kind, other, v) in slots for v in range(variant + 1)), (t, kind, other))
            self.assertTrue(any("filled with the atlas default tile TT00S" in n for n in report.notes))

    def test_undefined_mat_slots_solid_mode_and_new_default_tile(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = _redux_folder(Path(tmp))
            self._mat_with_undefined_slots(src)
            # A default cell no tile uses: it becomes its own tile family.
            csv = src / "tt_detail_atlas.csv"
            csv.write_text(csv.read_text().replace(",0,0,0.5,0.5", ",0.5,0.5,0.5,0.5", 1))
            out = Path(tmp) / "legacy"
            report = port_redux_to_legacy(src, out, LegacyExportOptions(missing_tiles="solid"))
            self.assertTrue(report.ok, report.lines())
            doc = TRNDocument.read(out / "ttworld.trn")
            self.assertEqual(doc.get("TextureType0", "CapTo1_A0"), "TT00S0.MAP")      # type 0's own solid
            self.assertEqual(doc.get("TextureType7", "SolidA1"), "TTDEF1.MAP")        # no type 7 solid
            for level, side in enumerate((256, 128, 64, 32)):
                self.assertEqual(struct.unpack_from("<HHI", (out / f"TTDEF{level}.MAP").read_bytes()), (side, 0, side))

    def test_undefined_mat_slots_can_be_left(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = _redux_folder(Path(tmp))
            self._mat_with_undefined_slots(src)
            report = port_redux_to_legacy(src, Path(tmp) / "legacy", LegacyExportOptions(missing_tiles="none"))
            self.assertTrue(any("checkerboard" in w and "15 cell(s)" in w for w in report.warnings), report.warnings)

    def test_missing_atlas_texture_is_an_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = _redux_folder(Path(tmp))
            (src / "tt_atlas.png").unlink()
            report = port_redux_to_legacy(src, Path(tmp) / "legacy", LegacyExportOptions())
            self.assertFalse(report.ok)
            self.assertTrue(any("tt_atlas.png" in e for e in report.errors))

    def test_refuses_to_write_over_the_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = _redux_folder(Path(tmp))
            with self.assertRaises(ValueError):
                port_redux_to_legacy(src, src)


STOCK_SPRITES = [SpriteEntry("status_left", "scrncut", 0, 0, 63, 84, 0),
                 SpriteEntry("sun.0", "sprite_a", 0, 0, 63, 63, 16)]

STA = '''# Custom sprite table
"ttsun"      ttsunmat     0   0   512  512   512  512 0x00000000
"ttfx.0"     ttfxmat      0   0   256  256   512  256 0x00000000
"ttfx.1"     ttfxmat    256   0   256  256   512  256 0x00000000
"nothere"    nomaterial   0   0    32   32    32   32 0x00000000
'''


class SpriteTableTests(unittest.TestCase):
    def test_stb_round_trip_and_layout(self):
        data = write_stb(STOCK_SPRITES)
        self.assertEqual(len(data), 2 * 52)
        self.assertEqual(data[32:40], b"scrncut\0")
        self.assertEqual(struct.unpack_from("<4HI", data, 52 + 40), (0, 0, 63, 63, 16))
        self.assertEqual(read_stb(data), STOCK_SPRITES)
        with self.assertRaises(ValueError):
            write_stb([SpriteEntry("x", "ninechars", 0, 0, 1, 1)])

    def test_sta_lines(self):
        entries = read_sta(STA)
        self.assertEqual([e.name for e in entries], ["ttsun", "ttfx.0", "ttfx.1", "nothere"])
        self.assertEqual((entries[2].material, entries[2].u, entries[2].image_width), ("ttfxmat", 256, 512))


class SpritePortTests(unittest.TestCase):
    def _folder(self, root: Path) -> Path:
        src = _redux_folder(root)
        trn = (src / "ttworld.trn").read_bytes().decode("cp1252").replace("[Sky]\r\n", "[Sky]\r\nSunTexture=ttsun\r\n")
        (src / "ttworld.trn").write_bytes(trn.encode("cp1252"))
        (src / "spritea.sta").write_text(STA)
        (src / "sprites.material").write_text("material ttsunmat\n{\n technique\n {\n  pass\n  {\n   texture_unit\n"
                                             "   {\n    texture ttsun.png\n   }\n  }\n }\n}\n"
                                             "material ttfxmat\n{\n technique\n {\n  pass\n  {\n   texture_unit\n"
                                             "   {\n    texture ttfx.png\n   }\n  }\n }\n}\n")
        sun = Image.new("RGBA", (512, 512), (0, 0, 0, 0))
        sun.paste((120, 160, 255, 255), (128, 128, 384, 384))
        sun.save(src / "ttsun.png")
        Image.new("RGBA", (512, 256), (255, 128, 0, 255)).save(src / "ttfx.png")
        return src

    def test_sprites_extend_the_stock_tables(self):
        from bztoolbox.modules.world import redux_to_legacy as module

        original = module.stock_sprite_tables
        module.stock_sprite_tables = lambda _dir: {"spritea.stb": list(STOCK_SPRITES), "sprite8.stb": list(STOCK_SPRITES)}
        try:
            with tempfile.TemporaryDirectory() as tmp:
                src = self._folder(Path(tmp))
                out = Path(tmp) / "legacy"
                report = port_redux_to_legacy(src, out, LegacyExportOptions(legacy_dir=tmp))
                self.assertTrue(report.ok, report.lines())
                hw = read_stb((out / "spritea.stb").read_bytes())
                sw = read_stb((out / "sprite8.stb").read_bytes())
                self.assertEqual(hw[:2], STOCK_SPRITES)                     # stock entries kept, in order
                sun = next(e for e in hw if e.name == "ttsun")
                self.assertEqual((sun.texture, sun.width, sun.height, sun.flags), ("ttsun", 64, 64, 16))
                self.assertEqual(next(e for e in sw if e.name == "ttsun").texture, "ttsun8")
                fx1 = next(e for e in hw if e.name == "ttfx.1")
                self.assertEqual((fx1.u, fx1.v, fx1.width, fx1.height), (128, 0, 128, 128))   # 512x256 -> 256x128
                self.assertIsNone(next((e for e in hw if e.name == "nothere"), None))
                sheet = (out / "TTSUN.MAP").read_bytes()
                self.assertEqual(struct.unpack_from("<HHI", sheet), (128, 1, 64))            # A4R4G4B4, top-down
                alpha = np.frombuffer(sheet[8:], "<u2").reshape(64, 64) >> 12
                self.assertEqual((alpha[0, 0], alpha[32, 32]), (0, 15))
                soft = np.frombuffer((out / "TTSUN8.MAP").read_bytes()[8:], np.uint8).reshape(64, 64)
                self.assertEqual((soft[0, 0], soft[32, 32] != 255), (255, True))
                self.assertIn("SunTexture=ttsun", (out / "ttworld.trn").read_text(encoding="cp1252"))
                self.assertFalse((out / "spritea.sta").exists())
        finally:
            module.stock_sprite_tables = original

    def test_custom_sun_falls_back_to_sun0_without_a_legacy_install(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = self._folder(Path(tmp))
            out = Path(tmp) / "legacy"
            report = port_redux_to_legacy(src, out, LegacyExportOptions(legacy_dir=None))
            self.assertIn("SunTexture=sun.0", (out / "ttworld.trn").read_text(encoding="cp1252"))
            self.assertFalse((out / "spritea.stb").exists())
            self.assertTrue(any("SunTexture ttsun" in w for w in report.warnings), report.warnings)


if __name__ == "__main__":
    unittest.main()
