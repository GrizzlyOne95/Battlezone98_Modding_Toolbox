import contextlib
import io
import json
import struct
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from battlezone.bzn.bzcc_port import (AiPath, MissionData, PortError, apply_offset, convert, main,
                       normalize_edge_path, parse_team_map, read_binary_source)


def matrix_lines():
    keys = ("right.x", "right.y", "right.z", "up.x", "up.y", "up.z",
            "front.x", "front.y", "front.z", "posit.x", "posit.y", "posit.z")
    return ["transform [1] ="] + [part for key, value in zip(keys, (1, 0, 0, 0, 1, 0, 0, 0, 1, 10, 20, 30))
                                    for part in (f"  {key} [1] =", str(value))]


SOURCE = "\r\n".join([
    "version [1] =", "1197", "saveType [1] =", "0", "binarySave [1] =", "0",
    "size [1] =", "1", "[GameObject]", "objClass = ivscout", "seqno [1] =", "a",
    "team [1] =", "2", "label = Scout", "isUser [1] =", "0",
    *matrix_lines(), "[AiMission]", "size [1] =", "0", "[AOIs]", "size [1] =", "0",
    "[AiPaths]", "count [1] =", "0", "",
]).encode("cp1252")

TEMPLATE = "\r\n".join([
    "version [1] =", "2016", "binarySave [1] =", "0", "seq_count [1] =", "2",
    "missionSave [1] =", "1", "TerrainName = moon", "size [1] =", "1",
    "[GameObject]", "PrjID = avscout", "seqno [1] =", "1", "pos [1] =",
    "  x [1] =", "0", "  y [1] =", "0", "  z [1] =", "0",
    "team [1] =", "0", "label = Prototype", "isUser [1] =", "0", "obj_addr = 00000000",
    *[line.replace(".", "_") if line.lstrip().startswith(("right.", "up.", "front.", "posit.")) else line
      for line in matrix_lines()], "illumination [1] =", "0", "pos [1] =", "  x [1] =", "0",
    "  y [1] =", "0", "  z [1] =", "0", "seqNo [1] =", "1",
    "name = LuaMission", "sObject = 00000000", "[AiMission]", "[AOIs]", "size [1] =", "0",
    "[AiPaths]", "count [1] =", "0", "",
]).encode("cp1252")


