"""Where the toolbox keeps its files.

* Resources ship inside the package (``bztoolbox/resources``) and resolve the
  same way from source and from a PyInstaller bundle, because the bundle keeps
  the package layout.
* Per-user state (settings, project profiles, caches) lives in one user data
  directory instead of beside each executable.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
RESOURCES_DIR = PACKAGE_DIR / "resources"

_APP_DIR_NAME = "BattlezoneModdingToolbox"


def resource(*parts: str) -> Path:
    return RESOURCES_DIR.joinpath(*parts)


def user_data_dir() -> Path:
    override = os.environ.get("BZTOOLBOX_HOME")
    if override:
        base = Path(override)
    elif sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / _APP_DIR_NAME
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / _APP_DIR_NAME
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / _APP_DIR_NAME
    base.mkdir(parents=True, exist_ok=True)
    return base


def projects_dir() -> Path:
    return user_data_dir() / "projects"


def cache_dir() -> Path:
    path = user_data_dir() / "cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


def module_data_dir(module: str) -> Path:
    """Per-module state folder (legacy tool configs, profiles, temp files)."""
    path = user_data_dir() / "modules" / module
    path.mkdir(parents=True, exist_ok=True)
    return path
