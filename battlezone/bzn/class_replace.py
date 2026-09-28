"""Preview and apply class-aware record replacements in Redux mission maps.

The target ODF supplies the class, a same-version mission supplies its record,
and the original object supplies identity and placement. ODFs are never edited.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from battlezone.bzn.bz1 import (
    BZNError, BZNFile, BZNObject, Field, SCHEMAS, WriteReport, _Writer,
    compare_fields, default_value, entity_descriptor, read_bzn, write_bzn,
)
from battlezone.odf.class_labels import read_class_label


# Commands, health/ammo, physics and class state intentionally come from the
# prototype (commands and pointers are cleared below). Never copy its identity.
PRESERVED = (
    "seqno", "seqNo", "obj_addr", "label", "name", "team", "isUser",
    "pos", "pos2", "transform", "isCritical", "isObjective", "perceivedTeam",
)


class ReplacementError(ValueError):
    pass


def _hash(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def load_mission(path) -> BZNFile:
    mission = read_bzn(path)
    if not mission.is_redux or mission.save:
        raise ReplacementError("Select a Redux mission map, not a saved game or BZ2/BZCC BZN.")
    return mission


def object_rows(mission: BZNFile) -> list[dict]:
    return [{"index": i, "odf": obj.prjid, "label": obj.label, "seqno": obj.seqno,
             "record_class": obj.class_label, "alternatives": obj.candidates}
            for i, obj in enumerate(mission.objects)]


def _check_layout(obj: BZNObject, label: str, version: int) -> None:
    report = WriteReport()
    writer = _Writer(version, False, False, report)
    with writer.scope(obj.fields, obj.prjid):
        entity_descriptor(writer)
        SCHEMAS[label](writer)
    if report.changes:
        fields = ", ".join(sorted({change.key for change in report.changes}))
        raise ReplacementError(
            f"Record {obj.prjid!r} does not fit target class {label!r}: {fields}. "
            "Choose a prototype with the matching class layout.")


def _reference_warnings(mission: BZNFile) -> list[str]:
    addresses = [obj.fields["obj_addr"].value for obj in mission.objects]
    nonzero = [address for address in addresses if address]
    if len(set(nonzero)) != len(nonzero):
        raise ReplacementError("Duplicate nonzero object addresses make reference preservation ambiguous.")
    seqs = [obj.seqno for obj in mission.objects]
    if len(set(seqs)) != len(seqs):
        raise ReplacementError("Duplicate object sequence numbers make object selection ambiguous.")
    paths = set()
    for path in mission.paths:
        value = path["old_ptr"].value
        paths.add(int.from_bytes(value, "little") if isinstance(value, bytes) else value)
    warnings = []
    for i, obj in enumerate(mission.objects):
        for key in ("cargo", "powerSource", "nextCmd.where"):
            value = obj.fields.get(key)
            allowed = set(nonzero) | (paths if key == "nextCmd.where" else set())
            if value and value.value and value.value not in allowed:
                warnings.append(f"Object {i}: unresolved {key} reference 0x{value.value:X}")
    for i, aoi in enumerate(mission.aois):
        if aoi["path"].value and aoi["path"].value not in paths:
            warnings.append(f"AOI {i}: unresolved path reference 0x{aoi['path'].value:X}")
    # mission.sObject identifies the mission itself, not a GameObject.
    return warnings


def _summary_value(field: Field | None):
    if field is None:
        return None
    value = field.value
    return value.decode("latin-1") if field.kind in ("id", "chars") else (
        value.hex() if isinstance(value, bytes) else value)


@dataclass
class ReplacementPlan:
    source: Path
    inputs: dict[Path, str]
    data: bytes
    report: dict

    def summary_lines(self) -> list[str]:
        lines = [f"Target: {self.report['target_odf']} ({self.report['target_class']})",
                 f"Prototype: object {self.report['prototype_index']} in {self.report['template']}",
                 f"Replace {len(self.report['objects'])} object(s); keep BZN version and encoding."]
        for obj in self.report["objects"]:
            lines.append(f"Object {obj['index']}: {obj['odf']} / {obj['label'] or '(no label)'} "
                         f"(seq {obj['seqno']}, record {obj['record_class']})")
            lines.append("  Preserve: " + ", ".join(obj["preserved"]))
            lines.append("  From prototype: " + ", ".join(obj["prototype_fields"]))
            lines.append("  Clear commands/references: " + (", ".join(obj["cleared"]) or "none"))
            lines.append("  Remove old fields: " + (", ".join(obj["removed"]) or "none"))
            for key, change in obj["changed_values"].items():
                lines.append(f"    {key}: {change['before']!r} -> {change['after']!r}")
        lines += [f"Existing reference warning: {w}" for w in self.report["reference_warnings"]]
        lines.append("Verified: preserved identity/placement, untouched objects, mission, AOIs and paths.")
        return lines


def preview_replacement(source, template, indices, prototype_index: int, target_odf) -> ReplacementPlan:
    """Build and verify output in memory. No files are written."""
    source, template, target_odf = (Path(p).resolve() for p in (source, template, target_odf))
    payloads = {p: p.read_bytes() for p in (source, template, target_odf)}
    mission = load_mission(payloads[source])
    donor = load_mission(payloads[template])
    if donor.version != mission.version:
        raise ReplacementError("Source and prototype BZNs must have the same version; use BZN Convert first.")
    indices = list(indices) if indices is not None else []
    if not indices or any(type(i) is not int or not 0 <= i < len(mission.objects) for i in indices):
        raise ReplacementError("Select one or more valid source object indices.")
    selected = sorted(set(indices))
    if type(prototype_index) is not int or not 0 <= prototype_index < len(donor.objects):
        raise ReplacementError("Select a valid prototype object index.")
    name = target_odf.stem
    if target_odf.suffix.lower() != ".odf" or not re.fullmatch(r"[A-Za-z0-9_-]{1,8}", name):
        raise ReplacementError("Target ODF must have a filename of 1–8 ASCII letters, digits, '_' or '-'.")
    label = read_class_label(target_odf)
    if label not in SCHEMAS:
        raise ReplacementError(f"Target class {label!r} has no supported BZN record schema.")
    prototype = donor.objects[prototype_index]
    _check_layout(prototype, label, mission.version)
    warnings = _reference_warnings(mission)
    result = copy.deepcopy(mission)
    changes = []
    for index in selected:
        old = mission.objects[index]
        fields = copy.deepcopy(prototype.fields)
        missing = [key for key in PRESERVED if key in old.fields and key not in fields]
        if missing:
            raise ReplacementError(f"Prototype lacks fields that must be preserved: {missing}")
        preserved = [key for key in PRESERVED if key in old.fields]
        for key in preserved:
            fields[key] = copy.deepcopy(old.fields[key])
        fields["PrjID"] = Field("id", name.encode("ascii"))
        cleared = []
        for key, value in list(fields.items()):
            if (value.kind == "ptr" and key != "obj_addr") or key.startswith(("nextCmd.", "curCmd.")):
                size = len(value.value) if isinstance(value.value, bytes) else 4
                fields[key] = Field(value.kind, default_value(value.kind, size=size))
                cleared.append(key)
        result.objects[index] = BZNObject(label, fields, hinted=True, basis="hint")
        inherited = sorted(set(fields) - set(preserved) - set(cleared) - {"PrjID"})
        removed = sorted(set(old.fields) - set(fields))
        changes.append({**object_rows(mission)[index], "preserved": preserved,
                        "prototype_fields": inherited, "cleared": cleared, "removed": removed,
                        "changed_values": {key: {"before": _summary_value(old.fields.get(key)),
                                                  "after": _summary_value(fields.get(key))}
                                           for key in sorted(set(fields) | set(old.fields))
                                           if key not in preserved and
                                           _summary_value(old.fields.get(key)) != _summary_value(fields.get(key))}})
    # An ODF class applies to every object using that ODF, including unselected
    # instances. Do not leave a mixed-layout mission behind.
    for index, obj in enumerate(result.objects):
        if obj.prjid.casefold() == name.casefold():
            try:
                _check_layout(obj, label, result.version)
            except ReplacementError as exc:
                raise ReplacementError(f"Object {index} also uses {name}; include it in the replacement. {exc}") from exc
    report = WriteReport()
    data = write_bzn(result, result.version, binary=result.binary, report=report)
    if report.changes:
        raise ReplacementError("Writing would change unrelated fields: " +
                               ", ".join(f"{c.context}: {c.key}" for c in report.changes))
    back = read_bzn(data, hints={name.lower(): [label]})
    if len(back.objects) != len(mission.objects):
        raise ReplacementError("Output object count changed during verification.")
    problems = []
    for i, (expected, actual) in enumerate(zip(result.objects, back.objects)):
        problems += compare_fields(expected.fields, actual.fields, f"Object {i}",
                                   1e-5 if i in selected else 0.0)
        if i in selected:
            problems += compare_fields({k: mission.objects[i].fields[k] for k in PRESERVED if k in mission.objects[i].fields},
                                       {k: actual.fields[k] for k in PRESERVED if k in actual.fields}, f"Identity {i}")
    for key in ("header", "mission"):
        problems += compare_fields(getattr(mission, key), getattr(back, key), key)
    for key in ("aois", "paths"):
        before, after = getattr(mission, key), getattr(back, key)
        if len(before) != len(after):
            problems.append(f"{key} count changed")
        for i, (a, b) in enumerate(zip(before, after)):
            problems += compare_fields(a, b, f"{key} {i}")
    new_warnings = set(_reference_warnings(back)) - set(warnings)
    problems += sorted(new_warnings)
    if problems:
        raise ReplacementError("Output verification failed: " + "; ".join(problems[:10]))
    return ReplacementPlan(source, {p: _hash(b) for p, b in payloads.items()}, data, {
        "source": str(source), "template": str(template), "prototype_index": prototype_index,
        "target_odf": name, "target_class": label, "objects": changes,
        "version": mission.version, "binary": mission.binary, "reference_warnings": warnings,
    })


def apply_replacement(plan: ReplacementPlan, output) -> dict:
    """Apply a verified preview atomically, backing up any file being replaced."""
    output = Path(output).resolve()
    if output.suffix.lower() != ".bzn":
        raise ReplacementError("Output must be a .bzn file.")
    if output in plan.inputs and output != plan.source:
        raise ReplacementError("Output cannot overwrite the prototype BZN or target ODF.")
    for path, fingerprint in plan.inputs.items():
        if _hash(path.read_bytes()) != fingerprint:
            raise ReplacementError(f"Input changed since preview: {path}. Preview again.")
    output.parent.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    backup = None
    previous = output.read_bytes() if output.exists() else None
    if previous is not None:
        backup = output.with_name(output.name + f".bak-{stamp}")
        with backup.open("xb") as stream:
            stream.write(previous)
    fd, temp = tempfile.mkstemp(prefix=output.name + ".", suffix=".tmp", dir=output.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(plan.data)
            stream.flush()
            os.fsync(stream.fileno())
        current = output.read_bytes() if output.exists() else None
        if current != previous:
            raise ReplacementError("Output changed while preparing the write; nothing was replaced.")
        os.replace(temp, output)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    result = {**plan.report, "output": str(output), "backup": str(backup) if backup else None,
              "output_sha256": _hash(plan.data)}
    report_path = output.with_name(output.name + f".replacement-{stamp}.json")
    try:
        report_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        result["report"] = str(report_path)
    except OSError as exc:
        result["report_warning"] = f"BZN written, but report could not be saved: {exc}"
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--list", action="store_true", help="list zero-based object indices")
    parser.add_argument("--template", type=Path)
    parser.add_argument("--prototype-index", type=int)
    parser.add_argument("--object", type=int, action="append", dest="indices", help="source index; repeatable")
    parser.add_argument("--target-odf", type=Path)
    parser.add_argument("-o", "--output", type=Path)
    parser.add_argument("--apply", action="store_true", help="write after verification; default is preview only")
    args = parser.parse_args(argv)
    try:
        if args.list:
            print(json.dumps(object_rows(load_mission(args.source)), indent=2))
            return 0
        if args.template is None or args.prototype_index is None or not args.indices or args.target_odf is None:
            parser.error("supply --template, --prototype-index, --object and --target-odf, or use --list")
        plan = preview_replacement(args.source, args.template, args.indices, args.prototype_index, args.target_odf)
        print("\n".join(plan.summary_lines()))
        if args.apply:
            if args.output is None:
                parser.error("--apply requires --output (may be the source, which is backed up)")
            print(json.dumps(apply_replacement(plan, args.output), indent=2))
        return 0
    except (BZNError, ReplacementError, OSError) as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
