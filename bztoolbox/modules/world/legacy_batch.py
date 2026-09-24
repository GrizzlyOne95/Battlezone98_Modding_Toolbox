from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from typing import Callable

from bztoolbox.modules.world.legacy_preflight import validate_legacy_port_folder


@dataclass(frozen=True)
class BatchPortItem:
    name: str
    source_dir: str
    output_dir: str
    prefix: str
    status: str
    ready: bool
    error_count: int
    warning_count: int
    report_path: str | None
    message: str


@dataclass(frozen=True)
class LegacyBatchResult:
    source_root: str
    output_root: str
    items: tuple[BatchPortItem, ...]
    skipped_folders: tuple[str, ...]
    report_path: str
    json_path: str

    @property
    def ready_count(self) -> int:
        return sum(1 for item in self.items if item.ready)

    @property
    def failed_count(self) -> int:
        return sum(1 for item in self.items if not item.ready)

    @property
    def all_ready(self) -> bool:
        return bool(self.items) and self.failed_count == 0


def _contains_bzn(directory: str) -> bool:
    try:
        return any(
            name.lower().endswith(".bzn") and os.path.isfile(os.path.join(directory, name))
            for name in os.listdir(directory)
        )
    except OSError:
        return False


def discover_legacy_batch_folders(source_root: os.PathLike | str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Find immediate child folders containing one or more BZN missions.

    Batch mode deliberately does not recurse further. Keeping one mission package
    per immediate subfolder prevents unrelated palettes, MAP sources, TRNs, and
    support assets from being mixed into one conversion pass.
    """
    root = os.path.abspath(os.fspath(source_root))
    if not os.path.isdir(root):
        raise ValueError("Batch source root must be an existing directory")

    found: list[str] = []
    skipped: list[str] = []
    for name in sorted(os.listdir(root), key=str.casefold):
        path = os.path.join(root, name)
        if not os.path.isdir(path):
            continue
        if _contains_bzn(path):
            found.append(path)
        else:
            skipped.append(name)
    return tuple(found), tuple(skipped)


def default_batch_prefix(source_dir: os.PathLike | str) -> str:
    source_dir = os.path.abspath(os.fspath(source_dir))
    bzns = sorted(
        name
        for name in os.listdir(source_dir)
        if name.lower().endswith(".bzn") and os.path.isfile(os.path.join(source_dir, name))
    )
    if len(bzns) == 1:
        return os.path.splitext(bzns[0])[0]
    base = os.path.basename(os.path.normpath(source_dir)) or "legacy"
    value = "".join(ch for ch in base if ch.isalnum() or ch in "_-")
    return value or "legacy"


def _render_batch_report(result: LegacyBatchResult) -> str:
    lines = [
        "Battlezone98Redux WorldBuilder - Legacy Batch Port Report",
        "=" * 61,
        f"STATUS: {'ALL READY TO LAUNCH' if result.all_ready else 'COMPLETED WITH FAILURES'}",
        f"Source root: {result.source_root}",
        f"Output root: {result.output_root}",
        f"Mission folders processed: {len(result.items)}",
        f"Ready: {result.ready_count}",
        f"Failed / not ready: {result.failed_count}",
        f"Skipped non-mission folders: {len(result.skipped_folders)}",
        "",
    ]
    if result.skipped_folders:
        lines.append("Skipped folders: " + ", ".join(result.skipped_folders))
        lines.append("")

    for item in result.items:
        lines.extend(
            [
                f"[{item.status.upper()}] {item.name}",
                f"  Source: {item.source_dir}",
                f"  Output: {item.output_dir}",
                f"  Prefix: {item.prefix}",
                f"  Errors: {item.error_count} | Warnings: {item.warning_count}",
                f"  Message: {item.message}",
            ]
        )
        if item.report_path:
            lines.append(f"  Report: {item.report_path}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _write_batch_reports(result: LegacyBatchResult) -> LegacyBatchResult:
    with open(result.report_path, "w", encoding="utf-8", newline="\n") as stream:
        stream.write(_render_batch_report(result))
    with open(result.json_path, "w", encoding="utf-8", newline="\n") as stream:
        json.dump(
            {
                "source_root": result.source_root,
                "output_root": result.output_root,
                "all_ready": result.all_ready,
                "ready_count": result.ready_count,
                "failed_count": result.failed_count,
                "skipped_folders": list(result.skipped_folders),
                "items": [asdict(item) for item in result.items],
            },
            stream,
            indent=2,
        )
        stream.write("\n")
    return result


def run_legacy_batch(
    source_root: os.PathLike | str,
    output_root: os.PathLike | str,
    port_one: Callable[[str, str, str], None],
    *,
    explicit_palette: os.PathLike | str | None = None,
    log: Callable[[str, str], None] | None = None,
) -> LegacyBatchResult:
    """Port every immediate mission subfolder independently.

    `port_one(source_dir, output_dir, prefix)` must run the normal single-map
    conversion path. This function provides iteration, fault isolation,
    authoritative post-port validation, and the parent-level summary report.
    """
    source_root = os.path.abspath(os.fspath(source_root))
    output_root = os.path.abspath(os.fspath(output_root))
    if os.path.normcase(source_root) == os.path.normcase(output_root):
        raise ValueError("Batch source root and output root must be different directories")

    mission_folders, skipped = discover_legacy_batch_folders(source_root)
    if not mission_folders:
        raise ValueError("No immediate subfolders containing BZN missions were found")
    os.makedirs(output_root, exist_ok=True)

    palette = os.path.abspath(os.fspath(explicit_palette)) if explicit_palette else None
    items: list[BatchPortItem] = []

    for index, source_dir in enumerate(mission_folders, start=1):
        name = os.path.basename(os.path.normpath(source_dir))
        output_dir = os.path.join(output_root, name)
        prefix = default_batch_prefix(source_dir)
        os.makedirs(output_dir, exist_ok=True)
        if log:
            log(f"Batch [{index}/{len(mission_folders)}] {name}: starting", "info")

        try:
            port_one(source_dir, output_dir, prefix)
            validation = validate_legacy_port_folder(
                source_dir,
                output_dir,
                explicit_palette=palette,
                prepare_extras=True,
                write_report=True,
            )
            ready = validation.ready
            status = "ready" if ready else "not_ready"
            message = (
                "READY TO LAUNCH"
                if ready
                else f"Preflight found {validation.error_count} blocking error(s)"
            )
            item = BatchPortItem(
                name=name,
                source_dir=source_dir,
                output_dir=output_dir,
                prefix=prefix,
                status=status,
                ready=ready,
                error_count=validation.error_count,
                warning_count=validation.warning_count,
                report_path=validation.report_path,
                message=message,
            )
            if log:
                level = "success" if ready else "error"
                log(
                    f"Batch [{index}/{len(mission_folders)}] {name}: {message} "
                    f"({validation.warning_count} warning(s))",
                    level,
                )
        except Exception as exc:
            item = BatchPortItem(
                name=name,
                source_dir=source_dir,
                output_dir=output_dir,
                prefix=prefix,
                status="error",
                ready=False,
                error_count=1,
                warning_count=0,
                report_path=None,
                message=str(exc),
            )
            if log:
                log(
                    f"Batch [{index}/{len(mission_folders)}] {name}: ERROR: {exc}; continuing",
                    "error",
                )
        items.append(item)

    result = LegacyBatchResult(
        source_root=source_root,
        output_root=output_root,
        items=tuple(items),
        skipped_folders=skipped,
        report_path=os.path.join(output_root, "legacy_batch_report.txt"),
        json_path=os.path.join(output_root, "legacy_batch_report.json"),
    )
    return _write_batch_reports(result)


def render_batch_report(result: LegacyBatchResult) -> str:
    return _render_batch_report(result)
