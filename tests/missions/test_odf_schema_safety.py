import tempfile
import unittest
from pathlib import Path

from battlezone.odf.validator import validate_directory


class ODFSchemaSafetyTests(unittest.TestCase):
    def test_canonical_gameobject_lowercase_basename_is_not_auto_migration_advice(self):
        """Do not suggest turning a harmless ignored self-reference into baseName."""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "abstor.odf").write_text(
                '[GameObjectClass]\nbasename = "abstor"\nclassLabel = "powerplant"\n[BuildingClass]\n',
                encoding="latin-1",
            )
            issues = validate_directory(root)
            self.assertFalse(any(issue.key == "basename" for issue in issues))


if __name__ == "__main__":
    unittest.main()
