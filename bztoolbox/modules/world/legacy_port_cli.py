from __future__ import annotations

import argparse
import os
import sys

from bztoolbox.modules.world.legacy_batch import default_batch_prefix, render_batch_report, run_legacy_batch
from bztoolbox.modules.world.legacy_preflight import render_validation_report, validate_legacy_port_folder
from bztoolbox.modules.world.maketrn_compat import convert_legacy_hgt_folder_no_smoothing


def _console_log(message: str, level: str = "info") -> None:
    print(f"[{str(level).upper()}] {message}", flush=True)


def _require_source_folder(source: str) -> str:
    source = os.path.abspath(source)
    if not os.path.isdir(source):
        raise ValueError("Source must be an extracted legacy map folder")
    if not any(name.lower().endswith(".bzn") for name in os.listdir(source)):
        raise ValueError("Source folder does not contain a BZN mission")
    return source


def _require_directory(path: str, description: str) -> str:
    path = os.path.abspath(path)
    if not os.path.isdir(path):
        raise ValueError(f"{description} must be an existing directory")
    return path


def _new_hidden_app():
    from bztoolbox.modules.world import world_builder

    core = world_builder.core
    root = core.tk.Tk()
    root.withdraw()
    app = world_builder.BZ98TRNArchitect(root)
    app.log = _console_log
    return root, app


def _configure_port_app(
    app,
    source_dir: str,
    output_dir: str,
    *,
    prefix: str,
    palette: str | None,
    image_format: str,
) -> None:
    app.legacy_source_dir.set(source_dir)
    app.legacy_out_dir.set(output_dir)
    app.legacy_prefix.set(prefix)
    app.legacy_format.set(image_format)
    app.legacy_pal_path.set(palette or "")
    # The CLI runs the terrain step itself (convert_legacy_terrain), so the
    # worker's own HGT pass is switched off when it is present at all. Leaving
    # terrain to that pass is what used to drop it: the checkbox variable only
    # exists once the Legacy Atlas tab has been laid out, and both its guard
    # and the guard here are hasattr/getattr tests that skip in silence.
    if hasattr(app, "legacy_auto_hgt"):
        app.legacy_auto_hgt.set(False)
    if hasattr(app, "legacy_auto_package"):
        app.legacy_auto_package.set(True)


def convert_legacy_terrain(source_dir: str, output_dir: str, log=_console_log) -> list:
    """Port every authored HGT in the source folder, and always say what happened.

    Unconditional by design. A port that quietly ships no .hg2 is not
    launchable, and preflight reporting it as missing much later is a far worse
    signal than one line here saying the folder had no terrain to convert.
    """
    try:
        results = convert_legacy_hgt_folder_no_smoothing(source_dir, output_dir)
    except Exception as exc:
        log(f"Legacy terrain: HGT -> HG2 conversion failed: {exc}", "error")
        return []
    if not results:
        log("Legacy terrain: no HGT files found; atlas conversion only.", "info")
        return results
    for result in results:
        log(
            f"Legacy terrain: {os.path.basename(result.hgt_path)} -> "
            f"{os.path.basename(result.hg2_path)} (-nohgtsmoothing equivalent), "
            f"{result.zones_x}x{result.zones_z} zones, "
            f"range {result.min_height}..{result.max_height}.",
            "success",
        )
    return results


def _run_shared_pipeline(
    source_dir: str,
    output_dir: str,
    *,
    prefix: str,
    palette: str | None,
    image_format: str,
) -> None:
    # The CLI intentionally drives the exact same Legacy Atlas worker as the GUI.
    root, app = _new_hidden_app()
    try:
        _configure_port_app(
            app,
            source_dir,
            output_dir,
            prefix=prefix,
            palette=palette,
            image_format=image_format,
        )
        # Terrain first: a texture-side failure must not cost the caller the HG2.
        convert_legacy_terrain(source_dir, output_dir)
        app._generate_legacy_worker(source_dir, output_dir)
    finally:
        try:
            root.destroy()
        except Exception:
            pass


