"""Render a top-down preview image of a Battlezone map from its own data.

Every Redux map wants two pictures that nothing generates for you:

  * `<mission>.bmp` -- the in-game preview the shell shows beside the mission.
    The size is not a choice: every stock and community map that ships one is
    **108x89, 24-bit**, so that is what this writes.
  * a square `.jpg` for a Workshop listing, 256 or 512 on a side.

Both are drawn from the map itself rather than screenshotted, which is what
makes this runnable over a hundred maps unattended:

  * the `.mat` says which terrain material paints each 64-per-zone cell;
  * the `.trn` says which tile each material uses, and which atlas it lives in;
  * the atlas gives that tile's average colour;
  * the `.hg2` (or `.hgt`) gives the relief, which is shaded over the colour so
    the landform reads at thumbnail size.

Usage:
    python map_preview.py addon/MyMap                 # writes both next to the .trn
    python map_preview.py addon/MyMap/mymap.trn --jpg-size 256
    python map_preview.py addon --all --dry-run
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import sys

import numpy as np
from PIL import Image

from bztoolbox.modules.world.hg2_codec import read_hg2
from bztoolbox.modules.world.mat_codec import read_mat, decode_entry

# The shell's preview slot. Not a preference -- every map that ships one uses it.
INGAME_BMP_SIZE = (108, 89)
DEFAULT_JPG_SIZE = 512

GAME_ROOT = r"C:\Program Files (x86)\GOG Galaxy\Games\Battlezone 98 Redux"
# Where a stock atlas and its CSV live. The Edit/ copies are plain PNG, so they
# are preferred over the shipped DDS purely because they decode everywhere.
STOCK_DIRS = [
    os.path.join(GAME_ROOT, "Edit", "PlanetMaterials"),
    os.path.join(GAME_ROOT, "Edit", "BZ_TERRAIN_ATLASES_DIFF_PNG"),
    os.path.join(GAME_ROOT, "BZ_ASSETS", "common", "materials"),
    os.path.join(GAME_ROOT, "BZ_ASSETS", "pc", "materials"),
    os.path.join(GAME_ROOT, "BZ_ASSETS", "pc", "textures", "TerrainTextures",
                 "BZ_TERRAIN_ATLASES_DIFF_DDS"),
]

# A section header owns its whole line. Authored TRNs routinely label one with
# a bare note -- "[TextureType1] Liquid Sulphur" -- and only sometimes mark it
# as a // comment, so whatever follows the "]" belongs to the header and is
# dropped. Requiring "]" to end the line folded every later texture type into
# type 0's body and rendered 60 of the 236 shipped TRNs monochrome.
_SECT = re.compile(r"^[ \t]*\[([A-Za-z0-9_]+)\][^\r\n]*\r?$", re.M)
_KEY = re.compile(r"^\s*([A-Za-z0-9_]+)\s*=\s*(.*?)\s*$", re.M)


def _strip_comments(text: str) -> str:
    """A .trn value may carry a trailing // note; it is part of the line."""
    return "\n".join(line.split("//")[0] for line in text.splitlines())


def parse_trn(path: str) -> dict:
    """Material name, per-texture-type solid tile, and declared world size."""
    text = _strip_comments(open(path, "r", errors="ignore").read())
    parts = _SECT.split(text)
    sections = {parts[i].lower(): parts[i + 1] for i in range(1, len(parts), 2)}

    material = None
    if "atlases" in sections:
        m = re.search(r"MaterialName\s*=\s*(\S+)", sections["atlases"], re.I)
        if m:
            material = m.group(1).strip()

    solids: dict[int, str] = {}
    for name, body in sections.items():
        m = re.fullmatch(r"texturetype(\d+)", name)
        if not m:
            continue
        # SolidA0 is the material's plain face; caps and diagonals are edges.
        s = re.search(r"SolidA0\s*=\s*(\S+\.map)", body, re.I)
        if not s:
            s = re.search(r"Solid[A-D]0\s*=\s*(\S+\.map)", body, re.I)
        if s:
            solids[int(m.group(1))] = s.group(1).strip().upper()

    size = {}
    for k, v in _KEY.findall(sections.get("size", "")):
        try:
            size[k.lower()] = float(v)
        except ValueError:
            pass
    return {"material": material, "solids": solids, "size": size}


def _find(name: str, dirs) -> str | None:
    for d in dirs:
        if not os.path.isdir(d):
            continue
        for f in os.listdir(d):
            if f.lower() == name.lower():
                return os.path.join(d, f)
    return None


