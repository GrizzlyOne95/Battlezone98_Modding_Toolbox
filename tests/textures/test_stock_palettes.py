import hashlib
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from bztoolbox.modules.textures.stock_palettes import STOCK_PALETTE_NAMES, get_stock_palette, get_stock_palette_bytes


EXPECTED_SHA256 = {
    'achilles.act': '9ed5bb3150b01a645ad331a07d5bab62db8df1dafb3e2264cfec422f77b55436',
    'black.act': 'a797fb381160a1ba5a515b2036835f3d3bafb040c7f0069b514891c612d37a45',
    'brown.act': '1bec6dfa325bfb51a78bf02ea55c755e792a76455e0541edfe489b95c9d7961a',
    'elysium.act': '8ea41a03249de524bdf62cbec800640a839c7b7c30ab6e55e1574fce70f364a1',
    'europa.act': '0402c1996d175cd9e7330d4c53c348b458232a4544dfa421e23b8e524dee76af',
    'explode.act': '7f9e8b3ebf190d82332c49e44b613c926551f71f9e87cef7af02791d062ae90c',
    'ganymede.act': 'af125fb7e1df5b807261ff2652f9efa2c68ec7b9c7399e3d9b76ed2ebf8c427e',
    'grey.act': '2b7c303533c1bf3c23d76d2de315580efa71b170af9b33c5c72e180954b85ca3',
    'hblack.act': '8691f96a3d4468b9525a34b12233990947f805ce3f25f606a78de1c0667f4161',
    'hblue.act': '9cf053206359ee33240e538d255b58b6d1caf003a4448c3f846c5979cd47ac5a',
    'hbrown.act': 'e14b4a20d8b9642cb7fa5a174bc8bea50262c3d04f4669de4ed3caaded8b89de',
    'hcyan.act': '545675d84f3d1f8bdc0243d1a6406f3decd66819a08a24c61d0e868711ae368d',
    'hgreen.act': '8bdd0df7d43e167b61f6fde2b72c8673c64f21ba009bc06593aabea334d4d1e5',
    'hgrey.act': 'a234c90932ce5887f21bcb469f4d68acc2851ae685694085ec841cbca40374a8',
    'hplasblu.act': 'a2961e43c1507b82b91bc6574787a433f9c65a0a9e58869e3d205f99141cb4af',
    'hplasgrn.act': 'd1581f98e5ec83d22640fe99dd1dbc71532ba8f2daf7cc0ebf433743ae895398',
    'hplasred.act': '801867532299bc4acd209c79e4daaec21ea84c1a080b4ae0a1564ab563c81f0b',
    'hred.act': 'fac8767ba166a0552167d82a9856b5381784378b98d732a33ad444fdd676b90d',
    'htan.act': '0e95d43b752044249be086664e7c1690fa66cf43707e8a53244053161a267a00',
    'hwhite.act': 'f290305d2cf3b141113c534fcc5c440ec6bbdbfab415d5b72ceb301df7ab7538',
    'hyellow.act': 'aa9d4d221db0b9b3207d3323a2d6b5446838c915df1b80d9c163e73228d49c19',
    'interface.act': 'a117bcbedd85ef23d57db52ece72ccf97394bb173d65ebff42856b8ff89d60bf',
    'io.act': 'bc3b4c22613b433351b28e9f08d6e0a11f17db468ba55ebbbcb22786d03673a9',
    'mars.act': '2ef0015d676ca0678d825d3041df2acbef49181797d41a9e7ffa215b625d8be4',
    'moon.act': 'db0fc6881f44384a706e269f906e917135c41dbb63f47b73d9a2030fd2383a7a',
    'objects.act': '6bbad3136601b6a7b6e12a3b593717bf28fc9d39a76cdabebefefecba534321b',
    'plasblue.act': '27db81a048d7b645490745be6e4b3d6819d02b37ad1624439515f9dbd27a58b6',
    'plasgrn.act': '7acbff1ef06c49af3269b872af2df93dd5ab147ad2368f24ce02e7d6e72fab95',
    'plasred.act': '6aa91d0bed794ebdf7f633ff6edc3176d7923af4918780e3a7a80074db45aa3f',
    'tan.act': '82d936bfb576206f338c652a7d097ea85a13cfef967bc3be5cfa9da32cfe228f',
    'titan.act': 'ca258aacc558b2e8ebeb7ec4fea3dc3fe2393f710045567f442d2d5042869f13',
    'venus.act': '8b9557e679791f0a392cb772b9e7908631379c8989c22e3ade29dece3c887968',
    'white.act': 'c7659926bfc5b62f2c4fc80303e99e10f6f237b95a5e881796f1ad5168b582a9',
}


class StockPaletteTests(unittest.TestCase):
    def test_all_stock_palettes_are_present(self):
        self.assertEqual(tuple(EXPECTED_SHA256), STOCK_PALETTE_NAMES)

    def test_payloads_are_exact_256_color_act_palettes(self):
        for name in STOCK_PALETTE_NAMES:
            with self.subTest(name=name):
                raw = get_stock_palette_bytes(name)
                self.assertEqual(len(raw), 768)
                self.assertEqual(hashlib.sha256(raw).hexdigest(), EXPECTED_SHA256[name])

                palette = get_stock_palette(name)
                self.assertEqual(len(palette), 256)
                self.assertTrue(all(len(rgb) == 3 for rgb in palette))
                self.assertTrue(all(0 <= channel <= 255 for rgb in palette for channel in rgb))

    def test_unknown_palette_raises(self):
        with self.assertRaises(KeyError):
            get_stock_palette("not-a-stock-palette.act")


if __name__ == "__main__":
    unittest.main()
