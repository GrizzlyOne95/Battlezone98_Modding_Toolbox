"""Command-line authoring for independent OpenShim HD terrain tiles."""
from __future__ import annotations

import argparse
import json
import sys

from battlezone.terrain.hd_tiles import build_bundle, check_bundle, load_project, new_project, save_project


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init", help="Discover independent tile images and save an editable recipe.")
    init.add_argument("sources", help="Folder containing ALIAS_d/n/s/e.png, .tga or .dds")
    init.add_argument("--layout", required=True, help="Existing atlas CSV (metadata only)")
    init.add_argument("--material", required=True, help="Exact Ogre terrain material name")
    init.add_argument("--diffuse-resource", required=True, help="Original diffuse atlas name (identity guard)")
    init.add_argument("--normal-resource", default="", help="Original normal atlas; omit to keep stock normals")
    init.add_argument("--specular-resource", default="")
    init.add_argument("--emissive-resource", default="")
    init.add_argument("--default-alias", required=True, help="Authored tile for the blank CSV row, e.g. MA00SA0.MAP")
    init.add_argument("--tile-size", type=int, default=1024)
    init.add_argument("--prefix", default="hd", help="Unique mod-specific output resource prefix")
    init.add_argument("--normal-space", choices=("directx", "opengl"), default="directx")
    init.add_argument("--out", required=True, help="New authoring.json recipe filename")
    build = commands.add_parser("build", help="Build a portable bundle from a recipe or ready CR source-tile folder.")
    build.add_argument("project")
    build.add_argument("--out", required=True, help="New output directory; existing folders are never overwritten")
    build.add_argument("--tile-size", type=int, help="Override export resolution (never upscale)")
    build.add_argument("--prefix", help="Override resource prefix (use a unique name for your mod)")
    check = commands.add_parser("check", help="Validate a generated bundle before packaging.")
    check.add_argument("bundle")
    for command in (init, build, check):
        command.add_argument("--json", action="store_true", help="Machine-readable result/error")
    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            project = new_project(args.sources, args.layout, material=args.material,
                                  diffuse_resource=args.diffuse_resource, default_alias=args.default_alias,
                                  normal_resource=args.normal_resource, specular_resource=args.specular_resource,
                                  emissive_resource=args.emissive_resource, tile_size=args.tile_size,
                                  prefix=args.prefix, normal_space=args.normal_space)
            save_project(args.out, project)
            result = {"recipe": args.out, "tiles": len(project["tiles"])}
        elif args.command == "build":
            project = load_project(args.project)
            if args.tile_size is not None:
                project["tileSize"] = args.tile_size
            if args.prefix is not None:
                project["prefix"] = args.prefix
            result = build_bundle(project, args.out)
        else:
            result = check_bundle(args.bundle)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        if args.json:
            print(json.dumps({"error": str(exc)}))
        else:
            print(f"HD terrain: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, indent=2))
    elif args.command == "init":
        print(f"Recipe saved: {result['recipe']} ({result['tiles']} tiles)")
    else:
        print(f"Validated {result['slices']} slices, {result['rectangles']} rectangles, "
              f"{result['resourceCount']} DDS resources at {result['tileSize']}px.")
        print(f"Estimated GPU arrays: {result['estimatedGpuArrayBytes'] / 1048576:.1f} MiB. {result['memoryNote']}")
        if "output" in result:
            print(f"Bundle: {result['output']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
