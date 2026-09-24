import json
import struct
import tempfile
import unittest
from pathlib import Path

import numpy as np

from bztoolbox.modules.world.bz2_ter_codec import SourceTerrain, decode_ter
from bztoolbox.modules.world.bz2_terrain_port import convert_ter_height, geometry_for, resample_hg2
from bztoolbox.modules.world.hg2_codec import read_hg2
from bztoolbox.modules.world.mat_codec import read_mat


def fixture(version=5, flags=0, minimum_x=0, minimum_z=0, height=12.5, info=0x654321):
    cluster = 4 if version == 3 else 16
    out = bytearray(b"TERR" + struct.pack("<Ihhhh", version, minimum_x, minimum_z,
                                          minimum_x + cluster, minimum_z + cluster))
    count = cluster * cluster
    if version == 5:
        out.append(flags)
    raw_height = int(height * 10) if version == 3 else height
    expanded = version != 5 or flags & 1
    out += struct.pack("<" + ("h" if version == 3 else "f") * (count if expanded else 1),
                       *([raw_height] * (count if expanded else 1)))
    if version == 3:
        out += bytes(count)
    out += bytes((10, 20, 30)) * (count if version != 5 or flags & 2 else 1)
    for index in range(3):
        out += bytes([index + 1]) * (count if version != 5 or flags & (1 << (2 + index)) else 1)
    out += bytes([0x02]) * (count if version != 5 or flags & 32 else 1)
    out += struct.pack("<I", info)
    return bytes(out)


