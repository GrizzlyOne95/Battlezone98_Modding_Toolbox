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
        self.assertEqual(unknown, {"[HoverCraftClass] cloakAllowed (Redux reads it under [CraftClass], not here)"})

    def test_keys_are_checked_against_both_binaries(self):
        from battlezone.validation.mod_scanner import _bz2_crc, _fnv1a, key_readers

        # the hash functions each engine uses to look keys up
        self.assertEqual((_fnv1a("GameObjectClass"), _fnv1a("classLabel")), (0xD3DD9CEC, 0x92D04727))
        self.assertEqual(key_readers("classlabel"), (True, True))
        self.assertEqual(key_readers("soundsteer"), (False, False))
        self.assertTrue(_bz2_crc("isAssault"))
        issues = self.scan("[WeaponClass]\nisAssault = 1\nwpnTypo = 2\nwpnTypo3 = 2\n"
                           "[QuakeBlastClass]\nquakeTime = 5\n[CraftClass]\nholdMsg = \"x.wav\"\n"
                           "[ExplosionClass]\nrenderBase = \"x\"\n")
        self.assertIn(("BZ2 Field", "[WeaponClass] isAssault: BZ2/BZCC reads this key, Redux has no reader "
                                    "for it, so it is ignored"), issues)
        # a plain key neither binary reads is dead; an indexed one may be built at run time
        self.assertIn(("Dead Field", "[WeaponClass] wpnTypo: no reader in the Redux or BZ2 binaries"), issues)
        self.assertIn(("Dead Field", "[QuakeBlastClass] quakeTime: no reader in the Redux or BZ2 binaries"), issues)
        self.assertIn(("Dead Field", "[CraftClass] holdMsg: no reader in the Redux or BZ2 binaries"), issues)
        self.assertIn(("Unknown Field", "[WeaponClass] wpnTypo3 (no reader in the Redux or BZ2 binaries)"), issues)
        self.assertFalse([d for k, d in issues if "renderBase" in d])   # read by Redux, section not recovered

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


class LuaReadKeysTests(unittest.TestCase):
    def test_keys_and_sections_the_mods_lua_reads_are_valid(self):
        with tempfile.TemporaryDirectory() as tmp:
            with open(os.path.join(tmp, "unit.odf"), "w", encoding="latin-1") as handle:
                handle.write('[GameObjectClass]\nclassLabel = "wingman"\ngunPos1 = "hard0"\nsupplyAmount3 = 5\n'
                             'hasPilot = 1\nisAssault = 1\ngunPoz1 = "typo"\n'
                             '[towerai]\nshotCheckDelay = 2\n')
            with open(os.path.join(tmp, "mission.lua"), "w", encoding="latin-1") as handle:
                handle.write('local a = GetODFString(odf, "GameObjectClass", "gunPos1")\n'
                             'local b = GetODFFloat(hData.odf, "GameObjectClass", "supplyAmount"..tostring(i), 0)\n'
                             'local c = GetODFBool(OpenODF(GetOdf(h)), "GameObjectClass", "hasPilot", false)\n'
                             "local d = GetODFFloat(odf, 'towerai', 'shotCheckDelay', 3.0)\n")
            issues = [(kind, detail) for _, kind, detail, _ in ModScanner().scan_mod_safety(tmp)]
        flagged = " ".join(detail for _, detail in issues)
        for read_by_lua in ("gunPos1", "supplyAmount3", "hasPilot", "towerai", "shotCheckDelay"):
            self.assertNotIn(read_by_lua, flagged)
        self.assertIn("gunPoz1", flagged)                 # not read by anything
        self.assertIn("isAssault", flagged)               # BZ2 key this mod's Lua does not read


class ReduxLabelTests(unittest.TestCase):
    def test_registered_prototypes_are_known(self):
        for label in ("shieldtower", "animbuilding", "dropoff", "specialitem", "lobber", "radarlauncher",
                      "i76building2", "i76sign"):
            self.assertIn(label, REDUX_CLASS_LABELS)
        self.assertLessEqual(REDUX_BASE_LABELS, REDUX_CLASS_LABELS)
        self.assertEqual(len(REDUX_CLASS_LABELS), 91)


if __name__ == "__main__":
    unittest.main()
