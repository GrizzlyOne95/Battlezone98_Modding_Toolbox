"""Assets > Legacy Model Port page: options, dropped files and a port through the job queue."""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from tests.app.test_gui import _make_root, pump
from tests.meshes.test_legacy_port import top_quad


class LegacyModelPortPageTests(unittest.TestCase):
    def test_options_drop_and_port(self):
        root = _make_root()
        try:
            from bztoolbox.app.pages.legacy_model_port import dropped_paths
            from bztoolbox.app.shell import Shell
            from bztoolbox.settings import Settings

            with tempfile.TemporaryDirectory() as tmp:
                src = Path(tmp) / "my src"
                src.mkdir()
                (src / "part.geo").write_bytes(top_quad("part"))
                settings = Settings(Path(tmp) / "settings.json")
                settings.set("game_dir", str(Path(tmp) / "no-game"))
                shell = Shell(root, settings)
                shell.navigate("assets.legacy_model_port")
                page = shell._pages["assets.legacy_model_port"].widget

                page.turret.set("yes")
                page.scope.set("no")
                page.headlights.set(False)
                options = page.options()
                self.assertEqual((options.turret, options.scope, options.person, options.headlights),
                                 (True, False, None, False))

                self.assertEqual(dropped_paths(page, "{C:/a b/x.vdf} C:/c.odf"), ["C:/a b/x.vdf", "C:/c.odf"])
                page._on_drop(SimpleNamespace(data="{%s} {%s}" % (src / "notes.txt", src / "part.geo")))
                self.assertEqual(Path(page.model.get()), src / "part.geo")
                self.assertEqual(Path(page.output.get()), src / "part_redux")

                page.format.set("none")
                page.game15.set("")
                page.port()
                pump(root, 10, until=lambda: page.job is not None and page.job.status not in ("queued", "running"))
                self.assertTrue((src / "part_redux" / "part.mesh").is_file())
                shell.close(confirm=False)
        finally:
            try:
                root.destroy()
            except Exception:
                pass


if __name__ == "__main__":
    unittest.main()
