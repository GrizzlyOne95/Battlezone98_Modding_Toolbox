"""Generate tuned stock-world ACT atmospheres, preserving the other palette entries."""
import argparse
import json
from pathlib import Path

from battlezone.terrain.atmosphere_presets import WORLD_ATMOSPHERES, tune_world_act
from battlezone.terrain.lum import validate_act
from battlezone.terrain.palettes import get_stock_act_bytes


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    tune = commands.add_parser("tune", help="Create one world's tuned ACT")
    tune.add_argument("world", choices=WORLD_ATMOSPHERES)
    tune.add_argument("output", type=Path)
    tune.add_argument("--base", type=Path, help="Keep this ACT's other entries instead of the bundled stock palette")
    tune.add_argument("--fog-index", type=int, help="Actual custom LUM[223] value; default uses the world's stock LUM")
    batch = commands.add_parser("tune-all", help="Create all nine world ACTs")
    batch.add_argument("output_dir", type=Path)
    batch.add_argument("--keep-existing", action="store_true", help="Preserve existing ACTs byte for byte")
    args = parser.parse_args(argv)
    try:
        report = []
        if args.command == "tune":
            base = args.base.read_bytes() if args.base else get_stock_act_bytes(args.world)
            args.output.write_bytes(tune_world_act(args.world, base, fog_index=args.fog_index))
            report.append(dict(world=args.world, output=str(args.output), action="written"))
        else:
            args.output_dir.mkdir(parents=True, exist_ok=True)
            # Validate every retained input before writing any new outputs.
            for world in WORLD_ATMOSPHERES:
                path = args.output_dir / f"{world}.act"
                if path.exists() and args.keep_existing:
                    validate_act(path.read_bytes())
            for world in WORLD_ATMOSPHERES:
                path = args.output_dir / f"{world}.act"
                keep = path.exists() and args.keep_existing
                if not keep:
                    path.write_bytes(tune_world_act(world, get_stock_act_bytes(world)))
                report.append(dict(world=world, output=str(path), action="preserved" if keep else "written"))
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    print(json.dumps(report, indent=2))
    return 0
