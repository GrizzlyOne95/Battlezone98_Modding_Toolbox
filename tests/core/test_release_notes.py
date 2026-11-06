"""Release notes must be generated once, then reused in every release artifact."""

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "release" / "render_notes.py"
spec = importlib.util.spec_from_file_location("render_notes", SCRIPT)
render_notes = importlib.util.module_from_spec(spec)
spec.loader.exec_module(render_notes)


class ReleaseNotesTests(unittest.TestCase):
    def test_markdown_and_installer_text_share_version_and_changes(self):
        body = "## What's Changed\n* Fix **map importer** in [#12](https://github.com/x/y/pull/12)"
        markdown, plain = render_notes.prepare_notes("v1.2.3", body)
        self.assertIn("# Battlezone Modding Toolbox v1.2.3", markdown)
        self.assertIn("## What's Changed", markdown)
        self.assertIn("BATTLEZONE MODDING TOOLBOX V1.2.3", plain)
        self.assertIn("WHAT'S CHANGED", plain)
        self.assertIn("- Fix map importer in #12 (https://github.com/x/y/pull/12)", plain)

    def test_empty_release_notes_fail_the_release(self):
        for version, body in (("v1.2.3", " \n "), ("v1.2.3", "null"), ("", "A fix")):
            with self.assertRaises(ValueError):
                render_notes.prepare_notes(version, body)

    def test_workflow_packages_the_same_notes_it_publishes(self):
        workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
        installer = (ROOT / "packaging" / "windows" / "BZModdingToolbox.iss").read_text(encoding="utf-8")
        self.assertIn("releases/generate-notes", workflow)
        self.assertIn("name: release-notes", workflow)
        self.assertIn("body_path: build/RELEASE_NOTES.md", workflow)
        self.assertNotIn("generate_release_notes: true", workflow)
        self.assertIn(r"InfoBeforeFile={#RepoRoot}\build\RELEASE_NOTES.txt", installer)
        self.assertIn(r'Source: "{#RepoRoot}\build\RELEASE_NOTES.md"', installer)
        self.assertIn("wpInfoBefore", installer)


if __name__ == "__main__":
    unittest.main()
