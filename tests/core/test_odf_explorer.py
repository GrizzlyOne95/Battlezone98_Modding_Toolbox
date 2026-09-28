"""ODF explorer: effective fields, stock replacement, stat tables and the CLI."""

import contextlib
import csv
import io
import tempfile
import unittest
from pathlib import Path

from battlezone.archives.zfs import write_zfs
from battlezone.odf.explorer import (CRAFT_COLUMNS, WEAPON_COLUMNS, ClassModel, ODFLibrary, class_model,
                                     engine_value, show_main, sort_key, stats_main, write_csv)

TANK = """[GameObjectClass]
classLabel = "wingman"
baseName = "avtank"
unitName = "Test Tank"
scrapCost = 7
maxHealth = 2000
maxHealth = 2500
maxAmmo = NULL
weaponHard1 = "GC1"
weaponName1 = "tgun"
weaponHard2 = "GM1"
weaponName2 = "stockgun"
velocForward = 99

[CraftClass]
rangeScan = 300.0f // radar

[HoverCraftClass]
velocForward = 25.0
omegaTurn = 2.5

[BuildingClass]
soundAmbient = "hum.wav"

[Render]
renderBase = "draw_twirl"
"""

GUN = """[WeaponClass]
classLabel = "cannon"
ordName = "tshell"
wpnName = "Test Gun"
"""

SHELL = """[OrdnanceClass]
classLabel = "bullet"
shotSpeed = 200
lifeSpan = 1.5
ammoCost = 10
damageBallistic = 40
damageImpact = 10
xplVehicle = "txpl"
"""

XPL = """[ExplosionClass]
classLabel = "explosion"
damageRadius = 8
damageConcussion = 5
"""

STOCK_GUN = b"""[WeaponClass]
classLabel = "machinegun"
ordName = "tshell"

[CannonClass]
shotDelay = 0.1
"""

STOCK_TANK = b"""[GameObjectClass]
classLabel = "wingman"
scrapCost = 5
pilotCost = 1
"""


class ODFExplorerTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.project = self.tmp / "mod"
        (self.project / "odf").mkdir(parents=True)
        for name, text in (("ttank.odf", TANK), ("tgun.odf", GUN), ("tshell.odf", SHELL), ("txpl.odf", XPL)):
            (self.project / "odf" / name).write_text(text, encoding="latin-1")
        (self.project / "backup" / "old").mkdir(parents=True)
        (self.project / "backup" / "old" / "tgun.odf").write_text(GUN.replace("Test Gun", "Old Gun"))
        self.game = self.tmp / "game"
        self.game.mkdir()
        write_zfs(self.game / "bzone.zfs", [("stockgun.odf", STOCK_GUN), ("ttank.odf", STOCK_TANK),
                                            ("readme.txt", b"x")])

    def tearDown(self):
        self._tmp.cleanup()

    def library(self, stock=True):
        return ODFLibrary(self.project, self.game if stock else None, stock=stock)

    def test_engine_values(self):
        self.assertEqual(engine_value('"Test Tank" // name'), "Test Tank")
        self.assertEqual(engine_value("300.0f // radar"), "300.0f")
        self.assertIsNone(engine_value("NULL"))
        self.assertEqual(engine_value(""), "")

    def test_effective_fields_sources(self):
        eff = self.library().effective("TTANK")
        self.assertEqual(eff.dispatch.chain, ("WingmanClass", "HoverCraftClass", "CraftClass", "GameObjectClass"))
        health = eff.get("maxHealth")
        self.assertEqual((health.status, health.value), ("set", "2500"))           # last occurrence wins
        self.assertEqual(health.chain[1].kind, "ignored")
        ammo = eff.get("maxAmmo")                                                  # NULL is not stored
        self.assertEqual((ammo.status, ammo.value, ammo.chain[0].source), ("default", "0",
                                                                            "GameObjectClass prototype default"))
        self.assertEqual(eff.get("rangeScan").value, "300.0f")
        self.assertEqual(eff.get("velocForward").source, "odf/ttank.odf:19")
        self.assertEqual(eff.get("velocForward").reader, "HoverCraftClass")
        self.assertEqual(eff.value("weaponName2"), "stockgun")
        self.assertEqual(eff.get("baseName").value, "avtank")                      # a value, not a parent
        self.assertEqual(eff.get("buildTime").status, "default")
        self.assertIsNone(eff.get("cloakTime").value)                              # default not recovered

        unread = {(f.section, f.key): f.note for f in eff.fields if f.status == "unread"}
        self.assertIn("does not read velocForward", unread[("GameObjectClass", "velocForward")])
        self.assertIn("BuildingClass, which is not in this object's class chain",
                      unread[("BuildingClass", "soundAmbient")])
        self.assertIn("not an object-class section", unread[("Render", "renderBase")])

    def test_project_copy_replaces_stock_copy(self):
        eff = self.library().effective("ttank")
        self.assertTrue(eff.replaces_stock)
        cost = eff.get("scrapCost")
        self.assertEqual(cost.value, "7")
        self.assertTrue(cost.overridden)
        self.assertEqual([o.kind for o in cost.chain], ["file", "stock", "default"])
        pilot = eff.get("pilotCost")                    # set only in the stock copy: not used
        self.assertEqual((pilot.status, pilot.value), ("default", "0"))
        self.assertEqual(pilot.chain[1].kind, "stock")

    def test_duplicate_project_files(self):
        library = self.library()
        self.assertEqual(library.entry("tgun").rel, "odf/tgun.odf")     # the shallowest copy
        eff = library.effective("tgun")
        self.assertEqual([e.rel for e in eff.other_copies], ["backup/old/tgun.odf"])
        self.assertIn("duplicate", {p.kind for p in library.problems()})

    def test_default_from_prototype_and_stock_lookup(self):
        library = self.library()
        gun = library.effective("tgun")
        self.assertEqual(gun.dispatch.cls, "CannonClass")
        self.assertEqual((gun.get("shotDelay").status, gun.value("shotDelay")), ("default", "0.2"))
        stock = library.effective("stockgun")
        self.assertEqual(stock.entry.origin, "stock")
        self.assertEqual(stock.dispatch.chain, ("MachineGunClass", "CannonClass", "WeaponClass"))
        self.assertEqual(stock.get("shotDelay").source, "stock stockgun.odf:6")

    def test_stat_rows(self):
        library = self.library()
        craft = library.craft_rows()
        self.assertEqual([r["odf"] for r in craft], ["ttank"])
        row = craft[0]
        self.assertEqual((row["unitName"], row["scrapCost"], row["maxHealth"], row["speedForward"],
                          row["turnRate"], row["rangeScan"]), ("Test Tank", "7", "2500", "25", "2.5", "300"))
        self.assertEqual(row["weapons"], "GC1=tgun; GM1=stockgun (stock)")
        self.assertIn("maxAmmo", row["defaulted"])

        weapons = library.weapon_rows()
        self.assertEqual([r["odf"] for r in weapons], ["tgun"])
        gun = weapons[0]
        self.assertEqual((gun["shotDelay"], gun["shotsPerSecond"], gun["damageTotal"], gun["dps"], gun["range"],
                          gun["ammoCost"], gun["splashRadius"], gun["splashDamage"], gun["ordnanceFrom"]),
                         ("0.2", "5", "50", "250", "300", "10", "8", "5", "project"))
        self.assertIn("shotDelay", gun["defaulted"])

        out = io.StringIO()
        write_csv(weapons, WEAPON_COLUMNS, out)
        parsed = list(csv.DictReader(io.StringIO(out.getvalue())))
        self.assertEqual(list(parsed[0]), [c[0] for c in WEAPON_COLUMNS])
        self.assertEqual(parsed[0]["dps"], "250")

    def test_without_game_install(self):
        library = self.library(stock=False)
        self.assertEqual(library.stock, {})
        self.assertIsNone(library.effective("stockgun"))
        self.assertFalse(library.effective("ttank").replaces_stock)
        refs = [p.message for p in library.problems() if p.kind == "reference"]
        self.assertTrue(any("weaponName2 = stockgun" in m and "stock ODFs not loaded" in m for m in refs))
        self.assertFalse(any("baseName" in m for m in refs))
        self.assertEqual(library.craft_rows()[0]["weapons"], "GC1=tgun; GM1=stockgun (missing)")
        missing = ODFLibrary(self.project, self.tmp / "nowhere")
        self.assertTrue(missing.warnings)

    def test_unknown_label_and_non_object(self):
        (self.project / "odd.odf").write_text('[GameObjectClass]\nclassLabel = "bogus"\nmaxHealth = 5\n')
        (self.project / "fx.odf").write_text('[Shock]\nrenderBase = "draw_shock"\n')
        library = self.library()
        odd = library.effective("odd")
        self.assertEqual(odd.dispatch.cls, "")
        self.assertEqual(odd.fields[0].key, "classLabel")
        self.assertEqual(odd.get("maxHealth"), None)
        messages = [p.message for p in library.problems() if p.kind == "dispatch"]
        self.assertEqual(len(messages), 1)
        self.assertIn('"bogus"', messages[0])

    def test_class_model(self):
        model = class_model()
        self.assertEqual(model.resolve("GameObjectClass", "i76sign"), "BuildingClass")
        self.assertEqual(model.resolve("OrdnanceClass", "targeting"), "LeaderRoundClass")
        self.assertEqual(model.resolve("WeaponClass", "targeting"), "TargetingGunClass")
        looped = ClassModel({"classes": {"AClass": {"base": "BClass", "label": "a"},
                                         "BClass": {"base": "AClass"}}})
        self.assertEqual(looped.chain("AClass"), ("AClass", "BClass"))

    def test_sort_key(self):
        values = ["10", "", "abc", "9.5", "-1"]
        self.assertEqual(sorted(values, key=sort_key), ["-1", "9.5", "10", "abc", ""])

    def test_cli(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(show_main([str(self.project), "ttank", "--game", str(self.game)]), 0)
        text = out.getvalue()
        self.assertIn("class: wingman: WingmanClass -> HoverCraftClass", text)
        self.assertIn("replaces 5  (stock ttank.odf:3 (replaced by the project file))", text)
        self.assertIn("! velocForward", text)

        target = self.tmp / "stats.csv"
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(stats_main([str(self.project), "--game", str(self.game), "--csv", str(target)]), 0)
            self.assertEqual(stats_main([str(self.project), "--no-stock", "--kind", "craft"]), 0)
        with open(self.tmp / "stats-craft.csv", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(list(rows[0]), [c[0] for c in CRAFT_COLUMNS])
        self.assertTrue((self.tmp / "stats-weapon.csv").is_file())
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(show_main([str(self.project), "nothere", "--no-stock"]), 1)


if __name__ == "__main__":
    unittest.main()
