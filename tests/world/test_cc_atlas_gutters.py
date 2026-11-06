import struct
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from tests.world.test_atlas_name_contract import script


class AtlasGutterTests(unittest.TestCase):
    def test_compressed_mips_keep_neighbor_colors_out_of_uv_edges(self):
        builder = script('build2')
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            Image.new('RGB', (128, 128), (255, 0, 0)).save(root/'red.png')
            Image.new('RGB', (128, 128), (0, 0, 255)).save(root/'blue.png')
            cfg = dict(prefix='TEST', tile='tg', world='test', root=str(root),
                       types={0:'red.png', 1:'blue.png'}, blend=[0,1], pool=[],
                       gutter_px=16, mip_floor_px=32)
            out = root/'built'
            report = builder.build('test_gutter', cfg, str(out), [], tile_px=128, quiet=True)
            self.assertEqual(report['atlas_D']['mips'], 3)
            row = (out/'test_gutter.csv').read_text().splitlines()[1].split(',')
            u,v,du,dv = map(float, row[1:])
            data = (out/'TEST_ATLAS_D.dds').read_bytes()
            height,width = struct.unpack_from('<II', data, 12)
            offset = 128
            for level in range(3):
                w,h = width>>level,height>>level
                size = w*h//2
                pixels = builder.bc1.decode_bc1(data[offset:offset+size], w,h)
                offset += size
                # Bilinear filtering at a UV edge samples the pixels on both
                # sides of it. Every one must belong to red, including corners.
                for xuv in (u,u+du):
                    for yuv in (v,v+dv):
                        x,y = int(np.floor(xuv*w-.5)),int(np.floor(yuv*h-.5))
                        footprint = pixels[y:y+2,x:x+2]
                        self.assertTrue((footprint[...,0]>240).all())
                        self.assertTrue((footprint[...,2]<15).all())

    def test_rejects_gutter_that_disappears_in_last_mip(self):
        builder = script('build2')
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError, 'whole pixels'):
                builder.build('bad', dict(tile='tg', types={0:'red.png'}, blend=[0],
                                         gutter_px=3, mip_floor_px=4), folder, [], tile_px=128)
