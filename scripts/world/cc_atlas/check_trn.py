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
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(HERE))))
from battlezone.terrain.atlas import validate_tile_name
from battlezone.terrain.trn import TRNDocument
from worlds2 import MOD_DIR

MAPS = re.compile(r"=\s*([A-Za-z0-9_]+)\.map", re.I)
HEAD = re.compile(r"^\[TextureType\d+\]", re.I | re.M)


def split(path):
    """(everything above the first [TextureType, everything from it on).

    [Sky] and [Stars] name .map files too -- sky boxes, moons, nebulae, god
    rays -- and none of those are atlas tiles, so only the second half is the
    atlas's business."""
    with open(path, "r", encoding="latin-1", newline="") as source:
        t = source.read()
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
        doc = TRNDocument.read(new)
        if len(doc.sections_named("Atlases")) != 1 or not doc.material_name:
            print(f"{fn}: FAIL: requires one [Atlases] section with a non-empty first binding")
            bad += 1
            continue
        mat = doc.material_name.lower()
        csv = os.path.join(atlas_root, mat, mat + ".csv")
        with open(csv, encoding="latin-1") as source:
            cells = {l.split(",")[0].strip().lower().removesuffix(".map")
                     for l in source if l.split(",")[0].strip()}
        named = {n.lower() for n in MAPS.findall(nbody)}

        invalid = []
        for name in sorted(named | cells):
            try:
                validate_tile_name(name + ".map")
            except ValueError as exc:
                invalid.append(str(exc))

        miss = sorted(named - cells)
        unused = sorted(cells - named)
        drift = os.path.exists(old) and split(old)[0] != nhead
        ok = not miss and not drift and not invalid
        print("%-14s %-22s %3d named / %3d cells   %s" % (
            fn, mat, len(named), len(cells), "OK" if ok else "FAIL"))
        for n in miss:
            print("      names %s.map, not in the atlas" % n)
        for error in invalid:
            print("      " + error)
        if drift:
            print("      header above [TextureType0] differs from the original")
        if unused:
            print("      %d atlas cells unnamed: %s" % (
                len(unused), ", ".join(unused[:6]) + ("..." if len(unused) > 6 else "")))
        bad += len(miss) + len(invalid) + (1 if drift else 0)
    print("\n%s" % ("all clean" if not bad else "%d problems" % bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2],
                  sys.argv[3] if len(sys.argv) > 3 else MOD_DIR))
