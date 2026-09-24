import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from bztoolbox.modules.world.legacy_batch import (
    default_batch_prefix,
    discover_legacy_batch_folders,
    run_legacy_batch,
)


class LegacyBatchTests(unittest.TestCase):
    def _mission_folder(self, root, name, bzn_name="map.bzn"):
        path = os.path.join(root, name)
        os.makedirs(path)
        with open(os.path.join(path, bzn_name), "wb") as stream:
            stream.write(b"MultSTMission")
        return path

    def test_discovers_only_immediate_mission_subfolders(self):
        with tempfile.TemporaryDirectory() as root:
            self._mission_folder(root, "Alpha", "alpha.bzn")
            beta = os.path.join(root, "Beta")
            os.makedirs(beta)
            nested = os.path.join(beta, "Nested")
            os.makedirs(nested)
            with open(os.path.join(nested, "nested.bzn"), "wb") as stream:
                stream.write(b"MultSTMission")
            os.makedirs(os.path.join(root, "Docs"))

            found, skipped = discover_legacy_batch_folders(root)
            self.assertEqual([os.path.basename(path) for path in found], ["Alpha"])
            self.assertEqual(set(skipped), {"Beta", "Docs"})

    def test_default_prefix_uses_sole_bzn_stem(self):
        with tempfile.TemporaryDirectory() as root:
            mission = self._mission_folder(root, "Legends", "legends.bzn")
            self.assertEqual(default_batch_prefix(mission), "legends")

    def test_batch_continues_after_one_map_fails_and_writes_summary(self):
        with tempfile.TemporaryDirectory() as root:
            source_root = os.path.join(root, "source")
            output_root = os.path.join(root, "output")
            os.makedirs(source_root)
            self._mission_folder(source_root, "Alpha", "alpha.bzn")
            self._mission_folder(source_root, "Broken", "broken.bzn")
            self._mission_folder(source_root, "Charlie", "charlie.bzn")
            os.makedirs(os.path.join(source_root, "NotAMap"))

            calls = []

            def port_one(source_dir, output_dir, prefix):
                name = os.path.basename(source_dir)
                calls.append(name)
                if name == "Broken":
                    raise RuntimeError("synthetic conversion failure")
                with open(os.path.join(output_dir, "converted.marker"), "w", encoding="utf-8") as stream:
                    stream.write(prefix)

            def fake_validate(source_dir, output_dir, **_kwargs):
                name = os.path.basename(source_dir)
                return SimpleNamespace(
                    ready=True,
                    error_count=0,
                    warning_count=1 if name == "Charlie" else 0,
                    report_path=os.path.join(output_dir, "legacy_port_report.txt"),
                )

            with patch("bztoolbox.modules.world.legacy_batch.validate_legacy_port_folder", side_effect=fake_validate):
                result = run_legacy_batch(source_root, output_root, port_one)

            self.assertEqual(calls, ["Alpha", "Broken", "Charlie"])
            self.assertEqual(result.ready_count, 2)
            self.assertEqual(result.failed_count, 1)
            self.assertFalse(result.all_ready)
            self.assertEqual(result.items[1].status, "error")
            self.assertIn("synthetic conversion failure", result.items[1].message)
            self.assertEqual(result.skipped_folders, ("NotAMap",))
            self.assertTrue(os.path.isfile(result.report_path))
            self.assertTrue(os.path.isfile(result.json_path))
            with open(result.report_path, encoding="utf-8") as stream:
                report = stream.read()
            self.assertIn("Alpha", report)
            self.assertIn("Broken", report)
            self.assertIn("Charlie", report)

    def test_rejects_same_source_and_output_root(self):
        with tempfile.TemporaryDirectory() as root:
            self._mission_folder(root, "Alpha", "alpha.bzn")
            with self.assertRaisesRegex(ValueError, "must be different"):
                run_legacy_batch(root, root, lambda *_args: None)


if __name__ == "__main__":
    unittest.main()
