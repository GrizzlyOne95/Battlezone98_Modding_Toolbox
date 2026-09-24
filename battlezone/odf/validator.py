"""Battlezone 98 Redux ODF validation.

The validator is intentionally conservative: it reports loader mismatches and
known crash-risk omissions without rewriting user files. Rule data lives in
odf_schema.py, structured provenance lives in odf_evidence.py, and
odf_inheritance.py resolves only inheritance that can be proven from the
scanned package.
"""

from __future__ import annotations

from dataclasses import dataclass
from difflib import get_close_matches
from pathlib import Path
import re
from typing import Dict, Iterable, List, Mapping, Sequence, Tuple
import zipfile

from battlezone.odf.inheritance import (
    InheritanceState,
    build_inheritance_graph,
    canonical_base_reference,
    merge_effective_sections,
)
from battlezone.odf.schema import LOADER_RULES, REFERENCE_KEYS, LoaderRule


@dataclass(frozen=True)
class ODFIssue:
    severity: str
    filename: str
    section: str
    key: str
    message: str
    suggestion: str = ""
    source: str = ""
    rule_id: str = ""
    line: int = 0
    evidence_ids: Tuple[str, ...] = ()


@dataclass
class ODFDocument:
    path: Path
    sections: Dict[str, List[Tuple[str, str, int]]]
    original_sections: Dict[str, str]

    def has_section(self, name: str) -> bool:
        return name.lower() in self.sections

    def entries(self, section: str) -> List[Tuple[str, str, int]]:
        return list(self.sections.get(section.lower(), ()))

    def keys(self, section: str) -> Mapping[str, Tuple[str, int, str]]:
        out: Dict[str, Tuple[str, int, str]] = {}
        for key, value, line in self.sections.get(section.lower(), []):
            out[key.lower()] = (value, line, key)
        return out

    def value(self, section: str, key: str, default: str = "") -> str:
        return self.keys(section).get(key.lower(), (default, 0, key))[0]

    def class_label(self) -> str:
        for section in ("GameObjectClass", "GameObject", "OrdnanceClass", "WeaponClass"):
            value = self.value(section, "classLabel")
            if value:
                return _unquote(value).lower()
        return ""


def _unquote(value: str) -> str:
    return value.strip().strip('"').strip("'")


def _merge_evidence_ids(*groups: Iterable[str]) -> Tuple[str, ...]:
    out: List[str] = []
    seen = set()
    for group in groups:
        for evidence_id in group:
            if evidence_id and evidence_id not in seen:
                seen.add(evidence_id)
                out.append(evidence_id)
    return tuple(out)


def parse_odf_bytes(data: bytes, virtual_path: str | Path) -> ODFDocument:
    """Parse an ODF byte stream as permissive legacy INI text."""
    text = data.decode("latin-1")
    sections: Dict[str, List[Tuple[str, str, int]]] = {}
    original_sections: Dict[str, str] = {}
    current: str | None = None

    section_re = re.compile(r"^\s*\[([^\]]+)\]\s*(?:;.*)?$")
    key_re = re.compile(r"^\s*([^;#=\s][^=]*?)\s*=\s*(.*?)\s*$")

    for line_no, line in enumerate(text.splitlines(), 1):
        sec = section_re.match(line)
        if sec:
            original = sec.group(1).strip()
            current = original.lower()
            original_sections.setdefault(current, original)
            sections.setdefault(current, [])
            continue

        if current is None:
            continue
        stripped = line.strip()
        if not stripped or stripped.startswith(";") or stripped.startswith("#"):
            continue
        match = key_re.match(line)
        if not match:
            continue
        key = match.group(1).strip()
        value = match.group(2).strip()
        sections[current].append((key, value, line_no))

    return ODFDocument(path=Path(virtual_path), sections=sections, original_sections=original_sections)


def parse_odf(path: Path) -> ODFDocument:
    return parse_odf_bytes(path.read_bytes(), path)


