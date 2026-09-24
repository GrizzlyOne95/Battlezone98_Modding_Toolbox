import tempfile
import unittest
from pathlib import Path

from battlezone.odf.evidence import EVIDENCE
from battlezone.odf.schema import LOADER_RULES
from battlezone.odf.validator import validate_directory


class ODFMinedRuleTests(unittest.TestCase):
    def write_odf(self, root: Path, name: str, text: str) -> None:
        (root / name).write_text(text, encoding="latin-1", newline="\r\n")

    def test_explosion_legacy_section_is_error_on_explosion_ordnance_path(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.write_odf(
                root,
                "legacyexplosion.odf",
                """
[OrdnanceClass]
classLabel = "explosion"
[Explosion]
damageRadius = 25
""",
            )

            issues = validate_directory(root)
            matches = [i for i in issues if i.rule_id == "explosion-section"]
            self.assertEqual(1, len(matches))
            self.assertEqual("ERROR", matches[0].severity)
            self.assertEqual("Explosion", matches[0].section)
            self.assertIn("ExplosionClass", matches[0].suggestion)
            self.assertIn("redux-explosionclass-contract", matches[0].evidence_ids)

    def test_canonical_explosionclass_is_not_flagged(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.write_odf(
                root,
                "explosion.odf",
                """
[OrdnanceClass]
classLabel = "explosion"
[ExplosionClass]
damageRadius = 25
""",
            )

            issues = validate_directory(root)
            self.assertFalse(any(i.rule_id == "explosion-section" for i in issues))

    def test_explosion_section_is_not_globally_reclassified(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.write_odf(
                root,
                "other.odf",
                """
[OrdnanceClass]
classLabel = "switcher"
[Explosion]
damageRadius = 25
""",
            )

            issues = validate_directory(root)
            self.assertFalse(any(i.rule_id == "explosion-section" for i in issues))

    def test_explosion_rule_uses_confirmed_code_evidence(self):
        rule = next(rule for rule in LOADER_RULES if rule.rule_id == "explosion-section")
        self.assertEqual(("redux-explosionclass-contract",), rule.evidence_ids)
        evidence = EVIDENCE["redux-explosionclass-contract"]
        self.assertEqual("confirmed-code", evidence.confidence)
        self.assertIn("ExplosionClass", evidence.detail)
        self.assertIn("[Explosion]", evidence.detail)

    def test_spray_buildng_typo_is_error_on_building_path(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.write_odf(
                root,
                "spray.odf",
                """
[GameObjectClass]
classLabel = "building"
[BuildingClass]
health = 1000
[SprayBuildngClass]
sprayRange = 70
""",
            )

            issues = validate_directory(root)
            matches = [i for i in issues if i.rule_id == "spray-building-section"]
            self.assertEqual(1, len(matches))
            self.assertEqual("ERROR", matches[0].severity)
            self.assertEqual("SprayBuildngClass", matches[0].section)
            self.assertIn("SprayBuildingClass", matches[0].suggestion)
            self.assertIn("redux-spraybuilding-contract", matches[0].evidence_ids)

    def test_canonical_spraybuildingclass_is_not_flagged(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.write_odf(
                root,
                "spray.odf",
                """
[GameObjectClass]
classLabel = "building"
[BuildingClass]
health = 1000
[SprayBuildingClass]
sprayRange = 70
""",
            )

            issues = validate_directory(root)
            self.assertFalse(any(i.rule_id == "spray-building-section" for i in issues))

    def test_spray_typo_without_buildingclass_is_not_globally_reclassified(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.write_odf(
                root,
                "other.odf",
                """
[GameObjectClass]
classLabel = "wingman"
[CraftClass]
[SprayBuildngClass]
sprayRange = 70
""",
            )

            issues = validate_directory(root)
            self.assertFalse(any(i.rule_id == "spray-building-section" for i in issues))

    def test_spray_rule_uses_code_and_stock_evidence(self):
        rule = next(rule for rule in LOADER_RULES if rule.rule_id == "spray-building-section")
        self.assertEqual(("redux-spraybuilding-contract",), rule.evidence_ids)
        evidence = EVIDENCE["redux-spraybuilding-contract"]
        self.assertEqual("code+stock", evidence.confidence)
        self.assertIn("SprayBuildingClass", evidence.detail)
        self.assertIn("four stock", evidence.detail)


if __name__ == "__main__":
    unittest.main()
