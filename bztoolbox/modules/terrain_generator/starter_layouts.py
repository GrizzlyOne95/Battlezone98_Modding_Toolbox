"""Simple starting layouts for a first map.

The recipe styles produce varied, detailed terrain. These layouts produce a
plain, predictable shape instead: flat ground, a round arena with plateaus,
or two raised bases. Heights are HG2 units (0.1 m), so ``plateau_height=300``
is a 30 m rise.
"""

from __future__ import annotations

import math
from typing import Callable, Dict, Tuple

import numpy as np

from .builder import TerrainBuilder
from .hg2 import HG2Map
from .noise import smoothstep01
from .settings import GeneratorSettings

FLOOR = 1000.0  # 100 m: room below for the vertical-scale slider

# The starter-only controls each layout uses; the GUI shows just these.
LAYOUT_CONTROLS: Dict[str, Tuple[str, ...]] = {
    "Flat Field": (),
    "Simple Arena": ("plateaus", "plateau_height"),
    "Two Bases": ("plateau_height",),
}


def _radius_grid(b: TerrainBuilder) -> np.ndarray:
    yy, xx = np.mgrid[0:b.h, 0:b.w].astype(np.float32)
    # Normalised so a non-square map still gets a round arena.
    return np.hypot((xx - (b.w - 1) / 2) / (b.w / 2), (yy - (b.h - 1) / 2) / (b.h / 2))


def flat_field(s: GeneratorSettings) -> HG2Map:
    """Level ground with very gentle rolls: a blank canvas."""
    b = TerrainBuilder(s).set_level(FLOOR)
    m = min(b.h, b.w)
    b.add_fbm(60.0 * s.detail, m * 0.30, octaves=3)
    return b.finalize(center_height=FLOOR, preserve_flats=True)


def simple_arena(s: GeneratorSettings) -> HG2Map:
    """A round, flat arena floor ringed by a wall, with plateaus on a ring."""
    b = TerrainBuilder(s).set_level(FLOOR)
    m = min(b.h, b.w)
    r = _radius_grid(b)
    # Wall: rises 40 m from 80% of the half-width, high ground beyond it.
    b.a += 400.0 * smoothstep01((r - 0.80) / 0.10)
    count = max(0, int(s.plateaus))
    if count:
        ring = 0.0 if count == 1 else m * 0.24
        size = m * 0.09 if count == 1 else min(m * 0.09, math.tau * ring / (2.8 * count))
        # Under symmetry, line the ring up with the mirror axis so finalize's
        # mirror maps whole plateaus onto plateaus instead of slicing them.
        symmetry = (s.symmetry or "None").lower()
        if symmetry == "mirror x":
            start = math.pi / 2
        elif symmetry in ("mirror z", "2-way rotational", "4-way"):
            start = 0.0
        else:
            start = float(b.rng.uniform(0.0, math.tau))
        for i in range(count):
            angle = start + i * math.tau / count
            cx = (b.w - 1) / 2 + math.cos(angle) * ring
            cy = (b.h - 1) / 2 + math.sin(angle) * ring
            b.flatten_pad(cx, cy, size, size, target=FLOOR + s.plateau_height, feather=m * 0.035)
    b.add_detail(8.0 * s.detail, m * 0.05)
    return b.finalize(center_height=FLOOR, preserve_flats=True)


def two_bases(s: GeneratorSettings) -> HG2Map:
    """Two raised base shelves at opposite ends of a lowland, with a centre hill."""
    b = TerrainBuilder(s).set_level(FLOOR)
    m = min(b.h, b.w)
    b.add_fbm(40.0 * s.detail, m * 0.25, octaves=3)
    shelf = FLOOR + s.plateau_height
    for cx in (b.w * 0.16, b.w * 0.84):
        b.flatten_pad(cx, b.h / 2, b.w * 0.10, b.h * 0.20, target=shelf, feather=m * 0.05, rectangular=True)
    b.flatten_pad(b.w / 2, b.h / 2, m * 0.07, m * 0.07, target=FLOOR + s.plateau_height * 0.6, feather=m * 0.06)
    b.add_detail(8.0 * s.detail, m * 0.05)
    return b.finalize(center_height=FLOOR, preserve_flats=True)


STARTER_LAYOUTS: Dict[str, Callable[[GeneratorSettings], HG2Map]] = {
    "Flat Field": flat_field,
    "Simple Arena": simple_arena,
    "Two Bases": two_bases,
}
