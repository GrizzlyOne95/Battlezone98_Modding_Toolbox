"""Check GitHub releases for a newer toolbox and fetch the matching download.

GUI-free: the shell runs :func:`check` on a worker thread at startup (at most
once a day, see :data:`CHECK_INTERVAL`) and shows a banner when it returns a
:class:`Update`. Which download fits depends on how this copy was installed
(:func:`install_kind`): the Windows setup for an installed copy, the portable
zip for a portable one, the disk image on macOS, the archive on Linux.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import tempfile
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Optional

from bztoolbox import APP_NAME, __version__

REPOSITORY = "GrizzlyOne95/Battlezone98_Modding_Toolbox"
LATEST_URL = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
RELEASES_PAGE = f"https://github.com/{REPOSITORY}/releases/latest"
CHECK_INTERVAL = 24 * 60 * 60   # seconds between automatic checks
TIMEOUT = 10


@dataclass
class Update:
    version: str
    page_url: str                      # the release's web page (notes)
    download_url: str = ""             # the asset for this install, or "" for the page
    download_name: str = ""
    sha256: str = ""                   # from GitHub's asset digest, when published
    notes: str = ""
    assets: Dict[str, dict] = field(default_factory=dict)

    @property
    def can_install(self) -> bool:
        """True when the download is a Windows setup the toolbox can run itself."""
        return self.download_name.endswith("-windows-setup.exe")


def parse_version(text: str) -> tuple:
    """``v1.2.3`` / ``1.2`` -> (1, 2, 3) / (1, 2, 0); anything else -> ()."""
    match = re.match(r"v?(\d+)(?:\.(\d+))?(?:\.(\d+))?", (text or "").strip())
    return tuple(int(part or 0) for part in match.groups()) if match else ()


def is_newer(candidate: str, current: str = __version__) -> bool:
    new, old = parse_version(candidate), parse_version(current)
    return bool(new) and (not old or new > old)


def install_kind(executable: Optional[str] = None, platform: str = sys.platform,
                 frozen: Optional[bool] = None) -> str:
    """``installed``, ``portable`` (Windows), ``app`` (macOS), ``linux`` or ``source``."""
    if frozen is None:
        frozen = bool(getattr(sys, "frozen", False))
    if not frozen:
        return "source"
    if platform == "win32":
        folder = Path(executable or sys.executable).parent
        return "installed" if (folder / "unins000.exe").exists() else "portable"
    return "app" if platform == "darwin" else "linux"


_ASSET_SUFFIX = {
    "installed": "-windows-setup.exe",
    "portable": "-windows-portable.zip",
    "app": "-macos.dmg",
    "linux": "-linux.tar.gz",
}


def release_to_update(release: dict, kind: str) -> Update:
    tag = release.get("tag_name", "")
    update = Update(version=tag.lstrip("v"), page_url=release.get("html_url") or RELEASES_PAGE,
                    notes=release.get("body") or "")
    for asset in release.get("assets") or []:
        update.assets[asset.get("name", "")] = asset
    suffix = _ASSET_SUFFIX.get(kind)
    for name, asset in update.assets.items():
        if suffix and name.endswith(suffix):
            update.download_url = asset.get("browser_download_url", "")
            update.download_name = name
            digest = asset.get("digest") or ""
            if digest.startswith("sha256:"):
                update.sha256 = digest.split(":", 1)[1].lower()
            break
    return update


def _get_json(url: str, timeout: float = TIMEOUT) -> dict:
    request = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": f"{APP_NAME.replace(' ', '')}/{__version__}",
    })
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed https URL
        return json.loads(response.read().decode("utf-8"))


def fetch_latest(kind: Optional[str] = None, fetch: Callable[[str], dict] = _get_json) -> Update:
    return release_to_update(fetch(LATEST_URL), kind or install_kind())


def check(settings, *, force: bool = False, now: Optional[float] = None,
          fetch: Callable[[str], dict] = _get_json) -> Optional[Update]:
    """A newer release worth telling the user about, or None.

    Unless *force*, respects the ``update_check`` setting, checks at most once
    per :data:`CHECK_INTERVAL` and stays quiet about a version the user chose
    to skip. Network errors propagate (the caller decides whether to show them).
    """
    now = time.time() if now is None else now
    if not force:
        if not settings.get("update_check", True):
            return None
        if now - float(settings.get("update_last_check", 0) or 0) < CHECK_INTERVAL:
            return None
    settings.set("update_last_check", now)
    update = fetch_latest(fetch=fetch)
    if not is_newer(update.version):
        return None
    if not force and update.version == settings.get("update_skipped_version", ""):
        return None
    return update


def download(update: Update, folder: Optional[str] = None,
             progress: Optional[Callable[[int, int], None]] = None) -> Path:
    """Download the update's asset, verify its SHA-256 when known, return the path."""
    if not update.download_url:
        raise ValueError("this release has no download for this platform")
    target_dir = Path(folder or tempfile.mkdtemp(prefix="bztoolbox-update-"))
    target = target_dir / update.download_name
    request = urllib.request.Request(update.download_url, headers={"User-Agent": f"BZModdingToolbox/{__version__}"})
    digest = hashlib.sha256()
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response, open(target, "wb") as out:  # noqa: S310
        total = int(response.headers.get("Content-Length") or 0)
        done = 0
        while True:
            chunk = response.read(1 << 16)
            if not chunk:
                break
            out.write(chunk)
            digest.update(chunk)
            done += len(chunk)
            if progress:
                progress(done, total)
    if update.sha256 and digest.hexdigest() != update.sha256:
        target.unlink(missing_ok=True)
        raise ValueError("the download does not match the checksum GitHub published; try again")
    return target


def launch_installer(path: Path) -> None:
    """Start the Windows setup; it upgrades this install in place once the toolbox exits."""
    os.startfile(str(path))  # type: ignore[attr-defined]  # Windows only