def atlas_colours(material: str, solids: dict[int, str], dirs) -> dict[int, tuple]:
    """Average colour of each texture type's tile, cropped out of the atlas."""
    csv_path = _find(material + ".csv", dirs)
    mat_path = _find(material + ".material", dirs)
    if not csv_path or not mat_path:
        return {}
    uv = {}
    for row in csv.reader(open(csv_path)):
        if row and row[0].strip():
            try:
                uv.setdefault(row[0].strip().upper(),
                              tuple(float(x) for x in row[1:5]))
            except ValueError:
                pass
    m = re.search(r"set_texture_alias\s+DiffuseMap\s+(\S+)",
                  open(mat_path, errors="ignore").read(), re.I)
    if not m:
        return {}
    img_path = _find(m.group(1), dirs)
    if not img_path:
        # Stock materials name a .dds; the Edit/ tree carries the same art as PNG.
        alt = os.path.splitext(m.group(1))[0] + ".png"
        img_path = _find(alt, dirs)
    if not img_path:
        return {}
    sheet = Image.open(img_path).convert("RGB")
    out = {}
    for idx, tile in solids.items():
        if tile not in uv:
            continue
        u, v, du, dv = uv[tile]
        box = (round(u * sheet.width), round(v * sheet.height),
               round((u + du) * sheet.width), round((v + dv) * sheet.height))
        crop = sheet.crop(box)
        if crop.width and crop.height:
            out[idx] = tuple(int(c) for c in np.asarray(crop).reshape(-1, 3).mean(0))
    return out


def _heights(folder: str, stem: str):
    """Relief grid, north-up. HG2 first: it is what the game loads."""
    for f in os.listdir(folder):
        if f.lower() == stem.lower() + ".hg2":
            header, h = read_hg2(os.path.join(folder, f))
            return np.flipud(h.astype(np.float32)), header.zones_x, header.zones_z
    for f in os.listdir(folder):
        if f.lower() == stem.lower() + ".hgt":
            raw = np.frombuffer(open(os.path.join(folder, f), "rb").read(),
                                dtype="<u2") & 0x0FFF
            zones = raw.size // (128 * 128)
            side = int(round(zones ** 0.5))
            if side * side != zones:
                return None, 0, 0
            g = np.empty((side * 128, side * 128), np.float32)
            p = 0
            for z in range(side):
                for x in range(side):
                    g[z * 128:(z + 1) * 128, x * 128:(x + 1) * 128] = \
                        raw[p:p + 16384].reshape(128, 128)
                    p += 16384
            return np.flipud(g), side, side
    return None, 0, 0


def _materials(folder: str, stem: str, zx: int, zz: int):
    for f in os.listdir(folder):
        if f.lower() == stem.lower() + ".mat":
            try:
                raw = read_mat(os.path.join(folder, f), zx, zz)
            except ValueError:
                return None
            base = np.vectorize(lambda v: decode_entry(int(v)).base)(raw)
            return np.flipud(base.astype(np.uint8))
    return None


def _hillshade(h: np.ndarray, strength: float = 0.55) -> np.ndarray:
    """Lambertian shade from the north-west, normalised so flat ground is 1.0.

    The relief is differentiated at preview resolution, never upsampled first:
    an HG2 carries 256 samples per zone and its per-sample stair-stepping turns
    into speckle the moment you take a gradient of an enlarged copy.
    """
    if h is None or h.size == 0 or float(h.max() - h.min()) < 1e-6:
        return None
    sm = _smooth(h.astype(np.float32), 1.0)
    gz, gx = np.gradient(sm)
    spread = float(np.percentile(np.abs(np.dstack([gx, gz])), 90))
    scale = 1.5 / spread if spread > 1e-6 else 0.0
    n = np.dstack([-gx * scale, -gz * scale, np.ones_like(gx)])
    n /= np.linalg.norm(n, axis=2, keepdims=True)
    light = np.array([-0.5, 0.5, 0.72])
    light /= np.linalg.norm(light)
    shade = np.clip(n @ light, 0.0, 1.0)
    return np.clip(1.0 + strength * (shade - float(shade.mean())), 0.35, 1.65)


def _smooth(a: np.ndarray, radius: float) -> np.ndarray:
    """Small separable blur, so the shading follows landform not sample noise."""
    if radius <= 0:
        return a
    k = max(3, int(radius * 4) | 1)
    x = np.arange(k) - k // 2
    g = np.exp(-(x ** 2) / (2 * radius ** 2))
    g /= g.sum()
    out = np.apply_along_axis(lambda m: np.convolve(m, g, mode="same"), 0, a)
    return np.apply_along_axis(lambda m: np.convolve(m, g, mode="same"), 1, out)


