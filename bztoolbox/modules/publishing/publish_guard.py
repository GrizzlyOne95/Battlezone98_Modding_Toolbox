"""Safety rules for Workshop publishing, kept free of any GUI so they can be tested.

A Workshop *update* replaces the item's whole content for every subscriber, so
the uploader must never publish the wrong folder to an item, or a folder that
would wipe it. This module answers three questions:

* :func:`installed_workshop_matches` - which published items does a local
  folder look like? Steam keeps a copy of every subscribed item in
  ``steamapps/workshop/content/<appid>/<item id>/``; a local folder with the
  same mission ``.ini`` names is almost certainly that item.
* :func:`check_publish` - what stops (``blocks``, never overridable) or must
  be confirmed separately (``confirms``) before a publish?
* :func:`other_folders_for_item` - which other local folders are linked to
  the same Workshop item?
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

# An update that leaves fewer files than this share of the last publish, or
# removes more than this many files, needs its own confirmation.
SHRINK_RATIO = 0.5
MAX_SILENT_REMOVALS = 20


def root_ini_names(folder: str | os.PathLike) -> set:
    """Lower-case names of the ``.ini`` files directly in ``folder`` (the Workshop entry points)."""
    try:
        return {entry.name.lower() for entry in os.scandir(folder)
                if entry.is_file() and entry.name.lower().endswith(".ini")}
    except OSError:
        return set()


def workshop_content_dirs(appid: str) -> List[Path]:
    """Every ``steamapps/workshop/content/<appid>`` folder in the local Steam libraries."""
    from bztoolbox import external

    found: List[Path] = []
    for root in external._steam_roots():
        for library in external._steam_libraries(root):
            candidate = Path(library) / "steamapps" / "workshop" / "content" / str(appid)
            if candidate.is_dir() and candidate not in found:
                found.append(candidate)
    return found


@dataclass
class InstalledMatch:
    item_id: str
    path: str
    shared_ini: List[str]


def installed_workshop_matches(folder: str | os.PathLike, content_dirs: Iterable[str | os.PathLike]) -> List[InstalledMatch]:
    """Installed Workshop items sharing ``.ini`` names with ``folder``, best match first.

    ``folder`` itself (when it *is* the installed copy) is skipped.
    """
    local = root_ini_names(folder)
    if not local:
        return []
    folder_key = os.path.normcase(os.path.abspath(folder))
    matches = []
    for content_dir in content_dirs:
        try:
            entries = list(os.scandir(content_dir))
        except OSError:
            continue
        for entry in entries:
            if not entry.is_dir() or not entry.name.isdigit():
                continue
            if os.path.normcase(os.path.abspath(entry.path)) == folder_key:
                continue
            shared = sorted(local & root_ini_names(entry.path))
            if shared:
                matches.append(InstalledMatch(entry.name, entry.path, shared))
    matches.sort(key=lambda m: len(m.shared_ini), reverse=True)
    return matches


def installed_copy(item_id: str, content_dirs: Iterable[str | os.PathLike]) -> Optional[str]:
    for content_dir in content_dirs:
        candidate = os.path.join(content_dir, str(item_id))
        if os.path.isdir(candidate):
            return candidate
    return None


def other_folders_for_item(item_id: str, folder: str, projects: Sequence[dict]) -> List[str]:
    """Other local folders whose upload profile targets ``item_id``."""
    if not is_item_id(item_id):
        return []
    here = os.path.normcase(os.path.abspath(folder))
    others = []
    for project in projects:
        path = project.get("mod_path", "")
        if str(project.get("item_id", "")).strip() == str(item_id) and path \
                and os.path.normcase(os.path.abspath(path)) != here:
            others.append(path)
    return sorted(set(others))


def is_item_id(value) -> bool:
    text = str(value or "").strip()
    return text.isdigit() and text != "0"


@dataclass
class PublishCheck:
    blocks: List[str] = field(default_factory=list)     # never publishable
    confirms: List[str] = field(default_factory=list)   # each needs an explicit confirmation

    @property
    def ok(self) -> bool:
        return not self.blocks


def _dangerous_folder(folder: str) -> Optional[str]:
    path = Path(folder).resolve()
    if path.parent == path:
        return "the root of a drive"
    try:
        home = Path.home().resolve()
    except (OSError, RuntimeError):
        home = None
    if home is not None and path in (home, home / "Desktop", home / "Documents", home / "Downloads"):
        return "your user folder"
    try:
        from bztoolbox import paths

        data = paths.user_data_dir().resolve()
        if path == data or data in path.parents or path in data.parents:
            return "the toolbox's own data folder"
    except Exception:  # noqa: BLE001 - never let the check itself block a publish
        pass
    return None


def check_publish(folder: str, item_id: str, inventory: Sequence[dict], last_snapshot: Optional[dict],
                  projects: Sequence[dict] = (), content_dirs: Iterable[str | os.PathLike] = ()) -> PublishCheck:
    """Rules for publishing ``folder`` to ``item_id`` ("0" or empty = create a new item)."""
    check = PublishCheck()
    if not folder or not os.path.isdir(folder):
        check.blocks.append("The content folder does not exist.")
        return check
    danger = _dangerous_folder(folder)
    if danger:
        check.blocks.append(f"The content folder is {danger}. Select the mod's own folder.")
    if not inventory:
        check.blocks.append("The content folder is empty. Publishing it would wipe the Workshop item.")
        return check
    local_ini = root_ini_names(folder)
    if not local_ini:
        check.blocks.append("There is no .ini file directly in the content folder, so this is not the root of a "
                            "Battlezone 98 Redux mod (it may be a subfolder or the wrong folder).")

    if not is_item_id(item_id):
        return check

    others = [path for path in other_folders_for_item(item_id, folder, projects) if os.path.isdir(path)]
    if others:
        check.blocks.append(f"Workshop item #{item_id} is linked to another folder:\n  " + "\n  ".join(others)
                            + "\nPublish from that folder, or link this folder to the right item first.")

    installed = installed_copy(item_id, content_dirs)
    if installed and local_ini:
        installed_ini = root_ini_names(installed)
        if installed_ini and not (installed_ini & local_ini):
            check.confirms.append(
                f"Workshop item #{item_id} does not look like this folder: its installed copy has "
                f"{', '.join(sorted(installed_ini)[:4])}, this folder has {', '.join(sorted(local_ini)[:4])}.\n"
                "Publishing replaces that item's content with this folder.")

    if last_snapshot:
        now = {entry["rel_path"] for entry in inventory}
        removed = sorted(set(last_snapshot) - now)
        if len(now) < len(last_snapshot) * SHRINK_RATIO or len(removed) > MAX_SILENT_REMOVALS:
            sample = "\n  ".join(removed[:8]) + ("\n  …" if len(removed) > 8 else "")
            check.confirms.append(
                f"This update removes {len(removed)} of the {len(last_snapshot)} files published last time "
                f"({len(now)} files now). Subscribers lose them:\n  {sample}")
    return check
