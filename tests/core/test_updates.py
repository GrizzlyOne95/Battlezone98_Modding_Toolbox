import hashlib
import unittest
from pathlib import Path
import tempfile

from bztoolbox import updates
from bztoolbox.settings import Settings

RELEASE = {
    "tag_name": "v2.0.0",
    "html_url": "https://github.com/x/y/releases/tag/v2.0.0",
    "body": "notes",
    "assets": [
        {"name": "BZModdingToolbox-v2.0.0-windows-setup.exe", "browser_download_url": "https://d/setup.exe",
         "digest": "sha256:ABCDEF"},
        {"name": "BZModdingToolbox-v2.0.0-windows-portable.zip", "browser_download_url": "https://d/p.zip"},
        {"name": "BZModdingToolbox-v2.0.0-macos.dmg", "browser_download_url": "https://d/m.dmg"},
        {"name": "BZModdingToolbox-v2.0.0-linux.tar.gz", "browser_download_url": "https://d/l.tgz"},
    ],
}


class VersionTests(unittest.TestCase):
    def test_parse_and_compare(self):
        self.assertEqual(updates.parse_version("v1.2.3"), (1, 2, 3))
        self.assertEqual(updates.parse_version("1.2"), (1, 2, 0))
        self.assertEqual(updates.parse_version("nightly"), ())
        self.assertTrue(updates.is_newer("0.10.0", "0.9.9"))
        self.assertFalse(updates.is_newer("1.0.0", "1.0.0"))
        self.assertFalse(updates.is_newer("0.9.0", "1.0.0"))
        self.assertFalse(updates.is_newer("garbage", "1.0.0"))


class InstallKindTests(unittest.TestCase):
    def test_kinds(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe = str(Path(tmp) / "BZModdingToolbox.exe")
            self.assertEqual(updates.install_kind(exe, "win32", True), "portable")
            (Path(tmp) / "unins000.exe").write_bytes(b"")
            self.assertEqual(updates.install_kind(exe, "win32", True), "installed")
        self.assertEqual(updates.install_kind("x", "darwin", True), "app")
        self.assertEqual(updates.install_kind("x", "linux", True), "linux")
        self.assertEqual(updates.install_kind("x", "win32", False), "source")

    def test_each_kind_gets_its_download(self):
        expected = {"installed": "https://d/setup.exe", "portable": "https://d/p.zip",
                    "app": "https://d/m.dmg", "linux": "https://d/l.tgz", "source": ""}
        for kind, url in expected.items():
            update = updates.release_to_update(RELEASE, kind)
            self.assertEqual(update.version, "2.0.0")
            self.assertEqual(update.download_url, url, kind)
        installed = updates.release_to_update(RELEASE, "installed")
        self.assertTrue(installed.can_install)
        self.assertEqual(installed.sha256, "abcdef")
        self.assertFalse(updates.release_to_update(RELEASE, "portable").can_install)


class CheckTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.settings = Settings(Path(self.tmp.name) / "settings.json")
        self.calls = 0

    def tearDown(self):
        self.tmp.cleanup()

    def fetch(self, _url):
        self.calls += 1
        return RELEASE

    def test_daily_throttle_skip_and_opt_out(self):
        update = updates.check(self.settings, now=1_000_000, fetch=self.fetch)
        self.assertEqual(update.version, "2.0.0")
        self.assertIsNone(updates.check(self.settings, now=1_000_100, fetch=self.fetch))  # checked today
        self.assertEqual(self.calls, 1)
        self.settings.set("update_skipped_version", "2.0.0")
        self.assertIsNone(updates.check(self.settings, now=2_000_000, fetch=self.fetch))
        self.assertIsNotNone(updates.check(self.settings, force=True, now=2_000_001, fetch=self.fetch))
        self.settings.set("update_check", False)
        self.assertIsNone(updates.check(self.settings, now=9_000_000, fetch=self.fetch))
        self.assertEqual(self.calls, 3)

    def test_current_version_is_not_an_update(self):
        release = dict(RELEASE, tag_name="v0.0.1")
        self.assertIsNone(updates.check(self.settings, force=True, fetch=lambda _u: release))


class DownloadTests(unittest.TestCase):
    def test_checksum_is_verified(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "src.exe"
            source.write_bytes(b"setup" * 1000)
            good = hashlib.sha256(source.read_bytes()).hexdigest()
            update = updates.Update("2.0.0", "", source.as_uri(), "BZModdingToolbox-v2.0.0-windows-setup.exe", good)
            out = Path(tmp) / "out"
            out.mkdir()
            path = updates.download(update, str(out))
            self.assertEqual(path.read_bytes(), source.read_bytes())
            update.sha256 = "0" * 64
            with self.assertRaises(ValueError):
                updates.download(update, str(out))
            self.assertFalse(path.exists())


if __name__ == "__main__":
    unittest.main()
