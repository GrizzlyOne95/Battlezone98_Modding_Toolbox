"""Check rewritten .trn files against the atlases they bind.

Three ways a .trn can be wrong that nothing else catches, all of them silent in
game:

  - it names a tile the CSV does not carry, which draws the default tile;
  - it leaves a tile in the atlas unnamed, which is memory nothing draws;
  - it disagrees with the original above the first [TextureType, which would
    mean the rebuild edited the map author's fog, sky or palette.
"""
import os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from worlds2 import MOD_DIR

MAPS = re.compile(r"=\s*([A-Za-z0-9_]+)\.map", re.I)
HEAD = re.compile(r"^\[TextureType\d+\]", re.I | re.M)


def split(path):
    """(everything above the first [TextureType, everything from it on).

    [Sky] and [Stars] name .map files too -- sky boxes, moons, nebulae, god
    rays -- and none of those are atlas tiles, so only the second half is the
    atlas's business."""
    t = open(path, "r", encoding="latin-1", newline="").read()
    m = HEAD.search(t)
    return (t, "") if not m else (t[:m.start()], t[m.start():])


def main(new_trn_dir, atlas_root, mod_dir=MOD_DIR):
    bad = 0
    for fn in sorted(os.listdir(new_trn_dir)):
        if not fn.lower().endswith(".trn"):
            continue
        new = os.path.join(new_trn_dir, fn)
        old = os.path.join(mod_dir, fn)
        nhead, nbody = split(new)
        mat = re.search(r"MaterialName\s*=\s*(\S+)", nhead, re.I).group(1).lower()
        csv = os.path.join(atlas_root, mat, mat + ".csv")
        cells = {l.split(",")[0].replace(".map", "").lower()
                 for l in open(csv) if l.split(",")[0].strip()}
        named = {n.lower() for n in MAPS.findall(nbody)}

        miss = sorted(named - cells)
        unused = sorted(cells - named)
        drift = os.path.exists(old) and split(old)[0] != nhead
        ok = not miss and not drift
        print("%-14s %-22s %3d named / %3d cells   %s" % (
            fn, mat, len(named), len(cells), "OK" if ok else "FAIL"))
        for n in miss:
            print("      names %s.map, not in the atlas" % n)
        if drift:
            print("      header above [TextureType0] differs from the original")
        if unused:
            print("      %d atlas cells unnamed: %s" % (
                len(unused), ", ".join(unused[:6]) + ("..." if len(unused) > 6 else "")))
        bad += len(miss) + (1 if drift else 0)
    print("\n%s" % ("all clean" if not bad else "%d problems" % bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2],
                  sys.argv[3] if len(sys.argv) > 3 else MOD_DIR))
