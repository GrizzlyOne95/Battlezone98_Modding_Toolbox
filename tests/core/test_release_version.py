"""Release versioning used by the CI workflow (scripts/release/next_version.py)."""

import importlib.util
from pathlib import Path
import unittest

_PATH = Path(__file__).resolve().parents[2] / "scripts" / "release" / "next_version.py"
_spec = importlib.util.spec_from_file_location("next_version", _PATH)
nv = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(nv)


class NextVersionTests(unittest.TestCase):
    def test_first_release_is_the_version_file(self):
        self.assertEqual(nv.plan([], [], "0.1.0\n", []),
                         {"version": "0.1.0", "tag": "v0.1.0", "release": "true", "bump": "patch"})

    def test_labels_pick_the_bump(self):
        tags = ["v0.1.0", "v0.1.1", "v0.9.9-rc1", "nightly"]
        self.assertEqual(nv.next_version(tags, "0.1.0", "patch"), "0.1.2")
        self.assertEqual(nv.next_version(tags, "0.1.0", "minor"), "0.2.0")
        self.assertEqual(nv.next_version(tags, "0.1.0", "major"), "1.0.0")
        self.assertEqual(nv.bump_from_labels(["bug", "Release: Minor"]), "minor")
        self.assertEqual(nv.bump_from_labels(["release: minor", "release: major"]), "major")
        self.assertEqual(nv.bump_from_labels(["release: major", "release: skip"]), "skip")
        self.assertEqual(nv.bump_from_labels(["release: bogus"]), "patch")

    def test_version_numbers_compare_numerically(self):
        self.assertEqual(nv.next_version(["v0.9.0", "v0.10.0"], "0.1.0", "patch"), "0.10.1")

    def test_newer_version_file_wins(self):
        self.assertEqual(nv.next_version(["v0.1.4"], "0.3.0", "patch"), "0.3.0")
        self.assertEqual(nv.next_version(["v0.3.0"], "0.3.0", "patch"), "0.3.1")

    def test_skip_and_rerun_do_not_release(self):
        self.assertEqual(nv.plan(["v0.1.0"], [], "0.1.0", ["release: skip"])["release"], "false")
        rerun = nv.plan(["v0.1.0", "v0.1.1"], ["v0.1.1"], "0.1.0", [])
        self.assertEqual((rerun["version"], rerun["release"]), ("0.1.1", "false"))

    def test_cli_output_and_bad_version_file(self):
        import contextlib, io, tempfile
        with tempfile.TemporaryDirectory() as tmp:
            version = Path(tmp) / "VERSION"
            version.write_text("0.2.0\n")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                nv.main(["--labels", "bug\nrelease: minor", "--tags", "v0.2.0\nv0.2.1",
                         "--version-file", str(version)])
            self.assertIn("version=0.3.0\n", out.getvalue())
            self.assertIn("release=true\n", out.getvalue())
        with self.assertRaises(ValueError):
            nv.next_version([], "one", "patch")


if __name__ == "__main__":
    unittest.main()
