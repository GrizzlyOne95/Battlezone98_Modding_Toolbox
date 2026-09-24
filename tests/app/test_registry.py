import importlib
import unittest

from bztoolbox import external
from bztoolbox.modules.registry import PAGES, PAGES_BY_ID, SECTIONS, pages_in


class RegistryTests(unittest.TestCase):
    def test_ids_unique_and_sections_known(self):
        self.assertEqual(len(PAGES_BY_ID), len(PAGES))
        sections = {s for s, _ in SECTIONS}
        for page in PAGES:
            self.assertIn(page.section, sections, page.id)
            self.assertIn(page.kind, ("native", "legacy"))
        for section, _ in SECTIONS:
            self.assertTrue(pages_in(section), f"empty section {section}")

    def test_every_standalone_tool_has_a_page(self):
        origins = {page.origin for page in PAGES if page.origin}
        self.assertEqual(origins, {
            "BZN Toolbox", "WorldBuilder", "Localization Tool", "Workshop Uploader", "HoloTextGen",
            "Font Generator", "OgreMeshTools", "HeightmapGen", "ZFS Specialist", "TextureManager",
            "AudioTool"})

    def test_factories_and_hooks_resolve(self):
        for page in PAGES:
            module_name = page.factory.partition(":")[0]
            module = importlib.import_module(module_name)
            self.assertTrue(hasattr(module, page.factory.partition(":")[2]), page.id)
            if page.project_hook:
                self.assertTrue(callable(page.load_project_hook()), page.id)

    def test_requirements_are_known_tools(self):
        for page in PAGES:
            for tool_id in page.requires:
                self.assertIn(tool_id, external.TOOLS, page.id)


if __name__ == "__main__":
    unittest.main()
