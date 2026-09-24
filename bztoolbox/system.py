"""Small OS integration helpers that need no GUI toolkit."""

from __future__ import annotations

import os
import subprocess
import sys


def open_in_file_manager(path: str) -> None:
    """Open ``path`` with the system: a folder in Explorer/Finder/the file
    manager, a file in its default application."""
    if not path or not os.path.exists(path):
        return
    if sys.platform == "win32":
        os.startfile(path)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])
