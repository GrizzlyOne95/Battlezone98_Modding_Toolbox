import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from battlezone.bzn import bz1
from battlezone.bzn.bz1 import BZNError, compare_bzn, f32, format_g6, read_bzn, write_bzn
from battlezone.bzn.version_convert import ConversionError, convert_bzn, main as convert_main

MATRIX = ("right_x", "right_y", "right_z", "up_x", "up_y", "up_z", "front_x", "front_y", "front_z",
          "posit_x", "posit_y", "posit_z")


def val(name, value):
    return f"{name} [1] =\r\n{value}\r\n"


def one(name, value):
    return f"{name} = {value}\r\n"


def vec(name, *values, indent="  "):
    text = f"{name} [1] =\r\n"
    for axis, value in zip("xyz", values):
        text += f"{indent}{axis} [1] =\r\n{value}\r\n"
    return text


def matrix(name, x, y, z):
    values = (0.6, 0.0002, -0.7, 0.006, 0.99, 0.006, 0.7, -0.009, 0.6, x, y, z)
    text = f"{name} [1] =\r\n"
    for sub, value in zip(MATRIX, values):
        text += f"  {sub} [1] =\r\n{value}\r\n"
    return text


def euler():
    text = "euler =\r\n"
    for name, value in (("mass", 1750), ("mass_inv", 0.000666667), ("v_mag", 0), ("v_mag_inv", 0),
                        ("I", 1500), ("k_i", 1)):
        text += f" {name} [1] =\r\n{value}\r\n"
    for name in ("v", "omega", "Accel"):
        text += f" {name} [1] =\r\n"
        for axis in "xyz":
            text += f"  {axis} [1] =\r\n0\r\n"
    return text


def game_object(seq, *, critical="false", param="", pilot="aspilo"):
    return (val("illumination", 1) + vec("pos", 1137.3, 2.99397, 102268) + euler() + val("seqNo", seq)
            + one("name", "") + val("isCritical", critical) + val("isObjective", "false")
            + val("isSelected", "false") + val("isVisible", "ffffffff") + val("seen", 2)
            + val("healthRatio", 1) + val("curHealth", 2000) + val("maxHealth", 2000)
            + val("ammoRatio", 1) + val("curAmmo", 1000) + val("maxAmmo", 1000)
            + val("priority", 0) + one("what", "00000000") + val("who", 0) + one("where", "00000000")
            + val("param", param) + val("aiProcess", "true") + val("isCargo", "false")
            + val("independence", 1) + val("curPilot", pilot) + val("perceivedTeam", 1))


def descriptor(odf, seq, label):
    return ("[GameObject]\r\n" + val("PrjID", odf) + val("seqno", seq) + vec("pos", 1137.3, 2.99397, 102268)
            + val("team", 1) + one("label", label) + val("isUser", 0) + one("obj_addr", "50EA7000")
            + matrix("transform", 1137.3, 2.99397, 102268))


def redux_bzn(*, critical="false", param="", tank="avtank", pilot="aspilo", cloak="00000000", extra=""):
    """A small version 2016 ASCII mission: a hover tank, a comm tower, one path."""
    text = (val("version", 2016) + val("binarySave", "false") + one("msn_filename", "test.bzn")
            + val("seq_count", 7) + val("missionSave", "true") + one("TerrainName", "testmap") + val("size", 2))
    text += (descriptor(tank, 5, "unit_one") + extra + val("abandoned", 0) + one("cloakState", cloak)
             + val("cloakTransBeginTime", 0) + val("cloakTransEndTime", 0)
             + game_object(5, critical=critical, param=param, pilot=pilot))
    text += descriptor("abcomm", 6, "tower") + game_object(6, pilot="")
    text += one("name", "LuaMission") + one("sObject", "00E175C0") + "[AiMission]\r\n[AOIs]\r\n" + val("size", 0)
    text += "[AiPaths]\r\n" + val("count", 1) + "[AiPath]\r\n" + one("old_ptr", "4075E100") + val("size", 6)
    text += one("label", "path_1") + val("pointCount", 2)
    text += "points [2] =\r\n  x [1] =\r\n411.715\r\n  z [1] =\r\n102111\r\n  x [1] =\r\n395.85\r\n  z [1] =\r\n101901\r\n"
    text += one("pathType", "00000000")
    return text.encode("latin-1")


