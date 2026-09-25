"""The bundled Redux ODF key list (generated from the BZ1_Source loader schema)."""

import os
import tempfile
import unittest

from battlezone.odf.class_labels import REDUX_BASE_LABELS, REDUX_CLASS_LABELS
from battlezone.validation.mod_scanner import ModScanner


class BundledParamsTests(unittest.TestCase):
    def scan(self, text):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "unit.odf"), "w", encoding="latin-1") as handle:
                handle.write(text)
            return [(kind, detail) for _, kind, detail, _ in ModScanner().scan_mod_safety(tmp)]

    def test_live_keys_and_indexed_families_pass(self):
        issues = self.scan(
            "[GameObjectClass]\nclassLabel = \"wingman\"\nweaponHard1 = \"HP_CANNON_1\"\nweaponName2 = \"gchain\"\n"
            "[CraftClass]\ncloakAllowed = 1\nvelocJam = 5\n"
            "[HoverCraftClass]\nflameParent12 = \"flame_1\"\n"
            "[ProducerClass]\nbuildItem9 = \"avfigh\"\n"
            "[LauncherClass]\ntargetReticle01 = \"lock\"\n")
        self.assertEqual(issues, [])

    def test_dead_and_wrong_section_keys_are_reported(self):
        issues = self.scan("[PowerPlantClass]\npowerRange = 100\n"
                           "[HoverCraftClass]\nsoundSteer = \"x.wav\"\ncloakAllowed = 1\n"
                           "[MinelayerClass]\nmineRad = 5\n"
                           "[WeaponClass]\nbaseName = \"gspstab\"\n")
        dead = {detail for kind, detail in issues if kind == "Dead Field"}
        self.assertEqual(dead, {
            "[PowerPlantClass] powerRange: no Redux loader reads it",
            "[HoverCraftClass] soundSteer: no Redux loader reads it",   # dead in every section
            "[MinelayerClass] mineRad: no Redux loader reads it",
            "[WeaponClass] baseName: Redux reads it only under [GameObjectClass]",
        })
        unknown = {detail for kind, detail in issues if kind == "Unknown Field"}
        self.assertEqual(unknown, {"[HoverCraftClass] cloakAllowed (Redux reads it under [CraftClass])"})

    def test_dead_sections_are_reported(self):
        issues = self.scan("[GameObjectClass]\nclassLabel = \"flare\"\n[FlareBuildingClass]\npayloadName = \"x\"\n")
        self.assertIn(("Dead Section", "[FlareBuildingClass] is never read by Redux, so all its keys are "
                                       "ignored; Redux reads [FlareMineClass]"), issues)

    def test_a_section_loader_that_reads_a_key_overrides_a_group_dead_note(self):
        # the turret note lists timeDeploy, but the TurretTankClass loader reads it
        self.assertEqual(self.scan("[TurretTankClass]\ntimeDeploy = 1\n"), [])

    def test_flare_payload_is_required(self):
        issues = self.scan("[FlareMineClass]\ntriggerDelay = 1\n")
        self.assertIn("payloadname", " ".join(d.lower() for k, d in issues if k == "Missing Fields"))


class ReduxLabelTests(unittest.TestCase):
    def test_registered_prototypes_are_known(self):
        for label in ("shieldtower", "animbuilding", "dropoff", "specialitem", "lobber", "radarlauncher",
                      "i76building2", "i76sign"):
            self.assertIn(label, REDUX_CLASS_LABELS)
        self.assertLessEqual(REDUX_BASE_LABELS, REDUX_CLASS_LABELS)
        self.assertEqual(len(REDUX_CLASS_LABELS), 91)


if __name__ == "__main__":
    unittest.main()
