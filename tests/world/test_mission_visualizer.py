import struct
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from bztoolbox.modules.world.hg2_codec import HG2Header
from bztoolbox.modules.world.mission_visualizer import (
    extract_terrain_name,
    hg2_north_up,
    hg2_world_size,
    is_binary_bzn,
    parse_binary_bzn_overlay,
    parse_mission_bzn,
    resolve_companion_hg2,
    resolve_mission_trn,
    world_to_canvas,
)


def _bzn_token(field_type, payload, *, high_byte=0):
    raw_type = ((high_byte & 0xFF) << 8) | (field_type & 0xFF)
    return struct.pack("<HH", raw_type, len(payload)) + payload


def _binary_bzn_fixture(*, object_count=1):
    prefix = (
        b"version [1] =\r\n"
        b"2016\r\n"
        b"binarySave [1] =\r\n"
        b"1\r\n"
    )
    data = bytearray(prefix)
    data += _bzn_token(2, b"testmis\x00" + b"\x00" * 8)
    data += _bzn_token(4, struct.pack("<i", 2))
    data += _bzn_token(1, b"\x01")
    # Non-zero upper type byte matches a known BZ1 quirk documented by BZNTools.
    data += _bzn_token(2, b"MARS.TRN\x00" + b"\x00" * 91, high_byte=0xA7)
    data += _bzn_token(4, struct.pack("<i", object_count))

    if object_count:
        # BZNTools documents binary ID fields as an 8-byte payload and BZ1
        # GameObject labels as a 40-byte CHAR buffer.
        data += _bzn_token(7, b"avrecy\x00\x00")
        data += _bzn_token(3, struct.pack("<H", 17))
        data += _bzn_token(9, struct.pack("<fff", 640.0, 12.5, 960.0))
        data += _bzn_token(4, struct.pack("<I", 1))
        data += _bzn_token(2, b"Recycler\x00" + b"\x00" * 31)
        data += _bzn_token(4, struct.pack("<I", 0))
        data += _bzn_token(8, struct.pack("<I", 0x12345678))
        data += _bzn_token(11, struct.pack("<12f", *([0.0] * 12)))

        # Class-specific payload: Mission Visualizer must safely skip this
        # without knowing the object's ClassLabel-specific serialization.
        data += _bzn_token(5, struct.pack("<f", 42.0))
        data += _bzn_token(2, b"class-specific\x00")

    # Tail contains one AI path using the exact BZ1/2016 schema:
    # count, old_ptr, sized label, pointCount, points, pathType.
    data += _bzn_token(4, struct.pack("<i", 1))
    data += _bzn_token(8, struct.pack("<I", 0xDEADBEEF))
    data += _bzn_token(4, struct.pack("<I", 5))
    data += _bzn_token(2, b"route")
    data += _bzn_token(4, struct.pack("<i", 2))
    data += _bzn_token(10, struct.pack("<ffff", 100.0, 200.0, 300.0, 400.0))
    data += _bzn_token(0, struct.pack("<I", 2))
    return bytes(data)


