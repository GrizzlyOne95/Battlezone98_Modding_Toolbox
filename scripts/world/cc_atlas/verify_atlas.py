"""Check a built atlas against the seam contract measured from stock Redux.

Runs on the decoded DXT1, with the same nearest-of-two classifier used to measure
the nine shipped atlases, so the numbers are directly comparable.

  cap       N ~0%   S 63-99%   W ~0%   E 0-2%
  diagonal  N 0-1%  S 98-100%  W 0-1%  E 97-100%
"""
import glob
import os
import re
import struct
import sys

import numpy as np
from PIL import Image

Image.MAX_IMAGE_PIXELS = None
TILE = re.compile(r"^([a-z]+)(\d)(\d)([scd])(\d)$", re.I)
CONTRACT = {"c": dict(S=(0.60, 1.01), N=(0.0, 0.20), W=(0.0, 0.20), E=(0.0, 0.20)),
            "d": dict(S=(0.60, 1.01), E=(0.60, 1.01), N=(0.0, 0.20), W=(0.0, 0.20))}


def _med3(m):
    p = np.pad(m, 1, mode="edge")
    return np.median(np.stack([p[y:y + m.shape[0], x:x + m.shape[1]]
                               for y in range(3) for x in range(3)]), axis=0)


def verify(out_dir):
    csvs = glob.glob(os.path.join(out_dir, "*.csv"))
    if not csvs:
        return 0, ["no .csv in " + out_dir]
    material = os.path.splitext(os.path.basename(csvs[0]))[0]
    atlases = sorted(glob.glob(os.path.join(out_dir, "*_ATLAS_?.dds")))
    if not atlases:
        return 0, ["no *_ATLAS_?.dds in " + out_dir]
    prefix = os.path.basename(atlases[0]).rsplit("_ATLAS_", 1)[0]

    rows = []
    for line in open(os.path.join(out_dir, material + ".csv")):
        p = line.strip().split(",")
        if len(p) >= 5:
            rows.append((p[0].replace(".map", ""), float(p[1]), float(p[2]),
                         float(p[3]), float(p[4])))
    grid = int(round(1.0 / rows[0][3]))

    fails = []
    for path in atlases:
        ch = path[-5]
        head = open(path, "rb").read(128)
        _, _, h, w, _, _, mips = struct.unpack_from("<7I", head, 4)
        want = 128 + sum(max(1, (w >> i) // 4) * max(1, (h >> i) // 4) * 8 for i in range(mips))
        got = os.path.getsize(path)
        tile = w // grid
        if got != want:
            fails.append(f"{ch}: file is {got} B, header declares {want} B")
        if mips != int(np.log2(tile)) - 1:
            fails.append(f"{ch}: {mips} mips, contract wants "
                         f"{int(np.log2(tile)) - 1} for {tile}px tiles")
        im = Image.open(path)
        im.load()
        if np.asarray(im.convert("RGBA"))[..., 3].min() != 255:
            fails.append(f"{ch}: not fully opaque, so diffuseTex.a would gate the detail map")

    dpath = os.path.join(out_dir, prefix + "_ATLAS_D.dds")
    im = Image.open(dpath)
    im.load()
    a = np.asarray(im.convert("RGB")).astype(np.float32)
    tile = a.shape[0] // grid
    cells = {}
    for name, u, v, du, dv in rows:
        if name:
            cells.setdefault(name, (int(round(v * grid)), int(round(u * grid))))

    def cut(n):
        r, c = cells[n]
        return a[r * tile:(r + 1) * tile, c * tile:(c + 1) * tile]

    checked = 0
    for n in cells:
        m = TILE.match(n)
        if not m or m.group(4).lower() == "s":
            continue
        pfx, i, j, kind = m.group(1), m.group(2), m.group(3), m.group(4).lower()
        sa, sb = f"{pfx}{i}{i}s{m.group(5)}", f"{pfx}{j}{j}s{m.group(5)}"
        if sa not in cells or sb not in cells:
            continue
        ta, tb, tt = cut(sa), cut(sb), cut(n)
        if np.abs(ta - tb).mean() < 4:
            continue                       # the two solids are too alike to classify
        msk = _med3((np.abs(tt - ta).mean(2) > np.abs(tt - tb).mean(2)).astype(np.float32))
        edges = dict(N=msk[0].mean(), S=msk[-1].mean(),
                     W=msk[:, 0].mean(), E=msk[:, -1].mean())
        # The per-pixel vote is only a proxy for "which material does this edge
        # show", and it degrades when the two solids are merely similar rather
        # than identical: Tunnel_2 vs Tunnel_5 differ by 11.9 mean abs, clearing
        # the skip test above, yet enough pixels along the shared edge are nearly
        # equidistant that 42% of them vote the wrong way -- on a column that is
        # byte-for-byte solid B. An edge that matches one solid exactly needs no
        # vote, so take that reading directly when it is available.
        for e, sl in (("N", np.s_[0, :]), ("S", np.s_[-1, :]),
                      ("W", np.s_[:, 0]), ("E", np.s_[:, -1])):
            da, db = np.abs(tt[sl] - ta[sl]).mean(), np.abs(tt[sl] - tb[sl]).mean()
            if min(da, db) < 0.5 and abs(da - db) > 1.0:
                edges[e] = 0.0 if da < db else 1.0
        checked += 1
        for e, (lo, hi) in CONTRACT[kind].items():
            if not lo <= edges[e] <= hi:
                fails.append(f"{n}: {e} edge {edges[e]:.0%}, wants {lo:.0%}-{hi:.0%}")
    return checked, fails


if __name__ == "__main__":
    bad = 0
    for d in sys.argv[1:]:
        checked, fails = verify(d)
        name = os.path.basename(d.rstrip("/\\"))
        print(f"{name:24s} {checked:3d} transition tiles  "
              f"{'PASS' if not fails else str(len(fails)) + ' FAILURES'}")
        for f in fails:
            print("    " + f)
        bad += len(fails)
    sys.exit(1 if bad else 0)
