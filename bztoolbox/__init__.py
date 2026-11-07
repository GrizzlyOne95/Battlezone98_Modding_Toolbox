"""Battlezone Modding Toolbox: one application for Battlezone 98 Redux modding."""

from pathlib import Path

APP_NAME = "Battlezone Modding Toolbox"
APP_ID = "GrizzlyOne95.BattlezoneModdingToolbox"


def _git_version(repo: Path) -> str:
    """``0.1.37`` on a release tag, ``0.1.37+3.gabc1234`` past it; "" outside a git checkout.

    CI stamps VERSION only in release builds, so a source checkout's VERSION
    file holds a placeholder; the newest ``v*`` tag is the real version.
    """
    if not (repo / ".git").exists():
        return ""
    import re
    import subprocess

    try:
        out = subprocess.run(
            ["git", "-C", str(repo), "describe", "--tags", "--match", "v[0-9]*"],
            capture_output=True, text=True, timeout=3,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""
    match = re.fullmatch(r"v(\d+\.\d+\.\d+)(?:-(\d+)-(g[0-9a-f]+))?", out)
    if not match:
        return ""
    base, ahead, sha = match.groups()
    return f"{base}+{ahead}.{sha}" if ahead else base


def _version_key(text: str) -> tuple:
    try:
        return tuple(int(part) for part in text.split("+")[0].split("."))
    except ValueError:
        return ()


def _read_version() -> str:
    for candidate in (Path(__file__).with_name("VERSION"), Path(__file__).parents[1] / "VERSION"):
        try:
            stamped = candidate.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        from_git = _git_version(Path(__file__).parents[1])
        # A VERSION set ahead of the latest tag (next release) still wins.
        return from_git if from_git and _version_key(from_git) >= _version_key(stamped) else stamped
    try:  # installed as a wheel
        from importlib.metadata import version

        return version("battlezone-modding-toolbox")
    except Exception:  # noqa: BLE001
        return "0.0.0"


__version__ = _read_version()
