import json
import tempfile
import unittest
from pathlib import Path

from battlezone.project import Project, ProjectStore, summarize_folder


class ProjectStoreTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.mod = base / "My Mod"
        self.mod.mkdir()
        self.store = ProjectStore(base / "profiles")

    def tearDown(self):
        self._tmp.cleanup()

    def test_open_creates_and_finds_profile(self):
        project = self.store.open(self.mod)
        self.assertTrue(Path(project.profile_path).exists())
        self.assertEqual(project.name, "My Mod")
        again = self.store.find(self.mod)
        self.assertEqual(again.mod_path, project.mod_path)
        self.assertEqual([p.mod_path for p in self.store.list()], [project.mod_path])

    def test_profile_is_compatible_with_workshop_uploader_layout(self):
        # Same slug-digest naming and field names as the uploader's ProjectStore.
        from bztoolbox.modules.publishing.project_store import ProjectStore as UploaderStore

        uploader_store = UploaderStore(str(self.store.profiles_dir), file_manager=None)
        self.assertEqual(Path(uploader_store._profile_path_for_mod(str(self.mod))),
                         self.store.profile_path_for(self.mod))

    def test_unknown_fields_round_trip_and_disk_wins_for_them(self):
        project = self.store.open(self.mod)
        project.title = "Title"
        self.store.save(project)
        # Another module (Publish) records upload history in the same file.
        path = Path(project.profile_path)
        data = json.loads(path.read_text())
        data["last_upload_signature"] = "abc"
        path.write_text(json.dumps(data))
        project.author = "me"
        self.store.save(project)
        data = json.loads(path.read_text())
        self.assertEqual(data["last_upload_signature"], "abc")
        self.assertEqual((data["title"], data["author"]), ("Title", "me"))

    def test_import_workshop_profile(self):
        profile = Path(self._tmp.name) / "old.json"
        profile.write_text(json.dumps({"mod_path": str(self.mod), "title": "Imported", "item_id": "123",
                                       "last_upload_at": "2026-01-01"}))
        project = self.store.import_profile(profile)
        self.assertEqual((project.title, project.workshop_id), ("Imported", "123"))
        self.assertEqual(project.extra["last_upload_at"], "2026-01-01")

    def test_forget(self):
        project = self.store.open(self.mod)
        self.store.forget(project)
        self.assertIsNone(self.store.find(self.mod))

    def test_summary(self):
        (self.mod / "a.bzn").write_bytes(b"x")
        (self.mod / "a.trn").write_bytes(b"xy")
        (self.mod / "odf").mkdir()
        (self.mod / "odf" / "t.odf").write_bytes(b"")
        summary = summarize_folder(self.mod)
        self.assertEqual(summary.file_count, 3)
        self.assertEqual(summary.total_bytes, 3)
        self.assertEqual(summary.missions, ["a.bzn"])
        self.assertEqual(summary.worlds, ["a.trn"])
        self.assertEqual(summary.kinds["Object files"], 1)
        self.assertEqual(summary.planets, {"Custom / unknown": 1})

    def test_missions_are_grouped_by_planet(self):
        for stem, trn in (("m1", '[Color]\r\nPalette = "mars.act"\r\n'),
                          ("m2", '[Color]\r\nPalette = "Mars.act"\r\n'),
                          ("v1", '[Atlases]\r\nMaterialName = VenusAtlas\r\n'),
                          ("c1", '[Color]\r\nPalette = "mymod.act"\r\n')):
            (self.mod / f"{stem}.bzn").write_bytes(b"x")
            (self.mod / f"{stem}.trn").write_text(trn, encoding="ascii")
        (self.mod / "unused.trn").write_text("[Size]\r\n", encoding="ascii")
        summary = summarize_folder(self.mod)
        self.assertEqual(summary.planets, {"Mars": 2, "Venus": 1, "Custom / unknown": 1})
        self.assertEqual(len(summary.worlds), 5)

    def test_workshop_id(self):
        self.assertEqual(Project(mod_path="x").workshop_id, "")
        self.assertEqual(Project(mod_path="x", item_id="42").workshop_id, "42")


if __name__ == "__main__":
    unittest.main()


class FingerprintTests(unittest.TestCase):
    def test_changes_when_a_file_changes(self):
        import os
        import tempfile

        from battlezone.project import folder_fingerprint

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.odf"
            path.write_text("x")
            first = folder_fingerprint(tmp)
            self.assertEqual(first, folder_fingerprint(tmp))
            path.write_text("xy")
            self.assertNotEqual(first, folder_fingerprint(tmp))
            second = folder_fingerprint(tmp)
            os.remove(path)
            self.assertNotEqual(second, folder_fingerprint(tmp))
