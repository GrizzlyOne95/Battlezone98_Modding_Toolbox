import unittest

import numpy as np

from bztoolbox.modules.world.bz2_mat_reducer import reduce_bz2_mat_cells
from bztoolbox.modules.world.bz2_ter_codec import SourceTerrain
from bztoolbox.modules.world.bz2_terrain_port import PortGeometry


def source_fixture():
    info = np.array([[(2 << 0) | (5 << 4) | (9 << 8) | (11 << 12)]], dtype=np.uint32)
    heights = np.zeros((10, 10), dtype=np.float32)
    colors = np.zeros((10, 10, 3), dtype=np.uint8)
    alphas = np.zeros((3, 10, 10), dtype=np.uint8)
    # Half the cell is layer 1, half is layer 0.  With alpha 255 the
    # sequential model makes this an exact 50/50 area-coverage fixture.
    alphas[0, :, 5:] = 255
    cells = np.zeros((10, 10), dtype=np.uint8)
    return SourceTerrain(5, 0, 0, 10, 10, heights, colors, alphas, cells, info)


class BZ2MatReducerTests(unittest.TestCase):
    def test_integrates_effective_weights_and_preserves_source_slots(self):
        source = source_fixture()
        geometry = PortGeometry(
            min_x=0, min_z=0, width_m=20, depth_m=20,
            zones_x=1, zones_z=1, source_min_x=0, source_min_z=0,
            source_width_m=20, source_depth_m=20, vertical_offset_m=0,
        )
        reduced = reduce_bz2_mat_cells(source, geometry)

        self.assertEqual(reduced.weights.shape, (16, 1, 1))
        self.assertEqual(reduced.primary_material.tolist(), [[2]])
        self.assertEqual(reduced.secondary_material.tolist(), [[5]])
        self.assertAlmostEqual(float(reduced.weights[:, 0, 0].sum()), 1.0)
        self.assertAlmostEqual(float(reduced.weights[2, 0, 0]), 0.5)
        self.assertAlmostEqual(float(reduced.weights[5, 0, 0]), 0.5)
        self.assertEqual(int(reduced.sample_counts[0, 0]), 100)
        self.assertEqual(reduced.corner_materials[:, 0, 0].tolist(), [2, 5, 5, 2])

    def test_padded_cells_edge_clamp_to_the_nearest_source_sample(self):
        source = source_fixture()
        geometry = PortGeometry(
            min_x=0, min_z=0, width_m=1280, depth_m=1280,
            zones_x=1, zones_z=1, source_min_x=0, source_min_z=0,
            source_width_m=20, source_depth_m=20, vertical_offset_m=0,
        )
        reduced = reduce_bz2_mat_cells(source, geometry)

        self.assertEqual(reduced.weights.shape, (16, 64, 64))
        np.testing.assert_allclose(reduced.weights[:, 0, 0].sum(), 1.0)
        self.assertEqual(int(reduced.primary_material[0, 0]), 2)
        self.assertEqual(int(reduced.secondary_material[0, 0]), 5)
        # The far cell is entirely padded beyond the authored 20 m source and
        # therefore repeats the nearest source sample at the right edge.
        self.assertEqual(int(reduced.primary_material[0, 63]), 5)
        self.assertEqual(int(reduced.secondary_material[0, 63]), 0)
        self.assertTrue(np.all(reduced.sample_counts > 0))

    def test_rehoming_preserves_local_material_sampling(self):
        source = source_fixture()
        natural = PortGeometry(
            min_x=0, min_z=0, width_m=20, depth_m=20,
            zones_x=1, zones_z=1, source_min_x=0, source_min_z=0,
            source_width_m=20, source_depth_m=20, vertical_offset_m=0,
        )
        rehomed = PortGeometry(
            min_x=2560, min_z=97280, width_m=20, depth_m=20,
            zones_x=1, zones_z=1, source_min_x=0, source_min_z=0,
            source_width_m=20, source_depth_m=20, vertical_offset_m=0,
        )

        expected = reduce_bz2_mat_cells(source, natural)
        actual = reduce_bz2_mat_cells(source, rehomed)

        np.testing.assert_allclose(actual.weights, expected.weights)
        np.testing.assert_array_equal(actual.primary_material, expected.primary_material)
        np.testing.assert_array_equal(actual.secondary_material, expected.secondary_material)
        np.testing.assert_array_equal(actual.sample_counts, expected.sample_counts)
        np.testing.assert_array_equal(actual.corner_materials, expected.corner_materials)

    def test_ignored_unbound_upper_slot_does_not_replace_base_material(self):
        source = source_fixture()
        source.info[0, 0] = np.uint32(2)  # layer 0 = slot 2; upper layers = unbound slot 0
        source.alphas[0].fill(255)
        geometry = PortGeometry(
            min_x=0, min_z=0, width_m=20, depth_m=20,
            zones_x=1, zones_z=1, source_min_x=0, source_min_z=0,
            source_width_m=20, source_depth_m=20, vertical_offset_m=0,
        )

        raw = reduce_bz2_mat_cells(source, geometry)
        resolved = reduce_bz2_mat_cells(source, geometry, ignored_slots={0})

        self.assertEqual(int(raw.primary_material[0, 0]), 0)
        self.assertEqual(int(resolved.primary_material[0, 0]), 2)
        self.assertEqual(resolved.corner_materials[:, 0, 0].tolist(), [2, 2, 2, 2])

    def test_rejects_non_redux_cell_geometry(self):
        source = source_fixture()
        geometry = PortGeometry(
            min_x=0, min_z=0, width_m=21, depth_m=20,
            zones_x=1, zones_z=1, source_min_x=0, source_min_z=0,
            source_width_m=20, source_depth_m=20, vertical_offset_m=0,
        )
        with self.assertRaisesRegex(ValueError, "20 m MAT cell"):
            reduce_bz2_mat_cells(source, geometry)


class UnboundBaseSlotTests(unittest.TestCase):
    def test_unbound_base_cluster_takes_nearest_bound_base_slot(self):
        from bztoolbox.modules.world.bz2_mat_reducer import fill_unbound_base_slots
        indices = np.zeros((4, 5, 5), dtype=np.uint8)
        indices[0] = 1
        indices[0, 0:2, 3:5] = 3
        indices[0, 2, 2] = 0   # unbound, surrounded mostly by slot 1
        indices[0, 0, 4] = 0   # unbound, neighbours mostly slot 3
        filled, count = fill_unbound_base_slots(indices, {0})
        self.assertEqual(count, 2)
        self.assertEqual(int(filled[0, 2, 2]), 1)
        self.assertEqual(int(filled[0, 0, 4]), 3)
        self.assertEqual(int(indices[0, 2, 2]), 0)  # input untouched

    def test_all_unbound_base_is_rejected(self):
        from bztoolbox.modules.world.bz2_mat_reducer import fill_unbound_base_slots
        with self.assertRaisesRegex(ValueError, "Every BZ2 layer-0"):
            fill_unbound_base_slots(np.zeros((4, 2, 2), dtype=np.uint8), {0})


if __name__ == "__main__":
    unittest.main()