def _issue(
    severity: str,
    doc: ODFDocument,
    section: str,
    key: str,
    message: str,
    suggestion: str = "",
    source: str = "",
    rule_id: str = "",
    line: int = 0,
    evidence_ids: Iterable[str] = (),
) -> ODFIssue:
    return ODFIssue(
        severity=severity,
        filename=doc.path.name,
        section=section,
        key=key,
        message=message,
        suggestion=suggestion,
        source=source,
        rule_id=rule_id,
        line=line,
        evidence_ids=tuple(evidence_ids),
    )


def _effective_document(doc: ODFDocument, state: InheritanceState) -> ODFDocument:
    sections, names = merge_effective_sections(state)
    return ODFDocument(path=doc.path, sections=sections, original_sections=names)


def _rule_matches(doc: ODFDocument, rule: LoaderRule) -> bool:
    if rule.class_labels and doc.class_label() not in {label.lower() for label in rule.class_labels}:
        return False
    return all(doc.has_section(section) for section in rule.required_sections)


def _active_rule_section(doc: ODFDocument, rule: LoaderRule) -> tuple[str | None, bool]:
    """Return (section name, is_legacy) for the first present section in a rule."""
    if doc.has_section(rule.expected_section):
        return rule.expected_section, False
    for legacy in rule.legacy_sections:
        if doc.has_section(legacy):
            return doc.original_sections.get(legacy.lower(), legacy), True
    return None, False


def _validate_loader_rules(
    doc: ODFDocument,
    effective: ODFDocument,
    inheritance_complete: bool,
) -> List[ODFIssue]:
    issues: List[ODFIssue] = []

    for rule in LOADER_RULES:
        if not _rule_matches(effective, rule):
            continue

        local_section, is_legacy = _active_rule_section(doc, rule)

        # Diagnose only declarations physically present in this ODF. Parent
        # files are validated independently, which prevents duplicate migration
        # findings across every inheriting child.
        if local_section is not None and is_legacy:
            issues.append(_issue(
                rule.section_severity,
                doc,
                local_section,
                "",
                rule.section_message,
                f"Rename [{local_section}] to [{rule.expected_section}].",
                rule.source,
                rule.rule_id,
                evidence_ids=rule.evidence_ids,
            ))

        if local_section is not None:
            local_keys = doc.keys(local_section)
            for alias in rule.key_aliases:
                if alias.legacy_only and not is_legacy:
                    continue
                entry = local_keys.get(alias.legacy.lower())
                if not entry:
                    continue
                _value, line, original_key = entry
                # Case-only aliases are intentionally exact. We do not invent
                # global key-case rules from one recovered loader spelling.
                if original_key != alias.legacy:
                    continue
                issues.append(_issue(
                    alias.severity,
                    doc,
                    local_section,
                    original_key,
                    alias.message or f"'{original_key}' is not the Redux loader key spelling.",
                    f"Use '{alias.canonical}'.",
                    rule.source,
                    rule.rule_id,
                    line,
                    _merge_evidence_ids(rule.evidence_ids, alias.evidence_ids),
                ))

            for legacy_key in rule.legacy_keys:
                entry = local_keys.get(legacy_key.name.lower())
                if not entry:
                    continue
                _value, line, original_key = entry
                issues.append(_issue(
                    legacy_key.severity,
                    doc,
                    local_section,
                    original_key,
                    legacy_key.message,
                    legacy_key.suggestion,
                    rule.source,
                    rule.rule_id,
                    line,
                    _merge_evidence_ids(rule.evidence_ids, legacy_key.evidence_ids),
                ))

        # A missing section is only meaningful when the entire inheritance
        # chain is locally resolved. Opaque stock parents may contain it.
        if (
            inheritance_complete
            and rule.missing_section_message
            and not effective.has_section(rule.expected_section)
            and not is_legacy
        ):
            issues.append(_issue(
                rule.missing_section_severity or rule.section_severity,
                doc,
                rule.expected_section,
                "",
                rule.missing_section_message,
                rule.missing_section_suggestion,
                rule.source,
                rule.rule_id,
                evidence_ids=rule.evidence_ids,
            ))
            # Required keys cannot add useful information when the entire
            # loader section itself is absent.
            continue

        # Required keys use the effective canonical section once inheritance is
        # fully known. For incomplete/opaque chains, only an explicitly blank
        # local value is conclusive; absence may be supplied by the parent.
        if rule.required_keys and effective.has_section(rule.expected_section):
            effective_keys = effective.keys(rule.expected_section)
            local_canonical_keys = doc.keys(rule.expected_section) if doc.has_section(rule.expected_section) else {}
            for required in rule.required_keys:
                evidence_ids = _merge_evidence_ids(rule.evidence_ids, required.evidence_ids)
                required_lower = required.name.lower()
                local_entry = local_canonical_keys.get(required_lower)
                if local_entry is not None and not _unquote(local_entry[0]):
                    issues.append(_issue(
                        required.severity,
                        doc,
                        rule.expected_section,
                        required.name,
                        required.message,
                        required.suggestion,
                        rule.source,
                        rule.rule_id,
                        local_entry[1],
                        evidence_ids,
                    ))
                    continue

                if not inheritance_complete:
                    continue

                effective_entry = effective_keys.get(required_lower)
                if effective_entry is None or not _unquote(effective_entry[0]):
                    issues.append(_issue(
                        required.severity,
                        doc,
                        rule.expected_section,
                        required.name,
                        required.message,
                        required.suggestion,
                        rule.source,
                        rule.rule_id,
                        effective_entry[1] if effective_entry else 0,
                        evidence_ids,
                    ))

    return issues


