import unittest

import numpy as np

from bztoolbox.modules.world.bz2_mat_encoder import encode_bz2_mat
from bztoolbox.modules.world.bz2_mat_reducer import MatReduction
from bztoolbox.modules.world.mat_codec import decode_entry


def reduction(primary, corners):
    primary = np.asarray(primary, dtype=np.uint8)
    height, width = primary.shape
    return MatReduction(
        weights=np.zeros((16, height, width), dtype=np.float32),
        primary_material=primary,
        secondary_material=np.zeros((height, width), dtype=np.uint8),
        secondary_weight=np.zeros((height, width), dtype=np.float32),
        sample_counts=np.ones((height, width), dtype=np.uint32),
        corner_materials=np.asarray(corners, dtype=np.uint8).reshape(4, height, width),
    )


class BZ2MatEncoderTests(unittest.TestCase):
    def test_encodes_supported_cap_and_records_exact_pair(self):
        encoded = encode_bz2_mat(reduction([[2]], [2, 5, 5, 2]))
        entry = decode_entry(int(encoded.entries[0, 0]))
        self.assertEqual((entry.base, entry.next, entry.mix), (2, 5, 1))
        self.assertEqual(encoded.cap_pairs, frozenset({(2, 5)}))
        self.assertEqual(encoded.diagonal_pairs, frozenset())
        self.assertEqual((encoded.cap_cells, encoded.ambiguous_cells), (1, 0))

    def test_encodes_supported_diagonal_and_records_exact_pair(self):
        encoded = encode_bz2_mat(reduction([[1]], [4, 4, 4, 1]))
        entry = decode_entry(int(encoded.entries[0, 0]))
        self.assertEqual((entry.base, entry.next, entry.mix), (1, 4, 8))
        self.assertEqual(encoded.diagonal_pairs, frozenset({(1, 4)}))
        self.assertEqual(encoded.ambiguous_cells, 0)

    def test_checkerboard_falls_back_to_primary_material(self):
        encoded = encode_bz2_mat(reduction([[5]], [2, 5, 2, 5]))
        entry = decode_entry(int(encoded.entries[0, 0]))
        self.assertEqual((entry.base, entry.next), (5, 5))
        self.assertEqual(encoded.ambiguous_cells, 1)
        self.assertFalse(encoded.cap_pairs)
        self.assertFalse(encoded.diagonal_pairs)

    def test_three_material_cell_falls_back_to_primary_material(self):
        encoded = encode_bz2_mat(reduction([[9]], [2, 5, 9, 2]))
        entry = decode_entry(int(encoded.entries[0, 0]))
        self.assertEqual((entry.base, entry.next), (9, 9))
        self.assertEqual(encoded.ambiguous_cells, 1)

    def test_maps_source_slots_before_encoding_transitions(self):
        encoded = encode_bz2_mat(reduction([[2]], [2, 5, 5, 2]),
                                 material_map={2: 1, 5: 4})
        entry = decode_entry(int(encoded.entries[0, 0]))
        self.assertEqual((entry.base, entry.next, entry.mix), (1, 4, 1))
        self.assertEqual(encoded.cap_pairs, frozenset({(1, 4)}))

    def test_rejects_unresolved_source_material(self):
        with self.assertRaisesRegex(ValueError, "unresolved source texture slot 5"):
            encode_bz2_mat(reduction([[2]], [2, 5, 5, 2]), material_map={2: 1})


if __name__ == "__main__":
    unittest.main()
