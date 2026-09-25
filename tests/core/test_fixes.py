import tempfile
import unittest
from pathlib import Path

from battlezone.validation import validate_project
from battlezone.validation.fixes import FixError, apply_fixes


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("latin-1"))


class LintFixTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name) / "mod"
        self.backups = Path(self._tmp.name) / "backups"

    def tearDown(self):
        self._tmp.cleanup()

    def fixes(self):
        report = validate_project(self.root, ["odf-lint"])
        return report, [i for i in report.issues if i.fix]

    def test_rename_remove_and_section_fixes_apply_and_clear_the_findings(self):
        write(self.root / "a.odf", '[GameObjectClass]\r\nclassLabel = "wingman"\r\n'
                                   'faction = "isdf" // team\r\nmaxHealth = 10\r\n')
        write(self.root / "b.odf", '[GameObjectClass]\r\nclassLabel = "scavenger"\r\nnation = "isdf"\r\n'
                                   'faction = "isdf"\r\n[ScavengerCraftClass]\r\nscrapHold = 20\r\n')
        _, fixes = self.fixes()
        by_file = {(i.path, i.fix[0]) for i in fixes}
        self.assertEqual(by_file, {("a.odf", "rename-key"), ("b.odf", "remove-line"),
                                   ("b.odf", "rename-section")})
        changed = apply_fixes(self.root, [(i.path, i.line, i.fix) for i in fixes], self.backups)
        self.assertEqual(sorted(changed), ["a.odf", "b.odf"])
        self.assertEqual((self.root / "a.odf").read_bytes(),
                         b'[GameObjectClass]\r\nclassLabel = "wingman"\r\nnation = "isdf" // team\r\nmaxHealth = 10\r\n')
        self.assertEqual((self.root / "b.odf").read_bytes(),
                         b'[GameObjectClass]\r\nclassLabel = "scavenger"\r\nnation = "isdf"\r\n'
                         b'[ScavengerClass]\r\nscrapHold = 20\r\n')
        self.assertIn(b"faction", (self.backups / "a.odf").read_bytes())    # originals kept outside the mod
        _, remaining = self.fixes()
        self.assertEqual(remaining, [])

    def test_a_file_changed_since_validation_is_not_edited(self):
        write(self.root / "a.odf", '[GameObjectClass]\nclassLabel = "wingman"\nfaction = "isdf"\n')
        _, fixes = self.fixes()
        write(self.root / "a.odf", '[GameObjectClass]\nclassLabel = "wingman"\nmaxHealth = 1\nfaction = "isdf"\n')
        with self.assertRaises(FixError):
            apply_fixes(self.root, [(i.path, i.line, i.fix) for i in fixes], self.backups)
        self.assertIn(b"maxHealth = 1\nfaction", (self.root / "a.odf").read_bytes())
        self.assertFalse(self.backups.exists())

    def test_paths_outside_the_project_are_refused(self):
        write(self.root / "a.odf", "[GameObjectClass]\nfaction = 1\n")
        with self.assertRaises(FixError):
            apply_fixes(self.root, [("../outside.odf", 2, ("rename-key", "faction", "nation", ""))])

    def test_ambiguous_replacements_get_no_fix(self):
        write(self.root / "a.odf", "[PowerPlantClass]\npowerRange = 100\n")   # not an alias of powerRadius
        _, fixes = self.fixes()
        self.assertEqual(fixes, [])


if __name__ == "__main__":
    unittest.main()
