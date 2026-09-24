"""Clean-room compatibility implementation of Battlezone MakeMAP (Mar 27 2017)."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence
import argparse
import glob
import os
import struct
import sys
import tempfile

import numpy as np
from PIL import Image


class MapFormat:
    INDEXED = 0
    ARGB4444 = 1
    RGB565 = 2
    ARGB8888 = 3
    XRGB8888 = 4
    BPP = {INDEXED: 1, ARGB4444: 2, RGB565: 2, ARGB8888: 4, XRGB8888: 4}
    NAMES = {
        INDEXED: "8-bit indexed", ARGB4444: "A4R4G4B4", RGB565: "R5G6B5",
        ARGB8888: "A8R8G8B8", XRGB8888: "X8R8G8B8",
    }


@dataclass
class MakeMapOptions:
    output_mode: str = "map"
    map_format: int | None = None
    palette: list[tuple[int, int, int]] | None = None
    recover_alpha: bool = False
    chroma_key: tuple[int, int, int] | None = None
    transparent_index: int = -1
    undo_pma: bool = False
    remap: Image.Image | None = None
    colorize_enabled: bool = False
    desaturate_percent: float = 0.0
    powers: tuple[float, float, float, float] = (1.0, 1.0, 1.0, 1.0)
    multipliers: tuple[float, float, float, float] = (255.0, 255.0, 255.0, 255.0)
    additions: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)
    flip_x: bool = False
    flip_y: bool = False
    diffusion_percent: float = 0.0

    def resolved_format(self) -> int:
        if self.map_format is not None:
            return self.map_format
        if self.palette is not None:
            return MapFormat.INDEXED
        raise ValueError("No palette or pixel format specified")


def read_palette(path: os.PathLike[str] | str) -> list[tuple[int, int, int]]:
    data = Path(path).read_bytes()
    if len(data) < 3:
        raise ValueError(f"{path}: palette is empty")
    count = min(len(data) // 3, 256)
    return [tuple(data[i * 3:i * 3 + 3]) for i in range(count)]


def _require_palette(palette):
    if not palette:
        raise ValueError("No palette for reading type 0 MAP file")
    return palette


def decode_map_bytes(data: bytes, palette=None) -> Image.Image:
    if len(data) < 8:
        raise ValueError("MAP file is smaller than its 8-byte header")
    row_bytes, fmt, height = struct.unpack_from("<HHI", data, 0)
    if fmt not in MapFormat.BPP:
        raise ValueError(f"Unknown MAP pixel format {fmt}")
    bpp = MapFormat.BPP[fmt]
    if row_bytes == 0 or row_bytes % bpp:
        raise ValueError(f"Invalid MAP row size {row_bytes} for format {fmt}")
    width = row_bytes // bpp
    expected = 8 + row_bytes * height
    if len(data) < expected:
        raise ValueError(f"Truncated MAP data: expected {expected} bytes, got {len(data)}")
    payload = data[8:expected]

    if fmt == MapFormat.INDEXED:
        pal = _require_palette(palette)
        idx = np.frombuffer(payload, dtype=np.uint8).reshape((height, width))
        rgba = np.empty((height, width, 4), dtype=np.uint8)
        table = np.zeros((256, 4), dtype=np.uint8)
        table[:, 3] = 255
        for i, color in enumerate(pal[:256]):
            table[i, :3] = color[:3]
        rgba[:] = table[idx]
        return Image.fromarray(rgba, "RGBA")

    if fmt in (MapFormat.ARGB4444, MapFormat.RGB565):
        words = np.frombuffer(payload, dtype="<u2").reshape((height, width))
        rgba = np.empty((height, width, 4), dtype=np.uint8)
        if fmt == MapFormat.ARGB4444:
            a = (words >> 12) & 0xF; r = (words >> 8) & 0xF
            g = (words >> 4) & 0xF; b = words & 0xF
            rgba[..., 0] = (r << 4) | r; rgba[..., 1] = (g << 4) | g
            rgba[..., 2] = (b << 4) | b; rgba[..., 3] = (a << 4) | a
        else:
            r = (words >> 11) & 0x1F; g = (words >> 5) & 0x3F; b = words & 0x1F
            rgba[..., 0] = (r << 3) | (r >> 2)
            rgba[..., 1] = (g << 2) | (g >> 4)
            rgba[..., 2] = (b << 3) | (b >> 2); rgba[..., 3] = 255
        return Image.fromarray(rgba, "RGBA")

    packed = np.frombuffer(payload, dtype=np.uint8).reshape((height, width, 4))
    rgba = np.empty_like(packed)
    rgba[..., 0] = packed[..., 2]; rgba[..., 1] = packed[..., 1]; rgba[..., 2] = packed[..., 0]
    rgba[..., 3] = packed[..., 3] if fmt == MapFormat.ARGB8888 else 255
    return Image.fromarray(rgba, "RGBA")


def load_map(path, palette=None) -> Image.Image:
    return decode_map_bytes(Path(path).read_bytes(), palette)


def _image_array(image: Image.Image) -> np.ndarray:
    return np.array(image.convert("RGBA"), dtype=np.uint8, copy=True)


def recover_alpha(image: Image.Image) -> Image.Image:
    arr = _image_array(image)
    arr[..., 3] = arr[..., :3].max(axis=2)
    return Image.fromarray(arr, "RGBA")


def apply_chroma_key(image: Image.Image, key: tuple[int, int, int]) -> Image.Image:
    arr = _image_array(image)
    mask = np.all(arr[..., :3] == np.array(key, dtype=np.uint8), axis=2)
    arr[mask] = 0
    return Image.fromarray(arr, "RGBA")


def desaturate(image: Image.Image, percent: float) -> Image.Image:
    arr = _image_array(image)
    amount = int(float(percent) * 256.0 / 100.0)
    rgb = arr[..., :3].astype(np.int32)
    luma = (77 * rgb[..., 0] + 150 * rgb[..., 1] + 29 * rgb[..., 2]) >> 8
    rgb = rgb + (((luma[..., None] - rgb) * amount) >> 8)
    arr[..., :3] = np.clip(rgb, 0, 255).astype(np.uint8)
    return Image.fromarray(arr, "RGBA")


def apply_remap(image: Image.Image, table_image: Image.Image) -> Image.Image:
    arr = _image_array(image)
    table = np.array(table_image.convert("RGBA"), dtype=np.uint8)
    if table.ndim != 3 or table.shape[1] <= 0:
        raise ValueError("Remap image has no pixels")
    row = table[0]
    width = row.shape[0]
    idx = (arr.astype(np.uint16) * (width - 1)) // 255
    out = np.empty_like(arr)
    for channel in range(4):
        out[..., channel] = row[idx[..., channel], channel]
    return Image.fromarray(out, "RGBA")


def colorize(image: Image.Image, powers, multipliers, additions) -> Image.Image:
    arr = _image_array(image).astype(np.float32)
    out = np.empty_like(arr)
    for channel in range(4):
        values = np.power(arr[..., channel] / 255.0, float(powers[channel]))
        values = values * float(multipliers[channel]) + float(additions[channel])
        out[..., channel] = np.floor(values + 0.5)
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8), "RGBA")


def undo_premultiplied_alpha(image: Image.Image) -> Image.Image:
    arr = _image_array(image)
    rgb = arr[..., :3].astype(np.int32); alpha = arr[..., 3].astype(np.int32)
    mask = alpha > 0
    for channel in range(3):
        c = rgb[..., channel]; restored = c.copy()
        restored[mask] = (c[mask] * 255) // alpha[mask]
        rgb[..., channel] = np.clip(restored, 0, 255)
    arr[..., :3] = rgb.astype(np.uint8)
    return Image.fromarray(arr, "RGBA")


def apply_preprocess(image: Image.Image, opts: MakeMapOptions) -> Image.Image:
    out = image.convert("RGBA")
    if opts.recover_alpha: out = recover_alpha(out)
    if opts.chroma_key is not None: out = apply_chroma_key(out, opts.chroma_key)
    if opts.desaturate_percent: out = desaturate(out, opts.desaturate_percent)
    if opts.remap is not None: out = apply_remap(out, opts.remap)
    if opts.colorize_enabled: out = colorize(out, opts.powers, opts.multipliers, opts.additions)
    if opts.undo_pma: out = undo_premultiplied_alpha(out)
    if opts.flip_x: out = out.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    if opts.flip_y: out = out.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
    return out


def _clamp_byte(value: int) -> int:
    return 0 if value < 0 else 255 if value > 255 else value


def _nearest_palette_index(rgb, palette) -> int:
    best_i = 0; best_d = None
    r, g, b = (int(rgb[0]), int(rgb[1]), int(rgb[2]))
    for i, color in enumerate(palette[:256]):
        dr = r - int(color[0]); dg = g - int(color[1]); db = b - int(color[2])
        d = dr * dr + dg * dg + db * db
        if best_d is None or d < best_d:
            best_d = d; best_i = i
    return best_i


def _quantize_pixel(pixel: np.ndarray, fmt: int, palette, trans_index: int):
    r, g, b, a = (int(v) for v in pixel)
    if fmt == MapFormat.INDEXED:
        pal = _require_palette(palette)
        if trans_index >= 0 and r == 0 and g == 0 and b == 0 and a == 0:
            idx = trans_index & 0xFF
        else:
            idx = _nearest_palette_index((r, g, b), pal)
        color = pal[idx] if idx < len(pal) else (0, 0, 0)
        return bytes((idx,)), np.array((color[0], color[1], color[2], 255), dtype=np.uint8)
    if fmt == MapFormat.ARGB4444:
        an, rn, gn, bn = a >> 4, r >> 4, g >> 4, b >> 4
        word = (an << 12) | (rn << 8) | (gn << 4) | bn
        q = np.array(((rn << 4) | rn, (gn << 4) | gn, (bn << 4) | bn, (an << 4) | an), dtype=np.uint8)
        return struct.pack("<H", word), q
    if fmt == MapFormat.RGB565:
        rr, gg, bb = r >> 3, g >> 2, b >> 3
        word = (rr << 11) | (gg << 5) | bb
        q = np.array(((rr << 3) | (rr >> 2), (gg << 2) | (gg >> 4), (bb << 3) | (bb >> 2), 255), dtype=np.uint8)
        return struct.pack("<H", word), q
    if fmt == MapFormat.ARGB8888:
        return bytes((b, g, r, a)), np.array((r, g, b, a), dtype=np.uint8)
    if fmt == MapFormat.XRGB8888:
        return bytes((b, g, r, 0)), np.array((r, g, b, 255), dtype=np.uint8)
    raise ValueError(f"Unknown MAP pixel format {fmt}")


def _diffuse(work, x, y, original, quantized, percent):
    if not percent: return
    strength = int(float(percent) * 256.0 / 100.0)
    err = [((int(original[c]) - int(quantized[c])) * strength) >> 8 for c in range(3)]
    h, w, _ = work.shape
    def add_error(tx, ty, divisor):
        if tx < 0 or tx >= w or ty < 0 or ty >= h: return
        for c in range(3):
            delta = int(err[c] / divisor)
            work[ty, tx, c] = _clamp_byte(int(work[ty, tx, c]) + delta)
    # MakeMAP: 1/2 right, 1/4 below-left, 1/4 below. Alpha is not diffused.
    add_error(x + 1, y, 2); add_error(x - 1, y + 1, 4); add_error(x, y + 1, 4)


def quantize_image(image: Image.Image, fmt: int, palette=None, transparent_index=-1, diffusion_percent=0.0):
    work = _image_array(image); h, w, _ = work.shape
    payload = bytearray(); preview = np.empty_like(work)
    for y in range(h):
        for x in range(w):
            original = work[y, x].copy()
            encoded, q = _quantize_pixel(original, fmt, palette, transparent_index)
            payload.extend(encoded); preview[y, x] = q
            _diffuse(work, x, y, original, q, diffusion_percent)
    return bytes(payload), Image.fromarray(preview, "RGBA")


def encode_map_bytes(image: Image.Image, opts: MakeMapOptions) -> bytes:
    fmt = opts.resolved_format(); bpp = MapFormat.BPP[fmt]
    width, height = image.size; row_bytes = width * bpp
    if row_bytes > 0xFFFF:
        raise ValueError(f"MAP row is too wide for the 16-bit row-size field: {row_bytes} bytes")
    payload, _ = quantize_image(image, fmt, opts.palette, opts.transparent_index, opts.diffusion_percent)
    return struct.pack("<HHI", row_bytes, fmt, height) + payload


def load_input_image(path, palette=None) -> Image.Image:
    path = Path(path)
    return load_map(path, palette) if path.suffix.lower() == ".map" else Image.open(path).convert("RGBA")


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as f: f.write(data)
        os.replace(tmp_name, path)
    except Exception:
        try: os.unlink(tmp_name)
        except OSError: pass
        raise


def convert_file(path, opts: MakeMapOptions) -> Path:
    source = Path(path)
    image = apply_preprocess(load_input_image(source, opts.palette), opts)
    fmt = opts.resolved_format()
    extension = {"map": ".map", "bmp": ".bmp", "tga": ".tga", "png": ".png"}[opts.output_mode]
    destination = source.with_suffix(extension)
    if opts.output_mode == "map":
        _atomic_write(destination, encode_map_bytes(image, opts))
    else:
        _, preview = quantize_image(image, fmt, opts.palette, opts.transparent_index, opts.diffusion_percent)
        fd, tmp_name = tempfile.mkstemp(prefix=destination.stem + ".", suffix=extension, dir=str(destination.parent))
        os.close(fd)
        try:
            preview.save(tmp_name); os.replace(tmp_name, destination)
        except Exception:
            try: os.unlink(tmp_name)
            except OSError: pass
            raise
    return destination


def _expand_inputs(items: Iterable[str]) -> list[Path]:
    result = []; seen = set()
    for item in items:
        matches = [Path(p) for p in glob.glob(item, recursive=True)] if any(ch in item for ch in "*?[") else [Path(item)]
        for match in matches:
            children = [p for p in match.rglob("*") if p.is_file()] if match.is_dir() else [match] if match.is_file() else []
            for child in children:
                key = child.resolve()
                if key not in seen: seen.add(key); result.append(child)
    return result


def _normalize_slash_options(argv: list[str]) -> list[str]:
    known = {"bmp","tga","recoveralpha","chromakey","transindex","undopma","remap","colorize","desat","powr","powg","powb","powa","mulr","mulg","mulb","mula","addr","addg","addb","adda","pal","4444","565","8888","888","flipx","flipy","diff"}
    return ["-" + arg[1:] if arg.startswith("/") and arg[1:].lower() in known else arg for arg in argv]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="makemap_compat", description="Clean-room Battlezone MakeMAP compatibility utility.")
    mode = p.add_mutually_exclusive_group(); mode.add_argument("-bmp", action="store_true"); mode.add_argument("-tga", action="store_true")
    p.add_argument("-recoveralpha", action="store_true")
    p.add_argument("-chromakey", nargs=3, type=int, metavar=("R","G","B"))
    p.add_argument("-transindex", type=int, default=-1, metavar="INDEX")
    p.add_argument("-undopma", action="store_true")
    p.add_argument("-remap", metavar="IMAGE")
    p.add_argument("-colorize", action="store_true")
    p.add_argument("-desat", type=float, default=0.0, metavar="PERCENT")
    for c in "rgba": p.add_argument(f"-pow{c}", type=float, default=1.0, metavar="VALUE")
    for c in "rgba": p.add_argument(f"-mul{c}", type=float, default=255.0, metavar="VALUE")
    for c in "rgba": p.add_argument(f"-add{c}", type=float, default=0.0, metavar="VALUE")
    p.add_argument("-pal", metavar="PALETTE")
    fmt = p.add_mutually_exclusive_group()
    fmt.add_argument("-4444", dest="fmt4444", action="store_true")
    fmt.add_argument("-565", dest="fmt565", action="store_true")
    fmt.add_argument("-8888", dest="fmt8888", action="store_true")
    fmt.add_argument("-888", dest="fmt888", action="store_true")
    p.add_argument("-flipx", action="store_true"); p.add_argument("-flipy", action="store_true")
    p.add_argument("-diff", type=float, default=0.0, metavar="PERCENT")
    p.add_argument("files", nargs="+", help="files, wildcard patterns, or directories")
    return p


def options_from_args(args) -> MakeMapOptions:
    palette = read_palette(args.pal) if args.pal else None
    map_format = MapFormat.ARGB4444 if args.fmt4444 else MapFormat.RGB565 if args.fmt565 else MapFormat.ARGB8888 if args.fmt8888 else MapFormat.XRGB8888 if args.fmt888 else MapFormat.INDEXED if palette is not None else None
    remap = Image.open(args.remap).convert("RGBA") if args.remap else None
    return MakeMapOptions(
        output_mode="bmp" if args.bmp else "tga" if args.tga else "map", map_format=map_format, palette=palette,
        recover_alpha=args.recoveralpha, chroma_key=tuple(args.chromakey) if args.chromakey else None,
        transparent_index=args.transindex, undo_pma=args.undopma, remap=remap, colorize_enabled=args.colorize,
        desaturate_percent=args.desat, powers=(args.powr,args.powg,args.powb,args.powa),
        multipliers=(args.mulr,args.mulg,args.mulb,args.mula), additions=(args.addr,args.addg,args.addb,args.adda),
        flip_x=args.flipx, flip_y=args.flipy, diffusion_percent=args.diff,
    )


def main(argv: list[str] | None = None) -> int:
    parser = build_parser(); args = parser.parse_args(_normalize_slash_options(list(sys.argv[1:] if argv is None else argv)))
    try:
        opts = options_from_args(args); opts.resolved_format()
    except Exception as exc:
        parser.error(str(exc))
    inputs = _expand_inputs(args.files)
    if not inputs:
        print("No matching input files", file=sys.stderr); return 1
    failed = 0
    for path in inputs:
        try:
            out = convert_file(path, opts); print(f"{path} -> {out}")
        except Exception as exc:
            failed += 1; print(f"{path}: {exc}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
