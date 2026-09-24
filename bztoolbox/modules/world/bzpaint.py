from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Sequence

from bztoolbox.modules.world.hg2_codec import read_hg2
from bztoolbox.modules.world.mat_codec import (
    HG2_SAMPLES_PER_ZONE,
    default_make_trn_rules,
    generate_mat,
    parse_trn_painter,
    validate_paint_rules,
    write_mat,
)


@dataclass(frozen=True)
class PaintResult:
    trn: str
    hg2: str
    parameters: str | None
    output: str
    zones_x: int
    zones_z: int
    entries_x: int
    entries_z: int
    seed: int
    empty_elevation: int
    solid_tiles: int
    cap_tiles: int
    diagonal_tiles: int
    ambiguous_tiles: int
    unsupported_transition_tiles: int
    unmatched_samples: int
    wrote_file: bool


def _normalize_legacy_args(argv: Sequence[str]) -> list[str]:
    """Translate the historical MakeTRN slash switches into argparse switches.

    Supported compatibility forms:
        map.trn /p=moon.ini
        map.trn /e=0

    Only known MakeTRN switches are rewritten, so POSIX absolute paths remain intact.
    """
    normalized: list[str] = []
    for arg in argv:
        low = arg.lower()
        if low.startswith("/p="):
            normalized.extend(("--params", arg[3:]))
        elif low.startswith("/e="):
            normalized.extend(("--empty-elevation", arg[3:]))
        else:
            normalized.append(arg)
    return normalized


def _case_insensitive_sibling(path: Path, suffix: str) -> Path:
    candidate = path.with_suffix(suffix)
    if candidate.exists():
        return candidate
    parent = path.parent if str(path.parent) else Path(".")
    stem = path.stem.casefold()
    wanted_suffix = suffix.casefold()
    for child in parent.iterdir():
        if child.is_file() and child.stem.casefold() == stem and child.suffix.casefold() == wanted_suffix:
            return child
    return candidate


def _resolve_hg2(trn_path: Path) -> Path:
    hg2 = _case_insensitive_sibling(trn_path, ".hg2")
    if not hg2.exists():
        raise FileNotFoundError(
            f"No companion HG2 found for {trn_path}. Expected a same-stem .hg2 file."
        )
    return hg2


