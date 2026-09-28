"""Apply the one-to-one ODF repairs the lint offers (``Issue.fix``).

A fix is ``(action, old, new, label)``:

``rename-key``      the key on the line becomes ``new`` (value, spacing and
                    comment kept)
``remove-line``     the line is deleted (an ignored key whose correct twin is
                    already set in the section)
``rename-section``  the ``[old]`` header on the line becomes ``[new]``
``rebake-lgt``      a whole-file fix: the LGT ``new`` is rebaked from the HG2 ``old``
                    (Redux stock lighting); the line is ignored

Before editing, each fix checks the line still holds what was validated, so a
file changed since the scan is never edited blindly. Originals are copied to
``backup_dir`` (outside the mod folder, so backups are never uploaded) and
files are replaced atomically. Line endings and bytes outside the edit are
kept.
"""

from __future__ import annotations

import os
import re
import shutil
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Tuple

ACTIONS = ("rename-key", "remove-line", "rename-section")
FILE_ACTIONS = ("rebake-lgt",)


class FixError(Exception):
    """The fix could not be applied (file changed since validation, unknown action, ...)."""


def _key_pattern(key: str):
    return re.compile(rf"^(\s*){re.escape(key)}(\s*=)", re.I)


def _section_pattern(section: str):
    return re.compile(rf"^(\s*\[){re.escape(section)}(\]\s*(?://.*)?)$", re.I)


def _apply_to_lines(lines: List[str], line: int, fix: Sequence[str]) -> None:
    action, old, new = fix[0], fix[1], fix[2]
    if action not in ACTIONS:
        raise FixError(f"Unknown fix action {action!r}")
    if not 1 <= line <= len(lines):
        raise FixError(f"Line {line} no longer exists")
    text = lines[line - 1]
    body = text.rstrip("\r\n")
    ending = text[len(body):]
    if action == "rename-section":
        match = _section_pattern(old).match(body)
        if not match:
            raise FixError(f"Line {line} is no longer [{old}]")
        lines[line - 1] = f"{match.group(1)}{new}{match.group(2)}{ending}"
        return
    match = _key_pattern(old).match(body)
    if not match:
        raise FixError(f"Line {line} no longer sets {old}")
    if action == "remove-line":
        del lines[line - 1]
    else:
        lines[line - 1] = f"{match.group(1)}{new}{match.group(2)}{body[match.end():]}{ending}"


def apply_fixes(root: str | os.PathLike, fixes: Iterable[Tuple[str, int, Sequence[str]]],
                backup_dir: Optional[str | os.PathLike] = None) -> List[str]:
    """Apply ``(relative_path, line, fix)`` items under ``root``; return the files changed.

    All fixes for one file are checked before that file is written, bottom-up
    so removed lines do not shift the ones above them. A file whose fixes do
    not all apply is left untouched and :class:`FixError` names it.
    """
    root = Path(root)
    by_file: dict = {}
    whole_file = []
    for rel, line, fix in fixes:
        if fix and fix[0] in FILE_ACTIONS:
            whole_file.append(tuple(fix))
        else:
            by_file.setdefault(rel, []).append((int(line), tuple(fix)))
    changed = _apply_file_fixes(root, whole_file, backup_dir)
    for rel, items in sorted(by_file.items()):
        path = (root / rel).resolve()
        if root.resolve() not in path.parents:
            raise FixError(f"{rel} is outside the project")
        data = path.read_bytes().decode("latin-1")
        lines = data.splitlines(keepends=True)
        try:
            for line, fix in sorted(items, key=lambda item: item[0], reverse=True):
                _apply_to_lines(lines, line, fix)
        except FixError as exc:
            raise FixError(f"{rel}: {exc}. Run validation again before fixing.") from None
        if backup_dir is not None:
            target = Path(backup_dir) / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
        tmp = path.with_name(path.name + ".fixtmp")
        tmp.write_bytes("".join(lines).encode("latin-1"))
        os.replace(tmp, path)
        changed.append(rel)
    return changed


def _inside(root: Path, rel: str) -> Path:
    path = (root / rel).resolve()
    if root.resolve() not in path.parents:
        raise FixError(f"{rel} is outside the project")
    return path


def _apply_file_fixes(root: Path, fixes: List[tuple], backup_dir) -> List[str]:
    from battlezone.terrain.lgt import rebake_lgt_file

    changed = []
    for fix in dict.fromkeys(fixes):                    # a shared LGT can be listed twice
        action, source, target = fix[0], fix[1], fix[2]
        if action != "rebake-lgt":
            raise FixError(f"Unknown fix action {action!r}")
        hg2, lgt = _inside(root, source), _inside(root, target)
        if not hg2.is_file():
            raise FixError(f"{source} no longer exists. Run validation again before fixing.")
        if backup_dir is not None and lgt.is_file():
            backup = Path(backup_dir) / target
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(lgt, backup)
        try:
            rebake_lgt_file(hg2, lgt)
        except (OSError, ValueError) as exc:
            raise FixError(f"{target}: {exc}") from None
        changed.append(target)
    return changed
