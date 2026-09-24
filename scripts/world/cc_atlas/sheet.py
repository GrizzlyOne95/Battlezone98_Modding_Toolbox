"""One contact sheet of every built atlas, labelled, for eyeballing the whole set.

Each atlas is decoded from its own DXT1 -- not from an intermediate -- so what
the sheet shows is what the engine will sample.
"""
import glob, json, os, struct, sys

import numpy as np
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
import bc1
from worlds2 import WORLDS

CELL = 300


def decode(path):
    b = open(path, "rb").read()
    h, w = struct.unpack_from("<II", b, 12)
    return bc1.decode_bc1(b[128:128 + (w // 4) * (h // 4) * 8], w, h), w


def main(root, out_png, channel="D"):
    tiles = []
    for mat, cfg in WORLDS.items():
        p = os.path.join(root, mat, f"{cfg['prefix']}_ATLAS_{channel}.dds")
        if not os.path.exists(p):
            continue
        a, w = decode(p)
        rep = json.load(open(os.path.join(root, mat, "build_report.json")))
        img = Image.fromarray(a).resize((CELL, CELL), Image.LANCZOS)
        tiles.append((f"{cfg['world']}  {rep['grid']}x{rep['grid']} @ {rep['tile_px']}px"
                      f"  ({w}²)", img))

    cols = 5
    rows = (len(tiles) + cols - 1) // cols
    pad, lab = 8, 18
    sheet = Image.new("RGB", (cols * (CELL + pad) + pad,
                              rows * (CELL + lab + pad) + pad), (18, 18, 20))
    d = ImageDraw.Draw(sheet)
    for i, (name, img) in enumerate(tiles):
        x = pad + (i % cols) * (CELL + pad)
        y = pad + (i // cols) * (CELL + lab + pad)
        sheet.paste(img, (x, y))
        d.text((x + 2, y + CELL + 3), name, fill=(200, 205, 210))
    sheet.save(out_png)
    print(f"{len(tiles)} atlases -> {out_png} {sheet.size}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "D")
