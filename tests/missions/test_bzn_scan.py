"""Regression tests for BZN dependency extraction."""

import tempfile
import unittest
from pathlib import Path

from battlezone.bzn.scan import BZNParser


class BZNDependencyScanTests(unittest.TestCase):
    def _parse(self, content):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "test.bzn"
            path.write_text(content, encoding="ascii")
            return BZNParser(str(path)).parse()

    def test_empty_indexed_field_does_not_capture_next_field_name(self):
        matches = self._parse("""\
PrjID [0] = "avtank"
buildClass [1] =
buildDoneTime [1] = 4.0
dropClass [2] = apammo
""")

        self.assertEqual(matches, {"avtank", "apammo"})
        self.assertNotIn("buildDoneTime", matches)

    def test_empty_legacy_prjid_does_not_capture_next_line(self):
        matches = self._parse("""\
PrjID =
buildDoneTime = 4.0
""")

        self.assertEqual(matches, set())
        self.assertNotIn("buildDoneTime", matches)

    def test_valid_dependency_fields_still_parse(self):
        matches = self._parse("""\
PrjID [0] = "avtank"
buildClass [1] = svscav
dropClass [2] = "apammo"
curPilot [3] = sspilo
label [4] = "missionlabel"
""")

        self.assertEqual(matches, {"avtank", "svscav", "apammo", "sspilo", "missionlabel"})


if __name__ == "__main__":
    unittest.main()
