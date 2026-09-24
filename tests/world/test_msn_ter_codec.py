import os
import struct
import tempfile
import unittest

import numpy as np

from bztoolbox.modules.world import msn_ter_codec


def chunk(tag: bytes, payload: bytes) -> bytes:
    return tag + struct.pack("<i", len(payload) + 8) + payload


class MSNTerrainCodecTests(unittest.TestCase):
    def make_fixture(self, folder, *, zone_count=3):
        zone_map = np.full((80, 80), 0xFF, dtype=np.uint8)
        zone_map[2, 4] = 0
        zone_map[3, 3] = 1
        zmap_payload = bytes([zone_count]) + zone_map.tobytes()
        msn = chunk(b"JUNK", b"") + chunk(b"TDEF", chunk(b"ZMAP", zmap_payload))

        msn_path = os.path.join(folder, "sample.MSN")
        ter_path = os.path.join(folder, "sample.TER")
        with open(msn_path, "wb") as stream:
            stream.write(msn)

        zones = []
        for value in (0xF123, 0x0456, 0x0789):
            zones.append(
                np.full(
                    msn_ter_codec.TER_ZONE_SIDE * msn_ter_codec.TER_ZONE_SIDE,
                    value,
                    dtype="<u2",
                ).tobytes()
            )
        with open(ter_path, "wb") as stream:
            stream.write(b"".join(zones[:zone_count]))
        return msn_path, ter_path

    def test_extracts_tdef_zmap(self):
        zone_map = np.full((80, 80), 0xFF, dtype=np.uint8)
        zone_map[7, 9] = 0
        payload = bytes([1]) + zone_map.tobytes()
        msn = chunk(b"HEAD", b"abc") + chunk(b"TDEF", chunk(b"ZMAP", payload))
        count, parsed = msn_ter_codec.extract_zmap(msn)
        self.assertEqual(count, 1)
        self.assertEqual(int(parsed[7, 9]), 0)
        self.assertEqual(int(parsed[0, 0]), 0xFF)

    def test_import_crops_zmap_preserves_origin_and_masks_12_bits(self):
        with tempfile.TemporaryDirectory() as folder:
            msn_path, _ = self.make_fixture(folder)
            terrain = msn_ter_codec.read_msn_ter(msn_path)

        self.assertEqual((terrain.zones_x, terrain.zones_z), (2, 2))
        self.assertEqual((terrain.min_x_meters, terrain.min_z_meters), (3 * 1280, 2 * 1280))
        self.assertEqual(terrain.heights.shape, (512, 512))
        self.assertEqual(terrain.missing_zone_ids, (2,))

        # Zone 0 is top-right of the cropped 2x2 rectangle and is masked to 0x123.
        self.assertTrue(np.all(terrain.heights[:256, 256:] == 0x0123))
        # Zone 1 is bottom-left and remains 0x456.
        self.assertTrue(np.all(terrain.heights[256:, :256] == 0x0456))
        # Unassigned ZMAP cells retain the zero-initialized output used by MakeTRN.
        self.assertTrue(np.all(terrain.heights[:256, :256] == 0))
        self.assertTrue(np.all(terrain.heights[256:, 256:] == 0))

    def test_truncated_ter_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            msn_path, ter_path = self.make_fixture(folder, zone_count=1)
            with open(ter_path, "wb") as stream:
                stream.write(b"\x00" * 8)
            with self.assertRaisesRegex(ValueError, "TER is truncated"):
                msn_ter_codec.read_msn_ter(msn_path, ter_path)


if __name__ == "__main__":
    unittest.main()
