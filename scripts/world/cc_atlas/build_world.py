"""Rebuild any ISDF Chronicles terrain atlas set from the Combat Commander source art.

Generalises the Pluto build: the layout, tile names and cell rects come from the
world's existing .csv, so every .trn that binds the material keeps working, and the
existing .material's lighting values are carried forward untouched.  The point is
that normal / specular / emissive come from the *authored* BZ2 maps composited
through the same mask as the diffuse, rather than being derived from the diffuse.
"""
import json, os, re, sys
import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bc1, masks as maskgen
from ddswrite import write_dxt1

Image.MAX_IMAGE_PIXELS = None
TILE = re.compile(r"^([a-z]+)(\d)(\d)([scd])(\d)$", re.I)
CHANNELS = ("D", "N", "S", "E")
SUFFIX = {"D": "", "N": "_n", "S": "_s", "E": "_e"}
DEFAULT = {"D": (128, 128, 128), "N": (128, 128, 255), "S": (128, 128, 128), "E": (0, 0, 0)}

MATERIAL_TEMPLATE = '''import * from "BZTerrainBase.material"

material {name} : BZTerrainBase
{{
\tset_texture_alias DiffuseMap  {prefix}_ATLAS_D.dds
\tset_texture_alias NormalMap   {prefix}_ATLAS_N.dds
\tset_texture_alias SpecularMap {prefix}_ATLAS_S.dds
\tset_texture_alias EmissiveMap {emissive}
\tset_texture_alias DetailMap   {detail}

{body}
}}
'''


def read_csv(path):
    rows = []
    for line in open(path):
        p = line.strip().split(",")
        if len(p) >= 5:
            rows.append((p[0].replace(".map", "").replace(".MAP", ""),
                         float(p[1]), float(p[2]), float(p[3]), float(p[4])))
    return rows


def read_material(path):
    txt = open(path, errors="ignore").read()
    tex = {k.lower(): v for k, v in re.findall(r"set_texture_alias\s+(\w+)\s+(\S+)", txt)}
    setv = dict(re.findall(r'set\s+\$(\w+)\s+"([^"]*)"', txt))
    return tex, setv


def _renorm(a):
    v = a / 255.0 * 2.0 - 1.0
    v /= np.maximum(np.linalg.norm(v, axis=2, keepdims=True), 1e-6)
    return (v * 0.5 + 0.5) * 255.0


def load_source(cc_root, rel, channel, size, emissive_scale=1.0, specular_scale=1.0):
    """rel is the diffuse's path relative to the CC root; siblings carry the suffix."""
    stem, ext = os.path.splitext(os.path.join(cc_root, rel))
    path = None
    for e in (ext, ".tga", ".png", ".dds"):
        cand = stem + SUFFIX[channel] + e
        if os.path.exists(cand):
            path = cand
            break
    if path is None:
        return np.full((size, size, 3), DEFAULT[channel], np.float32), False
    im = Image.open(path)
    im.load()
    a = np.asarray(im.convert("RGBA")).astype(np.float32)
    if channel == "E" and a[..., 3].min() < 255:
        # alpha-masked glow: RGB is near-white, the shape is in alpha
        a = a[..., :3] * (a[..., 3:4] / 255.0)
    else:
        a = a[..., :3]
    # Both levers exist because the BZ2 art sits outside the stock envelope in
    # both directions: stock specular atlases all average 128, the rebuilt ones
    # land 21-96 (the source surfaces really are matte), and stock emissive tops
    # out at Io's 1.52 where rebuilt Pluto and Rend read 8-9.  Faithful by
    # default; scale per world when the look needs it.
    if channel == "E" and emissive_scale != 1.0:
        a = a * emissive_scale
    if channel == "S" and specular_scale != 1.0:
        a = a * specular_scale
    im = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8)).resize((size, size), Image.LANCZOS)
    a = np.asarray(im).astype(np.float32)
    return (_renorm(a) if channel == "N" else a), True