class BZ2TerrainPortTests(unittest.TestCase):
    def test_geometry_can_rehome_source_into_existing_mission_world(self):
        source = SourceTerrain(
            version=5, grid_min_x=-1024, grid_min_z=-1024,
            grid_max_x=1024, grid_max_z=1024,
            heights_m=np.zeros((2048, 2048), dtype=np.float32),
            colors=np.zeros((2048, 2048, 3), dtype=np.uint8),
            alphas=np.zeros((3, 2048, 2048), dtype=np.uint8),
            cells=np.zeros((1024, 1024), dtype=np.uint8),
            info=np.zeros((1024, 1024), dtype=np.uint32),
        )
        geometry = geometry_for(source, target_min_x=0, target_min_z=97280)
        self.assertEqual((geometry.min_x, geometry.min_z), (0, 97280))
        self.assertEqual((geometry.width_m, geometry.depth_m), (5120, 5120))
        # Objects move with the source raster: centred BZCC -2048 lands 512 m
        # inside the padded zone that now starts at the target origin.
        self.assertEqual(geometry.object_offset_m, (2560, 0.0, 99840))

    def test_decode_v3_and_v4(self):
        for version in (3, 4):
            with self.subTest(version=version):
                terrain = decode_ter(fixture(version))
                self.assertEqual(terrain.heights_m.shape, (4, 4) if version == 3 else (16, 16))
                self.assertAlmostEqual(float(terrain.heights_m[0, 0]), 12.5)
                self.assertEqual(terrain.colors[0, 0].tolist(), [10, 20, 30])
                self.assertEqual(terrain.alphas[:, 0, 0].tolist(), [1, 2, 3])
                self.assertEqual(terrain.texture_indices[:, 0, 0].tolist(), [1, 2, 3, 4])

    def test_info_word_metadata_decoding(self):
        info = (2 << 24) | (7 << 20) | (0xA << 16) | 0x4321
        terrain = decode_ter(fixture(info=info))
        self.assertEqual(terrain.texture_indices[:, 0, 0].tolist(), [1, 2, 3, 4])
        self.assertEqual(int(terrain.visibility_mask[0, 0]), 0xA)
        self.assertEqual(int(terrain.owner_team[0, 0]), 7)
        self.assertEqual(int(terrain.build_type[0, 0]), 2)

    def test_v5_each_compression_bit_is_independent(self):
        for flags in (0, 0x3F, 0b001001, 0b010100):
            with self.subTest(flags=flags):
                terrain = decode_ter(fixture(5, flags))
                self.assertEqual(terrain.alphas[:, -1, -1].tolist(), [1, 2, 3])
                self.assertEqual(int(terrain.cells[-1, -1]), 2)

    def test_truncation_unknown_flags_and_trailing_data(self):
        raw = fixture()
        with self.assertRaisesRegex(ValueError, "Truncated"):
            decode_ter(raw[:-1])
        with self.assertRaisesRegex(ValueError, "trailing"):
            decode_ter(raw + b"X")
        with self.assertRaisesRegex(ValueError, "compression flags"):
            decode_ter(fixture(flags=0x40))

    def test_world_origin_padding_and_vertical_offset(self):
        src = decode_ter(fixture(5, minimum_x=-16, minimum_z=16, height=-2.5))
        geo = geometry_for(src)
        self.assertEqual((geo.min_x, geo.min_z), (-1280, 0))
        self.assertEqual((geo.zones_x, geo.zones_z), (1, 1))
        self.assertEqual(geo.vertical_offset_m, 2.5)
        self.assertTrue(np.all(resample_hg2(src, geo) == 0))

    def test_rehoming_preserves_authored_inset_inside_padded_zone(self):
        src = decode_ter(fixture(5, minimum_x=5, minimum_z=7))
        src.heights_m[0, 0] = 10
        src.heights_m[0, 1] = 20
        natural = geometry_for(src)
        rehomed = geometry_for(src, target_min_x=2560, target_min_z=97280)

        self.assertEqual(rehomed.source_target_min_x - rehomed.min_x,
                         natural.source_min_x - natural.min_x)
        self.assertEqual(rehomed.source_target_min_z - rehomed.min_z,
                         natural.source_min_z - natural.min_z)
        np.testing.assert_array_equal(resample_hg2(src, rehomed), resample_hg2(src, natural))

    def test_height_resampling_preserves_meter_scale_without_normalizing(self):
        src = decode_ter(fixture(5))
        src.heights_m[0, 0] = 10
        src.heights_m[0, 1] = 20
        src.heights_m[1, 0] = 30
        src.heights_m[1, 1] = 40
        geo = geometry_for(src)
        out = resample_hg2(src, geo)
        self.assertEqual(int(out[0, 0]), 100)
        # 5 m from the first source sample is 2.5 BZCC samples away.
        self.assertEqual(int(out[0, 1]), 125)
        self.assertEqual(geo.vertical_offset_m, 0)

    def test_unsafe_vertical_span_fails_instead_of_scaling(self):
        src = decode_ter(fixture(5))
        src.heights_m[0, 0] = -3
        src.heights_m[0, 1] = 410
        with self.assertRaisesRegex(ValueError, "cannot fit"):
            geometry_for(src)

    def test_valid_hg2_and_no_existing_output_replacement(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            ter = root / "test.ter"
            ter.write_bytes(fixture(5, flags=0x3F))
            result = convert_ter_height(ter, root / "port", "BZ2TEST")
            header, heights = read_hg2(root / "port" / "BZ2TEST.hg2")
            self.assertEqual((header.zones_x, header.zones_z), (1, 1))
            self.assertEqual(heights.shape, (256, 256))
            self.assertTrue(np.all(heights == 125))
            self.assertEqual(result["status"], "height_and_source_channels_only_not_a_launchable_map")
            self.assertEqual(result["mat_reduction"]["cell_size_m"], 20)
            self.assertEqual(result["mat_reduction"]["shape"], [64, 64])
            self.assertTrue((root / "port" / "BZ2TEST_mat_reduction.npz").is_file())
            self.assertTrue((root / "port" / "BZ2TEST_reduced.MAT").is_file())
            encoded = read_mat(root / "port" / "BZ2TEST_reduced.MAT", 1, 1)
            self.assertEqual(encoded.shape, (64, 64))
            self.assertEqual(result["used_texture_slots"], [1, 2, 3, 4])
            self.assertEqual(result["unresolved_texture_slots"], [1, 2, 3, 4])
            self.assertTrue(result["texture_blend_model"].startswith("sequential:"))
            manifest = json.loads((root / "port" / "BZ2TEST_source_manifest.json").read_text())
            self.assertEqual(len(manifest["slots"]), 16)
            self.assertEqual([slot["slot"] for slot in manifest["slots"]], list(range(16)))
            self.assertEqual(manifest["unresolved_used_slots"], [1, 2, 3, 4])
            self.assertFalse(manifest["ready_for_atlas"])
            for slot in (1, 2, 3, 4):
                self.assertEqual(manifest["slots"][slot]["redux_material"], slot)
                self.assertEqual(manifest["slots"][slot]["status"], "unresolved")
            self.assertEqual(manifest["slots"][0]["status"], "unused")
            self.assertEqual(result["cluster_info"]["visibility_masks"], [5])
            self.assertEqual(result["cluster_info"]["owner_teams"], [6])
            self.assertEqual(result["cluster_info"]["build_types"], [0])
            with np.load(root / "port" / "BZ2TEST_ter_channels.npz") as preserved:
                self.assertEqual(preserved["texture_indices"][:, 0, 0].tolist(), [1, 2, 3, 4])
                self.assertEqual(int(preserved["visibility_mask"][0, 0]), 5)
                self.assertEqual(int(preserved["owner_team"][0, 0]), 6)
                self.assertEqual(int(preserved["build_type"][0, 0]), 0)
            with np.load(root / "port" / "BZ2TEST_mat_reduction.npz") as reduced:
                self.assertEqual(reduced["weights"].shape, (16, 64, 64))
                self.assertEqual(reduced["primary_material"].dtype, np.uint8)
                self.assertEqual(reduced["secondary_material"].dtype, np.uint8)
                self.assertEqual(reduced["corner_materials"].shape, (4, 64, 64))
            self.assertEqual(result["mat_reduction"]["encoded_mat"], "BZ2TEST_reduced.MAT")
            self.assertIn("ambiguous_cells", result["mat_reduction"])
            with self.assertRaises(FileExistsError):
                convert_ter_height(ter, root / "port", "BZ2TEST")


if __name__ == "__main__":
    unittest.main()
