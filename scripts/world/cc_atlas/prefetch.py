"""Mirror just the source textures the build needs onto local disk, at tile size.

The CC art lives in Google Drive, and reading it straight from there is what the
build is actually limited by: seven encoder processes sat at 16% CPU while
GoogleDriveFS burned 820 seconds streaming 2048-square TGAs on demand. Pulling
each file once, in parallel (the wait is I/O, not CPU), and writing a 1024 PNG
beside it in a local mirror turns a Drive-bound build into a CPU-bound one.

The mirror keeps the source tree's relative paths, so load_source finds the PNG
by its own extension search with nothing to change in the builder.
"""
import os, sys
from concurrent.futures import ThreadPoolExecutor

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from worlds2 import CC_ROOT, WORLDS

Image.MAX_IMAGE_PIXELS = None
CACHE = os.path.join(HERE, "cache")
SUFFIX = ("", "_n", "_s", "_e")
EXT = (".tga", ".png", ".dds", ".bmp")
TILE = 1024


def jobs():
    rels = []
    for cfg in WORLDS.values():
        rels += [r for r in cfg["types"].values() if r != "keep"]
        rels += list(cfg.get("pool", []))
        rels += list(cfg.get("explicit", {}).values())
    out = []
    for rel in dict.fromkeys(rels):
        stem = os.path.splitext(rel)[0]
        for suf in SUFFIX:
            out.append((stem, suf))
    return out


def fetch(job):
    stem, suf = job
    dst = os.path.join(CACHE, (stem + suf).replace("/", os.sep) + ".png")
    if os.path.exists(dst):
        return "cached"
    src = None
    for e in EXT:
        p = os.path.join(CC_ROOT, (stem + suf).replace("/", os.sep) + e)
        if os.path.exists(p):
            src = p
            break
    if src is None:
        return "absent"
    im = Image.open(src)
    im.load()
    # keep alpha: the interior-prop _e maps carry their glow shape in it
    im = im.convert("RGBA")
    if im.size[0] > TILE:
        im = im.resize((TILE, TILE), Image.LANCZOS)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    im.save(dst)
    return "fetched"


if __name__ == "__main__":
    js = jobs()
    counts = {}
    with ThreadPoolExecutor(max_workers=16) as ex:
        for i, r in enumerate(ex.map(fetch, js)):
            counts[r] = counts.get(r, 0) + 1
            if (i + 1) % 25 == 0:
                print(f"{i+1}/{len(js)} {counts}", flush=True)
    print(len(js), counts)
