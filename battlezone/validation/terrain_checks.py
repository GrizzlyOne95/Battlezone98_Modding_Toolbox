"""Terrain checks: light maps, TRN tile coverage and sky sprites.

Each came out of a real mod:

* ``lgt``     - ISDF Chronicles shipped light maps that were one flat value,
  shared between two different missions, or baked from older terrain, so the
  maps looked flat. A light map is compared with the one Redux would bake from
  the map's own HG2 (:func:`battlezone.terrain.lgt.bake_redux_lgt`); the fix
  rebakes it.
* ``tiles``   - an auto-painted MAT asked for tile slots its TRN never defines
  (non-adjacent transitions, a spare type 7). Redux quietly draws the atlas's
  default tile there; Battlezone 1.5 draws its checkerboard.
* ``sprites`` - a TRN ``SunTexture`` names a sprite; one that is neither a
  stock Redux sprite nor in a project ``.sta`` table draws nothing.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Dict, Iterator, List

import numpy as np

from battlezone.images.sprites import read_sta
from battlezone.terrain.hg2 import HG2Map
from battlezone.terrain.lgt import bake_redux_lgt, read_lgt
from battlezone.terrain.mat import defined_slots, mat_slot_usage
from battlezone.terrain.trn import TRNDocument

LGT_MIN_CORRELATION = 0.5
REBAKE_LABEL = "Rebake the LGT from the map's HG2 (Redux stock lighting)"
_DATA = Path(__file__).with_name("data")


def _issue(*args, **kwargs):
    from battlezone.validation.engine import Issue

    return Issue(*args, **kwargs)


def _companion(path: Path, suffix: str) -> Path | None:
    wanted = path.stem.lower()
    for candidate in path.parent.iterdir():
        if candidate.is_file() and candidate.suffix.lower() == suffix and candidate.stem.lower() == wanted:
            return candidate
    return None


def _correlation(a: np.ndarray, b: np.ndarray) -> float:
    a = a.astype(np.float64).ravel() - a.mean()
    b = b.astype(np.float64).ravel() - b.mean()
    denominator = float(np.sqrt((a * a).sum() * (b * b).sum()))
    return float((a * b).sum() / denominator) if denominator else 0.0


def assess_lgt(hg2_path: Path, lgt_path: Path | None):
    """``(rule_id, severity, message)`` for a light map that needs rebaking, else ``None``."""
    try:
        hg2 = HG2Map.read(hg2_path)
    except (OSError, ValueError):
        return None                                     # an unreadable HG2 is not a light-map problem
    if lgt_path is None or not Path(lgt_path).is_file():
        return ("lgt-missing", "info", f"{Path(hg2_path).name} has no .lgt light map; the terrain gets no baked "
                "shading")
    try:
        light, _zx, _zz, cells = read_lgt(lgt_path, hg2.zones_x, hg2.zones_z)
    except (OSError, ValueError) as exc:
        return ("lgt-size", "error", f"Light map does not fit {Path(hg2_path).name}: {exc}")
    if len(np.unique(light)) <= 2:
        return ("lgt-flat", "warning", f"Light map is flat (every cell {int(light.flat[0])}): the terrain gets no "
                "shading")
    expected = bake_redux_lgt(hg2.heights, hg2.zones_x, hg2.zones_z, cells)
    if expected.std() == 0:
        return None                                     # flat terrain: nothing to compare against
    correlation = _correlation(light, expected)
    if correlation < LGT_MIN_CORRELATION:
        return ("lgt-mismatch", "warning",
                f"Light map does not follow {Path(hg2_path).name} (correlation {correlation:.2f} with the shading "
                "baked from it): it is probably from another map or an older version of this terrain")
    return None


_LGT_SUGGESTIONS = {
    "lgt-missing": "Add one: the fix or `bztoolbox terrain relight` bakes it from the HG2.",
    "lgt-size": "Rebake it from the HG2.",
    "lgt-flat": "Rebake it from the HG2.",
    "lgt-mismatch": "Rebake it from the HG2, unless the light map is deliberately different (a story effect).",
}


def check_lgt(ctx) -> Iterator:
    lgt_hashes: Dict[str, List[Path]] = {}
    for hg2_path in ctx.with_suffix(".hg2"):
        ctx.check_cancel()
        lgt_path = _companion(hg2_path, ".lgt")
        rel_hg2 = ctx.rel(hg2_path)
        rel = ctx.rel(lgt_path) if lgt_path else rel_hg2[:-4] + ".lgt"
        problem = assess_lgt(hg2_path, lgt_path)
        if problem is not None:
            rule, severity, message = problem
            yield _issue(severity, "lgt", message, rel if lgt_path else rel_hg2, rule_id=rule,
                         suggestion=_LGT_SUGGESTIONS[rule], fix=("rebake-lgt", rel_hg2, rel, REBAKE_LABEL))
        if lgt_path is not None and (problem is None or problem[0] != "lgt-size"):
            lgt_hashes.setdefault(hashlib.sha1(lgt_path.read_bytes()).hexdigest(), []).append(lgt_path)
    for paths in lgt_hashes.values():
        terrains = {hashlib.sha1(h.read_bytes()).hexdigest() for h in map(lambda p: _companion(p, ".hg2"), paths) if h}
        if len(paths) > 1 and len(terrains) > 1:          # one terrain reused by two missions may share its LGT
            names = ", ".join(p.name for p in paths)
            for path in paths:
                hg2_path = _companion(path, ".hg2")
                yield _issue("warning", "lgt", f"Identical light maps: {names}. Different terrains cannot share "
                             "one", ctx.rel(path), rule_id="lgt-shared", suggestion="Rebake each from its own HG2.",
                             fix=("rebake-lgt", ctx.rel(hg2_path), ctx.rel(path), REBAKE_LABEL) if hg2_path else ())


def check_tiles(ctx) -> Iterator:
    for trn_path in ctx.with_suffix(".trn"):
        ctx.check_cancel()
        mat_path = _companion(trn_path, ".mat")
        if mat_path is None:
            continue
        try:
            doc = TRNDocument.read(trn_path)
            entries = np.fromfile(mat_path, dtype="<u2")
        except OSError:
            continue
        if not doc.texture_types():
            continue
        usage = mat_slot_usage(entries)
        defined = defined_slots(doc)
        beyond = sum(n for (t, _k, o, _v), n in usage.items() if t > 7 or o > 7)
        if beyond:
            yield _issue("error", "tiles", f"{mat_path.name}: {beyond} cell(s) use texture types above 7, which the "
                         "engine cannot draw", ctx.rel(mat_path), rule_id="mat-type-range",
                         suggestion="Repaint those cells with types 0-7.")
        missing: Dict[tuple, int] = {}
        for (t, kind, other, variant), count in usage.items():
            if t <= 7 and other <= 7 and not any((t, kind, other, v) in defined for v in range(variant + 1)):
                missing[(t, kind, other)] = missing.get((t, kind, other), 0) + count
        if not missing:
            continue
        cells = sum(missing.values())
        names = {"S": "Solid", "C": "CapTo", "D": "DiagonalTo"}
        listed = ", ".join(f"[TextureType{t}] {names[k]}{'' if k == 'S' else o}"
                           for (t, k, o) in sorted(missing)[:8]) + (" ..." if len(missing) > 8 else "")
        redux = doc.material_name is not None
        yield _issue(
            "info" if redux else "warning", "tiles",
            f"{mat_path.name}: {cells} cell(s) use {len(missing)} tile slot(s) {trn_path.name} does not define ("
            f"{listed}). " + ("Redux draws the atlas's default tile there; Battlezone 1.5 would draw a checkerboard."
                              if redux else "Battlezone 1.5 draws a checkerboard there."),
            ctx.rel(trn_path), rule_id="trn-undefined-tiles",
            suggestion="Add those keys to the TRN, or repaint the MAT. The Redux -> 1.5 port fills them "
                       "automatically.")


_STOCK_SPRITES: set | None = None


def stock_sprites() -> set:
    global _STOCK_SPRITES
    if _STOCK_SPRITES is None:
        text = (_DATA / "redux_stock_sprites.txt").read_text(encoding="utf-8")
        _STOCK_SPRITES = {line.strip().lower() for line in text.splitlines() if line.strip() and not line.startswith("#")}
    return _STOCK_SPRITES


def check_sprites(ctx) -> Iterator:
    project = set()
    for sta in ctx.with_suffix(".sta"):
        try:
            project |= {e.name.lower() for e in read_sta(sta.read_text(encoding="cp1252", errors="replace"))}
        except OSError:
            continue
    known = stock_sprites() | project
    for trn_path in ctx.with_suffix(".trn"):
        ctx.check_cancel()
        try:
            doc = TRNDocument.read(trn_path)
        except OSError:
            continue
        for section in doc.sections_named("sky"):
            for entry in section.entries:
                if entry.key.lower() != "suntexture":
                    continue
                name = entry.value.strip().strip('"')
                if name and name.lower() not in known:
                    yield _issue("warning", "sprites", f"SunTexture '{name}' is not a stock sprite and no .sta in the "
                                 "project defines it: the sun draws nothing", ctx.rel(trn_path), line=entry.line,
                                 rule_id="trn-unknown-sprite", section="Sky", key="SunTexture",
                                 suggestion="Use a stock sprite such as sun.0, or ship a .sta table that defines it.")
