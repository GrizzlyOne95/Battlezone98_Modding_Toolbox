"""``bztoolbox`` command line.

The standalone utilities' command-line tools survive as subcommands so they
remain available for automation after the separate executables are retired::

    bztoolbox                                  # open the GUI
    bztoolbox gui --project path/to/mod        # GUI with a project open
    bztoolbox validate path/to/mod [--json]    # unified validation engine
    bztoolbox terrain generate --style ...     # (formerly HeightmapGen CLI)
    bztoolbox textures makemap ...             # (formerly BZMakeMAPCompat)
    bztoolbox help                             # every command

Delegated commands pass their arguments through unchanged, so the options
documented for the original tools still apply.
"""

from __future__ import annotations

import argparse
import contextlib
import importlib
import json
import sys
from dataclasses import dataclass
from typing import Callable, List, Optional, Sequence

from bztoolbox import APP_NAME, __version__


@dataclass(frozen=True)
class Delegate:
    group: str
    name: str
    target: str               # "module:function"
    summary: str
    takes_argv: bool = True   # function(argv) vs. reads sys.argv itself
    origin: str = ""

    def run(self, argv: Sequence[str]) -> int:
        module_name, _, attr = self.target.partition(":")
        func: Callable = getattr(importlib.import_module(module_name), attr)
        prog = f"bztoolbox {self.group} {self.name}"
        try:
            if self.takes_argv:
                with _argv([prog, *argv]):
                    result = func(list(argv))
            else:
                with _argv([prog, *argv]):
                    result = func()
        except SystemExit as exc:  # argparse --help / usage errors
            code = exc.code
            return code if isinstance(code, int) else (0 if code is None else 1)
        return int(result or 0) if isinstance(result, (int, type(None))) else 0


@contextlib.contextmanager
def _argv(values: List[str]):
    saved = sys.argv
    sys.argv = values
    try:
        yield
    finally:
        sys.argv = saved


DELEGATES: Sequence[Delegate] = (
    Delegate("odf", "validate", "battlezone.odf.validator:_cli_main",
             "Validate ODF files, a folder or a ZIP against Redux loader rules.", False, "BZN Toolbox"),
    Delegate("bzn", "port", "battlezone.bzn.bzcc_port:main",
             "Port a BZ2/BZCC mission onto a Redux ASCII template.", True, "BZN Toolbox"),
    Delegate("bzn", "classes", "battlezone.odf.class_labels:main",
             "Diff BZCC ODF class labels against Redux.", True, "BZN Toolbox"),
    Delegate("terrain", "generate", "bztoolbox.modules.terrain_generator.cli:cli",
             "Generate an HG2 heightmap (and optional LGT/previews).", False, "HeightmapGen"),
    Delegate("terrain", "paint", "bztoolbox.modules.world.bzpaint:main",
             "MakeTRN-compatible MAT painting from HG2 + TRN rules.", True, "WorldBuilder"),
    Delegate("terrain", "legacy-port", "bztoolbox.modules.world.legacy_port_cli:main",
             "Port legacy Battlezone worlds/missions to Redux.", True, "WorldBuilder"),
    Delegate("terrain", "msn2terrain", "bztoolbox.modules.world.msn2terrain:main",
             "Build terrain from a Battlezone MSN.", True, "WorldBuilder"),
    Delegate("terrain", "preview", "bztoolbox.modules.world.map_preview:main",
             "Render map preview images for TRN/HG2 folders.", False, "WorldBuilder"),
    Delegate("textures", "makemap", "bztoolbox.modules.textures.makemap_compat:main",
             "MakeMAP-compatible MAP encoder/decoder.", True, "TextureManager"),
    Delegate("textures", "recompress", "bztoolbox.modules.textures.recompress:main",
             "Bulk DDS recompression with backups.", False, "TextureManager"),
    Delegate("meshes", "to-obj", "bztoolbox.modules.meshes.MeshToObj:main",
             "Convert Ogre .mesh/.mesh.xml to OBJ.", False, "OgreMeshTools"),
    Delegate("meshes", "normals", "bztoolbox.modules.meshes.recalculate_normals:main",
             "Recalculate normals in an Ogre .mesh.xml.", False, "OgreMeshTools"),
    Delegate("fonts", "dump-st", "bztoolbox.modules.fonts.dump_bzfont_st:main",
             "Dump stock bzfont.st sprite coordinates.", False, "Font Generator"),
)