def paint_trn(
    trn_path: str | Path,
    *,
    parameter_path: str | Path | None = None,
    output_path: str | Path | None = None,
    empty_elevation: int = 0,
    seed: int = 1,
    dry_run: bool = False,
) -> PaintResult:
    """Paint a Redux MAT using the reverse-engineered MakeTRN /p behavior."""
    trn = Path(trn_path)
    if not trn.exists():
        raise FileNotFoundError(f"TRN not found: {trn}")
    if trn.suffix.casefold() != ".trn":
        raise ValueError(f"Input must be a .trn file, got: {trn}")

    hg2 = _resolve_hg2(trn)
    header, heights = read_hg2(hg2)
    if header.zone_size != HG2_SAMPLES_PER_ZONE:
        raise ValueError(
            f"MakeTRN compatibility requires 256 HG2 samples per zone; "
            f"{hg2} uses {header.zone_size}."
        )

    trn_config = parse_trn_painter(trn)

    params: Path | None = None
    if parameter_path is not None:
        params = Path(parameter_path)
        if not params.exists():
            raise FileNotFoundError(f"Painter parameter file not found: {params}")
        param_config = parse_trn_painter(params)
        if not param_config.layers:
            raise ValueError(
                f"{params} contains no valid [Layer0]..[Layer7] MakeTRN painter rules."
            )
        rules = [dict(layer) for layer in param_config.layers]
    else:
        rules = default_make_trn_rules()

    issues = validate_paint_rules(rules)
    fatal = [
        issue
        for issue in issues
        if any(
            marker in issue
            for marker in (
                "malformed",
                "must be 0..7",
                "ElevationStart >",
                "SlopeStart >",
                "at most",
                "does not exist",
            )
        )
    ]
    if fatal:
        raise ValueError("Invalid painter rules: " + "; ".join(fatal))

    has_texture_metadata = bool(trn_config.texture_types)
    entries, stats = generate_mat(
        heights,
        rules,
        header.zones_x,
        header.zones_z,
        cap_transitions=trn_config.cap_transitions if has_texture_metadata else None,
        diagonal_transitions=trn_config.diagonal_transitions if has_texture_metadata else None,
        min_x=trn_config.min_x,
        min_z=trn_config.min_z,
        world_width=trn_config.width or header.zones_x * 1280.0,
        world_depth=trn_config.depth or header.zones_z * 1280.0,
        legacy_seed=seed,
        fallback_elevation=empty_elevation,
        strict=True,
    )

    output = Path(output_path) if output_path is not None else trn.with_suffix(".mat")
    if not dry_run:
        write_mat(output, entries, header.zones_x, header.zones_z)

    return PaintResult(
        trn=str(trn),
        hg2=str(hg2),
        parameters=str(params) if params is not None else None,
        output=str(output),
        zones_x=header.zones_x,
        zones_z=header.zones_z,
        entries_x=int(entries.shape[1]),
        entries_z=int(entries.shape[0]),
        seed=int(seed),
        empty_elevation=int(empty_elevation),
        solid_tiles=stats.solid_tiles,
        cap_tiles=stats.cap_tiles,
        diagonal_tiles=stats.diagonal_tiles,
        ambiguous_tiles=stats.ambiguous_tiles,
        unsupported_transition_tiles=stats.unsupported_transition_tiles,
        unmatched_samples=stats.unmatched_samples,
        wrote_file=not dry_run,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bzpaint",
        description=(
            "Open-source Battlezone 98 Redux MAT auto-painter. Reproduces the "
            "reverse-engineered MakeTRN elevation/slope and transition behavior."
        ),
        epilog=(
            "Legacy-compatible example: bzpaint map.trn /p=moon.ini\n"
            "Modern example: bzpaint map.trn --params moon.ini --seed 1 --json"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("trn", help="Input TRN; a same-stem HG2 is loaded automatically")
    parser.add_argument("-p", "--params", help="MakeTRN [LayerN] parameter INI")
    parser.add_argument(
        "-e",
        "--empty-elevation",
        type=int,
        default=0,
        help="Out-of-bounds EmptyElevation value (legacy /e=, default: 0)",
    )
    parser.add_argument("-o", "--output", help="Output MAT path (default: input TRN with .mat)")
    parser.add_argument(
        "--seed",
        type=int,
        default=1,
        help=(
            "MSVCR120-compatible texture-variant RNG seed (default: 1). "
            "The historical MakeTRN used srand(clock()); a fixed seed makes builds reproducible."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run classification/transition validation without writing the MAT",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Print machine-readable result/diagnostic JSON",
    )
    return parser


def _print_result(result: PaintResult, json_output: bool) -> None:
    if json_output:
        print(json.dumps(asdict(result), indent=2, sort_keys=True))
        return

    action = "Validated" if not result.wrote_file else "Wrote"
    print(f"{action}: {result.output}")
    print(
        f"Terrain: {result.zones_x}x{result.zones_z} zones | "
        f"MAT: {result.entries_x}x{result.entries_z} entries"
    )
    print(
        "Tiles: "
        f"solid={result.solid_tiles} "
        f"cap={result.cap_tiles} "
        f"diagonal={result.diagonal_tiles} "
        f"collapsed={result.ambiguous_tiles}"
    )
    if result.unsupported_transition_tiles:
        print(
            "Warning: "
            f"{result.unsupported_transition_tiles} generated transitions have no matching "
            "TRN CapTo/DiagonalTo definition. MAT output was preserved."
        )
    print(f"RNG seed: {result.seed} (deterministic WorldBuilder extension)")


def main(argv: Sequence[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    parser = build_parser()
    args = parser.parse_args(_normalize_legacy_args(raw))
    try:
        result = paint_trn(
            args.trn,
            parameter_path=args.params,
            output_path=args.output,
            empty_elevation=args.empty_elevation,
            seed=args.seed,
            dry_run=args.dry_run,
        )
    except (OSError, ValueError) as exc:
        parser.exit(2, f"bzpaint: error: {exc}\n")
    _print_result(result, args.json_output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
