"""Headless custom terrain atlas builder used by WorldBuilder.

This module contains no Tk dependencies. Its output contract intentionally
matches the existing Custom Atlas Creator so GUI and future BZ2 import paths
can share one implementation.
"""
from __future__ import annotations

import math
import os
import random

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageOps


def generate_transition_mask(mode: str, cfg: dict) -> Image.Image:
    """Generate the existing Atlas Creator cap/diagonal mask."""
    res = cfg["res"]
    style = cfg["style"]
    random.seed(cfg["seed"])
    depth_v = cfg["depth"]
    teeth_v = cfg["teeth"]
    jitter_v = cfg["jitter"]
    soft_v = cfg["softness"]

    vertex_styles = [
        "Square/Blocky", "Sawtooth", "Interlocking L", "Sine Wave", "Stairs/Steps"
    ]

    if style in vertex_styles:
        mask = Image.new("L", (res, res), 0)
        draw = ImageDraw.Draw(mask)
        depth_px = res * depth_v
        count = max(1, teeth_v)
        jitter = jitter_v

        if mode == "cap":
            line_start, line_end = (0, res * 0.75), (res, res * 0.75)
            fill_pts = [(res, res), (0, res)]
        else:
            line_start, line_end = (0, res), (res, 0)
            fill_pts = [(res, res)]

        pts = [line_start]
        for i in range(1, count + 1):
            t = i / count
            px = line_start[0] + (line_end[0] - line_start[0]) * t
            py = line_start[1] + (line_end[1] - line_start[1]) * t
            off = (depth_px if i % 2 == 0 else -depth_px) + random.uniform(-jitter, jitter)

            if style == "Square/Blocky":
                pts.append(((line_start[0] + (line_end[0] - line_start[0]) * (i - 0.9) / count) + off,
                            py + off))
                pts.append((px + off, py + off))
            elif style == "Sawtooth":
                pts.append((px + off, py + off))
            elif style == "Sine Wave":
                s_val = math.sin(t * math.pi * 2) * depth_px
                pts.append((px + s_val, py + s_val))
            elif style == "Stairs/Steps":
                pts.append((px, py + off))
                pts.append((px + (res / count), py + off))
            else:
                pts.append((px, py + off))

        pts.append(line_end)
        draw.polygon(pts + fill_pts, fill=255)
    else:
        gradient = np.zeros((res, res), dtype=np.float32)
        for y in range(res):
            for x in range(res):
                if style == "Radial/Impact":
                    dist = math.sqrt((res - x) ** 2 + (res - y) ** 2)
                    gradient[y, x] = dist / (res * 1.414)
                elif mode == "cap":
                    gradient[y, x] = y / res
                else:
                    gradient[y, x] = (x + y) / (res * 2)

        influence = jitter_v / 100.0
        freq = max(1, teeth_v)
        noise_img = Image.effect_noise((res, res), freq)
        noise_arr = np.array(noise_img).astype(np.float32) / 255.0

        if style == "Voronoi/Cells":
            noise_arr = np.round(noise_arr * (freq / 5)) / (freq / 5)
        elif style == "Plasma/Circuit":
            plasma = np.sin(noise_arr * freq) * np.cos(noise_arr.T * freq)
            noise_arr = (plasma + 1) / 2

        warped = np.clip(gradient + (noise_arr - 0.5) * influence * 2, 0, 1)
        mask = Image.fromarray((warped * 255).astype(np.uint8))

        if style == "Soft Clouds":
            mask = mask.point(lambda p: 255 if p > 128 else 0)
        elif style == "Fractal Noise":
            mask = mask.point(lambda p: 255 if p > 128 else 0)
            crunch = Image.effect_noise((res, res), res // 4).point(
                lambda p: 255 if p > 220 else 0
            )
            mask = Image.composite(crunch, mask, mask.filter(ImageFilter.GaussianBlur(10)))
        elif style == "Binary Dither":
            mask = mask.convert("1").convert("L")
        elif style == "Plasma/Circuit":
            mask = mask.point(lambda p: 255 if 110 < p < 145 else 0)
        else:
            mask = mask.point(lambda p: 255 if p > 128 else 0)

    if soft_v > 0:
        mask = mask.filter(ImageFilter.GaussianBlur(soft_v))
    return mask


