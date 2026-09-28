"""``bztoolbox odf stats`` / ``odf show``: :mod:`battlezone.odf.explorer` with the configured game install.

The stock ODFs come from the first Redux install with a ``bzone.zfs``: the
Settings game folder, else a detected Steam/GOG install. ``--game`` overrides it.
"""

from __future__ import annotations

from typing import Optional, Sequence

from battlezone.odf import explorer


def default_game_dir(settings=None) -> Optional[str]:
    """The Redux install whose ``bzone.zfs`` supplies stock ODFs, or None."""
    candidates = []
    try:
        if settings is None:
            from bztoolbox.settings import Settings

            settings = Settings()
        configured = str(settings.get("game_dir", "") or "").strip()
        if configured:
            candidates.append(configured)
    except Exception:
        pass
    try:
        from bztoolbox import external

        candidates += [str(path) for path in external.detect_game_installs()]
    except Exception:
        pass
    return next((c for c in candidates if explorer.find_stock_archive(c)), None)


def stats_main(argv: Optional[Sequence[str]] = None) -> int:
    return explorer.stats_main(argv, game_dir=default_game_dir())


def show_main(argv: Optional[Sequence[str]] = None) -> int:
    return explorer.show_main(argv, game_dir=default_game_dir())
