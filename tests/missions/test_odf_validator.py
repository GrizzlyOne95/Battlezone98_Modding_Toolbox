import tempfile
import unittest
import zipfile
from pathlib import Path

from battlezone.odf import validator


class ODFValidatorTests(unittest.TestCase):
    def write_odf(self, root: Path, name: str, text: str) -> None:
        (root / name).write_text(text, encoding="latin-1", newline="\r\n")

    def test_flarebuilding_is_crash_risk(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.write_odf(root, "badflare.odf", """
[GameObjectClass]
classLabel = "flare"
[MineClass]
lifeSpan = 1e10
[FlareBuildingClass]
payloadName = "payload"
shotDelay = 0.10
""")
            self.write_odf(root, "payload.odf", "[OrdnanceClass]\nclassLabel = \"explosion\"\n")
            issues = validator.validate_directory(root)
            critical = [i for i in issues if i.severity == "CRITICAL"]
            self.assertEqual(1, len(critical))
            self.assertEqual("flare-mine", critical[0].rule_id)
            self.assertIn("FlareMineClass", critical[0].suggestion)

    def test_valid_flaremine_payload_does_not_raise_critical(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.write_odf(root, "flare.odf", """
[GameObjectClass]
classLabel = "flare"
[MineClass]
lifeSpan = 1e10
[FlareMineClass]
payloadName = "payload"
""")
            self.write_odf(root, "payload.odf", "[OrdnanceClass]\nclassLabel = \"explosion\"\n")
            issues = validator.validate_directory(root)
            self.assertFalse(any(i.severity == "CRITICAL" for i in issues))

    def test_missing_payload_on_canonical_flare_is_critical(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.write_odf(root, "flare.odf", """
[GameObjectClass]
classLabel = "flare"
[MineClass]
lifeSpan = 1e10
[FlareMineClass]
shotDelay = 0.1
""")
            issues = validator.validate_directory(root)
            self.assertTrue(any(i.key == "payloadName" and i.severity == "CRITICAL" for i in issues))

    def test_absent_flare_section_not_assumed_bad_until_inheritance_is_resolved(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.write_odf(root, "flarechild.odf", """
[GameObjectClass]
baseName = "someflare"
classLabel = "flare"
[MineClass]
lifeSpan = 1e10
""")
            issues = validator.validate_directory(root)
            self.assertFalse(any(i.rule_id == "flare-mine" for i in issues))

    def test_magnet_mine_legacy_section_and_typo(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.write_odf(root, "magmine.odf", """
[OrdnanceClass]
classLabel = "magnet"
[MineClass]
lifeSpan = 120
[MagnetClass]
triggetDelay = 0.1
fieldRadius = 30
""")
            issues = validator.validate_directory(root)
            self.assertTrue(any(i.rule_id == "magnet-mine" and "MagnetMineClass" in i.suggestion for i in issues))
            self.assertTrue(any(i.key == "triggetDelay" and "triggerDelay" in i.suggestion for i in issues))

    def test_building_magnet_is_not_reclassified_as_magnet_mine(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.write_odf(root, "buildingmagnet.odf", """
[GameObjectClass]
classLabel = "magnet"
[BuildingClass]
lifeSpan = 15
[MagnetClass]
triggetDelay = 0.0
fieldRadius = 120
""")
            issues = validator.validate_directory(root)
            self.assertFalse(any(i.rule_id == "magnet-mine" for i in issues))

    def test_scavenger_legacy_section(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.write_odf(root, "scav.odf", """
[GameObjectClass]
classLabel = "scavenger"
[CraftClass]
[HoverCraftClass]
[ScavengerCraftClass]
maxScrap = 4
""")
            issues = validator.validate_directory(root)
            self.assertTrue(any(i.rule_id == "scavenger" and "ScavengerClass" in i.suggestion for i in issues))

    def test_flamepuff_and_stock_explosion_typo(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.write_odf(root, "flame.odf", """
[OrdnanceClass]
classLabel = "flamepuff"
xplGround = "xlasgnd"
xplVehicle = "xlascar"
xplBuilding = "xmlasbld"
[flameClass]
flameTexture = "rpuff.5"
shotColor = 124
variance = 80
flameLength = 10
flameRadius = 40
""")
            stock = {"xlasgnd.odf", "xlascar.odf", "xlasbld.odf"}
            issues = validator.validate_directory(root, known_odfs=stock)
            self.assertTrue(any(i.rule_id == "flame-puff" and "FlamePuffClass" in i.suggestion for i in issues))
            typo = [i for i in issues if i.key.lower() == "xplbuilding"]
            self.assertEqual(1, len(typo))
            self.assertIn("xlasbld.odf", typo[0].suggestion)

    def test_switcher_flameclass_is_not_reclassified(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.write_odf(root, "switcher.odf", """
[OrdnanceClass]
classLabel = "switcher"
[TeamSwitcherClass]
switchTime = 1E6
[flameClass]
segmentRadius = 10
segmentLength = 40
""")
            issues = validator.validate_directory(root)
            self.assertFalse(any(i.rule_id == "flame-puff" for i in issues))

    def test_gameobject_legacy_section(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            self.write_odf(root, "tank.odf", """
[GameObject]
basename = "bvltnk"
classLabel = "wingman"
[CraftClass]
[HoverCraftClass]
""")
            issues = validator.validate_directory(root)
            self.assertTrue(any(i.rule_id == "game-object-root" and "GameObjectClass" in i.suggestion for i in issues))
            self.assertTrue(any(i.key == "basename" for i in issues))

    def test_zip_validation_does_not_require_extraction(self):
        with tempfile.TemporaryDirectory() as td:
            archive = Path(td) / "mission.zip"
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("mission/azflmpit.odf", """
[GameObjectClass]
classLabel = "flare"
[MineClass]
lifeSpan = 100
[FlareBuildingClass]
payloadName = "azflampt"
""")
                zf.writestr("mission/azflampt.odf", "[OrdnanceClass]\nclassLabel = \"flamepuff\"\n")
            issues = validator.validate_zip(archive)
            self.assertTrue(any(i.filename == "azflmpit.odf" and i.severity == "CRITICAL" for i in issues))

    def test_absozero_regression_family(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fixtures = {
                "azflmpit.odf": '[GameObjectClass]\nclassLabel = "flare"\n[MineClass]\nlifeSpan=1\n[FlareBuildingClass]\npayloadName="azflampt"\n',
                "azvolcan.odf": '[GameObjectClass]\nclassLabel = "flare"\n[MineClass]\nlifeSpan=1\n[FlareBuildingClass]\npayloadName="azflame"\n',
                "azfactsw.odf": '[GameObjectClass]\nclassLabel = "flare"\n[MineClass]\nlifeSpan=1\n[FlareBuildingClass]\npayloadName="azfacswt"\n',
                "azmgpull.odf": '[OrdnanceClass]\nclassLabel="magnet"\n[MineClass]\nlifeSpan=1\n[MagnetClass]\ntriggetDelay=0.1\n',
                "azmgpul2.odf": '[OrdnanceClass]\nclassLabel="magnet"\n[MineClass]\nlifeSpan=1\n[MagnetClass]\ntriggetDelay=0.1\n',
                "azmgpuL3.odf": '[OrdnanceClass]\nclassLabel="magnet"\n[MineClass]\nlifeSpan=1\n[MagnetClass]\ntriggetDelay=0.1\n',
                "azmag.odf": '[GameObjectClass]\nclassLabel="MAGNET"\n[BuildingClass]\nlifeSpan=15\n[MagnetClass]\ntriggetDelay=0.0\n',
                "azbcav.odf": '[GameObjectClass]\nclassLabel="scavenger"\n[CraftClass]\n[ScavengerCraftClass]\nmaxScrap=4\n',
                "azhvscav.odf": '[GameObjectClass]\nclassLabel="scavenger"\n[CraftClass]\n[ScavengerCraftClass]\nmaxScrap=10\n',
                "azbtnk.odf": '[GameObject]\nbasename="bvltnk"\nclassLabel="wingman"\n[CraftClass]\n',
                "azflampt.odf": '[OrdnanceClass]\nclassLabel="flamepuff"\nxplBuilding="xmlasbld"\n[flameClass]\nshotColor=124\nvariance=80\nflameLength=10\nflameRadius=40\n',
                "azflame.odf": '[OrdnanceClass]\nclassLabel="explosion"\n',
                "azfacswt.odf": '[OrdnanceClass]\nclassLabel="explosion"\n',
            }
            for name, text in fixtures.items():
                self.write_odf(root, name, text)

            issues = validator.validate_directory(root, known_odfs={"xlasbld.odf"})
            critical_files = {i.filename for i in issues if i.severity == "CRITICAL"}
            self.assertEqual({"azflmpit.odf", "azvolcan.odf", "azfactsw.odf"}, critical_files)
            self.assertFalse(any(i.filename == "azmag.odf" and i.rule_id == "magnet-mine" for i in issues))
            for name in ("azmgpull.odf", "azmgpul2.odf", "azmgpuL3.odf"):
                self.assertTrue(any(i.filename == name and i.rule_id == "magnet-mine" for i in issues))
            self.assertTrue(any(
                i.filename == "azflampt.odf"
                and i.key.lower() == "xplbuilding"
                and "xlasbld.odf" in i.suggestion
                for i in issues
            ))


if __name__ == "__main__":
    unittest.main()
