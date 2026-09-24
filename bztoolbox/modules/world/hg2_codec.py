"""HG2 codec; the implementation is :mod:`battlezone.terrain.hg2`."""

from battlezone.terrain.hg2 import *  # noqa: F401,F403
from battlezone.terrain.hg2 import (  # noqa: F401  (explicit names used by callers/tests)
    DEFAULT_ZONE_BITS, HG2_HEADER, HG2_MAP_VERSION, HG2_SAFE_MAX_HEIGHT, HG2_STORAGE_MASK,
    HG2_STORAGE_MAX_HEIGHT, HG2_STRUCTURE_VERSION, HG2Header, hg2_to_png16_array, png16_to_hg2_array,
    read_hg2, read_hg2_header, write_hg2,
)
