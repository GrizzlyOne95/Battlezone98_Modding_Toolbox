"""One sweep over a built or staged tree: seam contract, header/mip agreement,
CSV shape, and the zero-file check that a Google Drive copy needs.

verify_atlas.py already covers the seam contract and the DDS header; this adds
the things that only matter once the atlas is packed tight -- that the CSV names
exactly the cells the atlas has, that no cell is empty, and that nothing arrived
as a correctly-sized run of NULs.
"""
import glob, hashlib, json, os, struct, sys

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
import bc1
from verify_atlas import verify

Image.MAX_IMAGE_PIXELS = None


def cells_used(path, grid):
    b = open(path, "rb").read()
    h, w = struct.unpack_from("<II", b, 12)
    n = (w // 4) * (h // 4) * 8
    a = bc1.decode_bc1(b[128:128 + n], w, h).astype(np.float32)
    t = w // grid
    out = []
    for r in range(grid):
        for c in range(grid):
            cell = a[r * t:(r + 1) * t, c * t:(c + 1) * t]
            out.append(float(cell.std()))
    return out


def check(d):
    fails, warns = [], []
    mat = os.path.splitext(os.path.basename(glob.glob(os.path.join(d, "*.csv"))[0]))[0]
    rows = [l.strip().split(",") for l in open(os.path.join(d, mat + ".csv")) if l.strip()]
    named = [r for r in rows if r[0]]
    grid = int(round(1.0 / float(rows[0][3])))
    if not rows[0][0]:
        pass
    else:
        fails.append(f"{mat}: first CSV row is {rows[0][0]}, not the blank default row")
    if len(named) != grid * grid:
        fails.append(f"{mat}: {len(named)} named tiles for {grid*grid} cells -- not full")
    seen = {}
    for r in named:
        key = (r[1], r[2])
        if key in seen:
            fails.append(f"{mat}: {r[0]} and {seen[key]} share cell {key}")
        seen[key] = r[0]

    for p in sorted(glob.glob(os.path.join(d, "*"))):
        if os.path.isdir(p) or os.path.basename(p) == "desktop.ini":
            continue
        b = open(p, "rb").read()
        if not b:
            fails.append(f"{mat}: {os.path.basename(p)} is empty")
        elif not b.strip(b"\0"):
            fails.append(f"{mat}: {os.path.basename(p)} is all NULs "
                         f"({len(b)} B) -- a Drive copy that never carried data")

    n, msgs = verify(d)
    fails += [f"{mat}: {m}" for m in msgs]

    dpath = glob.glob(os.path.join(d, "*_ATLAS_D.dds"))[0]
    stds = cells_used(dpath, grid)
    flat = [i for i, s in enumerate(stds) if s < 0.5]
    if flat:
        fails.append(f"{mat}: {len(flat)} atlas cells are flat colour (cells {flat[:6]})")
    return fails, warns, dict(material=mat, grid=grid, tiles=len(named),
                              transitions=n, min_cell_std=round(min(stds), 2))


if __name__ == "__main__":
    root = sys.argv[1]
    allf, rows = [], []
    for d in sorted(glob.glob(os.path.join(root, "*"))):
        if not os.path.isdir(d) or not glob.glob(os.path.join(d, "*.csv")):
            continue
        f, w, info = check(d)
        allf += f
        rows.append(info)
        print("%-24s grid %d  %3d tiles  %3d transitions  min cell std %5.2f  %s"
              % (info["material"], info["grid"], info["tiles"], info["transitions"],
                 info["min_cell_std"], "FAIL" if f else "ok"))
    print(f"\n{len(rows)} atlases, {len(allf)} failures")
    for f in allf:
        print("  FAIL", f)