def downsample(a, n, channel):
    out = np.asarray(Image.fromarray(np.clip(a, 0, 255).astype(np.uint8))
                     .resize((n, n), Image.BOX)).astype(np.float32)
    return _renorm(out) if channel == "N" else out


def cut_existing(mod_dir, tex, channel, rect, size):
    """Fall back to the tile already in the hand-built atlas.

    Used for a TextureType whose art is not a Combat Commander texture -- Dark's
    type 4 is a circuit-board grid that matches nothing in the tree at 0.094, so
    rebuilding it from source is not possible and overwriting it would lose art.
    """
    alias = {"D": "diffusemap", "N": "normalmap", "S": "specularmap", "E": "emissivemap"}[channel]
    name = tex.get(alias)
    if not name:
        return np.full((size, size, 3), DEFAULT[channel], np.float32), False
    path = os.path.join(mod_dir, name)
    if not os.path.exists(path):
        return np.full((size, size, 3), DEFAULT[channel], np.float32), False
    im = Image.open(path)
    im.load()
    im = im.convert("RGB")
    W, H = im.size
    u, v, du, dv = rect
    box = (int(u*W), int(v*H), int((u+du)*W), int((v+dv)*H))
    a = np.asarray(im.crop(box).resize((size, size), Image.LANCZOS)).astype(np.float32)
    return (_renorm(a) if channel == "N" else a), True


