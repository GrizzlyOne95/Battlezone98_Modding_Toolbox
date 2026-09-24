"""Old atlas vs new, at the same on-screen size, for one tile of each world.

The number that matters is texels per tile: the hand-built atlases and the first
rebuild both put 25-32 tiles in an 8x8 grid, so a 2048 atlas gave each tile 256
texels and over half the image was black. Cutting the same tile out of both and
showing it at the same size is what makes the difference legible.
"""
import glob, os, struct, sys

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
import bc1
from worlds2 import MOD_DIR, WORLDS

Image.MAX_IMAGE_PIXELS = None
OLD_ROOT = os.environ.get("CC_OLD_ATLASES", os.path.join(
    os.path.dirname(MOD_DIR), "ISDF Chronicles Atlas Rebuild", "atlases"))
SHOW = 256


def load(path):
    b = open(path, "rb").read()
    h, w = struct.unpack_from("<II", b, 12)
    return bc1.decode_bc1(b[128:128 + (w // 4) * (h // 4) * 8], w, h), w


def cell(img, w, grid, name, csv):
    for line in open(csv):
        p = line.strip().split(",")
        if len(p) >= 5 and p[0].replace(".map", "") == name:
            u, v, du = float(p[1]), float(p[2]), float(p[3])
            t = int(round(du * w))
            return img[int(v * w):int(v * w) + t, int(u * w):int(u * w) + t]
    return None


def main(new_root, out_png):
    rows = []
    for mat, cfg in WORLDS.items():
        old_dir = os.path.join(OLD_ROOT, mat)
        new_dir = os.path.join(new_root, mat)
        if not (os.path.isdir(old_dir) and os.path.isdir(new_dir)):
            continue
        name = f"{cfg['tile']}00s1"
        try:
            oi, ow = load(glob.glob(os.path.join(old_dir, "*_ATLAS_D.dds"))[0])
            ni, nw = load(glob.glob(os.path.join(new_dir, "*_ATLAS_D.dds"))[0])
            oc = cell(oi, ow, 0, name, os.path.join(old_dir, mat + ".csv"))
            nc = cell(ni, nw, 0, name, os.path.join(new_dir, mat + ".csv"))
        except Exception as e:
            print("skip", mat, e)
            continue
        if oc is None or nc is None:
            continue
        rows.append((cfg["world"], oc, nc, oc.shape[0], nc.shape[0]))
        print(f"{cfg['world']:11s} {name}: {oc.shape[0]} px -> {nc.shape[0]} px")

    if not rows:
        return
    sheet = Image.new("RGB", (SHOW * 2 + 12, SHOW * len(rows) + 4 * len(rows)), (20, 20, 20))
    for i, (w_, oc, nc, op, np_) in enumerate(rows):
        y = i * (SHOW + 4)
        sheet.paste(Image.fromarray(oc).resize((SHOW, SHOW), Image.NEAREST), (0, y))
        sheet.paste(Image.fromarray(nc).resize((SHOW, SHOW), Image.NEAREST), (SHOW + 12, y))
    sheet.save(out_png)
    print("wrote", out_png, sheet.size)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
