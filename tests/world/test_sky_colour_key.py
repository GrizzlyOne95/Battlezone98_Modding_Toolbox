import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

import numpy as np
from PIL import Image

from bztoolbox.modules.world.world_builder_core import BZ98TRNArchitect

# Index 0 black, 1 grey, 255 the BZ colour key.
PALETTE = [(0, 0, 0), (128, 128, 128)] + [(10, 20, 30)] * 253 + [(255, 0, 255)]


def write_map(path, idx):
    h, w = idx.shape
    # Rows are stored bottom-up, as the converter reads them back with [::-1].
    path.write_bytes(struct.pack('<4H', w, 0, h, 0) + idx[::-1].astype(np.uint8).tobytes())


class SkyColourKeyTests(unittest.TestCase):
    """Clouds/stars keyed with palette 255 (magenta) came out opaque pink."""

    def convert(self, trn, maps):
        app = BZ98TRNArchitect.__new__(BZ98TRNArchitect)
        app.log = Mock()
        folder = Path(self.enterContext(tempfile.TemporaryDirectory()))
        src, out = folder / 'src', folder / 'out'
        src.mkdir(), out.mkdir()
        (src / 'test.trn').write_text(trn)
        for name, idx in maps.items():
            write_map(src / name, idx)
        app._convert_sky_textures(str(src), str(out), PALETTE, set())
        return out

    def test_magenta_cloud_pixels_become_transparent(self):
        idx = np.ones((16, 16), np.uint8)
        idx[4:12, 4:12] = 255          # an enclosed key patch, not border-connected
        idx[0, :] = 255                # and a border row
        out = self.convert('[Clouds]\nTexture0 = cloudz.map\n', {'cloudz.map': idx})
        a = np.asarray(Image.open(out / 'cloudz.png').convert('RGBA'))
        key = idx == 255
        self.assertTrue((a[..., 3][key] == 0).all())
        pink = (a[..., 0] > 230) & (a[..., 1] < 30) & (a[..., 2] > 230)
        self.assertFalse(pink.any(), 'key colour must be bled over, not left in RGB')

    def test_opaque_sky_has_no_magenta_left(self):
        idx = np.ones((16, 16), np.uint8)
        idx[2:14, 2:14] = 255
        out = self.convert('[Sky]\nSkyTexture = skyz.map\n', {'skyz.map': idx})
        rgb = np.asarray(Image.open(out / 'skyz.png').convert('RGB'))
        self.assertTrue((rgb == 128).all())


if __name__ == '__main__':
    unittest.main()
