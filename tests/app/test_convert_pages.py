import unittest

from bztoolbox.app.pages.bzn_convert import target_from_form
from bztoolbox.app.pages.heightmap_convert import output_for, parse_zones
from bztoolbox.app.pages.redux_to_legacy import default_output, palette_from_form
from bztoolbox.modules.registry import PAGES_BY_ID


class ConvertPageFormTests(unittest.TestCase):
    def test_bzn_target_choices(self):
        self.assertIsNone(target_from_form("auto", ""))
        self.assertEqual(target_from_form("1.5", ""), "1.5")
        self.assertEqual(target_from_form("redux", "9"), "redux")
        self.assertEqual(target_from_form("custom", " 1044 "), 1044)
        with self.assertRaises(ValueError):
            target_from_form("custom", "latest")

    def test_heightmap_zones_and_output(self):
        self.assertIsNone(parse_zones(" "))
        self.assertEqual(parse_zones("4x3"), (4, 3))
        self.assertEqual(parse_zones("2X2"), (2, 2))
        for bad in ("4", "0x2", "axb"):
            with self.assertRaises(ValueError):
                parse_zones(bad)
        self.assertTrue(output_for("C:/maps/misn01.HGT").endswith("misn01.hg2"))
        self.assertTrue(output_for("C:/maps/misn01.hg2").endswith("misn01.hgt"))

    def test_redux_to_legacy_form(self):
        self.assertTrue(default_output("C:/worlds/Polar Mars").endswith("Polar Mars_1.5"))
        self.assertEqual(palette_from_form("auto", ""), "auto")
        self.assertEqual(palette_from_form("rebuild", "ignored.act"), "rebuild")
        with self.assertRaises(ValueError):
            palette_from_form("file", "C:/nowhere/missing.act")

    def test_pages_are_registered_where_their_neighbours_live(self):
        self.assertEqual(PAGES_BY_ID["missions.convert"].section, "missions")
        self.assertEqual(PAGES_BY_ID["world.heightmap"].section, "world")
        self.assertEqual(PAGES_BY_ID["world.to_legacy"].section, "world")


if __name__ == "__main__":
    unittest.main()
