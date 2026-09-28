"""Carve a cut-and-cover tunnel trench into an HG2 and shade its LGT under the roof.

    bztoolbox terrain tunnel misn05.hg2 --path 600,1200 900,1200 --width 20 --depth 12 --ramp 60 \\
        --roof-shade 660,1188,840,1212
    bztoolbox terrain tunnel misn05.hg2 --trn misn05.trn --path -40,300 260,300 --width 20 --floor 40

Coordinates are map-relative metres (x east, z north from the map's south-west
corner) unless ``--trn`` or ``--origin`` is given; then they are world
coordinates and the TRN ``[Size]`` MinX/MinZ (or the origin) is subtracted.
The light map beside the HG2 (same name, ``.lgt``) is rebaked over the carved
area with Redux's stock lighting and then darkened under each ``--roof-shade``
rectangle (and along the whole path with ``--shade-path``). Without ``--out``
the originals are copied to a backup folder first. See docs/world/TUNNELS.md.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

import numpy as np

from battlezone.terrain.hg2 import BZ_ZONE_WORLD_SIZE, HG2Map
from battlezone.terrain.tunnel import (
    DEFAULT_SHADE, DEFAULT_WALL_SLOPE, HEIGHT_UNIT, RAMP_ENDS, TrenchResult, carve_trench, shade_path, shade_rect,
    trench_cells,
)

Point = Tuple[float, float]


@dataclass
class TunnelSpec:
    path: List[Point]
    width: float
    depth: Optional[float] = None
    floor: Optional[float] = None
    ramp: float = 0.0
    ramps: str = "both"
    wall_slope: Optional[float] = DEFAULT_WALL_SLOPE
    roof_rects: List[Tuple[float, float, float, float]] = field(default_factory=list)
    shade_path: bool = False
    shade: int = DEFAULT_SHADE
    feather: float = 5.0
    origin: Point = (0.0, 0.0)


@dataclass
class TunnelOutcome:
    hg2: HG2Map
    result: TrenchResult
    original: np.ndarray                  # heights before carving
    lightmap: Optional[np.ndarray] = None
    lgt_zones: Optional[Tuple[int, int]] = None
    lgt_source: Optional[Path] = None
    lgt_changed: bool = False
    written: List[str] = field(default_factory=list)
    backup: Optional[Path] = None
    notes: List[str] = field(default_factory=list)

    def lines(self) -> List[str]:
        r = self.result
        out = [f"carved {r.samples} height samples along {r.length_m:.0f} m; deepest cut {r.deepest_m:.1f} m, "
               f"floor {r.floor_min_m:.1f}..{r.floor_max_m:.1f} m"]
        if r.clipped:
            out.append(f"WARNING: {r.clipped} sample(s) would go below height 0 and were stopped there")
        out += self.notes
        out += [f"wrote {path}" for path in self.written]
        if self.backup:
            out.append(f"originals: {self.backup}")
        return out


def parse_point(text: str) -> Point:
    try:
        x, z = (float(part) for part in text.replace(";", ",").split(","))
    except ValueError as exc:
        raise ValueError(f"{text!r} is not a point like 600,1200") from exc
    return x, z


def parse_points(text: str) -> List[Point]:
    """``"600,1200 900,1200"`` -> [(600, 1200), (900, 1200)]."""
    return [parse_point(item) for item in text.split()]


def parse_rect(text: str) -> Tuple[float, float, float, float]:
    try:
        x0, z0, x1, z1 = (float(part) for part in text.split(","))
    except ValueError as exc:
        raise ValueError(f"{text!r} is not a rectangle like x0,z0,x1,z1") from exc
    return x0, z0, x1, z1


def trn_origin(trn_path) -> Point:
    from battlezone.terrain.trn import TRNDocument

    size = TRNDocument.read(trn_path).size
    return float(size.min_x or 0.0), float(size.min_z or 0.0)


def companion(path: Path, suffix: str) -> Optional[Path]:
    for candidate in path.parent.iterdir():
        if candidate.is_file() and candidate.suffix.lower() == suffix and candidate.stem.lower() == path.stem.lower():
            return candidate
    return None


def default_backup_dir() -> Path:
    try:
        from bztoolbox import paths

        base = paths.user_data_dir()
    except Exception:
        base = Path.home()
    return Path(base) / "tunnel-backups" / time.strftime("%Y%m%d-%H%M%S")


def apply_tunnel(hg2_path, spec: TunnelSpec, *, lgt_path=None, lgt: bool = True) -> TunnelOutcome:
    """Carve and shade in memory; nothing is written."""
    from battlezone.terrain.lgt import bake_redux_lgt, read_lgt

    hg2 = HG2Map.read(hg2_path)
    original_heights = hg2.heights.copy()
    result = carve_trench(hg2, spec.path, spec.width, depth_m=spec.depth, floor_height_m=spec.floor,
                          ramp_length_m=spec.ramp, ramps=spec.ramps, wall_slope=spec.wall_slope, origin=spec.origin)
    outcome = TunnelOutcome(hg2, result, original_heights)
    if result.samples == 0:
        outcome.notes.append("note: nothing was carved (the path may be outside the map, or the ground is already "
                             "lower than the trench)")
    source = Path(lgt_path) if lgt_path else companion(Path(hg2_path), ".lgt")
    if not lgt or source is None or not source.is_file():
        if lgt and (spec.roof_rects or spec.shade_path):
            outcome.notes.append("note: no light map beside the HG2, so the roof shading was not applied")
        return outcome
    original, zones_x, zones_z, cells = read_lgt(source, hg2.zones_x, hg2.zones_z)
    lightmap = original.copy()
    if result.samples:
        # The walls and floor need the terrain's own lighting before the roof darkens part of them.
        baked = bake_redux_lgt(hg2.heights, hg2.zones_x, hg2.zones_z, cells)
        region = trench_cells(result.carved, lightmap.shape)
        lightmap[region] = baked[region]
    cell_size = BZ_ZONE_WORLD_SIZE / cells
    spacing = BZ_ZONE_WORLD_SIZE / hg2.zone_size
    shading = dict(cell_size_m=cell_size, value=spec.shade, feather_m=spec.feather, origin=spec.origin,
                   vertex_spacing_m=spacing)
    for x0, z0, x1, z1 in spec.roof_rects:
        lightmap = shade_rect(lightmap, x0, z0, x1, z1, **shading)
    if spec.shade_path:
        lightmap = shade_path(lightmap, spec.path, spec.width, **shading)
    outcome.lightmap, outcome.lgt_zones, outcome.lgt_source = lightmap, (zones_x, zones_z), source
    outcome.lgt_changed = not np.array_equal(lightmap, original)
    outcome.notes.append(f"light map {source.name}: carved area rebaked"
                         + (f", {len(spec.roof_rects) + spec.shade_path} roof area(s) shaded to {spec.shade}"
                            if spec.roof_rects or spec.shade_path else ""))
    return outcome


def write_tunnel(hg2_path, outcome: TunnelOutcome, out=None, backup_dir=None) -> TunnelOutcome:
    """Write the carved HG2 (and LGT) to ``out`` or, backing the originals up first, over them."""
    from battlezone.terrain.lgt import REDUX_LGT_FLOOR, write_lgt

    hg2_path = Path(hg2_path)
    lgt_source = outcome.lgt_source
    if out:
        target = Path(out)
        if target.is_dir() or not target.suffix:
            target = target / hg2_path.name
        if target.resolve() == hg2_path.resolve():
            raise ValueError("--out is the source HG2; leave --out off to overwrite with a backup")
        target.parent.mkdir(parents=True, exist_ok=True)
    else:
        target = hg2_path
        outcome.backup = Path(backup_dir) if backup_dir else default_backup_dir()
        outcome.backup.mkdir(parents=True, exist_ok=True)
        for original in (hg2_path, lgt_source):
            if original is not None and original.is_file() and not (outcome.backup / original.name).exists():
                shutil.copy2(original, outcome.backup / original.name)
    if outcome.result.samples:
        outcome.hg2.write(target)
        outcome.written.append(str(target))
    if outcome.lightmap is not None and outcome.lgt_changed:
        lgt_target = target.with_suffix(".lgt") if out else lgt_source
        write_lgt(lgt_target, outcome.lightmap, *outcome.lgt_zones, border=REDUX_LGT_FLOOR)
        outcome.written.append(str(lgt_target))
    return outcome


def preview_image(heights: np.ndarray, carved: np.ndarray, original: Optional[np.ndarray] = None, bounds=None,
                  size: int = 512, zone_size: int = 256):
    """North-up hillshade around the carved samples (or ``bounds`` rows/columns), the cut tinted by its depth."""
    from PIL import Image

    rows, cols = heights.shape
    if bounds is None:
        found = np.argwhere(carved)
        if found.size:
            (r0, c0), (r1, c1) = found.min(axis=0), found.max(axis=0) + 1
        else:
            r0, r1, c0, c1 = 0, rows, 0, cols
    else:
        r0, r1, c0, c1 = bounds
    pad = max(8, (r1 - r0) // 2, (c1 - c0) // 2)
    r0, r1, c0, c1 = max(0, r0 - pad), min(rows, r1 + pad), max(0, c0 - pad), min(cols, c1 + pad)
    area = heights[r0:r1, c0:c1].astype(np.float64) * HEIGHT_UNIT
    spacing = BZ_ZONE_WORLD_SIZE / zone_size
    grad_z, grad_x = np.gradient(area, spacing) if min(area.shape) > 1 else (np.zeros_like(area),) * 2
    # Light from the north-west, 45 degrees up.
    light = np.array([-0.5, 0.7071, 0.5])
    shade = (-grad_x * light[0] + light[1] - grad_z * light[2]) / np.sqrt(grad_x ** 2 + grad_z ** 2 + 1)
    span = max(1e-6, float(area.max() - area.min()))
    tone = 0.35 + 0.35 * (area - area.min()) / span + 0.3 * np.clip(shade, 0, 1)
    grey = np.clip(tone * 255, 0, 255)
    rgb = np.stack([grey, grey, grey], axis=-1)
    if original is not None:
        cut = (original[r0:r1, c0:c1].astype(np.float64) - heights[r0:r1, c0:c1]) * HEIGHT_UNIT
        strength = np.clip(cut / 10.0, 0.0, 1.0)[..., None] * 0.6
    else:
        strength = carved[r0:r1, c0:c1][..., None] * 0.5
    rgb = rgb * (1 - strength) + np.array([40.0, 140.0, 255.0]) * strength
    image = Image.fromarray(np.flipud(rgb).astype(np.uint8), "RGB")          # south-first -> north-up
    scale = size / max(image.size)
    return image.resize((max(1, round(image.width * scale)), max(1, round(image.height * scale))),
                        Image.Resampling.NEAREST if scale >= 1 else Image.Resampling.LANCZOS)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bztoolbox terrain tunnel",
        description="Carve a cut-and-cover tunnel trench into an HG2 (ramps, sloped walls, never raising the "
                    "ground) and darken its light map under the roof. See docs/world/TUNNELS.md.")
    parser.add_argument("hg2", help="the map's .hg2")
    parser.add_argument("--path", nargs="+", required=True, metavar="X,Z", help="centre line points, in metres")
    parser.add_argument("--width", type=float, required=True, help="floor width in metres")
    how = parser.add_mutually_exclusive_group(required=True)
    how.add_argument("--depth", type=float, help="metres below the ground along the path")
    how.add_argument("--floor", type=float, help="a level floor at this height in metres")
    parser.add_argument("--ramp", type=float, default=0.0, help="ramp length in metres at the open ends (0: none)")
    parser.add_argument("--ramps", choices=RAMP_ENDS, default="both", help="which ends get a ramp (both)")
    parser.add_argument("--wall-slope", type=float, default=DEFAULT_WALL_SLOPE,
                        help=f"wall steepness, metres down per metre across ({DEFAULT_WALL_SLOPE:g}; 0: as steep as "
                             "the grid allows)")
    parser.add_argument("--roof-shade", nargs="+", default=[], metavar="X0,Z0,X1,Z1",
                        help="roof footprints (rectangles) to darken in the light map")
    parser.add_argument("--shade-path", action="store_true", help="darken the whole trench floor width along the path")
    parser.add_argument("--shade", type=int, default=DEFAULT_SHADE,
                        help=f"LGT value under the roof, 0..255 ({DEFAULT_SHADE}; Redux's own bake uses 56..255)")
    parser.add_argument("--feather", type=float, default=5.0, help="soft shade edge in metres (5)")
    where = parser.add_mutually_exclusive_group()
    where.add_argument("--trn", help="use world coordinates, with MinX/MinZ from this TRN's [Size]")
    where.add_argument("--origin", metavar="MINX,MINZ", help="use world coordinates with this map origin")
    parser.add_argument("--lgt", help="light map to update (default: the .lgt beside the HG2)")
    parser.add_argument("--no-lgt", action="store_true", help="leave the light map alone")
    parser.add_argument("--out", help="write here (a .hg2 path or a folder) instead of over the originals")
    parser.add_argument("--backup", help="folder for the originals when overwriting (default: the toolbox data folder)")
    parser.add_argument("--preview", help="also save a PNG preview of the carved area")
    parser.add_argument("--dry-run", action="store_true", help="report what would be carved, write nothing")
    return parser


def spec_from_args(args) -> TunnelSpec:
    origin = (0.0, 0.0)
    if args.trn:
        origin = trn_origin(args.trn)
    elif args.origin:
        origin = parse_point(args.origin)
    return TunnelSpec(path=[parse_point(p) for p in args.path], width=args.width, depth=args.depth,
                      floor=args.floor, ramp=args.ramp, ramps=args.ramps, wall_slope=args.wall_slope or None,
                      roof_rects=[parse_rect(r) for r in args.roof_shade], shade_path=args.shade_path,
                      shade=args.shade, feather=args.feather, origin=origin)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(list(sys.argv[1:] if argv is None else argv))
    try:
        spec = spec_from_args(args)
        outcome = apply_tunnel(args.hg2, spec, lgt_path=args.lgt, lgt=not args.no_lgt)
        if args.preview:
            preview_image(outcome.hg2.heights, outcome.result.carved, outcome.original,
                          zone_size=outcome.hg2.zone_size).save(args.preview)
            outcome.written.append(args.preview)
        if not args.dry_run and (outcome.result.samples or outcome.lgt_changed):
            write_tunnel(args.hg2, outcome, out=args.out, backup_dir=args.backup)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    if spec.origin != (0.0, 0.0):
        print(f"world coordinates, map origin {spec.origin[0]:g},{spec.origin[1]:g}")
    for line in outcome.lines():
        print(line)
    if args.dry_run:
        print("dry run: nothing written" + (" except the preview" if args.preview else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
