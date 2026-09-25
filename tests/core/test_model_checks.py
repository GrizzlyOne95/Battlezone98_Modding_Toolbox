"""Model checks, the legacy model readers and the official-uploader rules."""

import struct
import tempfile
import unittest
from pathlib import Path

from battlezone.meshes.legacy import ModelError, read_geo, read_sdf, read_vdf
from battlezone.validation import validate_project


def geo_bytes(vertices, faces, name=b"part"):
    out = struct.pack("<4si16siii", b"OEG.", 0, name, len(vertices), len(faces), 0)
    out += b"".join(struct.pack("<3f", *v) for v in vertices)
    out += b"".join(struct.pack("<3f", 0.0, 1.0, 0.0) for _ in vertices)
    for index, face in enumerate(faces):
        out += struct.pack("<iiBBBffffi3s13sii", index, len(face), 0, 0, 0, 0.0, 1.0, 0.0, 0.0, 0, b"", b"tex.map", 0, 0)
        out += b"".join(struct.pack("<iiff", v, v, 0.0, 0.0) for v in face)
    return out


def record(name, parent="world", klass=60, flags=0, size=100):
    fields = [name.encode(), *([0.0] * 12), parent.encode(), *([0.0] * 7), klass, flags]
    if size == 120:
        return struct.pack("<8s12f8s7fiii4f", *fields, 0, 0.0, 0.0, 0.0, 0.0)
    return struct.pack("<8s12f8s7fii", *fields)


def vdf_bytes(parts, chunks=(b"COLP",)):
    out = struct.pack("<4si4sii", b"BWD2", 8, b"REV\0", 12, 7)
    out += struct.pack("<4si16sii5ffffi", b"VDFC", 68, b"test", 0, 0, *([0.0] * 8), 0)
    out += struct.pack("<4si", b"EXIT", 8)
    out += struct.pack("<4sIi", b"VGEO", 0, len(parts))
    out += b"".join(record(*part) for part in parts)
    out += record("NULL") * (27 * len(parts))
    for tag in chunks:
        out += struct.pack("<4si", tag, 56) + b"\0" * 48
    return out + struct.pack("<4si", b"EXIT", 8)


def sdf_bytes(parts, chunks=()):
    out = struct.pack("<4si4sii", b"BWD2", 8, b"REV\0", 12, 8)
    out += struct.pack("<4si16si5fI13s13s", b"SDFC", 78, b"test", 0, *([0.0] * 5), 0, b"", b"")
    out += struct.pack("<4sIi", b"SGEO", 0, len(parts))
    out += b"".join(record(*part, size=120) for part in parts)
    out += record("NULL", size=120) * (5 * len(parts))
    for tag in chunks:
        out += struct.pack("<4si", tag, 16) + b"\0" * 8
    return out


SQUARE = [(0, 0, 0), (1, 0, 0), (1, 0, 1), (0, 0, 1)]


class LegacyReaderTests(unittest.TestCase):
    def test_geo_round_trip(self):
        geo = read_geo(geo_bytes(SQUARE, [[0, 1, 2, 3]]))
        self.assertEqual((geo.vertex_count, len(geo.faces), geo.faces[0].texture), (4, 1, "tex.map"))

    def test_truncated_geo_is_an_error(self):
        with self.assertRaises(ModelError):
            read_geo(geo_bytes(SQUARE, [[0, 1, 2, 3]])[:-10])

    def test_vdf_and_sdf_parts(self):
        vdf = read_vdf(vdf_bytes([("abc11bda",), ("abc11pov", "abc11bda", 40)]))
        self.assertEqual([(p.name, p.klass) for p in vdf.band(0)], [("abc11bda", 60), ("abc11pov", 40)])
        self.assertIn("COLP", vdf.chunks)
        sdf = read_sdf(sdf_bytes([("sbc11bda",)]))
        self.assertEqual((sdf.kind, sdf.geocount, sdf.band(0)[0].name), ("sdf", 1, "sbc11bda"))


class ModelCheckTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def rules(self, checks=("models",)):
        return {(i.rule_id, i.severity) for i in validate_project(self.root, list(checks)).issues}

    def test_geo_problems(self):
        (self.root / "bad11idx.geo").write_bytes(geo_bytes(SQUARE, [[0, 1, 9]]))
        (self.root / "nan11bda.geo").write_bytes(geo_bytes([(float("nan"), 0, 0)] + SQUARE[1:], [[0, 1, 2]]))
        (self.root / "cut11bda.geo").write_bytes(geo_bytes(SQUARE, [[0, 1, 2]])[:50])
        rules = self.rules()
        self.assertIn(("geo-bad-index", "error"), rules)
        self.assertIn(("geo-bad-vertex", "error"), rules)
        self.assertIn(("model-read-error", "error"), rules)

    def test_vehicle_rules(self):
        parts = [("abc11bda",), ("abc11gun", "abc11bda", 6), ("abc11ty1", "abc11bda", 65),
                 ("abc11trr", "abc11bda", 65), ("abc11bdb", "nowhere", 60, 0x200)]
        parts += [(f"abc11sm{i}", "abc11bda", 76) for i in range(9)]
        (self.root / "abctank.vdf").write_bytes(vdf_bytes(parts, chunks=()))
        for name in ("abc11bda", "abc11ty1", "abc11trr", "abc11bdb"):
            (self.root / f"{name}.geo").write_bytes(geo_bytes(SQUARE, [[0, 1, 2]]))
        issues = validate_project(self.root, ["models"]).issues
        rules = {(i.rule_id, i.severity) for i in issues}
        self.assertIn(("model-part-odf-remap", "error"), rules)       # class 6 part, abc11gun.odf missing
        self.assertIn(("model-missing-part", "warning"), rules)        # abc11gun.geo
        self.assertIn(("model-smoke-overflow", "error"), rules)
        self.assertIn(("model-destroyed-flag", "warning"), rules)
        self.assertIn(("model-bad-parent", "warning"), rules)
        self.assertIn(("model-no-eyepoint", "info"), rules)
        self.assertIn(("model-no-collision", "warning"), rules)
        turrets = [i.message for i in issues if i.rule_id == "model-turret-name"]
        self.assertEqual(len(turrets), 1)
        self.assertIn("abc11trr", turrets[0])                          # ty1 is fine, trr is not

    def test_stock_parts_and_a_redux_mesh_soften_missing_parts(self):
        # aam11bda.geo is a stock part; the other one has only a Redux mesh beside the model
        (self.root / "mytank.vdf").write_bytes(vdf_bytes([("aam11bda",), ("myt11bdb", "aam11bda")]))
        (self.root / "mytank.mesh").write_bytes(b"")
        issues = [i for i in validate_project(self.root, ["models"]).issues if i.rule_id == "model-missing-part"]
        self.assertEqual([(i.severity, "myt11bdb" in i.message) for i in issues], [("info", True)])

    def test_structure_rules(self):
        parts = [("sbc11bda",)] + [(f"sbc11hp{i}", "sbc11bda", 70) for i in range(9)]
        (self.root / "sbcfact.sdf").write_bytes(sdf_bytes(parts, chunks=(b"VLOC",)))
        (self.root / "sbc11bda.geo").write_bytes(geo_bytes(SQUARE, [[0, 1, 2]]))
        rules = self.rules()
        self.assertIn(("model-hardpoint-overflow", "warning"), rules)
        self.assertIn(("model-vloc-structure", "warning"), rules)
        self.assertNotIn(("model-no-eyepoint", "info"), rules)

    def test_empty_mesh(self):
        (self.root / "broken.mesh").write_bytes(b"")
        self.assertIn(("mesh-read-error", "error"), self.rules())


class UploadRuleTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def issues(self, check):
        return validate_project(self.root, [check]).issues

    def test_official_uploader_file_rules(self):
        for name in ("ok.odf", "waytoolong.odf", "longname_x.wav", "old.hgt", "sprites.material",
                     "terrain.program", "en/strings.txt", "en/mission.bzn", "backup/copy.odf"):
            path = self.root / name
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(b"")
        found = {(i.rule_id, i.path) for i in self.issues("upload-rules")}
        self.assertEqual(found, {
            ("upload-long-name", "waytoolong.odf"),      # .wav names may be long
            ("upload-hgt", "old.hgt"),
            ("upload-forbidden-override", "sprites.material"),
            ("upload-forbidden-override", "terrain.program"),
            ("upload-language-file", "en/mission.bzn"),
            ("upload-subfolder", "backup"),
        })

    def write_ini(self, name, map_type, extra=""):
        (self.root / f"{name}.ini").write_text(f'[WORKSHOP]\nmapType = "{map_type}"\n{extra}', encoding="utf-8")

    def test_every_ini_is_checked_and_types_cannot_mix(self):
        self.write_ini("amod", "mod")
        self.write_ini("bmap", "multiplayer", '[MULTIPLAYER]\nminPlayers=2\nmaxPlayers=4\ngameType="X"\n')
        self.write_ini("ccamp", "campaign")
        messages = [i.message for i in self.issues("structure") if i.severity == "error"]
        self.assertTrue(any("bmap.bmp" in m for m in messages), messages)   # second .ini is checked too
        self.assertTrue(any("gameType 'X'" in m for m in messages), messages)
        self.assertTrue(any("cannot share the content folder" in m for m in messages), messages)
        self.assertFalse(any("Invalid mapType" in m for m in messages), messages)   # campaign is valid


def binary_bzn(terrain: bytes) -> bytes:
    def field(code, value):
        return struct.pack("<BBH", code, 0, len(value)) + value
    return (b"version [1] =\r\n2016\r\nbinarySave [1] =\r\ntrue\r\n" + field(2, b"mymap.bzn\0\0\0")
            + field(4, struct.pack("<i", 54)) + field(1, b"\x01") + field(2, terrain + b"\0t\0bzn" + b"\0" * 20))


class TerrainNameTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        (self.root / "mymap.ini").write_text('[WORKSHOP]\nmapType = "instant_action"\n', encoding="utf-8")
        for ext in (".bmp", ".des"):
            (self.root / f"mymap{ext}").write_bytes(b"")

    def tearDown(self):
        self._tmp.cleanup()

    def structure(self):
        return [(i.severity, i.message) for i in validate_project(self.root, ["structure"]).issues]

    def test_terrain_name_from_both_formats(self):
        from battlezone.bzn.scan import bzn_terrain_name
        self.assertEqual(bzn_terrain_name(binary_bzn(b"chill")), "chill")
        self.assertEqual(bzn_terrain_name(b"binarySave [1] =\nfalse\nTerrainName = seabattl\n"), "seabattl")
        self.assertEqual(bzn_terrain_name(b"binarySave [1] =\nfalse\nTerrainName = misn03.bzn\n"), "misn03")

    def test_reused_terrain_is_a_warning(self):
        (self.root / "mymap.bzn").write_bytes(binary_bzn(b"chill"))
        (self.root / "chill.trn").write_bytes(b"")
        issues = self.structure()
        self.assertEqual([sev for sev, _ in issues], ["warning"], issues)
        self.assertIn("reuses terrain 'chill'", issues[0][1])

    def test_stock_terrain_counts_and_a_missing_one_is_an_error(self):
        (self.root / "mymap.bzn").write_bytes(b"binarySave [1] =\nfalse\nTerrainName = misn03\n")
        self.assertEqual([sev for sev, _ in self.structure()], ["warning"])
        (self.root / "mymap.bzn").write_bytes(b"binarySave [1] =\nfalse\nTerrainName = nowhere\n")
        self.assertIn(("error", "mymap.bzn loads terrain 'nowhere', which is not in the mod or the stock game."),
                      self.structure())


if __name__ == "__main__":
    unittest.main()
