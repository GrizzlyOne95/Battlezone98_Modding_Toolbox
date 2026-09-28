"""Assets > ODF Explorer page: follows the open project, fills fields and stat tables."""

import tempfile
import tkinter as tk
import unittest
from pathlib import Path

from tests.app.test_gui import _make_root, pump


class ODFExplorerPageTests(unittest.TestCase):
    def test_page_follows_project_and_fills_tables(self):
        root = _make_root()
        try:
            from bztoolbox.app.shell import Shell
            from bztoolbox.settings import Settings

            with tempfile.TemporaryDirectory() as tmp:
                mod = Path(tmp) / "mod"
                mod.mkdir()
                (mod / "ttank.odf").write_text('[GameObjectClass]\nclassLabel = "wingman"\nmaxHealth = 900\n'
                                               'weaponHard1 = "GC1"\nweaponName1 = "tgun"\n'
                                               '[HoverCraftClass]\nvelocForward = 30\n')
                (mod / "tgun.odf").write_text('[WeaponClass]\nclassLabel = "cannon"\nordName = "tshell"\n'
                                              '[CannonClass]\nshotDelay = 0.5\n')
                (mod / "tshell.odf").write_text('[OrdnanceClass]\nclassLabel = "bullet"\ndamageImpact = 20\n')
                settings = Settings(Path(tmp) / "settings.json")
                settings.set("game_dir", str(Path(tmp) / "no-game"))
                shell = Shell(root, settings)
                shell.navigate("assets.odf")
                page = shell._pages["assets.odf"].widget
                self.assertIsNone(page.result)                       # no project: nothing to read
                shell.open_project(str(mod))
                pump(root, 10, until=lambda: page.result is not None)
                self.assertIsNotNone(page.result)
                self.assertEqual(len(page.odf_list.get_children()), 3)
                self.assertEqual(len(page.craft_table.tree.get_children()), 1)
                self.assertEqual(len(page.weapon_table.tree.get_children()), 1)
                self.assertEqual(page.weapon_table.visible_rows()[0]["dps"], "40")

                page.search_var.set("tgun")
                self.assertEqual(page.odf_list.get_children(), ("tgun",))
                page.show_odf("ttank")
                sections = [page.fields.item(i, "text") for i in page.fields.get_children()]
                self.assertEqual(sections[0], "[GameObjectClass]")
                shown = {page.fields.item(i, "text"): page.fields.item(i, "tags")
                         for s in page.fields.get_children() for i in page.fields.get_children(s)}
                self.assertEqual(shown["maxHealth"], ("set",))
                self.assertEqual(shown["buildTime"], ("default",))
                page.defaults_var.set(False)
                page._render_fields()
                keys = {page.fields.item(i, "text") for s in page.fields.get_children()
                        for i in page.fields.get_children(s)}
                self.assertNotIn("buildTime", keys)

                page.craft_table.sort("maxHealth")
                self.assertIn("maxHealth", page.column_label.cget("text"))
                shell.close(confirm=False)
        finally:
            try:
                root.destroy()
            except tk.TclError:
                pass


if __name__ == "__main__":
    unittest.main()