class FloatFormatTests(unittest.TestCase):
    def test_matches_bznparser_g6(self):
        for value, text in ((0.000248641, "0.000248641"), (102268.0, "102268"), (1137.3, "1137.3"),
                            (-0.72552, "-0.72552"), (5.96046e-8, "5.96046e-008"), (0.0, "0"),
                            (-1e30, "-1e+030"), (116.393, "116.393"), (1234567.0, "1.23457e+006")):
            self.assertEqual(format_g6(f32(value)), text)

    def test_halves_round_away_from_zero(self):
        # 1234565 is exact in float32; C#'s FormatG6 rounds the tie up, Python's %g to even
        self.assertEqual(format_g6(1234565.0), "1.23457e+006")


class ReadWriteTests(unittest.TestCase):
    def test_reads_objects_classes_and_tail(self):
        bzn = read_bzn(redux_bzn())
        self.assertEqual(bzn.version, 2016)
        self.assertFalse(bzn.binary)
        self.assertEqual([o.class_label for o in bzn.objects], ["wingman", "commtower"])
        tank = bzn.objects[0]
        self.assertEqual(tank.prjid, "avtank")
        self.assertEqual(tank.fields["curHealth"].value, 2000)
        self.assertEqual(tank.fields["nextCmd.param"].kind, "id")
        self.assertEqual(bzn.mission_name, "LuaMission")
        self.assertEqual(len(bzn.paths), 1)
        self.assertEqual(bzn.paths[0]["points"].value, [(f32(411.715), 102111.0), (f32(395.85), 101901.0)])

    def test_same_version_rewrite_is_byte_identical(self):
        data = redux_bzn()
        self.assertEqual(read_bzn(data).write(), data)

    def test_binary_round_trip(self):
        source = read_bzn(redux_bzn())
        for version in (1045, 2016):
            binary = write_bzn(source, version, binary=True)
            back = read_bzn(binary)
            self.assertTrue(back.binary)
            self.assertEqual(back.version, version)
            self.assertEqual(back.write(), binary)
            again = read_bzn(write_bzn(back, 2016))
            self.assertEqual(compare_bzn(source, again, tolerance=1e-5), [])

    def test_rejects_other_games_and_old_versions(self):
        with self.assertRaises(BZNError):
            read_bzn((val("version", 1180) + val("saveType", 0)).encode())
        with self.assertRaises(BZNError):
            read_bzn((val("version", 1011) + val("seq_count", 1)).encode())

    def test_tug_pointer_named_state_in_1045(self):
        data = convert_bzn(redux_bzn(tank="svhaul", extra=one("undefptr", "00000000")), "1.5").data
        self.assertIn(b"undefptr = ", data)
        renamed = data.replace(b"undefptr = 00000000", b"state = 00000000", 1)
        bzn = read_bzn(renamed)
        self.assertEqual(bzn.objects[0].class_label, "tug")


