"""Helpers the ZFS and PAK pages share."""

from __future__ import annotations

import os
from pathlib import Path
from tkinter import messagebox
from typing import Iterable, List


def confirm_overwrite(targets: Iterable[Path], out_dir: str) -> bool:
    """Ask before an extract replaces files already in ``out_dir``; True to go ahead."""
    existing: List[Path] = []
    seen = set()
    for target in targets:
        key = os.path.normcase(str(target))
        if key not in seen and target.is_file():
            seen.add(key)
            existing.append(target)
    if not existing:
        return True
    names = "\n".join(str(p.relative_to(out_dir)) if p.is_relative_to(out_dir) else str(p) for p in existing[:10])
    more = f"\n… and {len(existing) - 10} more" if len(existing) > 10 else ""
    return messagebox.askyesno(
        "Replace files?",
        f"{len(existing)} file(s) already exist in\n{out_dir}\nand would be replaced:\n\n{names}{more}\n\n"
        "Replace them?", icon="warning", default="no")


def is_same_or_temp(path: Path, output: str) -> bool:
    """True for the archive being written (or its ``.tmp``), so a pack never includes its own output."""
    out = os.path.normcase(os.path.abspath(output))
    here = os.path.normcase(os.path.abspath(path))
    return here in (out, out + ".tmp")


class Debounce:
    """Call ``func`` once, ``delay_ms`` after the last :meth:`__call__` (keeps typing in a filter smooth)."""

    def __init__(self, widget, func, delay_ms: int = 150):
        self.widget, self.func, self.delay = widget, func, delay_ms
        self._after = None

    def __call__(self, *_args) -> None:
        if self._after is not None:
            try:
                self.widget.after_cancel(self._after)
            except Exception:  # noqa: BLE001 - already ran
                pass
        self._after = self.widget.after(self.delay, self._run)

    def _run(self) -> None:
        self._after = None
        self.func()
