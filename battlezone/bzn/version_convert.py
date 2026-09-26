"""Convert Battlezone 1 BZNs between Battlezone 1.5 and Battlezone 98 Redux.

Battlezone 1.5 writes BZN versions 1037-1045; Redux writes 2016 (older
Redux builds 2003-2011). Both games share one format whose fields are gated
on the version, so a conversion is a re-save at the other version: fields the
target has no slot for are dropped, fields it needs but the source lacks get
the defaults BZNParser uses, and a few fields change type (``AiCmdInfo.param``
is a LONG before 2012 and an 8-byte ID after; ``AiPath.old_ptr`` is raw bytes
up to 2011 and a pointer after). See :mod:`battlezone.bzn.bz1` for the port.

Nothing is dropped silently. Every change is listed in the result, and a
conversion that would lose a value that is not the default (a Redux-only
``isCritical = true``, a build command whose ``param`` names an ODF, an ODF name
longer than the 8 bytes 1.5 can store, ...) is refused unless ``allow_loss``
is set, in which case the losses are listed.

Command line::

    bztoolbox bzn convert mission.bzn --to 1.5 -o mission_15.bzn
    bztoolbox bzn convert *.bzn --to redux --out-dir converted/ --odf-dir mymod/
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence

from battlezone.bzn.bz1 import (
    REDUX_MIN_VERSION, SCHEMAS, BZNError, BZNFile, Change, WriteReport, compare_fields, entity_descriptor,
    read_bzn, write_bzn, _Writer,
)

DEFAULT_15_VERSION = 1045       # Battlezone 1.5.2.x
DEFAULT_REDUX_VERSION = 2016    # Battlezone 98 Redux
TARGETS = {"1.5": DEFAULT_15_VERSION, "redux": DEFAULT_REDUX_VERSION}


class ConversionError(Exception):
    """The conversion would lose data (or failed); ``result`` has the details."""

    def __init__(self, message: str, result: Optional["ConversionResult"] = None):
        super().__init__(message)
        self.result = result


@dataclass
class ConversionResult:
    source_version: int
    target_version: int
    source_binary: bool
    target_binary: bool
    objects: int
    report: WriteReport
    data: bytes = b""
    ambiguous: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    verification: List[str] = field(default_factory=list)   # problems re-reading the output

    @property
    def lossy(self) -> List[Change]:
        return self.report.lossy

    @property
    def ok(self) -> bool:
        return not self.lossy and not self.verification

    def grouped(self) -> "OrderedDict[tuple, List[Change]]":
        groups: "OrderedDict[tuple, List[Change]]" = OrderedDict()
        for change in self.report.changes:
            groups.setdefault((change.action, change.key, change.lossy), []).append(change)
        return groups

    def summary_lines(self, *, detail: int = 3) -> List[str]:
        fmt = lambda v, b: f"{v} {'binary' if b else 'ASCII'}"   # noqa: E731
        lines = [f"version {fmt(self.source_version, self.source_binary)} -> "
                 f"{fmt(self.target_version, self.target_binary)}, {self.objects} objects"]
        lines += [f"note: {n}" for n in self.notes]
        lossless = [(k, v) for k, v in self.grouped().items() if not k[2]]
        lossy = [(k, v) for k, v in self.grouped().items() if k[2]]
        for (action, key, _), changes in lossless:
            lines.append(f"{action:10} {key}: {len(changes)}x, e.g. {changes[0].detail}")
        for (action, key, _), changes in lossy:
            lines.append(f"LOSS {action:10} {key}: {len(changes)}x")
            for change in changes[:detail if detail >= 0 else None]:
                lines.append(f"    {change.context}: {change.detail}")
            if detail >= 0 and len(changes) > detail:
                lines.append(f"    ... {len(changes) - detail} more")
        lines += [f"WARNING ambiguous class: {a}" for a in self.ambiguous]
        lines += [f"VERIFY {v}" for v in self.verification]
        return lines

    def to_dict(self) -> dict:
        return {
            "source_version": self.source_version, "target_version": self.target_version,
            "source_binary": self.source_binary, "target_binary": self.target_binary,
            "objects": self.objects, "ok": self.ok, "notes": self.notes, "ambiguous": self.ambiguous,
            "verification": self.verification,
            "changes": [c.__dict__ for c in self.report.changes],
        }


def default_target(version: int) -> int:
    """The other game's version: Redux files go to 1.5 and 1.x files to Redux."""
    return DEFAULT_15_VERSION if version >= REDUX_MIN_VERSION else DEFAULT_REDUX_VERSION