def _validate_references(doc: ODFDocument, available: set[str]) -> List[ODFIssue]:
    """Validate references declared in this physical ODF.

    Parent files are validated independently. This avoids repeating the same
    inherited missing-reference warning on every descendant.
    """
    issues: List[ODFIssue] = []
    if not available:
        return issues

    for section, specs in REFERENCE_KEYS.items():
        if not doc.has_section(section):
            continue
        keys = doc.keys(section)
        for spec in specs:
            entry = keys.get(spec.name.lower())
            if not entry:
                continue
            value, line, original_key = entry
            reference = _unquote(value)
            if not reference or reference.lower() in {"null", "none"}:
                continue
            target = reference.lower()
            if not target.endswith(".odf"):
                target += ".odf"
            if target in available:
                continue

            close = get_close_matches(target, sorted(available), n=1, cutoff=0.78)
            suggestion = f"Did you mean '{close[0]}'?" if close else "Add the referenced ODF or correct the name."
            label = "payload" if section.lower() == "flaremineclass" else "ODF"
            issues.append(_issue(
                spec.severity,
                doc,
                section,
                original_key,
                f"Referenced {label} '{reference}' was not found in the scanned local/stock ODF namespace.",
                suggestion,
                f"{section} ODF dependency",
                "reference-check",
                line,
                spec.evidence_ids,
            ))

    return issues