class PortTests(unittest.TestCase):
    def test_ascii_placement_and_template_tail(self):
        output, report = convert(SOURCE, TEMPLATE, {"ivscout": "avscout"}, True)
        self.assertEqual(report["ported_objects"], 1)
        self.assertIn(b"PrjID = avscout", output)
        self.assertIn(b"label = Scout", output)
        self.assertIn(b"seq_count [1] =\r\n11", output)
        self.assertIn(b"  x [1] =\r\n10", output)
        self.assertIn(b"name = LuaMission\r\nsObject = 00000000\r\n[AiMission]", output)
        self.assertEqual(output.count(b"[GameObject]"), 1)

    def test_offset_moves_objects_into_terrain_frame(self):
        output, report = convert(SOURCE, TEMPLATE, {"ivscout": "avscout"}, True,
                                 offset=(2048.0, 32.9, 2048.0))
        self.assertEqual(report["applied_offset_m"], [2048.0, 32.9, 2048.0])
        # Both pos blocks and the transform move; the rotation does not.
        self.assertEqual(output.count(b"  x [1] =\r\n2058"), 2)
        self.assertEqual(output.count(b"  z [1] =\r\n2078"), 2)
        self.assertIn(b"posit_y [1] =\r\n52.9", output)
        self.assertIn(b"right_x [1] =\r\n1", output)

    def test_offset_moves_path_points(self):
        mission = MissionData([], "t", "m", [AiPath(1, "p", [(-10.0, 5.0)], 0)], [])
        apply_offset(mission, (2048.0, 32.9, 2048.0))
        self.assertEqual(mission.paths[0].points, [(2038.0, 2053.0)])

    def test_edge_path_is_ported_and_rehomed(self):
        path_lines = ["[AiPaths]", "count [1] =", "1", "name = AiPath",
                      "sObject = 00000001", "size [1] =", "9",
                      "label = edge_path", "pointCount [1] =", "5",
                      "points [5] ="]
        for x, z in ((-10, -20), (10, -20), (10, 20), (-10, 20), (-9.9, -20)):
            path_lines.extend(["  x [1] =", str(x), "  z [1] =", str(z)])
        path_lines.append("pathType = 00000000")
        source = SOURCE.replace(b"[AiPaths]\r\ncount [1] =\r\n0",
                                "\r\n".join(path_lines).encode("cp1252"))
        output, report = convert(source, TEMPLATE, {"ivscout": "avscout"}, True,
                                 offset=(2560, 0, 2560))
        self.assertIn(b"label = edge_path", output)
        self.assertIn(b"pointCount [1] =\r\n4", output)
        self.assertIn(b"  x [1] =\r\n2550", output)
        self.assertIn(b"  z [1] =\r\n2540", output)
        self.assertEqual(report["boundary_path"], {
            "name": "edge_path", "source_point_count": 5, "point_count": 4,
            "bounds_xz_m": [2550, 2540, 2570, 2580]})

    def test_edge_path_accepts_two_or_four_and_rejects_other_shapes(self):
        for count in (2, 4):
            mission = MissionData([], "t", "m", [AiPath(1, "edge_path", [(i, i) for i in range(count)], 0)], [])
            boundary, source_count = normalize_edge_path(mission)
            self.assertEqual((len(boundary.points), source_count), (count, count))
        for points in ([(0, 0)] * 3,
                       [(0, 0), (10, 0), (10, 10), (0, 10), (5, 5)]):
            mission = MissionData([], "t", "m", [AiPath(1, "edge_path", points, 0)], [])
            with self.assertRaises(PortError):
                normalize_edge_path(mission)

    def test_isdf01_five_point_closure_becomes_four_corners(self):
        points = [(2031.660034, -2030.140015), (2039.410034, 663.893982),
                  (-495.808990, 666.960999), (-492.128998, -2041.849976),
                  (2019.5, -2030.650024)]
        mission = MissionData([], "isdf01", "", [AiPath(1, "edge_path", points, 0)], [])
        apply_offset(mission, (2560, 32.9, 2560))
        boundary, source_count = normalize_edge_path(mission)
        self.assertEqual(source_count, 5)
        self.assertEqual(len(boundary.points), 4)
        self.assertTrue(all(0 <= x <= 5120 and 0 <= z <= 5120 for x, z in boundary.points))

    def test_rejects_bzcc_player_team_outside_redux_range(self):
        source = SOURCE.replace(b"team [1] =\r\n2", b"team [1] =\r\n17")
        with self.assertRaisesRegex(PortError, "object 'Scout'.*source team 17.*Redux teams must be 0..15"):
            convert(source, TEMPLATE, {"ivscout": "avscout"}, True)

    def test_maps_object_and_aoi_teams(self):
        source = SOURCE.replace(b"team [1] =\r\n2", b"team [1] =\r\n17", 1)
        source = source.replace(
            b"[AOIs]\r\nsize [1] =\r\n0\r\n[AiPaths]",
            b"[AOIs]\r\nsize [1] =\r\n1\r\n[AOI]\r\npath [1] =\r\n00000000\r\n"
            b"team [1] =\r\n34\r\ninteresting [1] =\r\n0\r\ninside [1] =\r\n0\r\n"
            b"value [1] =\r\n0\r\nforce [1] =\r\n0\r\n[AiPaths]")
        team_map = parse_team_map({"17": 1, "34": 2})
        output, report = convert(source, TEMPLATE, {"ivscout": "avscout"}, True,
                                 team_map=team_map)
        self.assertIn(b"team [1] =\r\n1\r\nlabel = Scout", output)
        self.assertIn(b"[AOI]\r\nundefptr = 00000000\r\nteam [1] =\r\n2", output)
        self.assertEqual(report["applied_team_map"], {"17": 1, "34": 2})

    def test_team_map_targets_must_be_redux_teams(self):
        for mapping in ({"17": 16}, {"17": True}, {"player": 1}):
            with self.subTest(mapping=mapping), self.assertRaises(PortError):
                parse_team_map(mapping)

    def test_cli_requires_and_applies_team_map(self):
        source = SOURCE.replace(b"team [1] =\r\n2", b"team [1] =\r\n17", 1)
        template = TEMPLATE.replace(b"missionSave [1] =", b"msn_filename = template.bzn\r\nmissionSave [1] =", 1)
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source_path, template_path = root / "source.bzn", root / "template.bzn"
            output_path, map_path = root / "output.bzn", root / "teams.json"
            source_path.write_bytes(source)
            template_path.write_bytes(template)
            map_path.write_text(json.dumps({"17": 1}), encoding="utf-8")
            args = [str(source_path), str(template_path), str(output_path),
                    "--map", str(root / "odfs.json")]
            (root / "odfs.json").write_text(json.dumps({"ivscout": "avscout"}), encoding="utf-8")
            with contextlib.redirect_stderr(io.StringIO()), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(args), 1)
                self.assertFalse(output_path.exists())
                self.assertEqual(main(args + ["--team-map", str(map_path)]), 0)
            self.assertIn(b"team [1] =\r\n1\r\nlabel = Scout", output_path.read_bytes())

    def test_missing_prototype_is_reported(self):
        output, report = convert(SOURCE, TEMPLATE, {}, False)
        self.assertEqual(report["ported_objects"], 0)
        self.assertEqual(len(report["skipped_objects"]), 1)
        self.assertNotIn(b"[GameObject]", output)
        with self.assertRaises(PortError):
            convert(SOURCE, TEMPLATE, {}, True)

    def test_binary_object_header(self):
        def token(kind, value):
            return bytes([kind]) + struct.pack("<H", len(value)) + value

        header = (b"version [1] =\r\n1197\r\nsaveType [1] =\r\n0\r\n"
                  b"binarySave [1] =\r\ntrue\r\n")
        payload = b"".join([
            token(2, b"\x04"), token(2, b"map\0"),
            token(4, struct.pack("<I", 2)), token(4, struct.pack("<I", 0)),
            token(2, b"moon\0"), token(4, struct.pack("<I", 1)),
            token(2, b"\x08"), token(2, b"ivscout\0"),
            token(4, struct.pack("<I", 10)), token(2, b"\x02"),
            token(2, b"\x06"), token(2, b"Scout\0"),
            token(1, b"\0"), token(8, b"\0" * 4),
            token(12, struct.pack("<16f", 1, 0, 0, 0, 0, 1, 0, 0,
                                  0, 0, 1, 0, 10, 20, 30, 1)),
            token(0, bytes(640)), token(2, b"\x0c"), token(2, b"testmis.dll\0"),
            token(4, struct.pack("<I", 0)), token(4, struct.pack("<I", 0)),
        ])
        objects = read_binary_source(header + payload)
        self.assertEqual(len(objects), 1)
        self.assertEqual(objects[0].matrix[9:], (10, 20, 30))

    def test_old_bz2_binary_header(self):
        def token(kind, value):
            return bytes([kind]) + struct.pack("<H", len(value)) + value

        header = (b"version [1] =\r\n1105\r\nsaveType [1] =\r\n0\r\n"
                  b"binarySave [1] =\r\ntrue\r\n")
        payload = b"".join([
            token(2, b"map.bzn\0".ljust(16, b"\0")),
            token(4, struct.pack("<I", 2)), token(4, struct.pack("<I", 0)),
            token(2, b"moon\0".ljust(100, b"\0")), token(4, struct.pack("<I", 1)),
            token(2, b"ivscout\0".ljust(16, b"\0")),
            token(4, struct.pack("<I", 10)), token(4, struct.pack("<I", 2)),
            token(2, b"Scout\0".ljust(40, b"\0")),
            token(4, struct.pack("<I", 0)), token(8, b"\0" * 4),
            token(12, struct.pack("<16f", 1, 0, 0, 0, 0, 1, 0, 0,
                                  0, 0, 1, 0, 10, 20, 30, 1)),
            token(2, b"testmis.dll\0".ljust(40, b"\0")),
            token(4, struct.pack("<I", 0)), token(4, struct.pack("<I", 0)),
        ])
        objects = read_binary_source(header + payload)
        self.assertEqual(objects[0].odf, "ivscout")
        self.assertEqual(objects[0].matrix[9:], (10, 20, 30))


if __name__ == "__main__":
    unittest.main()
