import os
import tempfile
import time
import unittest
from pathlib import Path

from bztoolbox import launch


def _install(root: Path, kind: str) -> launch.GameInstall:
    (root / (launch.REDUX_EXE if kind == "redux" else launch.LEGACY_EXE)).write_bytes(b"MZ")
    return launch.install_at(root)


class LaunchTests(unittest.TestCase):
    def test_install_kind_and_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            redux = _install(Path(tmp), "redux")
            self.assertEqual(redux.kind, "redux")
            plan = launch.build_launch(redux, "missions/misn05.bzn", ["nointro", "win"], '/extra "two words"')
            # Options in the game's own order, then extra arguments, then the bare mission name.
            self.assertEqual(plan.argv[1:], ["/win", "/nointro", "/extra", '"two words"', "misn05.bzn"])
            self.assertEqual(plan.cwd, str(Path(tmp)))
            with self.assertRaises(ValueError):
                launch.build_launch(redux, "", ["sw"])                    # a 1.5-only option
        with tempfile.TemporaryDirectory() as tmp:
            legacy = _install(Path(tmp), "1.5")
            self.assertEqual(launch.build_launch(legacy, "", ["sw"]).argv[1:], ["/SW"])
            with self.assertRaises(ValueError):
                launch.build_launch(legacy, "", [], via_steam=True)
        self.assertIsNone(launch.install_at(tempfile.gettempdir() + "/definitely-not-a-game"))

    def test_deploy_copies_only_changes_and_skips_editor_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            install = _install(root / "game", "redux") if (root / "game").mkdir() is None else None
            project = root / "mymod"
            (project / "sub").mkdir(parents=True)
            (project / "a.odf").write_text("[GameObjectClass]\n")
            (project / "sub" / "b.bzn").write_text("x")
            (project / "art.xcf").write_text("editor")
            (project / ".git").mkdir()
            (project / ".git" / "HEAD").write_text("ref")
            first = launch.deploy_project(project, install)
            self.assertEqual(sorted(first.copied), ["a.odf", "sub/b.bzn"])
            self.assertEqual(first.skipped, ["art.xcf"])
            self.assertTrue((install.addon / "mymod" / "sub" / "b.bzn").is_file())
            self.assertFalse((install.addon / "mymod" / ".git").exists())
            second = launch.deploy_project(project, install)
            self.assertEqual((second.copied, second.unchanged), ([], 2))
            time.sleep(1.1)
            (project / "a.odf").write_text("[GameObjectClass]\nchanged\n")
            self.assertEqual(launch.deploy_project(project, install).copied, ["a.odf"])
            self.assertEqual(launch.missions_in(project), ["b.bzn"])
            self.assertTrue(launch.remove_deployment(install, "mymod"))
            self.assertFalse((install.addon / "mymod").exists())
            self.assertFalse(launch.remove_deployment(install, ".."))

    def test_log_watch_reads_appended_and_rewritten_logs(self):
        with tempfile.TemporaryDirectory() as tmp:
            install = _install(Path(tmp), "1.5")
            symlog = Path(tmp) / "symlog.txt"
            symlog.write_text("old line\n")
            watch = launch.LogWatch(install)
            with open(symlog, "a") as stream:
                stream.write('Couldn\'t find file "x.odf"\n')
            self.assertEqual(watch.new_lines(), {"symlog.txt": ['Couldn\'t find file "x.odf"']})
            watch = launch.LogWatch(install)
            time.sleep(1.1)
            symlog.write_text("fresh\n")                             # rewritten, shorter
            os.utime(symlog, None)
            self.assertEqual(watch.new_lines(), {"symlog.txt": ["fresh"]})

    def test_flagged_skips_noise_and_substrings(self):
        lines = ["MOD FOUND bvdblter.ini at addon\IAMP_DoubleTerror",       # 'Terror' is not 'error'
                 "23:43:45: Invalid target for D3D11 shader 'X' - 'vs_4_0'",
                 "[INFO] engine addresses: verified=70 failed=0",
                 "12:00:01 WARNING: unknown mapType 'NONE' in 'a.ini'",
                 "12:00:02 WARNING: unknown mapType 'NONE' in 'a.ini'",
                 "Texture foo.dds not found"]
        self.assertEqual(launch.flagged(lines), ["12:00:01 WARNING: unknown mapType 'NONE' in 'a.ini'",
                                                 "Texture foo.dds not found"])


if __name__ == "__main__":
    unittest.main()
