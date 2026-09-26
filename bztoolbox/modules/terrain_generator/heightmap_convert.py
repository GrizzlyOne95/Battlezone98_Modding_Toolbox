"""Terrain heightmap conversion between legacy ``.HGT`` (Battlezone 1.x) and Redux ``.HG2``.

HGT -> HG2 is Redux's own legacy cook (:meth:`HGTMap.to_hg2`): a 2x
piecewise-planar upsample, by default without the 3x3 blur and with the
half-up rounding Rebellion's shipped Redux HG2s were made with, which
reproduces every stock HGT/HG2 pair byte for byte.

HG2 -> HGT keeps the legacy vertices (:meth:`HGTMap.from_hg2`). An HG2 cooked
from an HGT comes back exactly; detail between legacy vertices (from a Redux
terrain editor or generator) has no place in the 10 m legacy grid, and the
report says how much there was. HG2 does not store HGT's flag nibble: it is
written as zero, or copied from ``flags_from`` (the original HGT) so a round
trip is byte-exact.

Zone counts: HG2 carries them in its header; HGT has none, so they come from
``zones``, the TRN beside the HGT (``[Size] Width/Depth``, 1280 per zone) or
the squarest factorisation of the file size.

    bztoolbox terrain heightmap misn20.hgt              # -> misn20.hg2
    bztoolbox terrain heightmap misn20.hg2 -o old.hgt   # -> legacy HGT
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

from battlezone.terrain.hg2 import HG2Map

from .hgt import (
    HGTFormatError, HGTMap, ROUNDING_MODES, find_trn, legacy_residual, read_trn_zone_counts,
    zone_count_candidates,
)

DEFAULT_ROUNDING = "half-up"


@dataclass
class HeightmapReport:
    source: str
    target: str
    zones: Tuple[int, int]
    zone_source: str = ""
    notes: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def lines(self) -> List[str]:
        out = [f"{Path(self.source).name} -> {Path(self.target).name}: {self.zones[0]}x{self.zones[1]} zones"
               + (f" ({self.zone_source})" if self.zone_source else "")]
        out += [f"note: {n}" for n in self.notes]
        out += [f"WARNING: {w}" for w in self.warnings]
        return out


def _zones_for_hgt(path: Path, zones: Optional[Tuple[int, int]], trn: Optional[os.PathLike]) -> Tuple[Tuple[int, int], str]:
    size = path.stat().st_size
    if zones is not None:
        return tuple(zones), "given"
    beside = find_trn(path)
    trn_path = Path(trn) if trn else (Path(beside) if beside else None)
    if trn_path is not None:
        counts = read_trn_zone_counts(trn_path)
        if counts is not None and counts[0] * counts[1] * 0x8000 == size:
            return counts, f"from {trn_path.name}"
        if trn:
            raise HGTFormatError(f"{trn_path.name} does not describe {size} bytes of HGT")
    candidates = zone_count_candidates(size)
    if not candidates:
        raise HGTFormatError(f"{path.name}: {size} bytes is not a whole number of 128x128 zones")
    guess = candidates[0]
    how = "guessed from the file size" + (f"; also possible: {candidates[1:4]}" if len(candidates) > 1 else "")
    return guess, how


def convert_hgt_to_hg2(src, dst, *, zones: Optional[Tuple[int, int]] = None, trn=None,
                       rounding: str = DEFAULT_ROUNDING, smoothing: bool = False) -> HeightmapReport:
    """Legacy HGT -> Redux HG2 (Redux's cook; no blur unless ``smoothing``)."""
    src, dst = Path(src), Path(dst)
    counts, how = _zones_for_hgt(src, zones, trn)
    hgt = HGTMap.read(src, *counts)
    hgt.to_hg2(smoothing=smoothing, rounding=rounding).write(dst)
    report = HeightmapReport(str(src), str(dst), counts, how)
    if how.startswith("guessed"):
        report.warnings.append("no TRN gave the zone counts; check the result, or pass zones / the TRN")
    report.notes.append(f"{rounding} rounding, {'with' if smoothing else 'without'} Redux's 3x3 smoothing")
    if hgt.flags.any():
        report.notes.append("the HGT's flag nibble (bits 12-15) is not part of HG2 and was left behind; "
                            "keep the HGT to restore it byte-exactly")
    return report


def convert_hg2_to_hgt(src, dst, *, flags_from=None, overflow: str = "error",
                       rounding: str = DEFAULT_ROUNDING) -> HeightmapReport:
    """Redux HG2 -> legacy HGT (the legacy vertices). ``flags_from``: an HGT to copy flags from."""
    src, dst = Path(src), Path(dst)
    hg2 = HG2Map.read(src)
    flags = None
    report = HeightmapReport(str(src), str(dst), (hg2.zones_x, hg2.zones_z), "from the HG2 header")
    if flags_from is not None:
        reference = HGTMap.read(flags_from, hg2.zones_x, hg2.zones_z)
        flags = reference.flags
        report.notes.append(f"flag nibble copied from {Path(flags_from).name}")
    else:
        report.notes.append("flag nibble written as zero (1.5 recomputes its coplanar flags when it loads)")
    hgt = HGTMap.from_hg2(hg2, flags=flags, overflow=overflow)
    if overflow == "clamp" and int(hg2.heights.max(initial=0)) > 4095:
        report.warnings.append(f"heights above 4095 ({int(hg2.heights.max())} max) were clamped")
    hgt.write(dst)
    residual = legacy_residual(hg2, hgt, rounding=rounding)
    if residual.get("comparable"):
        if residual["differing"]:
            report.warnings.append(
                f"{residual['differing']} of {residual['samples']} HG2 samples lie between legacy vertices and "
                f"differ from what the HGT reproduces (up to {residual['max_difference']} units = "
                f"{residual['max_difference_world']:.1f} m); the 10 m legacy grid cannot hold that detail")
        else:
            report.notes.append("lossless: the HGT cooks back to this HG2 exactly")
    trn = find_trn(src)
    if trn is not None:
        counts = read_trn_zone_counts(trn)
        if counts is not None and counts != (hg2.zones_x, hg2.zones_z):
            report.warnings.append(f"{Path(trn).name} declares {counts[0]}x{counts[1]} zones, the HG2 "
                                   f"{hg2.zones_x}x{hg2.zones_z}")
    return report


def convert_heightmap(src, dst=None, **kw) -> HeightmapReport:
    """Convert by extension: ``.hgt`` -> ``.hg2`` and ``.hg2`` -> ``.hgt``."""
    src = Path(src)
    ext = src.suffix.lower()
    if ext == ".hgt":
        kw = {k: v for k, v in kw.items() if k in ("zones", "trn", "rounding", "smoothing")}
        return convert_hgt_to_hg2(src, dst or src.with_suffix(".hg2"), **kw)
    if ext == ".hg2":
        kw = {k: v for k, v in kw.items() if k in ("flags_from", "overflow", "rounding")}
        return convert_hg2_to_hgt(src, dst or src.with_suffix(".hgt"), **kw)
    raise HGTFormatError(f"{src.name}: expected a .hgt or .hg2 file")


def _zones_arg(text: str) -> Tuple[int, int]:
    try:
        x, z = text.lower().split("x")
        return int(x), int(z)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("zones look like 4x3 (X by Z)") from exc


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="bztoolbox terrain heightmap",
        description="Convert legacy Battlezone .HGT terrain to Redux .HG2 and back.")
    parser.add_argument("inputs", nargs="+", help=".hgt or .hg2 file(s); the extension picks the direction")
    parser.add_argument("-o", "--output", help="output file (one input only)")
    parser.add_argument("--out-dir", help="folder for outputs (default: beside each input)")
    parser.add_argument("--zones", type=_zones_arg, help="HGT zone counts, e.g. 4x3 (default: from the TRN)")
    parser.add_argument("--trn", help="TRN that gives the HGT's size (default: the one beside it)")
    parser.add_argument("--rounding", choices=ROUNDING_MODES, default=DEFAULT_ROUNDING,
                        help="HGT->HG2 interpolation rounding (default half-up, as in the shipped Redux files)")
    parser.add_argument("--smooth", action="store_true",
                        help="HGT->HG2: apply Redux's 3x3 smoothing too (what the game does without -nohgtsmoothing)")
    parser.add_argument("--flags-from", help="HG2->HGT: copy the flag nibble from this HGT")
    parser.add_argument("--clamp", action="store_true", help="HG2->HGT: clamp heights above 4095 instead of failing")
    args = parser.parse_args(argv)
    if args.output and len(args.inputs) > 1:
        parser.error("--output takes one input; use --out-dir for several")

    failures = 0
    for item in args.inputs:
        src = Path(item)
        target_ext = ".hg2" if src.suffix.lower() == ".hgt" else ".hgt"
        dst = Path(args.output) if args.output else (Path(args.out_dir) / (src.stem + target_ext) if args.out_dir
                                                     else src.with_suffix(target_ext))
        if dst.resolve() == src.resolve():
            print(f"{src}: refusing to overwrite the input", file=sys.stderr)
            failures += 1
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            report = convert_heightmap(src, dst, zones=args.zones, trn=args.trn, rounding=args.rounding,
                                       smoothing=args.smooth, flags_from=args.flags_from,
                                       overflow="clamp" if args.clamp else "error")
        except (HGTFormatError, ValueError, OSError) as exc:
            print(f"{src}: error: {exc}", file=sys.stderr)
            failures += 1
            continue
        for line in report.lines():
            print(line)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
