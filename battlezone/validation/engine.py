"""Project validation engine.

The engine walks a mod folder once, then runs a set of independent checks
over that inventory. Checks wrap the proven implementations that used to live
in separate tools:

* ``odf``        - the evidence-driven ODF loader validator (BZN Toolbox)
* ``bzn``        - mission dependency scan (BZN Toolbox)
* ``structure``  - Workshop content-root layout (Workshop Uploader)
* ``assets``     - ODF/material asset references (Workshop Uploader)
* ``trn``        - TRN line endings / duplicate headers (Workshop Uploader)
* ``legacy``     - legacy ``.map`` textures left in the upload (Workshop Uploader)
* ``odf-lint``   - list-based ODF header/field scan; particle/render sections
  (``renderBase``/``simulateBase``, or named as ``file.Section``) are accepted

Every check reports :class:`Issue` records with one shared severity scale.
"""

from __future__ import annotations

import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Iterator, List, Optional, Sequence

from battlezone.bzn.scan import STOCK_SET, BZNParser
from battlezone.odf.validator import ODFIssue, parse_odf, validate_documents
from battlezone.validation.mod_scanner import ModScanner

SEVERITIES = ("error", "warning", "info")
_SEVERITY_ORDER = {name: index for index, name in enumerate(SEVERITIES)}

ProgressCallback = Callable[[float, str], None]


class ValidationCancelled(Exception):
    """Raised when the caller's cancel event is set mid-run."""


@dataclass(frozen=True)
class Issue:
    severity: str                 # "error" | "warning" | "info"
    check: str                    # id of the check that produced it
    message: str
    path: str = ""                # path relative to the project root, "/" separated
    line: int = 0
    rule_id: str = ""
    suggestion: str = ""
    section: str = ""
    key: str = ""
    evidence_ids: tuple = ()

    def location(self) -> str:
        if not self.path:
            return ""
        return f"{self.path}:{self.line}" if self.line else self.path


@dataclass
class ValidationReport:
    root: str
    checks: List[str]
    issues: List[Issue] = field(default_factory=list)
    file_count: int = 0

    @property
    def counts(self) -> dict:
        out = {name: 0 for name in SEVERITIES}
        for issue in self.issues:
            out[issue.severity] = out.get(issue.severity, 0) + 1
        return out

    @property
    def ok(self) -> bool:
        return self.counts["error"] == 0

    def by_check(self, check_id: str) -> List[Issue]:
        return [issue for issue in self.issues if issue.check == check_id]

    def to_dict(self) -> dict:
        return {
            "root": self.root,
            "checks": list(self.checks),
            "file_count": self.file_count,
            "counts": self.counts,
            "issues": [asdict(issue) for issue in self.issues],
        }


class _Context:
    """Shared, read-only view of the project handed to every check."""

    def __init__(self, root: Path, cancel: Optional[threading.Event]):
        self.root = root
        self.cancel = cancel
        self.files: List[Path] = sorted(
            (p for p in root.rglob("*") if p.is_file()), key=lambda p: str(p).lower())
        self.names_lower = {p.name.lower() for p in self.files}
        self.scanner = ModScanner()
        self._inventory = None

    def rel(self, path: Path | str) -> str:
        try:
            return Path(path).resolve().relative_to(self.root.resolve()).as_posix()
        except ValueError:
            return str(path)

    def with_suffix(self, *suffixes: str) -> List[Path]:
        wanted = {s.lower() for s in suffixes}
        return [p for p in self.files if p.suffix.lower() in wanted]

    @property
    def inventory(self):
        if self._inventory is None:
            self._inventory = self.scanner.build_inventory(str(self.root))
        return self._inventory

    def check_cancel(self) -> None:
        if self.cancel is not None and self.cancel.is_set():
            raise ValidationCancelled()


@dataclass(frozen=True)
class Check:
    id: str
    title: str
    description: str
    run: Callable[[_Context], Iterable[Issue]]
    default: bool = True


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

def _odf_severity(value: str) -> str:
    value = value.upper()
    if value in ("CRITICAL", "ERROR"):
        return "error"
    if value == "WARNING":
        return "warning"
    return "info"


def _check_odf(ctx: _Context) -> Iterator[Issue]:
    documents = []
    by_name: dict[str, List[Path]] = {}
    for path in ctx.with_suffix(".odf"):
        ctx.check_cancel()
        by_name.setdefault(path.name.lower(), []).append(path)
        try:
            documents.append(parse_odf(path))
        except OSError as exc:
            yield Issue("error", "odf", f"Could not read ODF: {exc}", ctx.rel(path), rule_id="read-error")
    if not documents:
        return
    for odf_issue in validate_documents(documents, known_odfs=STOCK_SET):
        yield _from_odf_issue(ctx, odf_issue, by_name)


def _from_odf_issue(ctx: _Context, odf_issue: ODFIssue, by_name: dict) -> Issue:
    matches = by_name.get(odf_issue.filename.lower(), [])
    path = ctx.rel(matches[0]) if len(matches) == 1 else odf_issue.filename
    return Issue(
        severity=_odf_severity(odf_issue.severity),
        check="odf",
        message=odf_issue.message,
        path=path,
        line=odf_issue.line,
        rule_id=odf_issue.rule_id,
        suggestion=odf_issue.suggestion,
        section=odf_issue.section,
        key=odf_issue.key,
        evidence_ids=tuple(odf_issue.evidence_ids),
    )


