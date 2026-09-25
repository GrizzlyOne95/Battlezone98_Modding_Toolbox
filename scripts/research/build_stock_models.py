"""Build battlezone/validation/data/stock_models.json from a Redux install.

The model check needs to know which parts, meshes, skeletons and materials
the stock game already provides, so a mod that uses them is not reported as
missing something. Only names are recorded, never file contents:

* ``geo`` / ``vdf`` / ``sdf``: members of ``bzone.zfs``;
* ``mesh`` / ``skeleton``: files under ``BZ_ASSETS`` and ``BZ_ASSETS_CORE``;
* ``materials``: every ``material <name>`` defined in their ``.material`` files.

Usage::

    python scripts/research/build_stock_models.py "<Battlezone 98 Redux install>"

Point it at an unmodded install; anything a mod has added there is recorded
as stock.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from battlezone.archives.zfs import ZFSArchive  # noqa: E402

OUTPUT = ROOT / "battlezone" / "validation" / "data" / "stock_models.json"
ASSET_DIRS = ("BZ_ASSETS", "BZ_ASSETS_CORE")
_MATERIAL_DEF = re.compile(r"^\s*material\s+([^\s:{]+)", re.I | re.M)


def build(install: Path) -> dict:
    out = {key: set() for key in ("geo", "vdf", "sdf", "mesh", "skeleton", "materials")}
    for entry in ZFSArchive(install / "bzone.zfs").entries:
        name = entry.name.lower()
        ext = name.rsplit(".", 1)[-1]
        if ext in ("geo", "vdf", "sdf"):
            out[ext].add(name)
    for folder in ASSET_DIRS:
        for path in sorted((install / folder).rglob("*")):
            if not path.is_file():
                continue
            ext = path.suffix.lower().lstrip(".")
            if ext in ("mesh", "skeleton"):
                out[ext].add(path.name.lower())
            elif ext == "material":
                text = path.read_text(encoding="latin-1", errors="ignore")
                out["materials"].update(name.strip("\"").lower() for name in _MATERIAL_DEF.findall(text))
    return {key: sorted(values) for key, values in out.items()}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("install", type=Path, help="Battlezone 98 Redux install folder")
    args = parser.parse_args()
    data = build(args.install)
    OUTPUT.write_text(json.dumps(data, indent=0) + "\n", encoding="utf-8")
    print(OUTPUT, {key: len(values) for key, values in data.items()})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
