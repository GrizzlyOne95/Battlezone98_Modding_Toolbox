"""Asset Porting page: direct picks, batch files, drops and background jobs."""

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tests.app.test_gui import _make_root, pump
from tests.meshes.test_legacy_port import top_quad


class LegacyModelPortPageTests(unittest.TestCase):
    def test_options_drop_and_port(self):
        root = _make_root()
        try:
            from bztoolbox.app.pages.legacy_model_port import batch_files, dropped_paths
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

                for suffix in (".vdf", ".sdf", ".geo"):
                    chosen = src / f"example{suffix}"
                    with patch("bztoolbox.app.pages.legacy_model_port.filedialog.askopenfilename",
                               return_value=str(chosen)) as dialog:
                        page.select_file(suffix)
                    self.assertEqual(Path(page.model.get()), chosen)
                    self.assertEqual(Path(page.output.get()), src / "example_redux")
                    self.assertEqual(dialog.call_args.kwargs["filetypes"][0][1], f"*{suffix}")

                self.assertEqual(dropped_paths(page, "{C:/a b/x.vdf} C:/c.odf"), ["C:/a b/x.vdf", "C:/c.odf"])
                page.format.set("none")
                page.game15.set("")
                page._on_drop(SimpleNamespace(data="{%s} {%s}" % (src / "notes.txt", src / "part.geo")))
                self.assertEqual(Path(page.model.get()), src / "part.geo")
                self.assertEqual(Path(page.output.get()), src / "part_redux")
                pump(root, 10, until=lambda: page.job is not None and page.job.status not in ("queued", "running"))
                self.assertTrue((src / "part_redux" / "part.mesh").is_file())

                (src / "other.geo").write_bytes(top_quad("other"))
                self.assertEqual([p.name for p in batch_files(str(src), str(src / "out"))],
                                 ["other.geo", "part.geo"])
                page._on_drop(SimpleNamespace(data="{%s}" % src))
                pump(root, 10, until=lambda: page.job is not None and page.job.status not in ("queued", "running"))
                self.assertTrue((Path(page.batch_output.get()) / "part_geo" / "part.mesh").is_file())
                self.assertTrue((Path(page.batch_output.get()) / "other_geo" / "other.mesh").is_file())

                dropped = Path(tmp) / "dropped"
                dropped.mkdir()
                for name in ("one", "two"):
                    (dropped / f"{name}.geo").write_bytes(top_quad(name))
                (dropped / "broken.geo").write_bytes(b"not a GEO")
                page._on_drop(SimpleNamespace(data="{%s} {%s} {%s}" %
                                                  (dropped / "one.geo", dropped / "broken.geo", dropped / "two.geo")))
                pump(root, 10, until=lambda: page.job is not None and page.job.status not in ("queued", "running"))
                self.assertEqual(page.job.status, "done")
                self.assertTrue((Path(page.batch_output.get()) / "one_geo" / "one.mesh").is_file())
                self.assertTrue((Path(page.batch_output.get()) / "two_geo" / "two.mesh").is_file())
                self.assertEqual(sum(bool(error) for _, _, error in page.job.result), 1)
                shell.close(confirm=False)
        finally:
            try:
                root.destroy()
            except Exception:
                pass

    def test_batch_scan_skips_output_and_can_recurse(self):
        from bztoolbox.app.pages.legacy_model_port import batch_files

        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp) / "input"
            folder.mkdir()
            (folder / "unit.VDF").touch()
            (folder / "notes.txt").touch()
            nested = folder / "nested"
            nested.mkdir()
            (nested / "unit.sdf").touch()
            output = folder / "redux"
            output.mkdir()
            (output / "old.geo").touch()
            self.assertEqual([p.name for p in batch_files(str(folder), str(output))], ["unit.VDF"])
            self.assertEqual([p.name for p in batch_files(str(folder), str(output), recursive=True)],
                             ["unit.sdf", "unit.VDF"])
            self.assertEqual([p.name for p in batch_files(str(folder), tmp)], ["unit.VDF"])


if __name__ == "__main__":
    unittest.main()
