"""Behaviour that must hold the same on Windows, macOS and Linux."""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]


class SettingsRecoveryTests(unittest.TestCase):
    def test_unreadable_settings_are_kept_aside_not_overwritten(self):
        from bztoolbox.settings import Settings

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            path.write_text('{"game_dir": "C:/Games", broken', encoding="utf-8")
            settings = Settings(path)
            self.assertEqual(settings.get("game_dir"), "")
            settings.set("last_page", "home")
            self.assertIn("broken", (Path(tmp) / "settings.json.bad").read_text(encoding="utf-8"))
            self.assertEqual(json.loads(path.read_text(encoding="utf-8"))["last_page"], "home")

    def test_missing_settings_start_from_defaults(self):
        from bztoolbox.settings import Settings

        with tempfile.TemporaryDirectory() as tmp:
            settings = Settings(Path(tmp) / "settings.json")
            self.assertEqual(settings.get("last_page"), "home")
            self.assertFalse((Path(tmp) / "settings.json.bad").exists())


@unittest.skipIf(os.name == "nt", "symlinks need extra rights on Windows")
class SteamRootTests(unittest.TestCase):
    def test_symlinked_steam_root_finds_each_install_once(self):
        from bztoolbox import external

        with tempfile.TemporaryDirectory() as tmp:
            real = Path(tmp) / "share" / "Steam"
            (real / "steamapps" / "common" / "Battlezone 98 Redux").mkdir(parents=True)
            (real / "steamapps" / "libraryfolders.vdf").write_text(f'"path"  "{real}"\n')
            link = Path(tmp) / "dot-steam"
            link.symlink_to(real)
            with mock.patch.object(external, "_steam_roots", return_value=[link, real]):
                self.assertEqual(len(external.detect_game_installs()), 1)


class ArchiveHelperTests(unittest.TestCase):
    def test_pack_output_and_its_temp_file_are_never_packed(self):
        from bztoolbox.modules.archives.common import is_same_or_temp

        with tempfile.TemporaryDirectory() as tmp:
            output = os.path.join(tmp, "mod.zfs")
            self.assertTrue(is_same_or_temp(Path(output), output))
            self.assertTrue(is_same_or_temp(Path(output + ".tmp"), output))
            self.assertFalse(is_same_or_temp(Path(tmp) / "unit.odf", output))

    def test_extract_asks_only_when_files_would_be_replaced(self):
        from bztoolbox.modules.archives import common

        with tempfile.TemporaryDirectory() as tmp:
            existing, new = Path(tmp) / "a.odf", Path(tmp) / "b.odf"
            existing.write_text("mine")
            with mock.patch.object(common.messagebox, "askyesno", return_value=False) as ask:
                self.assertTrue(common.confirm_overwrite([new], tmp))
                ask.assert_not_called()
                self.assertFalse(common.confirm_overwrite([existing, new], tmp))
                self.assertIn("a.odf", ask.call_args[0][1])


class HoloTextDDSTests(unittest.TestCase):
    def test_png_becomes_a_dxt5_dds_without_texconv(self):
        from PIL import Image

        from bztoolbox.modules.holotext.hud_gen import png_to_dds

        with tempfile.TemporaryDirectory() as tmp:
            png = os.path.join(tmp, "uiA.png")
            Image.new("RGBA", (64, 64), (0, 255, 0, 128)).save(png)
            dds = png_to_dds(png)
            self.assertTrue(dds.endswith("uiA.dds"))
            data = Path(dds).read_bytes()
            self.assertEqual(data[:4], b"DDS ")
            self.assertEqual(data[84:88], b"DXT5")
            self.assertEqual(int.from_bytes(data[28:32], "little"), 7)     # 64x64 down to 1x1
            with Image.open(dds) as image:
                self.assertEqual(image.size, (64, 64))


class LinuxDesktopEntryTests(unittest.TestCase):
    def test_window_class_matches_the_menu_entry(self):
        from bztoolbox.app.shell import WINDOW_CLASS

        entry = (ROOT / "packaging" / "linux" / "io.github.grizzlyone95.bzmoddingtoolbox.desktop").read_text(
            encoding="utf-8")
        self.assertIn(f"StartupWMClass={WINDOW_CLASS}\n", entry)


class FileDialogPatternTests(unittest.TestCase):
    def test_no_semicolon_separated_patterns(self):
        """Tk on macOS and Linux reads "*.png;*.jpg" as one pattern that matches nothing."""
        import re

        bad = []
        for path in (ROOT / "bztoolbox").rglob("*.py"):
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if re.search(r'"\*\.\w+;\*\.\w+', line):
                    bad.append(f"{path.relative_to(ROOT)}:{number}")
        self.assertEqual(bad, [])


if __name__ == "__main__":
    unittest.main()
