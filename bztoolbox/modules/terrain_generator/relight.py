"""Rebake LGT light maps from their HG2 terrain, the way Redux's stock maps are lit.

    bztoolbox terrain relight "addon/ISDF Chronicles" --only-broken
    bztoolbox terrain relight misn05.hg2

A folder is searched recursively for ``.hg2`` files; each gets the ``.lgt`` of
the same name beside it. With ``--only-broken`` only light maps the validation
check flags are rebaked: missing, the wrong size, flat, or not following the
terrain (see :func:`battlezone.validation.terrain_checks.assess_lgt`). The old
file is copied to the backup folder first.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional, Sequence

from battlezone.terrain.lgt import rebake_lgt_file
from battlezone.validation.terrain_checks import assess_lgt


@dataclass
class RelightResult:
    rebaked: List[str] = field(default_factory=list)
    kept: List[str] = field(default_factory=list)
    failed: List[str] = field(default_factory=list)
    backup: Optional[Path] = None


def find_terrains(paths: Sequence) -> List[Path]:
    out = []
    for item in paths:
        path = Path(item)
        if path.is_dir():
            out += sorted((p for p in path.rglob("*") if p.is_file() and p.suffix.lower() == ".hg2"),
                          key=lambda p: str(p).lower())
        elif path.suffix.lower() == ".hg2" and path.is_file():
            out.append(path)
    return out


def companion_lgt(hg2: Path) -> Path:
    for candidate in hg2.parent.iterdir():
        if candidate.is_file() and candidate.suffix.lower() == ".lgt" and candidate.stem.lower() == hg2.stem.lower():
            return candidate
    return hg2.with_suffix(".lgt")


def default_backup_dir() -> Path:
    try:
        from bztoolbox import paths

        base = paths.user_data_dir()
    except Exception:
        base = Path.home()
    return Path(base) / "lgt-backups" / time.strftime("%Y%m%d-%H%M%S")


def relight(paths: Sequence, *, only_broken: bool = False, backup_dir=None, dry_run: bool = False,
            log: Optional[Callable[[str], None]] = None) -> RelightResult:
    say = log or (lambda _m: None)
    result = RelightResult(backup=Path(backup_dir) if backup_dir else default_backup_dir())
    for hg2 in find_terrains(paths):
        lgt = companion_lgt(hg2)
        problem = assess_lgt(hg2, lgt if lgt.is_file() else None)
        if only_broken and problem is None:
            result.kept.append(str(lgt))
            continue
        reason = problem[2] if problem else "rebaking on request"
        say(f"{lgt.name}: {reason}")
        if dry_run:
            result.rebaked.append(str(lgt))
            continue
        try:
            if lgt.is_file():
                target = result.backup / hg2.parent.name / lgt.name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(lgt, target)
            rebake_lgt_file(hg2, lgt)
            result.rebaked.append(str(lgt))
        except (OSError, ValueError) as exc:
            result.failed.append(f"{lgt}: {exc}")
    return result


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="bztoolbox terrain relight",
                                     description="Rebake .lgt light maps from their .hg2 terrain with Redux's stock "
                                                 "lighting (sun due east, 80 degrees up).")
    parser.add_argument("paths", nargs="+", help=".hg2 files or folders (searched recursively)")
    parser.add_argument("--only-broken", action="store_true",
                        help="only light maps that are missing, the wrong size, flat or do not follow the terrain")
    parser.add_argument("--backup", help="folder for the old light maps (default: the toolbox data folder)")
    parser.add_argument("--dry-run", action="store_true", help="list what would be rebaked")
    args = parser.parse_args(list(sys.argv[1:] if argv is None else argv))
    result = relight(args.paths, only_broken=args.only_broken, backup_dir=args.backup, dry_run=args.dry_run,
                     log=print)
    verb = "would rebake" if args.dry_run else "rebaked"
    print(f"{verb} {len(result.rebaked)}, kept {len(result.kept)}, failed {len(result.failed)}")
    for failure in result.failed:
        print(f"error: {failure}", file=sys.stderr)
    if result.rebaked and not args.dry_run:
        print(f"old light maps: {result.backup}")
    return 1 if result.failed else 0


if __name__ == "__main__":
    sys.exit(main())
