import tempfile
import unittest
from pathlib import Path

from battlezone.odf.validator import validate_directory


class ODFBaseNameSemanticsTests(unittest.TestCase):
    def write_odf(self, root: Path, name: str, text: str) -> None:
        (root / name).write_text(text, encoding="latin-1", newline="\r\n")

    def test_base_name_does_not_inherit_parent_loader_sections(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.write_odf(root, "parent.odf", """
[GameObjectClass]
classLabel = "flare"
[MineClass]
[FlareMineClass]
payloadName = "payload"
""")
            self.write_odf(root, "child.odf", """
[GameObjectClass]
baseName = "parent"
unitName = "Not an inherited flare"
""")
            self.write_odf(root, "payload.odf", "[OrdnanceClass]\nclassLabel = \"explosion\"\n")

            issues = validate_directory(root, filenames=["child.odf"])
            self.assertFalse(any(i.rule_id == "flare-mine" for i in issues))

    def test_base_name_does_not_supply_missing_payload_key(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.write_odf(root, "parent.odf", """
[GameObjectClass]
classLabel = "flare"
[MineClass]
[FlareMineClass]
payloadName = "payload"
""")
            self.write_odf(root, "child.odf", """
[GameObjectClass]
baseName = "parent"
classLabel = "flare"
[MineClass]
[FlareMineClass]
shotDelay = 0.2
""")

            issues = validate_directory(root, filenames=["child.odf"])
            self.assertTrue(any(
                i.rule_id == "flare-mine"
                and i.key == "payloadName"
                and i.severity == "CRITICAL"
                for i in issues
            ))

    def test_missing_base_name_target_is_not_an_odf_dependency_error(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.write_odf(root, "child.odf", """
[GameObjectClass]
baseName = "doesnotexist"
classLabel = "wingman"
""")
            issues = validate_directory(root)
            self.assertFalse(any(i.rule_id.startswith("inheritance-") for i in issues))

    def test_base_name_self_reference_is_not_reported_as_file_cycle(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.write_odf(root, "self.odf", """
[GameObjectClass]
baseName = "self"
classLabel = "wingman"
""")
            issues = validate_directory(root)
            self.assertFalse(any(i.rule_id.startswith("inheritance-") for i in issues))

    def test_two_base_name_cross_references_are_not_file_cycle(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.write_odf(root, "a.odf", """
[GameObjectClass]
baseName = "b"
classLabel = "wingman"
""")
            self.write_odf(root, "b.odf", """
[GameObjectClass]
baseName = "a"
classLabel = "wingman"
""")
            issues = validate_directory(root)
            self.assertFalse(any(i.rule_id.startswith("inheritance-") for i in issues))

    def test_lowercase_basename_remains_inert(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.write_odf(root, "self.odf", """
[GameObjectClass]
basename = "self"
classLabel = "wingman"
""")
            issues = validate_directory(root)
            self.assertFalse(any(i.rule_id.startswith("inheritance-") for i in issues))

    def test_missing_base_name_is_not_automatically_invalid(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.write_odf(root, "root.odf", """
[GameObjectClass]
classLabel = "wingman"
[CraftClass]
""")
            issues = validate_directory(root)
            self.assertFalse(any(i.key == "baseName" and i.severity in {"ERROR", "CRITICAL"} for i in issues))


if __name__ == "__main__":
    unittest.main()
