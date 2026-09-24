import unittest

from bztoolbox.modules.missions.toolbox_app import build_port_arguments


class PortFormTests(unittest.TestCase):
    def test_builds_converter_arguments(self):
        fields = {
            "source": "source.bzn", "template": "template.bzn", "output": "output.bzn",
            "mapping": "odfs.json", "team_map": "teams.json",
            "offset_from": "terrain.json", "report": "report.json",
            "mission": "LuaMission", "source_odfs": "source_mod; source_stock",
            "redux_odfs": "redux_mod; redux_stock",
        }
        flags = {"auto_map": True, "allow_skips": True}
        args = build_port_arguments(fields, flags)
        self.assertEqual(args[:3], ["source.bzn", "template.bzn", "output.bzn"])
        for option, value in (("--map", "odfs.json"), ("--team-map", "teams.json"),
                              ("--offset-from", "terrain.json"), ("--report", "report.json")):
            self.assertEqual(args[args.index(option) + 1], value)
        self.assertEqual(args.count("--source-odfs"), 2)
        self.assertEqual(args.count("--redux-odfs"), 2)
        self.assertIn("--auto-map", args)
        self.assertIn("--allow-skips", args)

    def test_requires_complete_offset_and_exclusive_report(self):
        fields = {"source": "source.bzn", "template": "template.bzn", "output": "output.bzn",
                  "offset_x": "1", "offset_y": "", "offset_z": "3"}
        with self.assertRaisesRegex(ValueError, "all three"):
            build_port_arguments(fields, {})
        fields["offset_y"] = "2"
        fields["offset_from"] = "terrain.json"
        with self.assertRaisesRegex(ValueError, "not both"):
            build_port_arguments(fields, {})
        fields["offset_from"] = ""
        self.assertEqual(build_port_arguments(fields, {})[-4:], ["--offset", "1", "2", "3"])


if __name__ == "__main__":
    unittest.main()
