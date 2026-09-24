import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from bztoolbox import cli


def run(*argv):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cli.main(list(argv))
    return code, out.getvalue(), err.getvalue()


class CliTests(unittest.TestCase):
    def test_help_lists_migrated_commands(self):
        code, out, _ = run("help")
        self.assertEqual(code, 0)
        for delegate in cli.DELEGATES:
            self.assertIn(f"{delegate.group} {delegate.name}", out)

    def test_every_delegate_target_resolves(self):
        import importlib

        for delegate in cli.DELEGATES:
            module_name, _, attr = delegate.target.partition(":")
            self.assertTrue(callable(getattr(importlib.import_module(module_name), attr)), delegate)

    def test_delegate_help_exits_cleanly(self):
        code, out, _ = run("textures", "makemap", "--help")
        self.assertEqual(code, 0)
        self.assertIn("MakeMAP", out)
        code, out, _ = run("terrain", "generate", "--help")
        self.assertEqual(code, 0)
        self.assertIn("usage: bztoolbox terrain generate", out)

    def test_unknown_delegate(self):
        code, _, err = run("textures", "nope")
        self.assertEqual(code, 2)
        self.assertIn("unknown command", err)

    def test_validate_json_and_exit_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "m.bzn").write_text("PrjID [1] =\nghost\n")
            code, out, _ = run("validate", str(root), "--checks", "bzn", "--json")
            self.assertEqual(code, 1)
            data = json.loads(out)
            self.assertEqual(data["counts"]["error"], 1)
            (root / "ghost.odf").write_text("[GameObjectClass]\n")
            code, out, _ = run("validate", str(root), "--checks", "bzn")
            self.assertEqual(code, 0)
            self.assertIn("0 error(s)", out)

    def test_terrain_generate_delegate(self):
        with tempfile.TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "t.hg2"
            code, out, _ = run("terrain", "generate", "--zones", "1x1", "--seed", "3", "--output", str(out_path))
            self.assertEqual(code, 0, out)
            self.assertTrue(out_path.exists())

    def test_bzn_deps(self):
        with tempfile.TemporaryDirectory() as tmp:
            bzn = Path(tmp) / "m.bzn"
            bzn.write_text("PrjID [1] =\navtank\nPrjID [1] =\nmine\n")
            code, out, _ = run("bzn-deps", str(bzn), "--json")
            rows = {r["odf"]: r for r in json.loads(out)}
            self.assertEqual(code, 1)
            self.assertTrue(rows["avtank.odf"]["stock"])
            self.assertEqual(rows["mine.odf"]["status"], "MISSING")

    def test_clean_user_data_removes_the_data_folder(self):
        from bztoolbox import paths

        home = paths.user_data_dir()
        (paths.module_data_dir("world") / "world_builder_config.json").write_text("{}")
        code, out, _ = run("clean-user-data", "--yes", "--keep-credentials")
        self.assertEqual(code, 0)
        self.assertFalse(home.exists())
        self.assertIn(str(home), out)

    def test_clean_user_data_never_deletes_the_home_folder(self):
        import os
        from unittest import mock

        with mock.patch.dict(os.environ, {"BZTOOLBOX_HOME": str(Path.home())}):
            code, _, err = run("clean-user-data", "--yes", "--keep-credentials")
        self.assertEqual(code, 1)
        self.assertIn("refusing", err)
        self.assertTrue(Path.home().is_dir())

    def test_uploader_credentials_are_the_ones_cleaned(self):
        from bztoolbox import paths
        from bztoolbox.modules.publishing import uploader

        self.assertIn((uploader.KEYRING_SERVICE, uploader.KEYRING_API_KEY_ACCOUNT), paths.CREDENTIALS)


if __name__ == "__main__":
    unittest.main()
