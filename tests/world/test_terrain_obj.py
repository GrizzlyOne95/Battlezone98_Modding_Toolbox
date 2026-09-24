import os
import random
import tempfile
import unittest

import numpy as np

from bztoolbox.modules.world.hg2_codec import read_hg2, write_hg2
from bztoolbox.modules.world.terrain_obj import (
    TerrainOBJ,
    export_hg2_to_obj,
    read_terrain_obj,
    resolve_hg2_geometry,
    write_heightfield_obj,
)


class TerrainOBJTests(unittest.TestCase):
    def test_hg2_obj_round_trip_preserves_rectangular_heightfield(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            heights = (np.arange(8 * 12, dtype=np.uint16).reshape((8, 12)) * 3) % 8192
            hg2_path = os.path.join(temp_dir, "terrain.hg2")
            obj_path = os.path.join(temp_dir, "terrain.obj")

            write_hg2(hg2_path, heights, zones_x=3, zones_z=2, zone_bits=2)
            export_hg2_to_obj(hg2_path, obj_path)
            mesh = read_terrain_obj(obj_path)

            self.assertEqual(mesh.shape, (8, 12))
            self.assertEqual((mesh.zones_x, mesh.zones_z, mesh.zone_bits), (3, 2, 2))
            self.assertTrue(np.array_equal(mesh.heights, heights))

    def test_export_grid_matches_full_hg2_world_extent_convention(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            heights = np.zeros((4, 4), dtype=np.uint16)
            obj_path = os.path.join(temp_dir, "terrain.obj")
            write_heightfield_obj(obj_path, heights, zones_x=1, zones_z=1, zone_bits=2)

            with open(obj_path, "r", encoding="utf-8") as stream:
                vertices = [line.strip() for line in stream if line.startswith("v ")]

            # 1280 m / 4 samples = 320 m. Sample zero starts at the centered
            # world's minimum X / maximum Z edge; the final sample is one cell
            # short of the opposite world boundary, matching Width=samples*spacing.
            self.assertEqual(vertices[0], "v -640 0 640")
            self.assertEqual(vertices[-1], "v 320 0 -320")

    def test_obj_import_uses_xz_grid_not_vertex_order(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            heights = np.arange(16, dtype=np.uint16).reshape((4, 4)) * 17
            original = os.path.join(temp_dir, "original.obj")
            shuffled = os.path.join(temp_dir, "shuffled.obj")
            write_heightfield_obj(original, heights, zones_x=1, zones_z=1, zone_bits=2)

            with open(original, "r", encoding="utf-8") as stream:
                lines = stream.readlines()
            vertices = [line for line in lines if line.startswith("v ")]
            other = [line for line in lines if not line.startswith("v ")]
            random.Random(7).shuffle(vertices)
            with open(shuffled, "w", encoding="utf-8", newline="\n") as stream:
                stream.writelines(other[:10])
                stream.writelines(vertices)
                stream.writelines(other[10:])

            mesh = read_terrain_obj(shuffled)
            self.assertTrue(np.array_equal(mesh.heights, heights))

    def test_obj_import_accepts_tab_separated_vertices(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            heights = np.arange(16, dtype=np.uint16).reshape((4, 4)) * 5
            obj_path = os.path.join(temp_dir, "terrain.obj")
            write_heightfield_obj(obj_path, heights, zones_x=1, zones_z=1, zone_bits=2)
            with open(obj_path, "r", encoding="utf-8") as stream:
                text = stream.read()
            text = text.replace("v ", "v\t")
            with open(obj_path, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(text)
            mesh = read_terrain_obj(obj_path)
            self.assertTrue(np.array_equal(mesh.heights, heights))

    def test_obj_import_rejects_non_regular_xz_grid(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            heights = np.arange(16, dtype=np.uint16).reshape((4, 4))
            obj_path = os.path.join(temp_dir, "broken.obj")
            write_heightfield_obj(obj_path, heights, zones_x=1, zones_z=1, zone_bits=2)

            with open(obj_path, "r", encoding="utf-8") as stream:
                text = stream.read()
            text = text.replace("v -640 0 640", "v -639 0 640", 1)
            with open(obj_path, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(text)

            with self.assertRaisesRegex(ValueError, "rectangular grid|regular X/Z|regular terrain grid"):
                read_terrain_obj(obj_path)

    def test_metadata_geometry_resolves_for_hg2_export(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            heights = np.zeros((8, 12), dtype=np.uint16)
            obj_path = os.path.join(temp_dir, "terrain.obj")
            write_heightfield_obj(obj_path, heights, zones_x=3, zones_z=2, zone_bits=2)
            mesh = read_terrain_obj(obj_path)
            self.assertEqual(resolve_hg2_geometry(mesh), (3, 2, 2))

    def test_obj_heights_can_be_written_back_to_hg2(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            heights = np.arange(16, dtype=np.uint16).reshape((4, 4)) * 10
            obj_path = os.path.join(temp_dir, "terrain.obj")
            hg2_path = os.path.join(temp_dir, "terrain.hg2")
            write_heightfield_obj(obj_path, heights, zones_x=1, zones_z=1, zone_bits=2)
            mesh = read_terrain_obj(obj_path)
            zones_x, zones_z, zone_bits = resolve_hg2_geometry(mesh)
            write_hg2(
                hg2_path,
                mesh.heights,
                zones_x=zones_x,
                zones_z=zones_z,
                zone_bits=zone_bits,
            )
            header, restored = read_hg2(hg2_path)
            self.assertEqual((header.zones_x, header.zones_z, header.zone_bits), (1, 1, 2))
            self.assertTrue(np.array_equal(restored, heights))

    def test_obj_y_edits_quantize_to_tenth_meter_hg2_units(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            heights = np.zeros((4, 4), dtype=np.uint16)
            obj_path = os.path.join(temp_dir, "terrain.obj")
            write_heightfield_obj(obj_path, heights, zones_x=1, zones_z=1, zone_bits=2)
            with open(obj_path, "r", encoding="utf-8") as stream:
                text = stream.read()
            text = text.replace("v -640 0 640", "v -640 12.34 640", 1)
            with open(obj_path, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(text)

            mesh = read_terrain_obj(obj_path)
            self.assertEqual(int(mesh.heights[0, 0]), 123)

    def test_obj_metadata_rejects_unknown_height_scale(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            heights = np.zeros((4, 4), dtype=np.uint16)
            obj_path = os.path.join(temp_dir, "terrain.obj")
            write_heightfield_obj(obj_path, heights, zones_x=1, zones_z=1, zone_bits=2)
            with open(obj_path, "r", encoding="utf-8") as stream:
                text = stream.read()
            text = text.replace("# bzr_height_units_per_meter=10", "# bzr_height_units_per_meter=5")
            with open(obj_path, "w", encoding="utf-8", newline="\n") as stream:
                stream.write(text)

            with self.assertRaisesRegex(ValueError, "height scale"):
                read_terrain_obj(obj_path)

    def test_metadata_free_obj_rejects_non_redux_horizontal_scale(self):
        mesh = TerrainOBJ(
            path="generic.obj",
            heights=np.zeros((256, 256), dtype=np.uint16),
            samples_x=256,
            samples_z=256,
            zones_x=None,
            zones_z=None,
            zone_bits=None,
            spacing=1.0,
            used_metadata=False,
        )
        with self.assertRaisesRegex(ValueError, "requires 5 m/sample"):
            resolve_hg2_geometry(mesh)


if __name__ == "__main__":
    unittest.main()