def _validate_inheritance(doc: ODFDocument, state: InheritanceState, duplicate_name: bool) -> List[ODFIssue]:
    ref = canonical_base_reference(doc)
    if ref is None:
        return []

    evidence_ids = ("odf-basename-inheritance",)

    if duplicate_name:
        return [_issue(
            "ERROR",
            doc,
            ref.section,
            "baseName",
            f"ODF basename '{doc.path.name}' is duplicated in the scanned package, so inheritance resolution is ambiguous.",
            "Keep only one ODF with this filename in the effective package namespace.",
            "ODF baseName inheritance namespace",
            "inheritance-ambiguous-name",
            ref.line,
            evidence_ids,
        )]

    if state.status == "cycle":
        cycle = " -> ".join(state.cycle) if state.cycle else state.target
        return [_issue(
            "ERROR",
            doc,
            ref.section,
            "baseName",
            f"baseName inheritance cycle detected: {cycle}.",
            "Break the baseName cycle; inheritance must terminate at a non-cyclic parent.",
            "ODF baseName inheritance graph",
            "inheritance-cycle",
            ref.line,
            evidence_ids,
        )]

    if state.status == "ambiguous":
        return [_issue(
            "ERROR",
            doc,
            ref.section,
            "baseName",
            f"baseName '{state.target}' resolves to multiple ODFs in the scanned package.",
            "Remove the duplicate filename collision so the parent is unambiguous.",
            "ODF baseName inheritance graph",
            "inheritance-ambiguous-parent",
            ref.line,
            evidence_ids,
        )]

    if state.status == "missing":
        return [_issue(
            "ERROR",
            doc,
            ref.section,
            "baseName",
            f"baseName parent '{state.target}' was not found in the local or known stock ODF namespace.",
            "Add the parent ODF to the package or correct baseName.",
            "ODF baseName inheritance graph",
            "inheritance-missing-parent",
            ref.line,
            evidence_ids,
        )]

    # Opaque means a known stock parent exists but its contents are not bundled
    # with the scanner. That is valid; it simply prevents absence-based claims.
    return []


def validate_document(doc: ODFDocument, available_odfs: Iterable[str] = ()) -> List[ODFIssue]:
    """Validate one standalone document without guessing external inheritance."""
    available = {name.lower() for name in available_odfs}
    ref = canonical_base_reference(doc)
    state = InheritanceState("complete", (doc,)) if ref is None else InheritanceState("opaque", (doc,), target=ref.parent)
    effective = _effective_document(doc, state)
    issues = _validate_loader_rules(doc, effective, state.complete)
    issues.extend(_validate_references(doc, available))
    return issues


def _sort_issues(issues: List[ODFIssue]) -> List[ODFIssue]:
    order = {"CRITICAL": 0, "ERROR": 1, "WARNING": 2, "INFO": 3}
    issues.sort(
        key=lambda x: (
            order.get(x.severity, 99),
            x.filename.lower(),
            x.line or 1_000_000,
            x.section.lower(),
            x.key.lower(),
            x.rule_id,
        )
    )
    return issues


def _validate_document_set(
    all_documents: Sequence[ODFDocument],
    selected_documents: Sequence[ODFDocument],
    known_odfs: Iterable[str] = (),
) -> List[ODFIssue]:
    known = {name.lower() for name in known_odfs}
    available = {doc.path.name.lower() for doc in all_documents}
    available.update(known)

    graph = build_inheritance_graph(all_documents, known)
    issues: List[ODFIssue] = []

    for doc in selected_documents:
        state = graph.state_for(doc)
        effective = _effective_document(doc, state)
        duplicate_name = doc.path.name.lower() in graph.duplicates

        issues.extend(_validate_inheritance(doc, state, duplicate_name))
        issues.extend(_validate_loader_rules(doc, effective, state.complete))
        issues.extend(_validate_references(doc, available))

    return _sort_issues(issues)


def validate_documents(documents: Sequence[ODFDocument], known_odfs: Iterable[str] = ()) -> List[ODFIssue]:
    return _validate_document_set(documents, documents, known_odfs)


def validate_directory(
    directory: str | Path,
    filenames: Sequence[str] | None = None,
    known_odfs: Iterable[str] = (),
) -> List[ODFIssue]:
    root = Path(directory)
    paths = sorted(
        (p for p in root.iterdir() if p.is_file() and p.suffix.lower() == ".odf"),
        key=lambda p: p.name.lower(),
    )
    wanted = None if filenames is None else {Path(name).name.lower() for name in filenames}

    all_documents: List[ODFDocument] = []
    issues: List[ODFIssue] = []
    for path in paths:
        try:
            all_documents.append(parse_odf(path))
        except OSError as exc:
            if wanted is None or path.name.lower() in wanted:
                issues.append(ODFIssue(
                    severity="ERROR",
                    filename=path.name,
                    section="",
                    key="",
                    message=f"Could not read ODF: {exc}",
                    source="filesystem",
                    rule_id="read-error",
                ))

    if wanted is None:
        selected = all_documents
    else:
        selected = [doc for doc in all_documents if doc.path.name.lower() in wanted]

    issues.extend(_validate_document_set(all_documents, selected, known_odfs))
    return _sort_issues(issues)