def command_legacy_port(args: argparse.Namespace) -> int:
    source = _require_source_folder(args.source)
    output = os.path.abspath(args.output)
    os.makedirs(output, exist_ok=True)
    prefix = args.prefix or default_batch_prefix(source)
    palette = os.path.abspath(args.palette) if args.palette else None

    _console_log(f"Source: {source}")
    _console_log(f"Output: {output}")
    _console_log(f"Atlas prefix: {prefix}")
    _run_shared_pipeline(
        source,
        output,
        prefix=prefix,
        palette=palette,
        image_format=args.format,
    )

    validation = validate_legacy_port_folder(
        source,
        output,
        explicit_palette=palette,
        prepare_extras=True,
        write_report=True,
    )
    print()
    print(render_validation_report(validation), end="")
    if validation.report_path:
        print(f"Report: {validation.report_path}")
    return 0 if validation.ready else 2


def command_legacy_port_batch(args: argparse.Namespace) -> int:
    source_root = _require_directory(args.source_root, "Batch source root")
    output_root = os.path.abspath(args.output_root)
    palette = os.path.abspath(args.palette) if args.palette else None
    os.makedirs(output_root, exist_ok=True)

    _console_log(f"Batch source root: {source_root}")
    _console_log(f"Batch output root: {output_root}")
    if palette:
        _console_log(f"Manual palette override for every mission: {palette}", "warning")
    else:
        _console_log("Palette mode: automatic per mission", "info")

    root, app = _new_hidden_app()
    try:
        def port_one(source_dir: str, output_dir: str, prefix: str) -> None:
            _configure_port_app(
                app,
                source_dir,
                output_dir,
                prefix=prefix,
                palette=palette,
                image_format=args.format,
            )
            convert_legacy_terrain(source_dir, output_dir)
            app._generate_legacy_worker(source_dir, output_dir)

        result = run_legacy_batch(
            source_root,
            output_root,
            port_one,
            explicit_palette=palette,
            log=_console_log,
        )
    finally:
        try:
            root.destroy()
        except Exception:
            pass

    print()
    print(render_batch_report(result), end="")
    print(f"Batch report: {result.report_path}")
    return 0 if result.all_ready else 2


def command_validate(args: argparse.Namespace) -> int:
    source = _require_source_folder(args.source)
    output = os.path.abspath(args.output)
    palette = os.path.abspath(args.palette) if args.palette else None
    validation = validate_legacy_port_folder(
        source,
        output,
        explicit_palette=palette,
        prepare_extras=not args.no_prepare,
        write_report=True,
    )
    print(render_validation_report(validation), end="")
    if validation.report_path:
        print(f"Report: {validation.report_path}")
    return 0 if validation.ready else 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="world-builder-cli",
        description="Battlezone98Redux WorldBuilder command-line utilities",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    port = sub.add_parser(
        "legacy-port",
        help="Convert one extracted Battlezone 1.x map folder into a launchable Redux folder",
    )
    port.add_argument("source", help="Extracted legacy map folder")
    port.add_argument("output", help="Redux output folder")
    port.add_argument("--palette", help="Optional ACT palette override")
    port.add_argument("--prefix", help="Atlas/material prefix (defaults to the sole BZN stem)")
    port.add_argument(
        "--format",
        choices=(".dds", ".png"),
        default=".dds",
        help="Atlas texture format (default: .dds)",
    )
    port.set_defaults(func=command_legacy_port)

    batch = sub.add_parser(
        "legacy-port-batch",
        help="Port every immediate mission subfolder independently and continue past failures",
    )
    batch.add_argument("source_root", help="Parent folder whose immediate subfolders contain legacy maps")
    batch.add_argument("output_root", help="Parent folder that will receive one Redux subfolder per map")
    batch.add_argument(
        "--palette",
        help="Optional ACT override applied to every mission; omit for automatic per-map palette resolution",
    )
    batch.add_argument(
        "--format",
        choices=(".dds", ".png"),
        default=".dds",
        help="Atlas texture format for every map (default: .dds)",
    )
    batch.set_defaults(func=command_legacy_port_batch)

    validate = sub.add_parser(
        "validate-port",
        help="Validate an already converted Redux output against its legacy source",
    )
    validate.add_argument("source", help="Extracted legacy map folder")
    validate.add_argument("output", help="Converted Redux output folder")
    validate.add_argument("--palette", help="Optional ACT palette override")
    validate.add_argument(
        "--no-prepare",
        action="store_true",
        help="Do not emit palette/preview helper files while validating",
    )
    validate.set_defaults(func=command_validate)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except KeyboardInterrupt:
        print("Interrupted.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
