"""Rebuild every Combat Commander world atlas tight, at the largest tile the budget allows.

Two things change against build_world.py.

*The grid is no longer inherited from the world's existing .csv.* Those grids are
8x8 carrying 25 tiles -- 39% of the cells hold art and the rest is black, because
the layout was drawn by hand in an image editor and the CSV written to match. Here
the grid is ceil(sqrt(tiles)) and every spare cell is filled with a tile worth
having, so atlas area buys texels instead of padding. n blend types produce
exactly n*n tiles, so a world whose types all blend comes out an exactly full
n x n grid.

*The tile size comes from the atlas budget, not from what the world shipped.*
1024 px while the grid fits in 8x8, 512 beyond. The source art is 2048 square
throughout, so 1024 is 4x stock's 256 and 2x the first rebuild, while the atlas
stays at or under 8192 -- which is the dimension the same mod already ships
uncompressed, so nothing here is new ground for a 32-bit process.

Everything else -- the mask contract, the four channels composited through one
shared mask, alpha-premultiplied emissive, the mip floor at 4 px per tile -- is
build_world.py's and unchanged.
"""
import json, math, os, re, sys
import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
import bc1, masks as maskgen
from ddswrite import write_dxt1
from build_world import (CHANNELS, DEFAULT, MATERIAL_TEMPLATE, _renorm, cut_existing,
                         downsample, load_source, read_csv, read_material)
from worlds2 import CC_ROOT, MOD_DIR, WORLDS

Image.MAX_IMAGE_PIXELS = None

# The CC art lives in Google Drive and reading it there is what limits the build
# (see prefetch.py).  Once the local mirror exists, read from it.
CACHE = os.path.join(HERE, "cache")
SRC_ROOT = CACHE if os.path.isdir(CACHE) else CC_ROOT

MAX_ATLAS = 8192          # every channel of every world stays at or under this
MAX_TILE = 1024           # past here the win is invisible and the cost is not
TILE_RE = re.compile(r"^([a-z]+)(\d)(\d)([scd])(\d)$", re.I)


# --------------------------------------------------------------------- planning

def plan_tiles(mat, cfg, required):
    """Decide what every cell of the atlas holds.

    Returns an ordered list of dicts, one per cell, and the reason each tile is
    there -- 'core' for the full matrix, 'required' for a name some .trn already
    asks for, 'fill' for a tile added because the grid had a cell going spare.
    """
    types, blend = cfg["types"], cfg["blend"]
    pre = cfg["tile"]
    tiles, seen = [], set()

    def add(i, j, kind, var, why, src=None, seed_bump=0):
        name = f"{pre}{i}{j}{kind}{var}"
        if name in seen:
            return False
        seen.add(name)
        tiles.append(dict(name=name, i=i, j=j, kind=kind, var=var, why=why,
                          src=src, seed_bump=seed_bump))
        return True

    # 1. the matrix: every type's first solid, then a cap and a diagonal for each
    #    unordered pair of blend types.  Ordered type-major so the CSV reads the
    #    way the hand-built ones did.
    for i in sorted(types):
        add(i, i, "s", 1, "core")
        if i in blend:
            for j in sorted(j for j in blend if j > i):
                add(i, j, "c", 1, "core")
                add(i, j, "d", 1, "core")

    # 2. names a .trn already references that the matrix does not produce -- the
    #    extra solid variants core.trn has been asking for and never getting.
    for name in sorted(required):
        m = TILE_RE.match(name)
        if not m or name in seen:
            continue
        i, j, kind, var = int(m.group(2)), int(m.group(3)), m.group(4).lower(), int(m.group(5))
        add(i, j, kind, var, "required", src=cfg.get("explicit", {}).get(name))

    # A world that already has .trn files gets the smallest grid that holds the
    # matrix and nothing more.  Everything added below is inert until a .trn
    # names it, so growing the atlas 6x6 -> 7x7 to carry spare variants would be
    # a third more memory for tiles nothing draws yet.  A brand-new world has no
    # .trn to be compatible with, so there the grid grows to hold every texture
    # the world ships.
    pool = list(cfg.get("pool", []))
    want = len(tiles) + (len(pool) if cfg.get("new") else 0)
    grid = max(1, math.ceil(math.sqrt(want)))
    spare = grid * grid - len(tiles)

    # 3. spare cells, most useful first: unused source art as extra solid
    #    variants, then second cap/diagonal variants (a fresh mask seed on the
    #    same pair, which is what stock's CapTo2_B0 slots are for), then a
    #    rotation of the type's own solid.
    blendable = sorted(blend) or sorted(types)

    def next_var(i, kind, j=None):
        j = i if j is None else j
        v = 1
        while f"{pre}{i}{j}{kind}{v}" in seen:
            v += 1
        return v

    k = 0
    while spare > 0 and pool:
        i = blendable[k % len(blendable)]
        k += 1
        if add(i, i, "s", next_var(i, "s"), "fill", src=pool.pop(0)):
            spare -= 1

    pairs = [(i, j) for i in blendable for j in blendable if j > i]
    for v in (2, 3):
        for (i, j) in pairs:
            for kind in ("c", "d"):
                if spare <= 0:
                    break
                if add(i, j, kind, next_var(i, kind, j), "fill", seed_bump=v):
                    spare -= 1
    # A second solid for a type with no spare source art would otherwise be a
    # byte-for-byte copy of the first, which is the one thing a variant must not
    # be: the .trn picks between them per cell to break up repetition.  Rotate.
    for t in tiles:
        if t["kind"] == "s" and t["var"] > 1 and t["src"] is None:
            t["src"] = "rot%d" % (1 + (t["var"] - 2) % 3)

    rot = 1
    while spare > 0:
        for i in blendable:
            if spare <= 0:
                break
            if add(i, i, "s", next_var(i, "s"), "fill", src=("rot%d" % rot)):
                spare -= 1
        rot += 1
        if rot > 3:
            break
    return tiles, grid


