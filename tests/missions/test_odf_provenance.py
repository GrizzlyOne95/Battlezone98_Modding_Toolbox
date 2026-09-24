import tempfile
import unittest
from pathlib import Path

from battlezone.odf.evidence import EVIDENCE, EVIDENCE_CONFIDENCE
from battlezone.odf.schema import LOADER_RULES, SCHEMA_VERSION
from battlezone.odf.validator import validate_directory


class ODFProvenanceTests(unittest.TestCase):
    def rule(self, rule_id):
        return next(rule for rule in LOADER_RULES if rule.rule_id == rule_id)

    def test_schema_version_tracks_reconciled_provenance_model(self):
        self.assertGreaterEqual(SCHEMA_VERSION, 4)

    def test_flare_rule_has_full_crash_chain(self):
        flare = self.rule("flare-mine")
        ids = set(flare.evidence_ids)
        self.assertIn("redux-flaremine-load", ids)
        self.assertIn("redux-flaremine-update-null-payload", ids)
        self.assertIn("redux-ordnance-build-null-payload", ids)

        self.assertEqual("0x004D2B10", EVIDENCE["redux-flaremine-load"].address)
        self.assertEqual("0x004D2E90", EVIDENCE["redux-flaremine-update-null-payload"].address)
        self.assertEqual("0x00586FF0", EVIDENCE["redux-ordnance-build-null-payload"].address)
        self.assertIn("fault 0x00586FFC", EVIDENCE["redux-ordnance-build-null-payload"].related_addresses)

    def test_redux_addresses_are_not_falsely_attributed_to_bz1_source(self):
        for evidence_id in (
            "redux-flaremine-load",
            "redux-flaremine-update-null-payload",
            "redux-ordnance-build-null-payload",
        ):
            evidence = EVIDENCE[evidence_id]
            self.assertEqual("", evidence.repository)
            self.assertEqual("", evidence.path)

    def test_evidence_confidence_values_are_valid(self):
        allowed = set(EVIDENCE_CONFIDENCE)
        for evidence in EVIDENCE.values():
            self.assertIn(evidence.confidence, allowed)

    def test_no_inferred_evidence_drives_current_hard_rules(self):
        for rule in LOADER_RULES:
            for evidence_id in rule.evidence_ids:
                self.assertNotEqual("inferred", EVIDENCE[evidence_id].confidence)

    def test_basename_evidence_describes_prototype_not_file_inheritance(self):
        evidence = EVIDENCE["redux-basename-prototype-selection"]
        self.assertIn("prototype", evidence.detail.lower())
        self.assertIn("does not", evidence.detail.lower())
        self.assertIn("merge another odf", evidence.detail.lower())

    def test_flame_delay_is_reported_as_dead_spelling(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "flame.odf").write_text(
                """
[OrdnanceClass]
classLabel = "flamepuff"
[FlamePuffClass]
flameDelay = 0.1
""",
                encoding="latin-1",
                newline="\r\n",
            )
            issues = validate_directory(root)
            matches = [i for i in issues if i.rule_id == "flame-puff" and i.key == "flameDelay"]
            self.assertEqual(1, len(matches))
            self.assertIn("frameDelay", matches[0].suggestion)


if __name__ == "__main__":
    unittest.main()
