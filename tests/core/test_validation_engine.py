import tempfile
import threading
import unittest
from pathlib import Path

from battlezone.validation import CHECKS, DEFAULT_CHECKS, ValidationCancelled, validate_project


def write(path: Path, text: str, newline: str = "\r\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.replace("\n", newline).encode("utf-8"))


def make_mod(root: Path) -> None:
    write(root / "mymod.ini", '[DESCRIPTION]\nmissionName = "mymod"\n\n[WORKSHOP]\nmapType = "instant_action"\n')
    write(root / "mymod.trn", "[Size]\nTileSize = 8\n")
    for ext in (".hg2", ".mat", ".lgt"):
        (root / f"mymod{ext}").write_bytes(b"")
    write(root / "mymod.bzn", "version [1] =\n2016\nPrjID [1] =\navtank\nPrjID [1] =\nmytank\n")
    write(root / "odf" / "mytank.odf", '[GameObjectClass]\nclassLabel = "wingman"\n')


class ValidationEngineTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        make_mod(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def test_clean_mod_has_no_errors(self):
        report = validate_project(self.root)
        self.assertEqual(report.checks, list(DEFAULT_CHECKS))
        self.assertTrue(report.ok, [i.message for i in report.issues if i.severity == "error"])
        self.assertEqual(report.file_count, 7)

    def test_missing_custom_odf_from_mission_is_an_error(self):
        write(self.root / "mymod.bzn", "PrjID [1] =\nghosttank\nPrjID [1] =\navtank\n")
        issues = validate_project(self.root, ["bzn"]).issues
        self.assertEqual(len(issues), 1)
        self.assertEqual(issues[0].severity, "error")
        self.assertIn("ghosttank.odf", issues[0].message)
        self.assertEqual(issues[0].path, "mymod.bzn")

    def test_odfs_in_subfolders_satisfy_mission_references(self):
        self.assertEqual(validate_project(self.root, ["bzn"]).issues, [])

    def test_trn_checks(self):
        write(self.root / "mymod.trn", "[Size]\nA = 1\n[Size]\nB = 2\n", newline="\n")
        issues = validate_project(self.root, ["trn"]).issues
        self.assertEqual({i.rule_id for i in issues}, {"trn-line-endings", "trn-duplicate-size"})
        self.assertEqual(issues[0].severity, "error")  # errors sort first

    def test_structure_check_is_read_only(self):
        desktop_ini = self.root / "desktop.ini"
        desktop_ini.write_text("[.ShellClassInfo]\n")
        validate_project(self.root, ["structure"])
        self.assertTrue(desktop_ini.exists(), "validation must never modify the mod folder")

    def test_structure_reports_missing_workshop_files(self):
        (self.root / "mymod.lgt").unlink()
        issues = validate_project(self.root, ["structure"]).issues
        self.assertTrue(any("mymod.lgt" in i.message and i.severity == "error" for i in issues))

    def test_asset_reference_and_legacy_checks(self):
        write(self.root / "odf" / "mytank.odf", '[GameObjectClass]\nclassLabel = "wingman"\ngeometryName = "mytank.xsi"\n')
        (self.root / "old.map").write_bytes(b"")
        report = validate_project(self.root, ["assets", "legacy"])
        self.assertEqual(sorted(i.check for i in report.issues), ["assets", "legacy"])
        asset = report.by_check("assets")[0]
        self.assertEqual((asset.path, asset.line), ("odf/mytank.odf", 3))

    def test_odf_validator_findings_are_mapped(self):
        write(self.root / "odf" / "badflare.odf", '[GameObjectClass]\nclassLabel = "flare"\n[MineClass]\n'
              'lifeSpan = 1e10\n[FlareBuildingClass]\npayloadName = "payload"\n')
        report = validate_project(self.root, ["odf"])
        self.assertTrue(report.issues)
        self.assertTrue(all(i.check == "odf" and i.severity in ("error", "warning", "info") for i in report.issues))
        flare = [i for i in report.issues if i.rule_id == "flare-mine"]
        self.assertEqual(len(flare), 1)
        self.assertEqual((flare[0].severity, flare[0].path), ("error", "odf/badflare.odf"))

    def test_odf_lint_is_opt_in(self):
        self.assertIn("odf-lint", CHECKS)
        self.assertNotIn("odf-lint", DEFAULT_CHECKS)

    def test_unknown_check_and_bad_root(self):
        with self.assertRaises(ValueError):
            validate_project(self.root, ["nope"])
        with self.assertRaises(NotADirectoryError):
            validate_project(self.root / "missing")

    def test_progress_and_cancel(self):
        seen = []
        validate_project(self.root, ["trn", "legacy"], progress=lambda f, m: seen.append((f, m)))
        self.assertEqual(seen[0][0], 0.0)
        self.assertEqual(seen[-1], (1.0, "Done"))
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(ValidationCancelled):
            validate_project(self.root, cancel=cancel)

    def test_report_serializes(self):
        data = validate_project(self.root).to_dict()
        self.assertEqual(set(data), {"root", "checks", "file_count", "counts", "issues"})


if __name__ == "__main__":
    unittest.main()