def _downsample(a: np.ndarray, size: int) -> np.ndarray:
    """Area-average down to the preview grid (PIL would quantise to 8-bit)."""
    h, w = a.shape
    if h == size and w == size:
        return a
    zi = (np.arange(size) * (h / size)).astype(int)
    xi = (np.arange(size) * (w / size)).astype(int)
    if h >= size and w >= size:
        fz, fx = h // size, w // size
        if fz >= 1 and fx >= 1 and h % size == 0 and w % size == 0:
            return a.reshape(size, fz, size, fx).mean(axis=(1, 3))
    return a[np.ix_(zi, xi)]


def render(trn_path: str, size: int = DEFAULT_JPG_SIZE) -> Image.Image | None:
    folder = os.path.dirname(os.path.abspath(trn_path))
    stem = os.path.splitext(os.path.basename(trn_path))[0]
    info = parse_trn(trn_path)

    heights, zx, zz = _heights(folder, stem)
    if heights is None:
        return None
    dirs = [folder] + STOCK_DIRS
    colours = atlas_colours(info["material"], info["solids"], dirs) if info["material"] else {}
    mats = _materials(folder, stem, zx, zz)

    if mats is not None and colours:
        lut = np.zeros((16, 3), np.float32)
        fallback = np.asarray(colours.get(0, list(colours.values())[0]), np.float32)
        for i in range(16):
            lut[i] = colours.get(i, fallback)
        rgb = lut[np.clip(mats, 0, 15)]
    else:
        # No paint data or no atlas: fall back to relief alone, which still
        # reads as a map rather than shipping nothing.
        norm = heights - heights.min()
        norm /= max(norm.max(), 1e-6)
        rgb = np.dstack([norm * 180 + 40, norm * 170 + 40, norm * 150 + 40])

    img = Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8), "RGB")
    img = img.resize((size, size), Image.LANCZOS)

    shade = _hillshade(_downsample(heights, size))
    if shade is not None:
        arr = np.asarray(img).astype(np.float32) * shade[..., None]
        img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8), "RGB")
    return img


def write_previews(trn_path: str, jpg_size: int = DEFAULT_JPG_SIZE,
                   bmp_size=INGAME_BMP_SIZE, out_dir: str | None = None,
                   bmp_stem: str | None = None):
    img = render(trn_path, jpg_size)
    if img is None:
        return None
    folder = out_dir or os.path.dirname(os.path.abspath(trn_path))
    stem = os.path.splitext(os.path.basename(trn_path))[0]
    jpg = os.path.join(folder, f"{stem}_preview.jpg")
    img.save(jpg, "JPEG", quality=92)
    # The in-game slot is 108x89, which is not square: fit the square render
    # into it rather than stretching the terrain out of shape.
    bmp_img = Image.new("RGB", bmp_size, (0, 0, 0))
    fitted = img.copy()
    fitted.thumbnail(bmp_size, Image.LANCZOS)
    bmp_img.paste(fitted, ((bmp_size[0] - fitted.width) // 2,
                           (bmp_size[1] - fitted.height) // 2))
    bmp = os.path.join(folder, f"{bmp_stem or stem}.bmp")
    bmp_img.save(bmp, "BMP")
    return jpg, bmp


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("target", help=".trn file, a map folder, or a folder of map folders with --all")
    ap.add_argument("--all", action="store_true", help="recurse into subfolders")
    ap.add_argument("--jpg-size", type=int, default=DEFAULT_JPG_SIZE)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    targets = []
    if os.path.isfile(a.target):
        targets = [a.target]
    else:
        roots = ([os.path.join(a.target, d) for d in sorted(os.listdir(a.target))]
                 if a.all else [a.target])
        for r in roots:
            if not os.path.isdir(r):
                continue
            trns = [f for f in sorted(os.listdir(r)) if f.lower().endswith(".trn")]
            targets += [os.path.join(r, t) for t in trns]

    ok = skipped = 0
    for t in targets:
        if a.dry_run:
            print(f"would render {t}")
            ok += 1
            continue
        res = write_previews(t, a.jpg_size)
        if res:
            ok += 1
            print(f"{os.path.basename(os.path.dirname(t)):28s} {os.path.basename(res[0])}")
        else:
            skipped += 1
            print(f"{os.path.basename(os.path.dirname(t)):28s} SKIPPED (no heightmap)")
    print(f"\n{ok} rendered, {skipped} skipped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