def build(mod_dir, cc_root, material, mapping, out_dir, tile_px=256,
          prefix=None, emissive_scale=1.0, specular_scale=1.0):
    os.makedirs(out_dir, exist_ok=True)
    rows = [r for r in read_csv(os.path.join(mod_dir, material + ".csv")) if r[0]]
    tex, setv = read_material(os.path.join(mod_dir, material + ".material"))
    grid = int(round(1.0 / rows[0][3]))
    prefix = prefix or re.match(r"[A-Za-z]+", rows[0][0]).group().upper()

    placements = [(name, int(round(u * grid)), int(round(v * grid)))
                  for name, u, v, du, dv in rows]
    # rect of each type's own solid tile, for the "keep" fallback
    solid_rect = {}
    for name, u, v, du, dv in rows:
        m = TILE.match(name)
        if m and m.group(4).lower() == "s" and m.group(2) == m.group(3):
            solid_rect.setdefault(int(m.group(2)), (u, v, du, dv))

    have = {}
    report = {"material": material, "grid": grid, "tile_px": tile_px,
              "atlas_px": grid * tile_px, "sources": {}, "tiles": {}}
    for ch in CHANNELS:
        src, have[ch] = {}, {}
        for idx, rel in mapping.items():
            i = int(idx)
            if rel == "keep":
                src[i], have[ch][i] = cut_existing(
                    mod_dir, tex, ch, solid_rect.get(i, (0, 0, 1.0/grid, 1.0/grid)), tile_px)
            else:
                src[i], have[ch][i] = load_source(cc_root, rel, ch, tile_px,
                                                  emissive_scale, specular_scale)
            if ch == "D":
                report["sources"][idx] = rel

        tiles = {}
        for name, _, _ in placements:
            if name in tiles:
                continue
            m = TILE.match(name)
            if not m:
                tiles[name] = np.full((tile_px, tile_px, 3), DEFAULT[ch], np.float32)
                continue
            i, j, kind = int(m.group(2)), int(m.group(3)), m.group(4).lower()
            a = src.get(i, np.full((tile_px, tile_px, 3), DEFAULT[ch], np.float32))
            if kind == "s":
                tiles[name] = a
                continue
            b = src.get(j, a)
            seed = 1000 * i + 10 * j + (0 if kind == "c" else 1)
            msk = (maskgen.cap_mask(tile_px, seed) if kind == "c"
                   else maskgen.diagonal_mask(tile_px, seed))
            mm = msk[..., None]
            out = a * (1.0 - mm) + b * mm
            tiles[name] = _renorm(out) if ch == "N" else out
            if ch == "D":
                report["tiles"][name] = {"kind": kind, "from": i, "to": j,
                                         "coverage": round(float(msk.mean()), 3)}

        levels, n, peak = [], tile_px, 0.0
        while n >= 4:
            # uint8 canvas: at 1024px tiles this is 8192^2, and float32 there is
            # 800 MB before the encoder has allocated anything
            canvas = np.zeros((grid * n, grid * n, 3), np.uint8)
            for name, c, r in placements:
                t = tiles[name] if n == tile_px else downsample(tiles[name], n, ch)
                canvas[r*n:(r+1)*n, c*n:(c+1)*n] = np.clip(t, 0, 255).astype(np.uint8)
            if n == tile_px:
                peak = float(canvas.max())
                # mean over placed tiles only -- most atlases leave over half the
                # grid empty, and averaging the black cells in says nothing
                report["mean_" + ch] = round(float(np.mean(
                    [float(tiles[name].mean()) for name, _, _ in placements])), 2)
            levels.append(bc1.encode_bc1(canvas))
            n //= 2
        if ch == "E" and peak <= 2.0:
            # nothing to emit: point the material at stock black.dds instead of
            # shipping 2.7 MB of black, which is what stock does for these worlds
            report["atlas_E"] = {"file": "black.dds", "mips": 0, "bytes": 0,
                                 "sources_found": 0, "of": len(mapping), "skipped": True}
            continue
        path = os.path.join(out_dir, prefix + "_ATLAS_" + ch + ".dds")
        write_dxt1(path, grid * tile_px, grid * tile_px, levels)
        report["atlas_" + ch] = {"file": os.path.basename(path), "mips": len(levels),
                                 "bytes": os.path.getsize(path),
                                 "sources_found": sum(have[ch].values()), "of": len(mapping)}

    step = 1.0 / grid
    lines = [",0,0,%g,%g" % (step, step)]        # default row first, aliased to cell 0
    lines += ["%s.map,%g,%g,%g,%g" % (n, c*step, r*step, step, step)
              for n, c, r in placements]
    with open(os.path.join(out_dir, material + ".csv"), "w", newline="\r\n") as f:
        f.write("\n".join(lines) + "\n")

    detail = tex.get("detailmap", material.split("_")[0] + "_detail.dds")
    keep = [(k, setv[k]) for k in ("ambient", "diffuse", "specular", "shininess", "bias")
            if setv.get(k)]
    body = "\n".join('\tset $%-9s "%s"' % (k, v) for k, v in keep)
    emissive = report["atlas_E"]["file"]
    with open(os.path.join(out_dir, material + ".material"), "w", newline="\r\n") as f:
        f.write(MATERIAL_TEMPLATE.format(name=material.upper(), prefix=prefix,
                                         detail=detail, emissive=emissive, body=body))
    json.dump(report, open(os.path.join(out_dir, "build_report.json"), "w"), indent=1)
    return report


if __name__ == "__main__":
    mod_dir, cc_root, cfg_path, out_root = sys.argv[1:5]
    tile_px = int(sys.argv[5]) if len(sys.argv) > 5 else 256
    cfg = json.load(open(cfg_path))
    for material, spec in cfg.items():
        # per-world tile size: never ship fewer texels per tile than the world
        # already had, and never upscale past the source art
        rep = build(mod_dir, cc_root, material, spec["sources"],
                    os.path.join(out_root, material), spec.get("tile_px", tile_px),
                    spec.get("prefix"), spec.get("emissive_scale", 1.0),
                    spec.get("specular_scale", 1.0))
        tot = sum(rep["atlas_" + c]["bytes"] for c in CHANNELS)
        found = ", ".join("%s%d/%d" % (c, rep["atlas_" + c]["sources_found"],
                                       rep["atlas_" + c]["of"]) for c in CHANNELS)
        print("%-24s %d^2 grid%d  %5.1f MB  sources: %s"
              % (material, rep["atlas_px"], rep["grid"], tot / 1048576, found))
