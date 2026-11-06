"""Create, inspect and losslessly edit LUM files."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from battlezone.terrain.lum import LumaTable, atmosphere, validate_act


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    new = commands.add_parser("new", help="Create a neutral identity table")
    new.add_argument("output", type=Path)
    new.add_argument("--fog-index", type=int, default=223)
    info = commands.add_parser("info", help="Show the Redux fog mapping as JSON")
    info.add_argument("input", type=Path)
    info.add_argument("--act", type=Path)
    info.add_argument("--fog-direction", type=int, default=1)
    edit = commands.add_parser("set", help="Edit one cell, retaining all other bytes")
    edit.add_argument("input", type=Path)
    edit.add_argument("output", type=Path)
    edit.add_argument("row", type=int)
    edit.add_argument("column", type=int)
    edit.add_argument("index", type=int)
    export = commands.add_parser("to-png", help="Export indices as a lossless 256 x 256 PNG")
    export.add_argument("input", type=Path)
    export.add_argument("output", type=Path)
    export.add_argument("--act", type=Path)
    restore = commands.add_parser("from-png", help="Import an indexed or grayscale PNG")
    restore.add_argument("input", type=Path)
    restore.add_argument("output", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "new":
            LumaTable.identity(args.fog_index).write(args.output)
        elif args.command == "from-png":
            LumaTable.from_png(args.input).write(args.output)
        else:
            table = LumaTable.read(args.input)
            if args.command == "info":
                result = dict(bytes=len(table.data), fog_lookup_offset=223,
                              lum_fog_index=table.cell(0, 223),
                              fog_index=0 if args.fog_direction == 0 else table.cell(0, 223))
                if args.act:
                    result.update(atmosphere(args.act.read_bytes(), table, args.fog_direction))
                print(json.dumps(result, indent=2))
            elif args.command == "set":
                table.set_cell(args.row, args.column, args.index)
                table.write(args.output)
            else:
                palette = validate_act(args.act.read_bytes()) if args.act else None
                table.export_png(args.output, palette)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    return 0