def _check_bzn(ctx: _Context) -> Iterator[Issue]:
    for path in ctx.with_suffix(".bzn"):
        ctx.check_cancel()
        referenced = BZNParser(str(path)).parse()
        for base in sorted(referenced, key=str.lower):
            filename = f"{base}.odf".lower()
            if filename in STOCK_SET or filename in ctx.names_lower:
                continue
            yield Issue(
                "error", "bzn",
                f"Mission references custom ODF '{base}.odf', which is not in the project",
                ctx.rel(path), rule_id="bzn-missing-odf",
                suggestion=f"Add {base}.odf to the mod, or fix the object in the mission.",
            )


def _check_structure(ctx: _Context) -> Iterator[Issue]:
    errors, warnings = ctx.scanner.validate_content_structure(str(ctx.root), remove_system_files=False)
    for message in errors:
        yield Issue("error", "structure", message, rule_id="workshop-structure")
    for message in warnings:
        yield Issue("warning", "structure", message, rule_id="workshop-structure")


def _check_assets(ctx: _Context) -> Iterator[Issue]:
    for path, _kind, detail, line in ctx.scanner.scan_asset_references(str(ctx.root), inventory=ctx.inventory):
        yield Issue(
            "warning", "assets", detail, ctx.rel(path), line=line, rule_id="missing-asset",
            suggestion="Ship the file with the mod, or ignore this if it is a stock asset.",
        )


def _check_trn(ctx: _Context) -> Iterator[Issue]:
    line_endings, duplicate_headers = ctx.scanner.scan_trn_safety(str(ctx.root), inventory=ctx.inventory)
    for path in line_endings:
        yield Issue("warning", "trn", "TRN does not use CRLF line endings", ctx.rel(path),
                    rule_id="trn-line-endings", suggestion="Re-save the TRN with Windows (CRLF) line endings.")
    for path in duplicate_headers:
        yield Issue("error", "trn", "TRN contains more than one [Size] section", ctx.rel(path),
                    rule_id="trn-duplicate-size", suggestion="Remove the duplicate [Size] block.")


def _check_legacy(ctx: _Context) -> Iterator[Issue]:
    for path in ctx.scanner.scan_legacy_files(str(ctx.root), inventory=ctx.inventory):
        yield Issue("warning", "legacy", "Legacy .map texture in the mod folder", ctx.rel(path),
                    rule_id="legacy-map", suggestion="Convert to DDS/PNG, or remove it before publishing.")


def _check_odf_lint(ctx: _Context) -> Iterator[Issue]:
    for path, kind, detail, line in ctx.scanner.scan_mod_safety(str(ctx.root), inventory=ctx.inventory):
        severity = "warning" if kind == "Missing Fields" else "info"
        yield Issue(severity, "odf-lint", f"{kind}: {detail}", ctx.rel(path), line=line,
                    rule_id="odf-lint-" + kind.lower().replace(" ", "-"))


CHECKS: dict[str, Check] = {check.id: check for check in (
    Check("structure", "Workshop layout", "Content-root .ini, mapType and required map files.", _check_structure),
    Check("bzn", "Mission dependencies", "Custom ODFs referenced by .bzn missions exist in the project.", _check_bzn),
    Check("odf", "ODF validation", "Evidence-based Redux ODF loader rules.", _check_odf),
    Check("assets", "Asset references", "Geometry/texture files named by ODFs and materials.", _check_assets),
    Check("trn", "TRN files", "Line endings and duplicate [Size] sections.", _check_trn),
    Check("legacy", "Legacy files", "Old .map textures left in the upload.", _check_legacy),
    Check("odf-lint", "ODF field lint", "Class headers, unknown and missing fields.", _check_odf_lint),
)}

DEFAULT_CHECKS: tuple = tuple(check.id for check in CHECKS.values() if check.default)


def validate_project(
    root: str | Path,
    checks: Optional[Sequence[str]] = None,
    progress: Optional[ProgressCallback] = None,
    cancel: Optional[threading.Event] = None,
) -> ValidationReport:
    """Run ``checks`` (default: :data:`DEFAULT_CHECKS`) over the folder ``root``."""
    root = Path(root)
    if not root.is_dir():
        raise NotADirectoryError(f"Not a folder: {root}")
    selected = list(checks) if checks is not None else list(DEFAULT_CHECKS)
    unknown = [name for name in selected if name not in CHECKS]
    if unknown:
        raise ValueError(f"Unknown check(s): {', '.join(unknown)}")

    if progress:
        progress(0.0, "Indexing project files")
    ctx = _Context(root, cancel)
    report = ValidationReport(root=str(root), checks=selected, file_count=len(ctx.files))
    for index, check_id in enumerate(selected):
        ctx.check_cancel()
        check = CHECKS[check_id]
        if progress:
            progress(index / max(len(selected), 1), check.title)
        report.issues.extend(check.run(ctx))
    report.issues.sort(key=lambda i: (_SEVERITY_ORDER.get(i.severity, 9), i.check, i.path.lower(), i.line))
    if progress:
        progress(1.0, "Done")
    return report
