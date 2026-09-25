"""Regression tests for BZN dependency extraction."""

import tempfile
import unittest
from pathlib import Path

from battlezone.bzn.scan import BZNParser


class BZNDependencyScanTests(unittest.TestCase):
    def test_ascii_label_is_not_treated_as_odf_dependency(self):
        content = """\
PrjID [0] = "avtank"
buildClass [1] = "svscav"
dropClass [2] = "apammo"
curPilot [3] = "sspilo"
label [4] = "builddonetime"
"""
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "label-test.bzn"
            path.write_text(content, encoding="ascii")
            matches = BZNParser(str(path)).parse()

        self.assertEqual(matches, {"avtank", "svscav", "apammo", "sspilo"})
        self.assertNotIn("builddonetime", matches)


if __name__ == "__main__":
    unittest.main()
