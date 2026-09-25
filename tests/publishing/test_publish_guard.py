import os
import tempfile
import unittest
from pathlib import Path

from bztoolbox.modules.publishing.publish_guard import (
    check_publish, installed_workshop_matches, other_folders_for_item)


def touch(path: Path, text: str = "x") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def inventory(folder: Path) -> list:
    return [{"rel_path": p.relative_to(folder).as_posix().lower()} for p in folder.rglob("*") if p.is_file()]


class PublishGuardTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.mod = base / "isdf_chronicles"
        touch(self.mod / "isdfmscc.ini")
        touch(self.mod / "chill.ini")
        for i in range(10):
            touch(self.mod / f"odf/unit{i}.odf")
        self.workshop = base / "steamapps" / "workshop" / "content" / "301650"
        touch(self.workshop / "3001" / "isdfmscc.ini")      # the same mod, installed from the Workshop
        touch(self.workshop / "3001" / "chill.ini")
        touch(self.workshop / "4002" / "othermod.ini")      # someone else's mod

    def tearDown(self):
        self._tmp.cleanup()

    def check(self, item_id, snapshot=None, projects=()):
        return check_publish(str(self.mod), item_id, inventory(self.mod), snapshot, projects, [self.workshop])

    def test_installed_copy_with_the_same_ini_files_is_suggested(self):
        [match] = installed_workshop_matches(self.mod, [self.workshop])
        self.assertEqual((match.item_id, match.shared_ini), ("3001", ["chill.ini", "isdfmscc.ini"]))

    def test_a_good_update_and_a_new_item_pass(self):
        for item_id in ("3001", "0", ""):
            result = self.check(item_id)
            self.assertEqual((result.blocks, result.confirms), ([], []), item_id)

    def test_publishing_to_an_item_that_looks_like_another_mod_needs_confirmation(self):
        result = self.check("4002")
        self.assertTrue(result.ok)
        self.assertIn("does not look like this folder", result.confirms[0])

    def test_empty_folder_and_non_mod_folders_are_blocked(self):
        empty = Path(self._tmp.name) / "empty"
        empty.mkdir()
        self.assertIn("empty", check_publish(str(empty), "3001", [], None).blocks[0])
        sub = self.mod / "odf"
        result = check_publish(str(sub), "3001", inventory(sub), None)
        self.assertTrue(any("no .ini file" in b for b in result.blocks))
        self.assertFalse(check_publish(os.path.abspath(os.sep), "3001", [{"rel_path": "x"}], None).ok)

    def test_item_linked_to_another_existing_folder_is_blocked(self):
        other = Path(self._tmp.name) / "old_copy"
        other.mkdir()
        projects = [{"mod_path": str(other), "item_id": "3001"}, {"mod_path": str(self.mod), "item_id": "3001"}]
        self.assertEqual(other_folders_for_item("3001", str(self.mod), projects), [str(other)])
        self.assertIn("linked to another folder", self.check("3001", projects=projects).blocks[0])
        gone = [{"mod_path": str(Path(self._tmp.name) / "deleted"), "item_id": "3001"}]
        self.assertTrue(self.check("3001", projects=gone).ok)   # a folder that no longer exists does not block

    def test_update_that_removes_most_files_needs_confirmation(self):
        snapshot = {f"odf/old{i}.odf": {} for i in range(40)}
        snapshot.update({e["rel_path"]: {} for e in inventory(self.mod)})
        result = self.check("3001", snapshot=snapshot)
        self.assertIn("removes 40 of the 52 files", result.confirms[0])
        same = {e["rel_path"]: {} for e in inventory(self.mod)}
        self.assertEqual(self.check("3001", snapshot=same).confirms, [])


if __name__ == "__main__":
    unittest.main()
