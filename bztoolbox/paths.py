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


# Secrets kept in the OS credential store rather than in the data directory
# (service, account). The Publish page stores the Steam Web API key here.
CREDENTIALS = (("BattlezoneWorkshopUploader", "steam_web_api_key"),)


def remove_user_data(*, credentials: bool = True) -> list[str]:
    """Delete everything the toolbox stored for this user; return what went.

    Used by ``bztoolbox clean-user-data`` and by the Windows uninstaller when
    the user asks for their settings to be removed too.
    """
    import shutil

    removed: list[str] = []
    base = user_data_dir()
    home = Path.home().resolve()
    resolved = base.resolve()
    # BZTOOLBOX_HOME can point anywhere: never wipe a drive root or the home folder.
    if resolved == Path(resolved.anchor) or resolved == home or resolved in home.parents:
        raise ValueError(f"refusing to delete {resolved}: not a toolbox data folder")
    shutil.rmtree(base, ignore_errors=True)
    if not base.exists():
        removed.append(str(base))
    if credentials:
        try:
            import keyring
        except ImportError:
            return removed
        for service, account in CREDENTIALS:
            try:
                keyring.delete_password(service, account)
            except Exception:  # noqa: BLE001 - absent entry or no backend
                continue
            removed.append(f"credential {service}/{account}")
    return removed
