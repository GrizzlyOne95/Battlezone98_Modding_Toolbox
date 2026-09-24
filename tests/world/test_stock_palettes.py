import hashlib
import unittest

from bztoolbox.modules.world.stock_palettes import (
    get_stock_act_bytes,
    get_stock_palette,
    has_stock_palette,
    normalize_act_name,
    stock_palette_names,
)


class StockPaletteTests(unittest.TestCase):
    def test_embeds_complete_supplied_stock_pack(self):
        names = stock_palette_names()
        self.assertEqual(len(names), 33)
        for expected in (
            "achilles.act",
            "elysium.act",
            "europa.act",
            "ganymede.act",
            "io.act",
            "mars.act",
            "moon.act",
            "titan.act",
            "venus.act",
        ):
            self.assertIn(expected, names)
            self.assertTrue(has_stock_palette(expected.upper()))

    def test_mars_palette_round_trips_exact_supplied_bytes(self):
        raw = get_stock_act_bytes("MARS.ACT")
        self.assertIsNotNone(raw)
        self.assertEqual(len(raw), 768)
        self.assertEqual(
            hashlib.sha256(raw).hexdigest(),
            "2ef0015d676ca0678d825d3041df2acbef49181797d41a9e7ffa215b625d8be4",
        )
        palette = get_stock_palette("mars")
        self.assertEqual(len(palette), 256)
        self.assertTrue(all(len(rgb) == 3 for rgb in palette))

    def test_palette_name_normalization_is_case_insensitive(self):
        self.assertEqual(normalize_act_name("MARS.ACT"), "mars.act")
        self.assertEqual(normalize_act_name("venus"), "venus.act")

    def test_mars_and_moon_are_distinct(self):
        self.assertNotEqual(get_stock_act_bytes("mars.act"), get_stock_act_bytes("moon.act"))


if __name__ == "__main__":
    unittest.main()
