import math
import os
import tempfile
import unittest

import numpy as np

from bztoolbox.modules.world import mat_codec


class MatCodecTests(unittest.TestCase):
    def test_bzmapio_full_variant_nibble_roundtrip(self):
        value = mat_codec.encode_mix_entry(base=5, next_mat=2, mix=15, variant=8)
        self.assertEqual(value, 0x52F8)
        self.assertEqual(mat_codec.entry_to_bytes(value), b'\xF8\x52')
        decoded = mat_codec.decode_entry(value)
        self.assertEqual((decoded.base, decoded.next, decoded.mix, decoded.variant), (5, 2, 15, 8))
        self.assertEqual(decoded.documented_variant, 0)
        self.assertEqual(decoded.reserved, 2)

    def test_documented_reserved_compat_encoding(self):
        value = mat_codec.encode_entry(5, 2, cap=1, flip=1, rotation=3, variant=2, reserved=3)
        self.assertEqual(value, 0x52FE)
        decoded = mat_codec.decode_entry(value)
        self.assertEqual(decoded.variant, 14)
        self.assertEqual(decoded.documented_variant, 2)
        self.assertEqual(decoded.reserved, 3)

    def test_zone_pack_order_and_size(self):
        grid = np.empty((128, 128), dtype=np.uint16)
        for zz in range(2):
            for xx in range(2):
                material = zz * 2 + xx
                value = mat_codec.encode_mix_entry(material, material, 0)
                grid[zz*64:(zz+1)*64, xx*64:(xx+1)*64] = value
        payload = mat_codec.pack_mat_zones(grid, 2, 2)
        self.assertEqual(len(payload), 4 * 4096 * 2)
        zone_bytes = 4096 * 2
        self.assertEqual(payload[0:2], b'\x00\x00')
        self.assertEqual(payload[zone_bytes:zone_bytes+2], b'\x00\x11')
        self.assertEqual(payload[2*zone_bytes:2*zone_bytes+2], b'\x00\x22')
        self.assertEqual(payload[3*zone_bytes:3*zone_bytes+2], b'\x00\x33')
        np.testing.assert_array_equal(mat_codec.unpack_mat_zones(payload, 2, 2), grid)

    def test_make_trn_metrics_constant_and_border_fallback(self):
        heights = np.full((256, 256), 100, dtype=np.uint16)
        elevation, slope = mat_codec.make_trn_metrics_at(heights, 128, 128)
        self.assertEqual((elevation, slope), (20, 0))
        elevation, slope = mat_codec.make_trn_metrics_at(heights, 0, 0)
        self.assertEqual(elevation, 0)
        self.assertEqual(slope, math.trunc(math.degrees(math.atan(2.0))))

    def test_make_trn_metrics_uses_8x8_min_and_max_adjacent_delta(self):
        heights = np.full((256, 256), 100, dtype=np.uint16)
        heights[131, 131] = 75
        elevation, slope = mat_codec.make_trn_metrics_at(heights, 128, 128)
        self.assertEqual(elevation, 15)
        self.assertEqual(slope, math.trunc(math.degrees(math.atan(25.0 / 50.0))))

        heights.fill(100)
        heights[128, 129] = 114
        elevation, slope = mat_codec.make_trn_metrics_at(heights, 128, 128)
        self.assertEqual(elevation, 20)
        self.assertEqual(slope, 15)

    def test_first_match_wins_and_bounds_are_inclusive(self):
        heights = np.full((256, 256), 100, dtype=np.uint16)
        heights[128, 129] = 114
        rules = [
            {'mat_id': 5, 'min_h': 20, 'max_h': 20, 'min_s': 15, 'max_s': 15, 'mask_path': ''},
            {'mat_id': 2, 'min_h': 0, 'max_h': 4095, 'min_s': 0, 'max_s': 90, 'mask_path': ''},
        ]
        mats, unmatched = mat_codec.classify_samples(heights, rules, 1, 1)
        self.assertEqual(unmatched, 0)
        self.assertEqual(int(mats[32, 32]), 5)

        overlap = [
            {'mat_id': 1, 'min_h': 0, 'max_h': 4095, 'min_s': 0, 'max_s': 90, 'mask_path': ''},
            {'mat_id': 2, 'min_h': 0, 'max_h': 4095, 'min_s': 0, 'max_s': 90, 'mask_path': ''},
        ]
        mats, _ = mat_codec.classify_samples(np.zeros((256,256), dtype=np.uint16), overlap, 1, 1)
        self.assertTrue(np.all(mats == 1))

    def test_default_binary_rules_use_15_degree_threshold(self):
        rules = mat_codec.default_make_trn_rules()
        self.assertEqual(rules[0]['max_s'], 15)
        self.assertEqual(rules[1]['min_s'], 15)
        heights = np.full((256,256), 100, dtype=np.uint16)
        heights[128,129] = 114
        mats, _ = mat_codec.classify_samples(heights, rules, 1, 1)
        self.assertEqual(int(mats[32,32]), 0)

    def test_msvcr120_rand_sequence(self):
        rng = mat_codec.MSVCRand(1)
        self.assertEqual([rng.rand() for _ in range(5)], [41, 18467, 6334, 26500, 19169])

    def test_make_trn_transition_patterns(self):
        cases = {
            (1,1,0,0): 0,
            (0,1,1,0): 1,
            (0,0,1,1): 2,
            (1,0,0,1): 3,
            (1,1,1,0): 8,
            (0,1,1,1): 9,
            (1,0,1,1): 10,
            (1,1,0,1): 11,
        }
        for corners, expected_mix in cases.items():
            entry, kind = mat_codec.encode_make_trn_tile(corners, mat_codec.MSVCRand(1))
            decoded = mat_codec.decode_entry(entry)
            self.assertEqual((decoded.base, decoded.next), (0,1))
            self.assertEqual(decoded.mix, expected_mix)
            self.assertEqual(decoded.variant, 0)
            self.assertEqual(kind, 'diagonal' if expected_mix >= 8 else 'cap')

    def test_make_trn_all_unsupported_two_material_patterns_collapse_to_low(self):
        # Pattern bits are A/B/C/D = bit0/bit1/bit2/bit3 and mark corners != minimum.
        unsupported = (
            (1,0,0,0),  # 0001
            (0,1,0,0),  # 0010
            (0,0,1,0),  # 0100
            (0,0,0,1),  # 1000
            (1,0,1,0),  # 0101 checkerboard
            (0,1,0,1),  # 1010 checkerboard
        )
        for corners in unsupported:
            with self.subTest(corners=corners):
                entry, kind = mat_codec.encode_make_trn_tile(corners, mat_codec.MSVCRand(1))
                decoded = mat_codec.decode_entry(entry)
                self.assertEqual(kind, 'ambiguous')
                self.assertEqual((decoded.base, decoded.next), (0,0))

    def test_make_trn_three_material_case_collapses_to_material_7(self):
        entry, kind = mat_codec.encode_make_trn_tile((0,1,2,0), mat_codec.MSVCRand(1))
        decoded = mat_codec.decode_entry(entry)
        self.assertEqual(kind, 'ambiguous')
        self.assertEqual((decoded.base, decoded.next), (7,7))

    def test_make_trn_variant_and_mirror_distribution_logic(self):
        rng = mat_codec.MSVCRand(1)
        e1, _ = mat_codec.encode_make_trn_tile((0,0,0,0), rng)
        e2, _ = mat_codec.encode_make_trn_tile((0,0,0,0), rng)
        e3, _ = mat_codec.encode_make_trn_tile((0,0,0,0), rng)
        self.assertEqual((mat_codec.decode_entry(e1).mix, mat_codec.decode_entry(e1).variant), (0,0))
        self.assertEqual((mat_codec.decode_entry(e2).mix, mat_codec.decode_entry(e2).variant), (2,2))
        self.assertEqual((mat_codec.decode_entry(e3).mix, mat_codec.decode_entry(e3).variant), (4,0))

        rng = mat_codec.MSVCRand(1)
        generated_variants = {
            mat_codec.decode_entry(mat_codec.encode_make_trn_tile((0,0,0,0), rng)[0]).variant
            for _ in range(4096)
        }
        self.assertEqual(generated_variants, {0,1,2,3})

    def test_generate_mat_is_64_by_64_and_transition_validation_does_not_mutate(self):
        heights = np.zeros((256,256), dtype=np.uint16)
        rules = [{'mat_id':0,'min_h':0,'max_h':4095,'min_s':0,'max_s':90,'mask_path':''}]
        grid, stats = mat_codec.generate_mat(heights, rules, 1, 1, legacy_seed=1)
        self.assertEqual(grid.shape, (64,64))
        self.assertEqual(stats.solid_tiles, 4096)
        self.assertEqual(len(mat_codec.pack_mat_zones(grid,1,1)),8192)

    def test_parse_layer_ini_and_trn_transition_metadata(self):
        text = '''
[Size]
MinX=100
MinZ=200
Width=2560
Depth=1280

[Layer0]
ElevationStart=0
ElevationEnd=1000
SlopeStart=0
SlopeEnd=20
Material=0

[Layer1]
ElevationStart=1000
ElevationEnd=4095
SlopeStart=20
SlopeEnd=90
Material=3

[TextureType0]
SolidA0=x.map
CapTo3_A0=x.map
DiagonalTo3_A0=x.map

[TextureType3]
SolidA0=x.map
'''
        with tempfile.NamedTemporaryFile('w', suffix='.ini', delete=False) as handle:
            handle.write(text)
            path=handle.name
        try:
            config=mat_codec.parse_trn_painter(path)
        finally:
            os.unlink(path)
        self.assertEqual(config.texture_types,(0,3))
        self.assertEqual(config.cap_transitions,frozenset({(0,3)}))
        self.assertEqual(config.diagonal_transitions,frozenset({(0,3)}))
        self.assertEqual(len(config.layers),2)
        self.assertEqual(config.layers[1]['mat_id'],3)
        self.assertEqual((config.min_x,config.min_z,config.width,config.depth),(100.0,200.0,2560.0,1280.0))


if __name__ == '__main__':
    unittest.main()
