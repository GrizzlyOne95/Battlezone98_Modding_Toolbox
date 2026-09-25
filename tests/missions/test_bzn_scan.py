import tempfile
import unittest
from pathlib import Path

from battlezone.bzn.scan import BZNParser

ASCII_BZN = """version [1] =
2016
binarySave [1] =
false
[GameObject]
PrjID [1] =
avfact
label [1] =
unnamed_avfact
buildClass [1] =

buildDoneTime [1] =
0
[GameObject]
PrjID [1] =
avtank
dropClass [1] =
avscav
[GameObject]
PrjID [1] = "svturr"
curPilot [1] =
sspilo
"""


class BZNParserAsciiTests(unittest.TestCase):
    def parse(self, text):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "test.bzn"
            path.write_text(text, encoding="ascii")
            return BZNParser(str(path)).parse()

    def test_empty_build_class_does_not_capture_next_field_name(self):
        names = self.parse(ASCII_BZN)
        self.assertNotIn("buildDoneTime", names)
        self.assertNotIn("buildDoneTim", names)

    def test_reads_values_on_same_or_next_line(self):
        names = self.parse(ASCII_BZN)
        for expected in ("avfact", "avtank", "avscav", "svturr", "sspilo"):
            self.assertIn(expected, names)


if __name__ == "__main__":
    unittest.main()
