from __future__ import annotations

import argparse
import os
import sys

from bztoolbox.modules.world.maketrn_compat import make_stock_geometry, make_trn_runtime_seed
from bztoolbox.modules.world.mat_codec import default_make_trn_rules, parse_trn_painter, validate_paint_rules
from bztoolbox.modules.world.msn_ter_codec import read_msn_ter
from bztoolbox.modules.world.stock_map_creator import StockBuildConfig, StockBuildResult, build_stock_map


def _legacy_args(argv: list[str]) -> list[str]:
    """Accept the useful MakeTRN-style /p= and /e= spellings as aliases."""
    out: list[str] = []
    for arg in argv:
        low = arg.lower()
        if low.startswith(("/p=", "-p=")):
            out.extend(["--params", arg[3:]])
        elif low.startswith(("/e=", "-e=")):
            out.extend(["--empty-elevation", arg[3:]])
        else:
            out.append(arg)
    return out


def _worldbuilder_template(world: str) -> tuple[str, str]:
    """Reuse WorldBuilder's shipping stock-world templates without creating a Tk UI."""
    from bztoolbox.modules.world import world_builder_core as core

    architect = object.__new__(core.BZ98TRNArchitect)
    template = core.BZ98TRNArchitect.get_stock_template_data(architect, world)
    return template["NormalView"], template["Static"]


def build_msn_map(
    msn_path: str,
    out_dir: str,
    *,
    name: str | None = None,
    ter_path: str | None = None,
    world: str = "Moon",
    params_path: str | None = None,
    empty_elevation: int = 0,
    seed: int | None = None,
    normal_view: str | None = None,
    static_trn: str | None = None,
) -> tuple[StockBuildResult, tuple[int, ...]]:
    terrain = read_msn_ter(msn_path, ter_path)
    output_name = name or os.path.splitext(os.path.basename(msn_path))[0]
    if len(output_name) > 8 or not output_name.isalnum():
        raise ValueError(
            "Output map name must be 1-8 alphanumeric characters; use --name for long I76 filenames"
        )

    if params_path:
        parsed = parse_trn_painter(params_path)
        if not parsed.layers:
            raise ValueError("The selected parameter file contains no valid [Layer0]..[Layer7] rules")
        rules = [dict(layer) for layer in parsed.layers]
    else:
        rules = default_make_trn_rules()

    warnings = validate_paint_rules(rules)
    fatal = [warning for warning in warnings if "slope range" not in warning]
    if fatal:
        raise ValueError("; ".join(fatal))

    if normal_view is None or static_trn is None:
        normal_view, static_trn = _worldbuilder_template(world)

    geometry = make_stock_geometry(terrain.zones_x * 1280, terrain.zones_z * 1280)
    config = StockBuildConfig(
        name=output_name,
        out_dir=out_dir,
        geometry=geometry,
        empty_elevation=empty_elevation,
        time_of_day=1100,
        music_track=27,
        music_loop_first=27,
        music_loop_last=27,
        music_loop_skip=-1,
        ambient=(1.0, 1.0, 1.0),
        diffuse=(1.0, 1.0, 1.0),
        specular=(1.0, 1.0, 1.0),
        normal_view=normal_view,
        static_trn=static_trn,
        paint_rules=rules,
        legacy_seed=make_trn_runtime_seed() if seed is None else int(seed),
        min_x=terrain.min_x_meters,
        min_z=terrain.min_z_meters,
        source_heights=terrain.heights,
    )
    return build_stock_map(config), terrain.missing_zone_ids


def make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Convert the working MakeTRN 2.1.2 Interstate '76 MSN+TER mode into "
            "Battlezone Redux TRN/HG2/MAT files."
        )
    )
    parser.add_argument("msn", help="Interstate '76 .MSN file containing TDEF/ZMAP")
    parser.add_argument("--ter", help="Companion .TER path; defaults to the MSN stem")
    parser.add_argument("--output", "-o", default=".", help="Output directory")
    parser.add_argument("--name", help="1-8 character Battlezone output map name")
    parser.add_argument(
        "--world",
        default="Moon",
        choices=["Moon", "Achilles", "Europa", "Venus", "Mars", "Io", "Ganymede", "Elysium"],
        help="WorldBuilder Redux environment template for the generated TRN",
    )
    parser.add_argument("--params", help="MakeTRN [Layer0]..[Layer7] parameter file (/p= alias)")
    parser.add_argument(
        "--empty-elevation",
        type=int,
        default=0,
        help="Out-of-bounds painter elevation (/e= alias; MakeTRN accepts 0..4094)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        help="Deterministic MSVCR120 MAT seed; omit to emulate MakeTRN srand(clock())",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = make_parser().parse_args(_legacy_args(list(sys.argv[1:] if argv is None else argv)))
    try:
        result, missing = build_msn_map(
            args.msn,
            args.output,
            name=args.name,
            ter_path=args.ter,
            world=args.world,
            params_path=args.params,
            empty_elevation=args.empty_elevation,
            seed=args.seed,
        )
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(f"TRN: {result.trn_path}")
    print(f"HG2: {result.hg2_path}")
    print(f"MAT: {result.mat_path}")
    print(f"MAT entries: {result.mat_width}x{result.mat_height}")
    if missing:
        print("Warning: ZMAP references no placement for TER zone IDs: " + ", ".join(map(str, missing)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