def pick_tile_px(grid):
    px = MAX_TILE
    while grid * px > MAX_ATLAS and px > 4:
        px //= 2
    return px


# ---------------------------------------------------------------------- imaging

def rot_normal(a, k):
    """Rotate a tile by k*90 degrees CCW, rotating the tangent-space vector with it.

    Turning the image without turning the normal's XY leaves every slope lit from
    the wrong side, which reads as a lighting error rather than as a variant.
    """
    out = np.rot90(a, k)
    v = out.astype(np.float32) - 128.0
    for _ in range(k % 4):
        v[..., 0], v[..., 1] = v[..., 1].copy(), -v[..., 0].copy()
    return np.clip(v + 128.0, 0, 255)


def build(mat, cfg, out_dir, required, tile_px=None, quiet=False):
    os.makedirs(out_dir, exist_ok=True)
    types, pre = cfg["types"], cfg["tile"]
    plan, grid = plan_tiles(mat, cfg, required)
    tile_px = tile_px or pick_tile_px(grid)
    atlas_px = grid * tile_px

    # lighting and the detail map come from the world's own material where it has
    # one; a brand-new world gets the values declared in worlds2.py
    old_mat = os.path.join(MOD_DIR, mat + ".material")
    if os.path.exists(old_mat):
        tex, setv = read_material(old_mat)
    else:
        tex, setv = {}, dict(cfg.get("lighting", {}))
    old_csv = os.path.join(MOD_DIR, mat + ".csv")
    solid_rect = {}
    if os.path.exists(old_csv):
        rows = [r for r in read_csv(old_csv) if r[0]]
        for name, u, v, du, dv in rows:
            m = TILE_RE.match(name)
            if m and m.group(4).lower() == "s" and m.group(2) == m.group(3):
                solid_rect.setdefault(int(m.group(2)), (u, v, du, dv))

    # Most worlds read from the CC tree (or its local mirror); a world that
    # carries its own `root` -- Mercury comes from Forgotten Enemies Remastered,
    # not Combat Commander -- reads from that instead.
    root = cfg.get("root", SRC_ROOT)

    placements = [(t["name"], n % grid, n // grid) for n, t in enumerate(plan)]
    report = dict(material=mat, world=cfg["world"], grid=grid, tile_px=tile_px,
                  atlas_px=atlas_px, types={str(k): v for k, v in sorted(types.items())},
                  blend=cfg["blend"], cells=grid * grid, tiles=len(plan),
                  src_root=root,
                  occupancy=round(len(plan) / (grid * grid), 4),
                  added=[dict(name=t["name"], why=t["why"], src=t["src"]) for t in plan
                         if t["why"] != "core"])

    for ch in CHANNELS:
        src, found = {}, {}
        for i, rel in sorted(types.items()):
            if rel == "keep":
                src[i], found[i] = cut_existing(
                    MOD_DIR, tex, ch, solid_rect.get(i, (0, 0, 1.0 / grid, 1.0 / grid)), tile_px)
            else:
                src[i], found[i] = load_source(root, rel, ch, tile_px,
                                               cfg.get("emissive_scale", 1.0),
                                               cfg.get("specular_scale", 1.0))
        extra = {}
        for t in plan:
            s = t["src"]
            if s and not s.startswith("rot") and s not in extra:
                extra[s], _ = load_source(root, s, ch, tile_px,
                                          cfg.get("emissive_scale", 1.0),
                                          cfg.get("specular_scale", 1.0))

        # solids first: a transition in slot B has to blend the *B* solids of its
        # two types, because that is the pair the engine puts either side of it
        # when it picks slot B for a cell.  Blending the A art into a B cap is
        # what makes the seam classifier -- and the eye -- see a mismatch.
        tiles = {}
        for t in plan:
            if t["kind"] != "s":
                continue
            base = src.get(t["i"], np.full((tile_px, tile_px, 3), DEFAULT[ch], np.float32))
            s = t["src"]
            if s is None:
                a = base
            elif s.startswith("rot"):
                k = int(s[3:])
                a = rot_normal(base, k) if ch == "N" else np.rot90(base, k)
            else:
                a = extra[s]
            tiles[t["name"]] = np.ascontiguousarray(np.clip(a, 0, 255).astype(np.uint8))

        def solid(i, var):
            """The type's own art at that slot, falling back to slot A."""
            for v in range(var, 0, -1):
                t = tiles.get(f"{pre}{i}{i}s{v}")
                if t is not None:
                    return t.astype(np.float32)
            return src.get(i, np.full((tile_px, tile_px, 3), DEFAULT[ch], np.float32))

        for t in plan:
            if t["kind"] == "s":
                continue
            i, j, var = t["i"], t["j"], t["var"]
            a, b = solid(i, var), solid(j, var)
            seed = 1000 * i + 10 * j + (0 if t["kind"] == "c" else 1) + 100000 * t["seed_bump"]
            msk = (maskgen.cap_mask(tile_px, seed) if t["kind"] == "c"
                   else maskgen.diagonal_mask(tile_px, seed))[..., None]
            out = a * (1.0 - msk) + b * msk
            if ch == "N":
                out = _renorm(out)
            tiles[t["name"]] = np.clip(out, 0, 255).astype(np.uint8)

        levels, n, peak = [], tile_px, 0.0
        while n >= 4:
            canvas = np.zeros((grid * n, grid * n, 3), np.uint8)
            for name, c, r in placements:
                t = tiles[name] if n == tile_px else downsample(tiles[name].astype(np.float32), n, ch)
                canvas[r * n:(r + 1) * n, c * n:(c + 1) * n] = np.clip(t, 0, 255).astype(np.uint8)
            if n == tile_px:
                peak = float(canvas.max())
                report["mean_" + ch] = round(float(np.mean(
                    [float(tiles[name].mean()) for name, _, _ in placements])), 2)
            levels.append(bc1.encode_bc1(canvas))
            del canvas
            n //= 2
        if ch == "E" and peak <= 2.0:
            report["atlas_E"] = dict(file="black.dds", mips=0, bytes=0,
                                     sources_found=0, of=len(types), skipped=True)
            continue
        path = os.path.join(out_dir, cfg["prefix"] + "_ATLAS_" + ch + ".dds")
        write_dxt1(path, atlas_px, atlas_px, levels)
        report["atlas_" + ch] = dict(file=os.path.basename(path), mips=len(levels),
                                     bytes=os.path.getsize(path),
                                     sources_found=sum(found.values()), of=len(types))
        if not quiet:
            print(f"   {mat} {ch} {atlas_px}^2 {os.path.getsize(path)/1048576:.1f} MB", flush=True)

    step = 1.0 / grid
    lines = [",0,0,%g,%g" % (step, step)]
    lines += ["%s.map,%g,%g,%g,%g" % (n, c * step, r * step, step, step)
              for n, c, r in placements]
    with open(os.path.join(out_dir, mat + ".csv"), "w", newline="\r\n") as f:
        f.write("\n".join(lines) + "\n")

    # a brand-new world has no detail map of its own; it borrows the stock one
    # closest in character, which is a plain high-frequency overlay either way
    detail = tex.get("detailmap", cfg.get("detail", "ma_detail.dds"))
    keep = [(k, setv[k]) for k in ("ambient", "diffuse", "specular", "shininess", "bias", "glow")
            if setv.get(k)]
    body = "\n".join('\tset $%-9s "%s"' % (k, v) for k, v in keep)
    with open(os.path.join(out_dir, mat + ".material"), "w", newline="\r\n") as f:
        f.write(MATERIAL_TEMPLATE.format(name=mat.upper(), prefix=cfg["prefix"],
                                         detail=detail,
                                         emissive=report["atlas_E"]["file"], body=body))
    write_trn_entries(os.path.join(out_dir, "TRN_Entries.txt"), cfg, plan, mat)
    json.dump(report, open(os.path.join(out_dir, "build_report.json"), "w"), indent=1)
    return report


def write_trn_entries(path, cfg, plan, mat):
    """The [TextureType] blocks that name every tile in the atlas.

    A tile the .trn never names is dead weight, and every fill tile added here is
    new, so the world's .trn has to gain a line before it can draw one. Written
    out per type, ready to paste.
    """
    pre, slot = cfg["tile"], "ABCD"
    by = {}
    for t in plan:
        by.setdefault(t["i"], []).append(t)
    out = [f"; [Atlases] block and TextureType entries for {mat}",
           "; lines marked 'new' name a tile this rebuild added -- the world's",
           "; .trn has to gain them before the engine can draw one.",
           ";", "[Atlases]", f"MaterialName = {mat.upper()}", ""]
    for i in sorted(by):
        out.append(f"[TextureType{i}]")
        out.append("FlatColor= 128")
        for t in sorted(by[i], key=lambda t: (t["kind"] != "s", t["j"], t["kind"], t["var"])):
            if t["var"] > len(slot):
                out.append(f"; {t['name']}.map -- variant {t['var']} has no .trn slot")
                continue
            key = ("Solid%s" % slot[t["var"] - 1] if t["kind"] == "s" else
                   "%sTo%d_%s" % ("Cap" if t["kind"] == "c" else "Diagonal",
                                  t["j"], slot[t["var"] - 1]))
            mark = "" if t["why"] == "core" else "   ; new"
            # all four mip keys name the mip-0 tile, which is what every .trn in
            # this mod already does: Redux reads the *0 key and the atlas mips
            for mip in range(4):
                out.append("%-18s= %s.map%s" % (key + str(mip), t["name"], mark if mip == 0 else ""))
            out.append("")
    open(path, "w", newline="\r\n").write("\n".join(out) + "\n")


if __name__ == "__main__":
    out_root = sys.argv[1]
    only = sys.argv[2:]
    required = json.load(open(os.path.join(HERE, "required.json")))
    for mat, cfg in WORLDS.items():
        if only and mat not in only:
            continue
        rep = build(mat, cfg, os.path.join(out_root, mat), required.get(mat, []))
        tot = sum(rep["atlas_" + c]["bytes"] for c in CHANNELS)
        print("%-24s %5d^2 grid %2d  %3d/%3d cells  %6.1f MB"
              % (mat, rep["atlas_px"], rep["grid"], rep["tiles"], rep["cells"],
                 tot / 1048576), flush=True)