def resolve_target(target) -> Optional[int]:
    if target is None:
        return None
    if isinstance(target, int):
        return target
    text = str(target).strip().lower()
    if text in TARGETS:
        return TARGETS[text]
    try:
        return int(text)
    except ValueError as exc:
        raise ValueError(f"unknown target {target!r}: use 1.5, redux or a version number") from exc


def _ambiguities(bzn: BZNFile, version: int) -> tuple:
    """Objects whose class the file cannot pin down and whose candidates write differently.

    Returns ``(warnings, by_label)``: objects decided by nothing but parse
    order, and objects decided by the editor's ``<odf><n>_<classLabel>`` label.
    """
    warnings, by_label = [], []
    for index, obj in enumerate(bzn.objects):
        if not obj.candidates:
            continue
        outputs = {}
        for label in [obj.class_label, *obj.candidates]:
            w = _Writer(version, bzn.save, False, WriteReport())
            with w.scope(obj.fields, "", check=False):
                entity_descriptor(w)
                SCHEMAS[label](w)
            outputs.setdefault(bytes(w.out), []).append(label)
        if len(outputs) <= 1:
            continue
        others = ", ".join(obj.candidates)
        if obj.basis == "label":
            by_label.append(f"{obj.describe(index)}: class taken from its label (also parses as {others})")
        else:
            warnings.append(f"{obj.describe(index)} also parses as {others}, which differ at version {version}; "
                            f"wrote it as {obj.class_label}. Pass the mod's ODF folder (--odf-dir) so its "
                            f"classLabel decides.")
    return warnings, by_label


def _verify(source: BZNFile, output: bytes, result: ConversionResult, odf_dirs, hints) -> List[str]:
    """Re-read the output and check every field the report does not account for."""
    try:
        back = read_bzn(output, odf_dirs=odf_dirs, hints=hints)
    except BZNError as exc:
        return [f"the output does not parse: {exc}"]
    problems = []
    if back.version != result.target_version:
        problems.append(f"output reads as version {back.version}")
    if len(back.objects) != len(source.objects):
        return problems + [f"output has {len(back.objects)} objects, source {len(source.objects)}"]
    touched: Dict[str, set] = {}
    for change in result.report.changes:
        touched.setdefault(change.context, set()).add(change.key)

    # ASCII keeps six significant digits (C %g), so a binary source read back
    # from ASCII output matches to that precision only
    tolerance = 1e-5 if source.binary and not result.target_binary else 0.0

    def check(a, b, context):
        skip = touched.get(context, set())
        fa = {k: v for k, v in a.items() if k not in skip and not k.startswith("#")}
        fb = {k: v for k, v in b.items() if k not in skip and not k.startswith("#")}
        problems.extend(compare_fields(fa, fb, context, tolerance))

    header_skip = {"binarySave"}
    check({k: v for k, v in source.header.items() if k not in header_skip},
          {k: v for k, v in back.header.items() if k not in header_skip}, "header")
    for index, (a, b) in enumerate(zip(source.objects, back.objects)):
        context = a.describe(index)
        if b.class_label != a.class_label and b.class_label not in a.candidates \
                and a.class_label not in b.candidates:
            problems.append(f"{context}: reads back as class {b.class_label}")
        check(a.fields, b.fields, context)
    check(source.mission, back.mission, "mission")
    for index, (a, b) in enumerate(zip(source.aois, back.aois)):
        check(a, b, f"AOI {index}")
    for index, (a, b) in enumerate(zip(source.paths, back.paths)):
        label = a.get("label")
        name = label.value.decode("latin-1") if label is not None else ""
        check(a, b, f"AiPath {index} {name}".rstrip())
    return problems


