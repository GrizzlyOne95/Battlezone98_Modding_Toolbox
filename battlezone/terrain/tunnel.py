"""Cut-and-cover tunnels: carve a trench into an HG2 and darken the LGT under its roof.

A heightfield cannot overhang, so a tunnel is a trench with a roof building
over it (see docs/world/TUNNELS.md for the whole recipe).

Coordinates are metres, x east and z north. **Map-relative** coordinates start
at the map's south-west corner: HG2 sample (row r, column c) sits at
``x = c * spacing, z = r * spacing`` with ``spacing = 1280 / zone_size``
(5 m for Redux's 256 samples per zone). **World** coordinates, as in a BZN or
the editor, are map-relative plus the TRN ``[Size]`` ``MinX``/``MinZ``; pass
that as ``origin=(min_x, min_z)``. LGT cells follow the same south-first grid;
cell i covers ``cell_size`` metres and is centred on ``(i + 0.5) * cell_size -
spacing / 2`` (a 256-per-zone cell sits on vertex i, as in
:func:`battlezone.terrain.lgt.lambert_shading`).

HG2 heights are in 0.1 m units. Carving only ever lowers samples.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence, Tuple

import numpy as np

from battlezone.terrain.hg2 import BZ_ZONE_WORLD_SIZE, HG2Map

__all__ = ["TrenchResult", "carve_trench", "shade_polygon", "shade_rect", "shade_path", "path_distance",
           "trench_cells", "HEIGHT_UNIT", "RAMP_ENDS", "DEFAULT_SHADE", "DEFAULT_WALL_SLOPE"]

HEIGHT_UNIT = 0.1                 # metres per HG2 height step
RAMP_ENDS = ("both", "start", "end", "none")
DEFAULT_SHADE = 64                # LGT value under a roof; Redux's own bake never goes below 56
DEFAULT_WALL_SLOPE = 2.0          # metres of depth per metre across (about 63 degrees)

Point = Tuple[float, float]


@dataclass
class TrenchResult:
    carved: np.ndarray            # bool, heights shape: samples that were lowered
    samples: int                  # how many
    deepest_m: float              # largest cut
    floor_min_m: float            # lowest floor height along the path
    floor_max_m: float
    length_m: float               # path length
    clipped: int                  # samples that would have gone below height 0
    bounds: Tuple[int, int, int, int]   # rows r0:r1, columns c0:c1 of the work area


def _points(path: Sequence[Point], origin: Point) -> np.ndarray:
    pts = np.asarray(path, dtype=np.float64).reshape(-1, 2) - np.asarray(origin, dtype=np.float64)
    if len(pts) < 2:
        raise ValueError("a trench path needs at least two points")
    keep = np.r_[True, np.any(np.diff(pts, axis=0) != 0, axis=1)]
    pts = pts[keep]
    if len(pts) < 2:
        raise ValueError("the path points are all the same")
    return pts


def path_distance(xs: np.ndarray, zs: np.ndarray, pts: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    """Distance from each (x, z) to the polyline and the arc length of the nearest point on it."""
    best = np.full(np.broadcast(xs, zs).shape, np.inf)
    along = np.zeros_like(best)
    start = 0.0
    for (ax, az), (bx, bz) in zip(pts[:-1], pts[1:]):
        dx, dz = bx - ax, bz - az
        length = float(np.hypot(dx, dz))
        t = np.clip(((xs - ax) * dx + (zs - az) * dz) / (length * length), 0.0, 1.0)
        d = np.hypot(xs - (ax + t * dx), zs - (az + t * dz))
        closer = d < best
        best = np.where(closer, d, best)
        along = np.where(closer, start + t * length, along)
        start += length
    return best, along


def _bilinear(heights: np.ndarray, x: np.ndarray, z: np.ndarray, spacing: float) -> np.ndarray:
    rows, cols = heights.shape
    fx = np.clip(x / spacing, 0, cols - 1)
    fz = np.clip(z / spacing, 0, rows - 1)
    c0 = np.minimum(np.floor(fx).astype(int), cols - 2 if cols > 1 else 0)
    r0 = np.minimum(np.floor(fz).astype(int), rows - 2 if rows > 1 else 0)
    c1, r1 = np.minimum(c0 + 1, cols - 1), np.minimum(r0 + 1, rows - 1)
    tx, tz = fx - c0, fz - r0
    top = heights[r0, c0] * (1 - tx) + heights[r0, c1] * tx
    bottom = heights[r1, c0] * (1 - tx) + heights[r1, c1] * tx
    return top * (1 - tz) + bottom * tz


def _ramp_factor(s: np.ndarray, length: float, ramp: float, ends: str) -> np.ndarray:
    """0 at a ramped end, 1 once a ramp length in."""
    out = np.ones_like(s)
    if ramp <= 0 or ends == "none":
        return out
    if ends in ("both", "start"):
        out = np.minimum(out, s / ramp)
    if ends in ("both", "end"):
        out = np.minimum(out, (length - s) / ramp)
    return np.clip(out, 0.0, 1.0)


def carve_trench(hg2: HG2Map, path: Sequence[Point], width_m: float, *, depth_m: Optional[float] = None,
                 floor_height_m: Optional[float] = None, ramp_length_m: float = 0.0, ramps: str = "both",
                 wall_slope: Optional[float] = DEFAULT_WALL_SLOPE, origin: Point = (0.0, 0.0)) -> TrenchResult:
    """Lower ``hg2.heights`` into a trench along ``path`` (in place).

    The floor is ``width_m`` wide. With ``depth_m`` it follows the ground
    along the path (sampled on the centre line and averaged over one width) that
    far down; with ``floor_height_m`` it is level at that height. Ramps of
    ``ramp_length_m`` rise from the floor to the ground at the ``ramps`` ends
    (both, start, end or none); an end without a ramp is closed by a wall.
    Walls fall ``wall_slope`` metres per metre outward from the floor edge
    (None or 0: as steep as the grid allows). No sample is raised.
    """
    if (depth_m is None) == (floor_height_m is None):
        raise ValueError("give either depth_m or floor_height_m")
    if width_m <= 0:
        raise ValueError("the trench width must be positive")
    if depth_m is not None and depth_m <= 0:
        raise ValueError("the trench depth must be positive")
    if ramps not in RAMP_ENDS:
        raise ValueError(f"ramps must be one of {RAMP_ENDS}")
    hg2._validate_shape()
    pts = _points(path, origin)
    spacing = BZ_ZONE_WORLD_SIZE / hg2.zone_size
    original = hg2.heights.astype(np.float64) * HEIGHT_UNIT
    segment_lengths = np.hypot(*np.diff(pts, axis=0).T)
    length = float(segment_lengths.sum())
    half = width_m / 2.0

    # Floor profile along the path, one station per half sample.
    stations = np.linspace(0.0, length, max(2, int(np.ceil(length / (spacing / 2))) + 1))
    cumulative = np.r_[0.0, np.cumsum(segment_lengths)]
    sx = np.interp(stations, cumulative, pts[:, 0])
    sz = np.interp(stations, cumulative, pts[:, 1])
    ground = _bilinear(original, sx, sz, spacing)
    window = max(1, int(round(width_m / (spacing / 2))))
    if window > 1:
        padded = np.pad(ground, window // 2, mode="edge")
        ground = np.convolve(padded, np.ones(window) / window, mode="valid")[:len(stations)]
    base = ground - depth_m if depth_m is not None else np.full_like(ground, float(floor_height_m))
    floor = ground + _ramp_factor(stations, length, ramp_length_m, ramps) * (base - ground)

    # Work area: the path's bounds plus the widest the walls can reach.
    reach = half + spacing
    if wall_slope:
        reach += max(0.0, float(np.max(original) - floor.min())) / wall_slope
    rows, cols = hg2.shape
    c0 = max(0, int(np.floor((pts[:, 0].min() - reach) / spacing)))
    c1 = min(cols, int(np.ceil((pts[:, 0].max() + reach) / spacing)) + 1)
    r0 = max(0, int(np.floor((pts[:, 1].min() - reach) / spacing)))
    r1 = min(rows, int(np.ceil((pts[:, 1].max() + reach) / spacing)) + 1)
    carved = np.zeros(hg2.shape, dtype=bool)
    if r0 >= r1 or c0 >= c1:
        raise ValueError("the path is outside the map (check map-relative vs world coordinates)")

    zs, xs = np.mgrid[r0:r1, c0:c1].astype(np.float64) * spacing
    distance, along = path_distance(xs, zs, pts)
    target = np.interp(along, stations, floor)
    outside = distance - half
    if wall_slope:
        target = np.where(outside > 0, target + outside * wall_slope, target)
    else:
        target = np.where(outside > 0, np.inf, target)
    current = original[r0:r1, c0:c1]
    lowered = np.minimum(current, target)
    clipped = int(np.count_nonzero(lowered < 0))
    new_units = np.clip(np.floor(lowered / HEIGHT_UNIT + 1e-6), 0, None)
    region = hg2.heights[r0:r1, c0:c1]
    changed = new_units < region
    region[changed] = new_units[changed].astype(region.dtype)
    carved[r0:r1, c0:c1] = changed
    cut = (current - hg2.heights[r0:r1, c0:c1] * HEIGHT_UNIT)
    return TrenchResult(carved, int(np.count_nonzero(changed)), float(cut.max()) if cut.size else 0.0,
                        float(floor.min()), float(floor.max()), length, clipped, (r0, r1, c0, c1))


# --- light maps --------------------------------------------------------------------

def _cell_grid(shape, cell_size_m: float, vertex_spacing_m: float):
    """Map-relative centres of the LGT cell columns and rows."""
    rows, cols = shape
    offset = cell_size_m / 2 - vertex_spacing_m / 2
    return np.arange(cols) * cell_size_m + offset, np.arange(rows) * cell_size_m + offset


def _apply_shade(lightmap: np.ndarray, inside_distance: np.ndarray, rows: slice, cols: slice, value: int,
                 feather_m: float) -> np.ndarray:
    out = np.array(lightmap, dtype=np.uint8, copy=True)
    if feather_m > 0:
        weight = np.clip(0.5 + inside_distance / feather_m, 0.0, 1.0)
    else:
        weight = (inside_distance >= 0).astype(np.float64)
    region = out[rows, cols].astype(np.float64)
    shaded = region + weight * (float(value) - region)
    out[rows, cols] = np.rint(np.minimum(region, shaded)).astype(np.uint8)
    return out


def _window(xs, zs, lo_x, hi_x, lo_z, hi_z):
    c = np.nonzero((xs >= lo_x) & (xs <= hi_x))[0]
    r = np.nonzero((zs >= lo_z) & (zs <= hi_z))[0]
    if not len(c) or not len(r):
        return None
    return slice(r[0], r[-1] + 1), slice(c[0], c[-1] + 1)


def shade_polygon(lightmap: np.ndarray, polygon: Sequence[Point], *, cell_size_m: float = 5.0,
                  value: int = DEFAULT_SHADE, feather_m: float = 5.0, origin: Point = (0.0, 0.0),
                  vertex_spacing_m: float = 5.0) -> np.ndarray:
    """A copy of the south-first ``lightmap`` darkened to ``value`` inside ``polygon``.

    The edge is soft over ``feather_m`` (half outside, half inside). Cells
    already darker than the shade keep their value. ``cell_size_m`` is 5 for
    Redux LGTs (256 cells per zone), 10 for 1.5's (128).
    """
    if not 0 <= value <= 255:
        raise ValueError("the shade value must be 0..255")
    poly = np.asarray(polygon, dtype=np.float64).reshape(-1, 2) - np.asarray(origin, dtype=np.float64)
    if len(poly) < 3:
        raise ValueError("a polygon needs at least three points")
    xs, zs = _cell_grid(lightmap.shape, cell_size_m, vertex_spacing_m)
    margin = max(feather_m, 0.0) / 2 + cell_size_m
    window = _window(xs, zs, poly[:, 0].min() - margin, poly[:, 0].max() + margin,
                     poly[:, 1].min() - margin, poly[:, 1].max() + margin)
    if window is None:
        return np.array(lightmap, dtype=np.uint8, copy=True)
    rows, cols = window
    gx, gz = np.meshgrid(xs[cols], zs[rows])
    closed = np.vstack([poly, poly[:1]])
    distance, _along = path_distance(gx, gz, closed)
    inside = np.zeros(gx.shape, dtype=bool)
    for (ax, az), (bx, bz) in zip(closed[:-1], closed[1:]):     # even-odd rule
        crosses = (az > gz) != (bz > gz)
        with np.errstate(divide="ignore", invalid="ignore"):
            at = ax + (gz - az) * (bx - ax) / (bz - az)
        inside ^= crosses & (gx < at)
    return _apply_shade(lightmap, np.where(inside, distance, -distance), rows, cols, value, feather_m)


def shade_rect(lightmap: np.ndarray, x0: float, z0: float, x1: float, z1: float, **kwargs) -> np.ndarray:
    """:func:`shade_polygon` for an axis-aligned rectangle between two corners."""
    return shade_polygon(lightmap, [(x0, z0), (x1, z0), (x1, z1), (x0, z1)], **kwargs)


def shade_path(lightmap: np.ndarray, path: Sequence[Point], width_m: float, *, cell_size_m: float = 5.0,
               value: int = DEFAULT_SHADE, feather_m: float = 5.0, origin: Point = (0.0, 0.0),
               vertex_spacing_m: float = 5.0) -> np.ndarray:
    """:func:`shade_polygon` for a ``width_m`` band along a polyline (a roof that follows the trench)."""
    if not 0 <= value <= 255:
        raise ValueError("the shade value must be 0..255")
    pts = _points(path, origin)
    xs, zs = _cell_grid(lightmap.shape, cell_size_m, vertex_spacing_m)
    margin = width_m / 2 + max(feather_m, 0.0) / 2 + cell_size_m
    window = _window(xs, zs, pts[:, 0].min() - margin, pts[:, 0].max() + margin,
                     pts[:, 1].min() - margin, pts[:, 1].max() + margin)
    if window is None:
        return np.array(lightmap, dtype=np.uint8, copy=True)
    rows, cols = window
    gx, gz = np.meshgrid(xs[cols], zs[rows])
    distance, _along = path_distance(gx, gz, pts)
    return _apply_shade(lightmap, width_m / 2 - distance, rows, cols, value, feather_m)


def trench_cells(carved: np.ndarray, lgt_shape: Tuple[int, int]) -> np.ndarray:
    """The LGT cells over carved HG2 samples, grown by one cell (the walls' neighbours change shading too)."""
    rows, cols = lgt_shape
    factor_r, factor_c = carved.shape[0] // rows, carved.shape[1] // cols
    if factor_r < 1 or factor_c < 1 or carved.shape != (rows * factor_r, cols * factor_c):
        raise ValueError(f"LGT {lgt_shape} does not divide the heightmap {carved.shape}")
    cells = carved.reshape(rows, factor_r, cols, factor_c).any(axis=(1, 3))
    grown = cells.copy()
    grown[1:] |= cells[:-1]
    grown[:-1] |= cells[1:]
    grown[:, 1:] |= grown[:, :-1].copy()
    grown[:, :-1] |= grown[:, 1:].copy()
    return grown