class MissionVisualizerTests(unittest.TestCase):
    def test_hg2_world_size_uses_zone_dimensions(self):
        header = HG2Header(1, 8, 4, 3, 10)
        self.assertEqual(hg2_world_size(header), (5120.0, 3840.0))

    def test_hg2_display_is_north_up(self):
        heights = np.array([[1, 2], [3, 4]], dtype=np.uint16)
        display = hg2_north_up(heights)
        self.assertTrue(np.array_equal(display, np.array([[3, 4], [1, 2]], dtype=np.uint16)))

    def test_world_to_canvas_uses_independent_axes_and_flips_z(self):
        rect = (10.0, 20.0, 200.0, 100.0)
        self.assertEqual(
            world_to_canvas(
                100.0,
                200.0,
                min_x=100.0,
                min_z=200.0,
                world_width=2560.0,
                world_depth=1280.0,
                draw_rect=rect,
            ),
            (10.0, 120.0),
        )
        self.assertEqual(
            world_to_canvas(
                2660.0,
                1480.0,
                min_x=100.0,
                min_z=200.0,
                world_width=2560.0,
                world_depth=1280.0,
                draw_rect=rect,
            ),
            (210.0, 20.0),
        )

    def test_extract_terrain_name_from_ascii_bzn(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "mission.bzn"
            path.write_bytes(
                b"version [1] =\r\n2016\r\nTerrainName [1] =\r\nMARS.TRN\r\n"
            )
            self.assertEqual(extract_terrain_name(path), "MARS.TRN")
            self.assertFalse(is_binary_bzn(path))

    def test_extract_terrain_name_from_binary_bzn(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "mission.bzn"
            path.write_bytes(_binary_bzn_fixture())
            self.assertTrue(is_binary_bzn(path))
            self.assertEqual(extract_terrain_name(path), "MARS.TRN")

    def test_binary_overlay_extracts_objects_and_paths(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "mission.bzn"
            path.write_bytes(_binary_bzn_fixture())

            objects, paths = parse_binary_bzn_overlay(path)

            self.assertEqual(len(objects), 1)
            self.assertEqual(objects[0]["odf"], "avrecy")
            self.assertEqual(objects[0]["label"], "Recycler")
            self.assertEqual(objects[0]["seqno"], 17)
            self.assertEqual(objects[0]["team"], 1)
            self.assertEqual(objects[0]["pos"], (640.0, 12.5, 960.0))

            self.assertEqual(len(paths), 1)
            self.assertEqual(paths[0]["label"], "route")
            self.assertEqual(paths[0]["type"], 2)
            self.assertEqual(paths[0]["points"], [(100.0, 200.0), (300.0, 400.0)])

    def test_binary_object_count_mismatch_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "mission.bzn"
            path.write_bytes(_binary_bzn_fixture(object_count=2))
            with self.assertRaisesRegex(ValueError, "header says 2"):
                parse_binary_bzn_overlay(path)

    def test_dispatch_preserves_existing_ascii_parser(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "mission.bzn"
            path.write_bytes(b"version [1] =\r\n2016\r\nbinarySave [1] =\r\n0\r\n")
            calls = []

            def ascii_parser(selected_path):
                calls.append(Path(selected_path))
                return ([{"ascii": True}], [])

            objects, paths = parse_mission_bzn(path, ascii_parser)
            self.assertEqual(calls, [path])
            self.assertEqual(objects, [{"ascii": True}])
            self.assertEqual(paths, [])

    def test_binary_terrain_read_bridges_world_builder_core_parser(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "mission.bzn"
            path.write_bytes(_binary_bzn_fixture())

            class DummyBZNParser:
                @staticmethod
                def parse(_path):
                    raise AssertionError("binary mission reached the ASCII parser")

            previous = sys.modules.get("bztoolbox.modules.world.world_builder_core")
            sys.modules["bztoolbox.modules.world.world_builder_core"] = SimpleNamespace(BZNParser=DummyBZNParser)
            try:
                self.assertEqual(extract_terrain_name(path), "MARS.TRN")
                objects, paths = DummyBZNParser.parse(path)
                self.assertEqual(objects[0]["odf"], "avrecy")
                self.assertEqual(paths[0]["label"], "route")
            finally:
                if previous is None:
                    sys.modules.pop("world_builder_core", None)
                else:
                    sys.modules["bztoolbox.modules.world.world_builder_core"] = previous

    def test_resolve_trn_prefers_terrain_name_case_insensitively(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            bzn = root / "mission.bzn"
            bzn.write_text("", encoding="ascii")
            trn = root / "ActualTerrain.TrN"
            trn.write_text("[Size]\n", encoding="ascii")
            fallback = root / "mission.trn"
            fallback.write_text("[Size]\n", encoding="ascii")
            self.assertEqual(
                resolve_mission_trn(bzn, "actualterrain.trn"),
                trn,
            )

    def test_companion_hg2_resolution_is_case_insensitive(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            trn = root / "terrain.trn"
            trn.write_text("", encoding="ascii")
            hg2 = root / "Terrain.HG2"
            hg2.write_bytes(b"")
            self.assertEqual(resolve_companion_hg2(trn), hg2)


if __name__ == "__main__":
    unittest.main()
