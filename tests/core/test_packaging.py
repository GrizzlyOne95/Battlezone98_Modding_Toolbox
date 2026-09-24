"""The installers must agree with the application they install."""

import re
import unittest
from pathlib import Path

import bztoolbox
from bztoolbox import paths

ROOT = Path(__file__).resolve().parents[2]
ISS = (ROOT / "packaging" / "windows" / "BZModdingToolbox.iss").read_text(encoding="utf-8")


def load_script(path):
    import importlib.util

    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def iss_define(name):
    match = re.search(rf'^#define {name} "([^"]*)"', ISS, re.M)
    assert match, name
    return match.group(1)


class WindowsInstallerTests(unittest.TestCase):
    def test_shortcuts_group_with_the_running_window(self):
        self.assertEqual(iss_define("AppUserModelID"), bztoolbox.APP_ID)

    def test_names_match_the_build(self):
        version_info = load_script(ROOT / "packaging" / "generate_version_info.py")
        self.assertEqual(iss_define("AppName"), bztoolbox.APP_NAME)
        self.assertEqual(iss_define("AppPublisher"), version_info.COMPANY_NAME)
        self.assertEqual(iss_define("AppExe"), version_info.ORIGINAL_FILENAME)
        spec = (ROOT / "packaging" / "bztoolbox.spec").read_text(encoding="utf-8")
        for exe in (iss_define("AppExe"), iss_define("CliExe")):
            self.assertIn(f'name="{exe.removesuffix(".exe")}"', spec)

    def test_uninstaller_points_at_the_real_data_folder(self):
        self.assertIn(rf"{{userappdata}}\{paths._APP_DIR_NAME}", ISS)
        self.assertIn("clean-user-data --yes", ISS)

    def test_folder_menu_opens_the_folder_as_a_project(self):
        self.assertIn('"""{app}\\{#AppExe}"" gui --project ""%1"""', ISS)
        self.assertIn('"""{app}\\{#AppExe}"" gui --project ""%V"""', ISS)
        self.assertIn("RegDeleteKeyIncludingSubkeys(Root, 'Software\\Classes\\Directory\\shell\\{#MenuKey}')", ISS)

    def test_ci_checks_the_registered_app_id(self):
        app_id = re.search(r"^AppId=\{\{([0-9A-F-]{36})\}", ISS, re.M).group(1)
        ci = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        self.assertIn(f"{{{app_id}}}_is1", ci)


class LinuxInstallerTests(unittest.TestCase):
    def test_desktop_entry(self):
        linux = ROOT / "packaging" / "linux"
        entry = (linux / "io.github.grizzlyone95.bzmoddingtoolbox.desktop").read_text(encoding="utf-8")
        self.assertIn("Icon=io.github.grizzlyone95.bzmoddingtoolbox\n", entry)
        self.assertIn('Exec="@EXEC@" gui\n', entry)
        script = (linux / "install.sh").read_text(encoding="utf-8")
        self.assertIn("DESKTOP_ID=io.github.grizzlyone95.bzmoddingtoolbox\n", script)
        self.assertIn(paths._APP_DIR_NAME, script)


if __name__ == "__main__":
    unittest.main()
