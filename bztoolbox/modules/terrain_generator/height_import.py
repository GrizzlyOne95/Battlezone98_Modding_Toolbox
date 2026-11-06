"""Load an existing heightmap (HG2 or image) so the generator can preview and export it.

Image conventions match World Builder and the generator's own exports:

* 16-bit greyscale PNG: lossless, value = HG2 height x 8.
* Anything else (8-bit PNG, JPEG, BMP...): converted to greyscale, one grey
  level = 1 m, so black is 0 m and white is 255 m.

An image whose sides are multiples of 256 keeps its size (one zone per 256
pixels). Any other image is resized to the zones chosen in the UI.
"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
from PIL import Image

from .hg2 import DEFAULT_ZONE_BITS, HG2_STORAGE_MAX_HEIGHT, HG2Map

ZONE_SIZE = 1 << DEFAULT_ZONE_BITS
EIGHT_BIT_UNITS_PER_LEVEL = 10.0  # 1 grey level = 1 m = 10 HG2 units
SIXTEEN_BIT_MODES = {"I;16", "I;16L", "I;16B", "I"}


def _image_heights(img: Image.Image) -> np.ndarray:
    if img.mode in SIXTEEN_BIT_MODES:
        return np.asarray(img, dtype=np.float64) / 8.0
    return np.asarray(img.convert("L"), dtype=np.float64) * EIGHT_BIT_UNITS_PER_LEVEL


def load_height_file(path: os.PathLike | str, zones_x: int, zones_z: int) -> HG2Map:
    """Return ``path`` as an HG2 map; images that are not whole zones become zones_x x zones_z."""
    path = Path(path)
    if path.suffix.lower() == ".hg2":
        return HG2Map.read(path)
    with Image.open(path) as img:
        img.load()
        heights = _image_heights(img)
    h, w = heights.shape
    if h % ZONE_SIZE == 0 and w % ZONE_SIZE == 0:
        zones_x, zones_z = w // ZONE_SIZE, h // ZONE_SIZE
    else:
        resized = Image.fromarray(heights.astype(np.float32), mode="F").resize(
            (zones_x * ZONE_SIZE, zones_z * ZONE_SIZE), Image.BILINEAR)
        heights = np.asarray(resized, dtype=np.float64)
    heights = np.clip(np.rint(heights), 0, HG2_STORAGE_MAX_HEIGHT).astype(np.uint16)
    return HG2Map(heights, zones_x, zones_z)
