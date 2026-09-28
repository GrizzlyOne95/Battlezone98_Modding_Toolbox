"""``bztoolbox meshes port-legacy``: the Battlezone 1.5 model porter
(:mod:`battlezone.meshes.legacy_port`) with ``--game15 auto`` resolved from the
toolbox's install detection (Settings, Steam/GOG, the usual 1.5 folders).

``scripts/meshes/port_legacy_drop.cmd`` calls this with ``--game15 auto`` so
.vdf/.sdf/.odf/.geo/.map files dropped on it convert beside themselves.
"""

from __future__ import annotations

from typing import Optional, Sequence


def find_legacy_install() -> Optional[str]:
    """The first Battlezone 1.5 install found, or None."""
    try:
        from bztoolbox import launch
        from bztoolbox.settings import Settings

        installs = launch.detect_installs(Settings())
    except Exception:  # noqa: BLE001 - detection is a convenience
        return None
    return next((str(i.path) for i in installs if i.kind == "1.5"), None)


def main(argv: Optional[Sequence[str]] = None) -> int:
    from battlezone.meshes.legacy_port import main as port_main

    return port_main(argv, find_game15=find_legacy_install)