def validate_zip(
    archive: str | Path,
    filenames: Sequence[str] | None = None,
    known_odfs: Iterable[str] = (),
) -> List[ODFIssue]:
    """Validate ODFs directly inside a ZIP without extracting files to disk."""
    wanted = None if filenames is None else {Path(name).name.lower() for name in filenames}
    all_documents: List[ODFDocument] = []
    issues: List[ODFIssue] = []

    try:
        with zipfile.ZipFile(archive, "r") as zf:
            odf_infos = [
                info for info in zf.infolist()
                if not info.is_dir() and Path(info.filename).suffix.lower() == ".odf"
            ]
            for info in odf_infos:
                name = Path(info.filename).name
                try:
                    all_documents.append(parse_odf_bytes(zf.read(info), info.filename))
                except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
                    if wanted is None or name.lower() in wanted:
                        issues.append(ODFIssue(
                            severity="ERROR",
                            filename=name,
                            section="",
                            key="",
                            message=f"Could not read ODF from ZIP: {exc}",
                            source="ZIP archive",
                            rule_id="read-error",
                        ))
    except (OSError, zipfile.BadZipFile) as exc:
        return [ODFIssue(
            severity="ERROR",
            filename=Path(archive).name,
            section="",
            key="",
            message=f"Could not open ZIP: {exc}",
            source="ZIP archive",
            rule_id="archive-error",
        )]

    if wanted is None:
        selected = all_documents
    else:
        selected = [doc for doc in all_documents if doc.path.name.lower() in wanted]

    issues.extend(_validate_document_set(all_documents, selected, known_odfs))
    return _sort_issues(issues)


def _cli_main() -> int:
    import argparse
    import json
    from dataclasses import asdict

    parser = argparse.ArgumentParser(description="Validate Battlezone 98 Redux ODF files")
    parser.add_argument("path", help="ODF file, folder, or ZIP archive to validate")
    parser.add_argument("--json", action="store_true", dest="as_json", help="Emit JSON findings")
    args = parser.parse_args()

    try:
        from battlezone.bzn.scan import STOCK_SET
        known = STOCK_SET
    except Exception:
        known = ()

    target = Path(args.path)
    if target.is_dir():
        issues = validate_directory(target, known_odfs=known)
    elif target.suffix.lower() == ".zip":
        issues = validate_zip(target, known_odfs=known)
    elif target.suffix.lower() == ".odf" and target.is_file():
        issues = validate_directory(target.parent, filenames=[target.name], known_odfs=known)
    else:
        parser.error("path must be an ODF file, directory, or ZIP archive")

    if args.as_json:
        print(json.dumps([asdict(issue) for issue in issues], indent=2))
    else:
        for issue in issues:
            location = issue.section
            if issue.key:
                location = f"{location}/{issue.key}" if location else issue.key
            line = f":{issue.line}" if issue.line else ""
            print(f"{issue.severity:8} {issue.filename}{line} {location} - {issue.message}")
            if issue.suggestion:
                print(f"         fix: {issue.suggestion}")
            if issue.evidence_ids:
                print(f"         evidence: {', '.join(issue.evidence_ids)}")
        if not issues:
            print("No ODF validation findings.")

    if any(issue.severity == "CRITICAL" for issue in issues):
        return 2
    if any(issue.severity == "ERROR" for issue in issues):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli_main())