def convert_bzn(source, target=None, *, binary: Optional[bool] = None, odf_dirs: Sequence = (),
                allow_loss: bool = False, preserve_spelling: bool = True,
                hints: Optional[dict] = None) -> ConversionResult:
    """Convert a BZN (bytes or path) to ``target`` (``"1.5"``, ``"redux"`` or a version).

    ``binary`` selects the output format (default ASCII). Raises
    :class:`ConversionError` if the source cannot be read, or if values would
    be lost and ``allow_loss`` is false; the error carries the full result.
    """
    try:
        bzn = read_bzn(source, odf_dirs=odf_dirs, hints=hints)
    except BZNError as exc:
        raise ConversionError(f"cannot read the BZN: {exc}") from exc
    version = resolve_target(target) or default_target(bzn.version)
    out_binary = bool(binary)
    report = WriteReport()
    try:
        data = write_bzn(bzn, version, binary=out_binary, report=report, preserve_spelling=preserve_spelling)
    except BZNError as exc:
        raise ConversionError(f"cannot write version {version}: {exc}") from exc
    result = ConversionResult(bzn.version, version, bzn.binary, out_binary, len(bzn.objects), report, data)
    result.notes += bzn.notes
    if bzn.save:
        result.notes.append("the source is laid out as a save game; the output keeps that layout")
    if bzn.binary and not out_binary:
        result.notes.append("binary source written as ASCII: floats keep six significant digits, "
                            "as when the game itself saves an ASCII BZN")
    if bzn.mission_name == "LuaMission" or bzn.mission_name in ("MultSTMission", "MultDMMission"):
        result.notes.append(f"mission class {bzn.mission_name}: the matching script (.lua) and every ODF the map "
                            "uses must exist in the target game")
    result.ambiguous, by_label = _ambiguities(bzn, version)
    if by_label:
        result.notes.append(f"{len(by_label)} custom object(s) have no ODF class on record; their class was "
                            f"taken from the editor label (e.g. {by_label[0]}). Pass --odf-dir to use the ODFs.")
    result.verification = _verify(bzn, data, result, odf_dirs, hints)
    if result.verification:
        raise ConversionError("the converted file did not read back as expected", result)
    if result.lossy and not allow_loss:
        raise ConversionError(f"{len(result.lossy)} value(s) have no equivalent at version {version}; "
                              "nothing was written (allow the loss to write anyway)", result)
    return result


def convert_file(src, dst, target=None, **kw) -> ConversionResult:
    """:func:`convert_bzn` and write ``dst`` (only when the conversion is accepted)."""
    result = convert_bzn(src, target, **kw)
    Path(dst).write_bytes(result.data)
    return result


def default_output_path(src, version: int, out_dir=None) -> Path:
    src = Path(src)
    folder = Path(out_dir) if out_dir else src.parent
    return folder / f"{src.stem}_v{version}{src.suffix or '.bzn'}"


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="bztoolbox bzn convert",
        description="Convert Battlezone 1 BZN missions between Battlezone 1.5 (1045) and Redux (2016).")
    parser.add_argument("inputs", nargs="+", help="BZN file(s)")
    parser.add_argument("--to", default=None,
                        help="target: 1.5, redux or a version number (default: the other game)")
    parser.add_argument("-o", "--output", help="output file (one input only)")
    parser.add_argument("--out-dir", help="folder for outputs (default: beside each input, NAME_vVERSION.bzn)")
    parser.add_argument("--binary", action="store_true", help="write a binary BZN (default ASCII)")
    parser.add_argument("--odf-dir", action="append", default=[],
                        help="folder of the mod's ODFs; their classLabel decides how custom objects are read")
    parser.add_argument("--allow-loss", action="store_true",
                        help="write even when values have no equivalent in the target (they are listed)")
    parser.add_argument("--normalize", action="store_true",
                        help="format every value like BZNParser instead of keeping the source's spelling")
    parser.add_argument("--report", help="write the full change list as JSON here")
    parser.add_argument("-v", "--verbose", action="store_true", help="list every loss, not just the first few")
    args = parser.parse_args(argv)

    if args.output and len(args.inputs) > 1:
        parser.error("--output takes one input; use --out-dir for several")
    try:
        target = resolve_target(args.to)
    except ValueError as exc:
        parser.error(str(exc))
    failures = 0
    reports = {}
    for src in args.inputs:
        print(f"{src}:")
        try:
            result = convert_bzn(src, target, binary=args.binary, odf_dirs=args.odf_dir,
                                 allow_loss=args.allow_loss, preserve_spelling=not args.normalize)
        except ConversionError as exc:
            failures += 1
            if exc.result is not None:
                for line in exc.result.summary_lines(detail=-1 if args.verbose else 3):
                    print(f"  {line}")
                reports[src] = exc.result.to_dict()
            print(f"  error: {exc}")
            continue
        dst = Path(args.output) if args.output else default_output_path(src, result.target_version, args.out_dir)
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(result.data)
        for line in result.summary_lines(detail=-1 if args.verbose else 3):
            print(f"  {line}")
        print(f"  wrote {dst}")
        reports[src] = result.to_dict()
    if args.report:
        Path(args.report).write_text(json.dumps(reports, indent=2, default=str), encoding="utf-8")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