class ConversionTests(unittest.TestCase):
    def test_redux_to_15_drops_redux_fields_and_converts_types(self):
        result = convert_bzn(redux_bzn(), "1.5")
        self.assertEqual(result.target_version, 1045)
        self.assertEqual(result.lossy, [])
        actions = {(c.action, c.key) for c in result.report.changes}
        for key in ("isCritical", "cloakState", "cloakTransBeginTime", "cloakTransEndTime"):
            self.assertIn(("dropped", key), actions)
        self.assertIn(("converted", "nextCmd.param"), actions)
        self.assertIn(("converted", "old_ptr"), actions)
        out = read_bzn(result.data)
        self.assertEqual(out.version, 1045)
        self.assertNotIn("isCritical", out.objects[0].fields)
        self.assertEqual(out.objects[0].fields["nextCmd.param"].kind, "ulong")
        # AiPath.old_ptr: a pointer from 2012, its raw little-endian bytes before
        self.assertEqual(out.paths[0]["old_ptr"].value, bytes.fromhex("00e17540"))
        self.assertIn(b"old_ptr = 00e17540\r\n", result.data)
        # a mission map stays missionSave = true (false makes 1.5 load a save game)
        self.assertIn(b"missionSave [1] =\r\ntrue\r\n", result.data)

    def test_round_trip_reproduces_the_redux_file(self):
        original = redux_bzn()
        down = convert_bzn(original, "1.5")
        up = convert_bzn(down.data, "redux")
        self.assertEqual(up.data, original)
        added = {c.key for c in up.report.changes if c.action == "added"}
        self.assertEqual(added, {"isCritical", "cloakState", "cloakTransBeginTime", "cloakTransEndTime"})

    def test_default_target_is_the_other_game(self):
        self.assertEqual(convert_bzn(redux_bzn()).target_version, 1045)
        down = convert_bzn(redux_bzn()).data
        self.assertEqual(convert_bzn(down).target_version, 2016)

    def test_non_default_value_is_refused_then_listed(self):
        data = redux_bzn(critical="true")
        with self.assertRaises(ConversionError) as ctx:
            convert_bzn(data, "1.5")
        lossy = ctx.exception.result.lossy
        self.assertEqual([(c.action, c.key) for c in lossy], [("dropped", "isCritical")])
        self.assertIn("avtank", lossy[0].context)
        allowed = convert_bzn(data, "1.5", allow_loss=True)
        self.assertEqual(len(allowed.lossy), 1)
        self.assertTrue(any("LOSS" in line for line in allowed.summary_lines()))

    def test_param_naming_an_odf_has_no_long_equivalent(self):
        with self.assertRaises(ConversionError) as ctx:
            convert_bzn(redux_bzn(param="avscav"), "1.5")
        change = ctx.exception.result.lossy[0]
        self.assertEqual((change.action, change.key), ("unmappable", "nextCmd.param"))

    def test_param_number_survives_as_id_bytes(self):
        # BZNParser keeps param as one UInt64: 0xFFFFFFFF is the ID bytes ff ff ff ff
        down = convert_bzn(redux_bzn(param="\xff\xff\xff\xff"), "1.5")
        self.assertIn(b"param [1] =\r\n4294967295\r\n", down.data)
        up = convert_bzn(down.data, "redux")
        self.assertIn(b"param [1] =\r\n\xff\xff\xff\xff\r\n", up.data)

    def test_long_odf_names_do_not_fit_15(self):
        with self.assertRaises(ConversionError) as ctx:
            convert_bzn(redux_bzn(tank="avtanklong"), "1.5")
        keys = [(c.action, c.key) for c in ctx.exception.result.lossy]
        self.assertIn(("unmappable", "PrjID"), keys)

    def test_redux_cloak_state_is_data(self):
        with self.assertRaises(ConversionError):
            convert_bzn(redux_bzn(cloak="01000000"), "1.5")

    def test_binary_source_to_ascii_verifies_within_ascii_precision(self):
        binary = write_bzn(read_bzn(redux_bzn()), 1045, binary=True)
        result = convert_bzn(binary, "redux")
        self.assertEqual(result.verification, [])
        self.assertTrue(any("six significant digits" in n for n in result.notes))

    def test_label_suffix_picks_the_class_of_an_unknown_odf(self):
        data = redux_bzn(tank="zzcustom").replace(b"label = unit_one", b"label = zzcustom1_wingman")
        binary = write_bzn(read_bzn(data, hints={"abcomm": ["commtower"]}), 1045, binary=True)
        bzn = read_bzn(binary, hints={"abcomm": ["commtower"]})
        self.assertEqual(bzn.objects[0].class_label, "wingman")
        self.assertEqual(bzn.objects[0].basis, "label")
        self.assertIn("craft", bzn.objects[0].candidates)

    def test_odf_folder_class_labels(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp, "zzcustom.odf").write_text('[GameObjectClass]\nclassLabel = "tug"\n')
            hints = bz1.odf_class_hints([tmp])
        self.assertEqual(hints, {"zzcustom": ["tug"]})


class CommandLineTests(unittest.TestCase):
    def run_main(self, argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            code = convert_main(argv)
        return code, out.getvalue()

    def test_writes_output_and_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp, "m.bzn")
            src.write_bytes(redux_bzn())
            code, text = self.run_main([str(src), "--to", "1.5", "--report", str(Path(tmp, "r.json"))])
            self.assertEqual(code, 0, text)
            self.assertTrue(Path(tmp, "m_v1045.bzn").is_file())
            self.assertIn("dropped    isCritical", text)
            self.assertTrue(Path(tmp, "r.json").is_file())

    def test_refusal_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp, "m.bzn")
            src.write_bytes(redux_bzn(critical="true"))
            code, text = self.run_main([str(src), "--to", "1.5"])
            self.assertEqual(code, 1)
            self.assertFalse(Path(tmp, "m_v1045.bzn").exists())
            self.assertIn("LOSS", text)


if __name__ == "__main__":
    unittest.main()