def generate_normal_map(image: Image.Image, strength: float = 1.0) -> Image.Image:
    """Existing Atlas Creator grayscale-to-tangent-normal conversion."""
    gray = ImageOps.grayscale(image)
    arr = np.array(gray).astype(np.float32)
    dx = np.zeros_like(arr)
    dy = np.zeros_like(arr)
    dx[:, 1:-1] = (arr[:, 2:] - arr[:, :-2]) * strength
    dy[1:-1, :] = (arr[2:, :] - arr[:-2, :]) * strength

    mag = np.sqrt(dx ** 2 + dy ** 2 + 100.0 ** 2)
    nx = (dx / mag) * 127.5 + 127.5
    ny = (dy / mag) * 127.5 + 127.5
    nz = (100.0 / mag) * 127.5 + 127.5
    return Image.fromarray(np.stack([nx, ny, nz], axis=-1).astype(np.uint8))


def generate_specular_map(image: Image.Image) -> Image.Image:
    """Existing Atlas Creator luminosity/contrast specular conversion."""
    spec = ImageOps.grayscale(image)
    return ImageEnhance.Contrast(spec).enhance(1.5)


def _material_token(index: int, cfg: dict) -> str:
    """Encode a material index in generated MAP aliases.

    Existing Atlas Creator output stays decimal. BZ2/BZCC can opt into one
    hexadecimal digit so material IDs 10..15 remain compact in MAP aliases.
    """
    if cfg.get("index_format", "decimal") == "hex":
        if not 0 <= index <= 15:
            raise ValueError("Hex atlas material names support indices 0..15")
        return format(index, "X")
    return str(index)


