"""Emit the README's world table straight from the build reports."""
import glob, json, os, struct, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from worlds2 import MOD_DIR, WORLDS

OLD = os.environ.get("CC_OLD_ATLASES", os.path.join(
    os.path.dirname(MOD_DIR), "ISDF Chronicles Atlas Rebuild", "atlases"))


def dims(path):
    b = open(path, "rb").read(32)
    h, w = struct.unpack_from("<II", b, 12)
    return w


def old_tile(mat):
    d = os.path.join(OLD, mat)
    g = glob.glob(os.path.join(d, "*_ATLAS_D.dds"))
    if not g:
        return None, None, None
    w = dims(g[0])
    rows = [l.split(",") for l in open(os.path.join(d, mat + ".csv")) if l.strip()]
    grid = int(round(1 / float(rows[0][3])))
    named = len([r for r in rows if r[0]])
    mb = sum(os.path.getsize(p) for p in glob.glob(os.path.join(d, "*.dds"))) / 1048576
    return w // grid, named / (grid * grid), mb


def main(root):
    reps = json.load(open(os.path.join(root, "all_reports.json")))
    print("| material | world | types | grid | tile px | atlas | full | set |")
    print("|---|---|---|---|---|---|---|---|")
    tot_new = tot_old = 0
    for mat, cfg in WORLDS.items():
        r = reps.get(mat)
        if not r:
            continue
        mb = sum(r["atlas_" + c]["bytes"] for c in "DNSE") / 1048576
        tot_new += mb
        otile, occ, omb = old_tile(mat)
        tot_old += omb or 0
        was = (f"{otile} px, {occ:.0%} full, {omb:.0f} MB" if otile else "new")
        print(f"| `{mat}` | {cfg['world']} | {len(cfg['types'])} | {r['grid']}x{r['grid']} "
              f"| {r['tile_px']} | {r['atlas_px']}² | {r['occupancy']:.0%} | {mb:.0f} MB |")
    print(f"\nnew total {tot_new:.0f} MB, previous rebuild {tot_old:.0f} MB")
    print("\n| world | was | now |")
    print("|---|---|---|")
    for mat, cfg in WORLDS.items():
        r = reps.get(mat)
        if not r:
            continue
        otile, occ, omb = old_tile(mat)
        if not otile:
            continue
        print(f"| {cfg['world']} | {otile} px tiles, {occ:.0%} of an "
              f"{otile*8}² atlas used | {r['tile_px']} px tiles, "
              f"{r['occupancy']:.0%} of {r['atlas_px']}² |")


if __name__ == "__main__":
    main(sys.argv[1])
