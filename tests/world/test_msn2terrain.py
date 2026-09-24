import os
import struct
import tempfile
import unittest

import numpy as np

from bztoolbox.modules.world import msn2terrain
from bztoolbox.modules.world.hg2_codec import read_hg2
from bztoolbox.modules.world.mat_codec import expected_mat_bytes
from bztoolbox.modules.world.msn_ter_codec import TER_ZONE_SIDE


def chunk(tag: bytes, payload: bytes) -> bytes:
    return tag + struct.pack("<i", len(payload) + 8) + payload


class MSN2TerrainTests(unittest.TestCase):
    def test_end_to_end_msn_ter_builds_trn_hg2_mat(self):
        with tempfile.TemporaryDirectory() as folder:
            zone_map = np.full((80, 80), 0xFF, dtype=np.uint8)
            zone_map[1, 2] = 0
            msn_path = os.path.join(folder, "I76TEST.MSN")
            ter_path = os.path.join(folder, "I76TEST.TER")
            zmap = bytes([1]) + zone_map.tobytes()
            with open(msn_path, "wb") as stream:
                stream.write(chunk(b"TDEF", chunk(b"ZMAP", zmap)))
            source = np.full((TER_ZONE_SIDE, TER_ZONE_SIDE), 100, dtype="<u2")
            with open(ter_path, "wb") as stream:
                stream.write(source.tobytes())

            out = os.path.join(folder, "out")
            result, missing = msn2terrain.build_msn_map(
                msn_path,
                out,
                name="I76TST",
                seed=1,
                normal_view="[NormalView]\nTime=900\nFogStart=175",
                static_trn=(
                    "[TextureType0]\nSolidA0=MN00SA0.MAP\n"
                    "CapTo3_A0=MN03CA0.MAP\nDiagonalTo3_A0=MN03DA0.MAP\n\n"
                    "[TextureType3]\nSolidA0=MN33SA0.MAP"
                ),
            )

            self.assertEqual(missing, ())
            self.assertTrue(os.path.isfile(result.trn_path))
            self.assertTrue(os.path.isfile(result.hg2_path))
            self.assertTrue(os.path.isfile(result.mat_path))
            self.assertEqual(os.path.getsize(result.mat_path), expected_mat_bytes(1, 1))

            header, heights = read_hg2(result.hg2_path)
            self.assertEqual((header.zones_x, header.zones_z), (1, 1))
            self.assertTrue(np.all(heights == 100))

            with open(result.trn_path, "r", encoding="cp1252") as stream:
                trn = stream.read()
            self.assertIn("MinX=2560", trn)
            self.assertIn("MinZ=1280", trn)
            self.assertIn("Width=1280", trn)
            self.assertIn("Depth=1280", trn)

    def test_legacy_parameter_aliases_are_accepted(self):
        args = msn2terrain._legacy_args(["map.msn", "/p=layers.ini", "/e=42"])
        self.assertEqual(
            args,
            ["map.msn", "--params", "layers.ini", "--empty-elevation", "42"],
        )


if __name__ == "__main__":
    unittest.main()