_DELEGATE_INDEX = {(d.group, d.name): d for d in DELEGATES}


# ---------------------------------------------------------------------------
# Native commands
# ---------------------------------------------------------------------------

def _cmd_gui(args) -> int:
    from bztoolbox.app.shell import run

    return run(project=args.project, page=args.page)


def _cmd_validate(args) -> int:
    from battlezone.validation import CHECKS, DEFAULT_CHECKS, validate_project

    if args.list_checks:
        for check in CHECKS.values():
            flag = "default" if check.default else "opt-in"
            print(f"{check.id:10} {flag:8} {check.title}: {check.description}")
        return 0
    if not args.path:
        print("error: a folder to validate is required", file=sys.stderr)
        return 2
    checks = list(DEFAULT_CHECKS)
    if args.checks:
        checks = [c.strip() for c in args.checks.split(",") if c.strip()]
    if args.add:
        checks += [c.strip() for c in args.add.split(",") if c.strip() and c.strip() not in checks]
    try:
        report = validate_project(args.path, checks)
    except (NotADirectoryError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        for issue in report.issues:
            if issue.severity == "info" and not args.verbose:
                continue
            location = f" {issue.location()}" if issue.location() else ""
            print(f"{issue.severity.upper():7} [{issue.check}]{location}: {issue.message}")
            if args.verbose and issue.suggestion:
                print(f"        fix: {issue.suggestion}")
        counts = report.counts
        print(f"\n{report.file_count} files, {counts['error']} error(s), {counts['warning']} warning(s), "
              f"{counts['info']} info")
    if report.counts["error"]:
        return 1
    if args.strict and report.counts["warning"]:
        return 1
    return 0


def _cmd_bzn_deps(args) -> int:
    import os

    from battlezone.bzn.scan import STOCK_SET, BZNParser

    names = sorted(BZNParser(args.bzn).parse(), key=str.lower)
    folder = args.odf_dir or os.path.dirname(os.path.abspath(args.bzn))
    local = {n.lower() for n in os.listdir(folder)} if os.path.isdir(folder) else set()
    rows = []
    for base in names:
        filename = f"{base}.odf"
        stock = filename.lower() in STOCK_SET
        present = filename.lower() in local
        rows.append({"odf": filename, "stock": stock, "present": present,
                     "status": "OK" if (stock or present) else "MISSING"})
    if args.json:
        print(json.dumps(rows, indent=2))
    else:
        for row in rows:
            print(f"{row['status']:8} {'stock ' if row['stock'] else 'custom'} {row['odf']}")
    return 1 if any(r["status"] == "MISSING" for r in rows) else 0


def _cmd_tools(args) -> int:
    from bztoolbox import external

    for status in external.resolve_all():
        if args.versions:
            external.probe_version(status)
        where = f"{status.path} ({status.source})" if status.found else "not found"
        extra = f"  {status.version}" if status.version else ""
        print(f"{status.tool.name:18} {where}{extra}")
        for problem in status.problems:
            print(f"{'':18} ! {problem}")
    games = external.detect_game_installs()
    print(f"{'Battlezone 98 Redux':18} {games[0] if games else 'not detected'}")
    return 0


def _cmd_selftest(args) -> int:
    """Open every page once (used by CI against the frozen build)."""
    import tempfile
    import time
    import tkinter as tk
    from pathlib import Path

    from bztoolbox.app.shell import Shell, _make_root
    from bztoolbox.modules.registry import PAGES
    from bztoolbox.settings import Settings

    root = _make_root()
    failures = []
    with tempfile.TemporaryDirectory() as tmp:
        shell = Shell(root, Settings(Path(tmp) / "settings.json"))
        for page in PAGES:
            if not page.available:
                print(f"skip  {page.id} (not in this build)")
                continue
            shell.navigate(page.id)
            deadline = time.time() + 0.3
            while time.time() < deadline:
                root.update()
                time.sleep(0.01)
            ok = shell._pages[page.id].widget is not None
            print(f"{'ok  ' if ok else 'FAIL'}  {page.id}")
            if not ok:
                failures.append(page.id)
        shell.close(confirm=False)
    try:
        root.destroy()
    except tk.TclError:
        pass
    print(f"{len(failures)} page(s) failed" if failures else "all pages loaded")
    return 1 if failures else 0


def _cmd_projects(args) -> int:
    from battlezone.project import ProjectStore
    from bztoolbox import paths

    for project in ProjectStore(paths.projects_dir()).list():
        workshop = f"  workshop:{project.workshop_id}" if project.workshop_id else ""
        print(f"{project.name:32} {project.mod_path}{workshop}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="bztoolbox", description=f"{APP_NAME} {__version__}",
        epilog="Run 'bztoolbox help' for every command, including the migrated tool CLIs.")
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    sub = parser.add_subparsers(dest="command")

    gui = sub.add_parser("gui", help="open the toolbox window (default)")
    gui.add_argument("--project", help="mod folder to open")
    gui.add_argument("--page", help="page id to show, e.g. project.validation")
    gui.set_defaults(func=_cmd_gui)

    val = sub.add_parser("validate", help="validate a mod folder with the unified engine")
    val.add_argument("path", nargs="?")
    val.add_argument("--checks", help="comma-separated checks to run instead of the defaults")
    val.add_argument("--add", help="comma-separated extra checks, e.g. odf-lint")
    val.add_argument("--list-checks", action="store_true", help="list available checks")
    val.add_argument("--json", action="store_true", help="machine-readable output")
    val.add_argument("--strict", action="store_true", help="exit 1 on warnings too")
    val.add_argument("-v", "--verbose", action="store_true", help="include info findings and fixes")
    val.set_defaults(func=_cmd_validate)

    tools = sub.add_parser("tools", help="show external tools and game install detection")
    tools.add_argument("--versions", action="store_true", help="run each tool to report its version")
    tools.set_defaults(func=_cmd_tools)

    selftest = sub.add_parser("selftest", help="open every page once and report failures")
    selftest.set_defaults(func=_cmd_selftest)

    projects = sub.add_parser("projects", help="list known projects")
    projects.set_defaults(func=_cmd_projects)

    deps = sub.add_parser("bzn-deps", help="list ODFs a mission references and whether they are present")
    deps.add_argument("bzn")
    deps.add_argument("--odf-dir", help="folder to look for custom ODFs (default: beside the BZN)")
    deps.add_argument("--json", action="store_true")
    deps.set_defaults(func=_cmd_bzn_deps)
    return parser


def print_help() -> None:
    build_parser().print_help()
    print("\nMigrated tool commands (arguments are passed through unchanged):")
    for d in DELEGATES:
        origin = f"  [{d.origin}]" if d.origin else ""
        print(f"  {d.group + ' ' + d.name:24} {d.summary}{origin}")


def main(argv: Optional[Sequence[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv:
        argv = ["gui"]
    if argv[0] in ("help", "-h", "--help") and len(argv) == 1:
        print_help()
        return 0
    groups = {d.group for d in DELEGATES}
    if argv[0] in groups:
        if len(argv) < 2 or argv[1] in ("-h", "--help"):
            print(f"usage: bztoolbox {argv[0]} <command> [args...]\n")
            for d in DELEGATES:
                if d.group == argv[0]:
                    print(f"  {d.name:14} {d.summary}")
            return 0 if len(argv) >= 2 else 2
        delegate = _DELEGATE_INDEX.get((argv[0], argv[1]))
        if delegate is None:
            print(f"error: unknown command '{argv[0]} {argv[1]}'. Run 'bztoolbox help'.", file=sys.stderr)
            return 2
        return delegate.run(argv[2:])
    args = build_parser().parse_args(argv)
    if not getattr(args, "func", None):
        print_help()
        return 2
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