def build_custom_atlas(cfg: dict) -> dict:
    """Build and export a Custom Atlas Creator bundle without any GUI state."""
    res = cfg["res"]
    prfx = cfg["prfx"]
    prfx_upper = prfx.upper()
    mode = cfg["mode"]

    baked_data = []
    trn_blocks = {}
    indices = sorted(cfg["groups"].keys())
    if not indices:
        raise ValueError("Atlas build requires at least one texture group")

    for i in indices:
        trn_blocks[i] = {"solids": [], "transitions": []}

    for i in indices:
        vars_found = sorted(cfg["groups"][i].keys())
        token = _material_token(i, cfg)
        repeat_idx = f"{token}{token}"
        for idx, var in enumerate(vars_found):
            name = f"{prfx}{repeat_idx}s{var}0.MAP".upper()
            baked_data.append((name, cfg["groups"][i][var]))
            slot = chr(65 + idx)
            trn_blocks[i]["solids"].append((slot, name))

    c_m = generate_transition_mask("cap", cfg)
    d_m = generate_transition_mask("diag", cfg)
    pair_specs = []
    if mode == "ExplicitPairs":
        cap_pairs = frozenset(tuple(map(int, pair)) for pair in cfg.get("cap_pairs", ()))
        diagonal_pairs = frozenset(
            tuple(map(int, pair)) for pair in cfg.get("diagonal_pairs", ())
        )
        for i, j in sorted(cap_pairs | diagonal_pairs):
            if i not in cfg["groups"] or j not in cfg["groups"]:
                raise ValueError(
                    f"Explicit atlas transition {i}->{j} requires both material groups"
                )
            pair_specs.append((i, j, (i, j) in cap_pairs, (i, j) in diagonal_pairs))
    else:
        for idx, i in enumerate(indices):
            targets = (
                [indices[idx + 1]]
                if mode == "Linear" and idx + 1 < len(indices)
                else indices[idx + 1:]
                if mode == "Matrix"
                else []
            )
            pair_specs.extend((i, j, True, True) for j in targets)

    for i, j, want_cap, want_diagonal in pair_specs:
        base_img = cfg["groups"][i]["A"]
        target_img = cfg["groups"][j]["A"]
        i_token = _material_token(i, cfg)
        j_token = _material_token(j, cfg)
        c_name = d_name = None

        if want_cap:
            c_img = base_img.copy()
            c_img.paste(target_img, (0, 0), c_m)
            c_name = f"{prfx}{i_token}{j_token}cA0.MAP".upper()
            baked_data.append((c_name, c_img))
        if want_diagonal:
            d_img = base_img.copy()
            d_img.paste(target_img, (0, 0), d_m)
            d_name = f"{prfx}{i_token}{j_token}dA0.MAP".upper()
            baked_data.append((d_name, d_img))

        trn_blocks[i]["transitions"].append((j, c_name, d_name))

    gs = math.ceil(math.sqrt(len(baked_data)))
    at_res = gs * res
    at_img = Image.new("RGBA", (at_res, at_res), (128, 128, 128, 255))
    uv_step = 1.0 / gs
    csv_lines = [f",0,0,{uv_step:.6g},{uv_step:.6g}"]

    for idx, (name, img) in enumerate(baked_data):
        x_idx = idx % gs
        y_idx = idx // gs
        at_img.paste(img, (x_idx * res, y_idx * res))
        u = x_idx * uv_step
        v = y_idx * uv_step
        csv_lines.append(f"{name},{u:.6g},{v:.6g},{uv_step:.6g},{uv_step:.6g}")

    out_dir = cfg["out_dir"]
    os.makedirs(out_dir, exist_ok=True)
    written = []

    if cfg["exp_csv"]:
        mapping_filename = cfg.get("mapping_filename", f"{prfx}_mapping.csv")
        csv_path = os.path.join(out_dir, mapping_filename)
        with open(csv_path, "w") as f:
            f.write("\n".join(csv_lines))
        written.append(csv_path)

    def save_map_asset(img: Image.Image, suffix: str) -> str:
        base_filename = f"{prfx}_atlas_{suffix}"
        ext = ".dds" if cfg["exp_dds"] else ".png"
        if cfg["exp_png"]:
            png_path = os.path.join(out_dir, base_filename + ".png")
            img.save(png_path)
            written.append(png_path)
        if cfg["exp_dds"]:
            dds_path = os.path.join(out_dir, base_filename + ".dds")
            img.save(dds_path)
            written.append(dds_path)
        return base_filename + ext

    maps_to_write = {"DiffuseMap": save_map_asset(at_img, "d")}

    if cfg["exp_normal"]:
        maps_to_write["NormalMap"] = save_map_asset(generate_normal_map(at_img), "n")
    if cfg["exp_specular"]:
        maps_to_write["SpecularMap"] = save_map_asset(generate_specular_map(at_img), "s")

    if cfg["exp_emissive"]:
        mask = at_img.convert("L").point(lambda p: 255 if p > 220 else 0)
        black_bg = Image.new("RGB", at_img.size, (0, 0, 0))
        em_color = Image.composite(at_img, black_bg, mask)
        maps_to_write["EmissiveMap"] = save_map_asset(em_color, "e")
    else:
        maps_to_write["EmissiveMap"] = "black.dds"

    # Preserve the historical Custom Atlas reference by default. The BZ2 path
    # opts into a generated neutral map so every referenced runtime asset exists.
    detail_map = f"{prfx}_detail.dds"
    if cfg.get("exp_neutral_detail"):
        neutral_ext = ".dds" if cfg["exp_dds"] else ".png"
        detail_map = f"{prfx}_neutral{neutral_ext}"
        neutral_path = os.path.join(out_dir, detail_map)
        Image.new("RGB", (8, 8), (128, 128, 128)).save(neutral_path)
        written.append(neutral_path)
        if not cfg["exp_specular"]:
            maps_to_write["SpecularMap"] = detail_map

    mat_name = f"{prfx}_detail_atlas".upper()

    if cfg["exp_mat"]:
        mat_filename = f"{prfx}_detail_atlas"
        mat_path = os.path.join(out_dir, f"{mat_filename}.material")
        with open(mat_path, "w") as f:
            f.write('import * from "BZTerrainBase.material"\n\n')
            f.write(f'material {mat_filename.upper()} : BZTerrainBase\n{{\n')
            for alias, filename in maps_to_write.items():
                f.write(f'\tset_texture_alias {alias} {filename}\n')
            f.write(f'\tset_texture_alias DetailMap {detail_map}\n')
            f.write('\n\tset $diffuse "1 1 1"\n\tset $ambient "1 1 1"\n')
            f.write('\tset $specular ".25 .25 .25"\n\tset $shininess "63"\n}\n')
        written.append(mat_path)

    if cfg["exp_trn"]:
        trn_path = os.path.join(out_dir, f"{prfx_upper}_CONFIG.TRN")
        with open(trn_path, "w") as f:
            f.write("[Atlases]\n")
            f.write(f"MaterialName = {mat_name}\n\n")
            for idx in sorted(trn_blocks.keys()):
                f.write(f"[TextureType{idx}]\nFlatColor= 128\n")
                for slot, name in trn_blocks[idx]["solids"]:
                    f.write(f"Solid{slot}0 = {name}\n")
                for target, c_n, d_n in trn_blocks[idx]["transitions"]:
                    if c_n:
                        f.write(f"CapTo{target}_A0 = {c_n}\n")
                    if d_n:
                        f.write(f"DiagonalTo{target}_A0 = {d_n}\n")
        written.append(trn_path)

    return {
        "prefix": prfx_upper,
        "grid": gs,
        "atlas_size": [at_res, at_res],
        "tile_count": len(baked_data),
        "csv_lines": csv_lines,
        "trn_blocks": trn_blocks,
        "maps": maps_to_write,
        "written_files": written,
        "mapping_file": csv_path if cfg["exp_csv"] else None,
        "detail_map": detail_map,
    }
