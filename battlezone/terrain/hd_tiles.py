"""Portable, GUI-free authoring bundles for OpenShim's native HD terrain arrays.

The atlas CSV supplies rectangle metadata only. Image pixels always come from
independent authored tiles. Original terrain/atlas resources remain the fallback.
"""
from __future__ import annotations

import copy
import csv
import hashlib
import json
import math
import os
import re
import shutil
import struct
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

from battlezone.images import dds
from battlezone.terrain.atlas import validate_tile_name

SCHEMA = "bzr-terrain-hd-authoring-v1"
RUNTIME_SCHEMA = "bzr-openshim-terrain-hd-v2"
CHANNELS = {"D": "diffuse", "N": "normal", "S": "specular", "E": "emissive"}
MANIFEST = "terrain_hd_tiles.json"


def _json(path):
    value = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object in {Path(path).name}")
    return value


def _write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def _safe_name(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+", value) or value in (".", ".."):
        raise ValueError(f"Use a simple resource filename/prefix without directories: {value!r}")
    return value


def _alias(value):
    value = str(value).strip().upper()
    validate_tile_name(value)
    if not re.fullmatch(r"[A-Z0-9_-]+\.MAP", value):
        raise ValueError(f"Expected a terrain MAP alias: {value!r}")
    return value


def read_layout(path, default_alias):
    """Retain repeated aliases at distinct rectangles, including the nameless row."""
    default_alias = _alias(default_alias)
    rows = []
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        for number, row in enumerate(csv.reader(stream), 1):
            if not row or not any(part.strip() for part in row):
                continue
            if len(row) != 5:
                raise ValueError(f"Layout line {number}: expected NAME,u,v,width,height")
            alias = _alias(row[0]) if row[0].strip() else default_alias
            rect = [float(v) for v in row[1:]]
            _validate_rect(rect)
            for previous in rows:
                if max(abs(a - b) for a, b in zip(rect, previous["rect"])) <= 1e-6:
                    if previous["alias"] != alias:
                        raise ValueError(f"Layout line {number}: ambiguous rectangle selects different aliases")
                    break
            else:
                rows.append({"alias": alias, "rect": rect})
    if not 1 <= len(rows) <= 256:
        raise ValueError("Layout needs 1..256 distinct rectangles")
    return rows


def _validate_rect(rect):
    if (len(rect) != 4 or not all(math.isfinite(v) for v in rect)
            or min(rect[:2]) < 0 or min(rect[2:]) <= 0
            or rect[0] + rect[2] > 1.000001 or rect[1] + rect[3] > 1.000001):
        raise ValueError(f"Invalid normalized atlas rectangle: {rect}")


def new_project(source_dir, layout, *, material, diffuse_resource, default_alias,
                normal_resource="", specular_resource="", emissive_resource="",
                tile_size=1024, prefix="hd", normal_space="directx"):
    """Discover ALIAS_d/n/s/e images; enabled channels must be complete."""
    root = Path(source_dir).resolve()
    aliases = sorted({r["alias"] for r in read_layout(layout, default_alias)} | {_alias(default_alias)})
    guards = {"D": diffuse_resource, "N": normal_resource, "S": specular_resource, "E": emissive_resource}
    files = {}
    for path in sorted(root.iterdir()):
        if path.is_file() and path.suffix.lower() in (".png", ".tga", ".dds", ".tif", ".tiff", ".bmp"):
            key = path.stem.casefold()
            if key in files:
                raise ValueError(f"Ambiguous image basename: {path.stem}; keep one format per tile/channel")
            files[key] = path
    tiles = {}
    for alias in aliases:
        tiles[alias] = {}
        for channel, guard in guards.items():
            if not guard:
                continue
            key = f"{Path(alias).stem}_{channel}".casefold()
            if key not in files:
                raise ValueError(f"Missing source {key}.png/.tga/.dds for enabled {CHANNELS[channel]} channel")
            tiles[alias][channel] = str(files[key])
    project = {"schema": SCHEMA, "material": material, "layout": str(Path(layout).resolve()),
            "defaultAlias": _alias(default_alias), "tileSize": tile_size, "prefix": prefix,
            "normalSpace": normal_space, "resources": {k: v for k, v in guards.items() if v}, "tiles": tiles}
    _validated(project)
    return project


def load_project(path):
    """Read a Toolbox recipe or import a ready CR source-tile export, without executing code."""
    path = Path(path).resolve()
    if path.is_dir():
        if (path / "authoring.json").is_file():
            path /= "authoring.json"
        else:
            metadata = _json(path / "source_tiles.json")
            if metadata.get("schema") != "cr-mars-hd-source-tiles-v1":
                raise ValueError("Unsupported source_tiles.json schema")
            manifest = _json(path / "cr_mars_hd.json")
            if manifest.get("schema") != RUNTIME_SCHEMA or len(manifest.get("materials", {})) != 1:
                raise ValueError("CR import needs one v2 terrain material")
            material, binding = next(iter(manifest["materials"].items()))
            resources = {"D": binding["diffuseResource"]}
            for channel, key in CHANNELS.items():
                if channel != "D" and key in binding:
                    if channel == "N" and binding[key].get("encoding") != "rgb-xyz-linear":
                        raise ValueError("Only RGB XYZ linear normal maps are supported")
                    resources[channel] = binding[key]["sourceResource"]
            return {"schema": SCHEMA, "material": material, "layout": str(path / "native_layout.csv"),
                    "defaultAlias": metadata["defaultAlias"], "tileSize": metadata["tileSize"],
                    "prefix": "hd", "normalSpace": "directx", "resources": resources,
                    "tiles": {a: {c: str((path / t[c]).resolve()) for c in resources}
                              for a, t in metadata["aliases"].items()}}
    project = _json(path)
    if project.get("schema") != SCHEMA:
        raise ValueError(f"Expected {SCHEMA}")
    project["layout"] = str((path.parent / project["layout"]).resolve())
    for channels in project["tiles"].values():
        for channel, source in channels.items():
            channels[channel] = str((path.parent / source).resolve())
    return project


def save_project(path, project, *, overwrite=False):
    """Save relative paths; replacing a recipe requires an explicit caller choice."""
    path = Path(path).resolve()
    value = copy.deepcopy(project)
    def relative(source):
        try:
            return Path(os.path.relpath(source, path.parent)).as_posix()
        except ValueError:  # different Windows drive
            return str(Path(source).resolve())
    value["layout"] = relative(value["layout"])
    for channels in value["tiles"].values():
        for channel, source in channels.items():
            channels[channel] = relative(source)
    text = json.dumps(value, indent=2, allow_nan=False) + "\n"
    if not overwrite:
        with path.open("x", encoding="utf-8") as stream:
            stream.write(text)
    else:
        descriptor, temporary = tempfile.mkstemp(prefix=".authoring-", suffix=".json", dir=path.parent)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(text)
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)


def inspect_dds(path):
    """Strict classic 2D DDS inspection, including every mip's byte range."""
    path = Path(path)
    with path.open("rb") as stream:
        header = stream.read(128)
    if len(header) != 128 or header[:4] != b"DDS " or struct.unpack_from("<I", header, 4)[0] != 124:
        raise ValueError(f"Invalid DDS header: {path.name}")
    flags, height, width, pitch, depth, mips = struct.unpack_from("<6I", header, 8)
    pf_size, pf_flags, fourcc, bits, rm, gm, bm, am = struct.unpack_from("<II4s5I", header, 76)
    caps2 = struct.unpack_from("<I", header, 112)[0]
    if pf_size != 32 or depth > 1 or caps2 or flags & 0x800000:
        raise ValueError(f"Only ordinary 2D DDS textures are supported: {path.name}")
    if not width or not height or max(width, height) > 16384:
        raise ValueError(f"Invalid DDS dimensions: {path.name}")
    if pf_flags & dds.DDPF_FOURCC:
        if fourcc not in (b"DXT1", b"DXT5"):
            raise ValueError(f"Unsupported DDS encoding {fourcc!r}: {path.name}; use RGB XYZ normals")
        fmt = fourcc.decode("ascii")
    elif (pf_flags & dds.DDPF_RGB and bits in (24, 32)
          and (rm, gm, bm) == (0xff0000, 0xff00, 0xff)
          and am == (0xff000000 if bits == 32 else 0)):
        fmt = f"RGB{bits}"
        if flags & 8 and pitch != width * (bits // 8):
            raise ValueError(f"DDS row padding is unsupported: {path.name}; export tightly packed RGB")
    else:
        raise ValueError(f"Unsupported DDS pixel masks: {path.name}; export BC1, BC3 or RGB24/RGBA32")
    mips = max(1, mips) if flags & dds.DDSD_MIPMAPCOUNT else 1
    if mips > max(width, height).bit_length():
        raise ValueError(f"Too many DDS mip levels: {path.name}")
    offsets, sizes = [], []
    offset, w, h = 128, width, height
    for _ in range(mips):
        size = (max(1, (w + 3) // 4) * max(1, (h + 3) // 4) * (8 if fmt == "DXT1" else 16)
                if fmt.startswith("DXT") else w * h * (bits // 8))
        offsets.append(offset)
        sizes.append(size)
        offset += size
        w, h = max(1, w // 2), max(1, h // 2)
    if path.stat().st_size != offset:
        raise ValueError(f"DDS payload is truncated or has extra data: {path.name}")
    return {"width": width, "height": height, "mips": mips, "format": fmt,
            "offsets": offsets, "sizes": sizes, "bytes": offset}


def _normal_resize(rgba, size):
    vectors = rgba[:, :, :3].astype(np.float32) / 127.5 - 1
    vectors = np.stack([np.asarray(Image.fromarray(vectors[:, :, c]).resize((size, size), Image.Resampling.LANCZOS))
                        for c in range(3)], axis=2)
    lengths = np.linalg.norm(vectors, axis=2, keepdims=True)
    vectors = np.divide(vectors, lengths, out=np.zeros_like(vectors), where=lengths > 1e-8)
    vectors[lengths[:, :, 0] <= 1e-8] = (0, 0, 1)
    rgb = np.clip(np.rint((vectors + 1) * 127.5), 0, 255).astype(np.uint8)
    return np.dstack([rgb, np.full((size, size), 255, np.uint8)])


def _convert(source, target, channel, size, normal_space):
    info = inspect_dds(source) if source.suffix.lower() == ".dds" else None
    if channel == "N" and info and info["format"].startswith("DXT"):
        raise ValueError(f"{source.name}: use unpacked RGB XYZ normals, not compressed/packed normal data")
    wanted = "RGB24" if channel == "N" else "DXT1"
    full_mips = size.bit_length()
    if (info and info["format"] == wanted and info["width"] == info["height"] == size
            and info["mips"] == full_mips and (channel != "N" or normal_space == "directx")):
        shutil.copyfile(source, target)
        return "preserved"
    if info and info["format"].startswith("DXT"):
        levels = []
        with source.open("rb") as stream:
            for i, (offset, count) in enumerate(zip(info["offsets"], info["sizes"])):
                stream.seek(offset)
                levels.append(dds.decode_level(stream.read(count), max(1, info["width"] >> i),
                                               max(1, info["height"] >> i), info["format"]))
    elif info:
        levels, _ = dds.read_dds(str(source))
    else:
        with Image.open(source) as image:
            levels = [np.array(image.convert("RGBA"))]
    h, w = levels[0].shape[:2]
    if w != h or w < size:
        raise ValueError(f"{source.name}: source must be square and at least {size}px; no upscaling")
    if channel != "N" and any(np.any(level[:, :, 3] != 255) for level in levels):
        raise ValueError(f"{source.name}: terrain BC1 channels require opaque RGB; alpha data needs explicit repacking")
    if channel == "N" and normal_space == "opengl":
        for level in levels:
            level[:, :, 1] = 255 - level[:, :, 1]
    # Preserve matching authored mip levels; fill only the missing tail.
    matching = next((i for i, lv in enumerate(levels) if lv.shape[:2] == (size, size)), None)
    if matching is not None:
        levels = levels[matching:]
    else:
        base = (_normal_resize(levels[0], size) if channel == "N" else
                np.array(Image.fromarray(levels[0]).resize((size, size), Image.Resampling.LANCZOS)))
        levels = [base]
    while len(levels) < full_mips:
        next_size = max(1, size >> len(levels))
        levels.append(_normal_resize(levels[-1], next_size) if channel == "N" else
                      np.array(Image.fromarray(levels[-1]).resize((next_size, next_size), Image.Resampling.LANCZOS)))
    if channel == "N":
        dds.write_dds_uncompressed(str(target), levels, alpha=False)
    else:
        dds.write_dds(str(target), size, size,
                      [dds.encode_level(lv, "DXT1", max_blocks=16384) for lv in levels], "DXT1")
    return "converted"


def _validated(project):
    if project.get("schema") != SCHEMA:
        raise ValueError(f"Expected {SCHEMA}")
    size = project["tileSize"]
    if type(size) is not int or size < 4 or size > 4096 or size & (size - 1):
        raise ValueError("Tile size must be a power of two from 4 to 4096; start with 1024")
    if project.get("normalSpace", "directx") not in ("directx", "opengl"):
        raise ValueError("normalSpace must be directx or opengl (RGB XYZ linear)")
    material = project["material"]
    if not isinstance(material, str) or not material.strip() or any(c in material for c in "\r\n\0"):
        raise ValueError("An exact Ogre material name is required")
    _safe_name(project["prefix"])
    resources = project["resources"]
    if "D" not in resources or set(resources) - CHANNELS.keys():
        raise ValueError("resources requires D and optional N/S/E source-resource guards")
    for resource in resources.values():
        _safe_name(resource)
    if len(set(v.casefold() for v in resources.values())) != len(resources):
        raise ValueError("Channel source-resource guards must be distinct")
    rows = read_layout(project["layout"], project["defaultAlias"])
    aliases = sorted({r["alias"] for r in rows} | {_alias(project["defaultAlias"])})
    if len(aliases) > 256:
        raise ValueError("A material supports at most 256 physical slices")
    for alias in aliases:
        if alias not in project["tiles"]:
            raise ValueError(f"Missing tile {alias}")
        for channel in resources:
            source = Path(project["tiles"][alias].get(channel, ""))
            if not source.is_file():
                raise ValueError(f"Missing {CHANNELS[channel]} source for {alias}: {source}")
            if source.suffix.lower() == ".dds":
                info = inspect_dds(source)
                w, h = info["width"], info["height"]
            else:
                with Image.open(source) as image:
                    w, h = image.size
            if w != h or w < size:
                raise ValueError(f"{source.name}: source must be square and at least {size}px; no upscaling")
    return rows, aliases


def build_bundle(project, output, *, progress=None, check_cancelled=None):
    """Write a fresh directory atomically; failure/cancellation leaves no partial bundle."""
    rows, aliases = _validated(project)
    output = Path(output).resolve()
    if output.exists():
        raise ValueError(f"Output already exists; choose a new bundle folder: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{output.name}-", dir=output.parent))
    try:
        (staging / "resources").mkdir()
        (staging / "sources").mkdir()
        shutil.copyfile(project["layout"], staging / "layout.csv")
        recipe = copy.deepcopy(project)
        recipe["layout"] = "layout.csv"
        recipe["tiles"] = {}
        indices = {alias: i for i, alias in enumerate(aliases)}
        binding = {"sliceCount": len(aliases), "releaseSourceTextures": True,
                   "diffuseResource": project["resources"]["D"],
                   "tileRects": [{"rect": r["rect"], "slice": indices[r["alias"]]} for r in rows]}
        actions = {"preserved": 0, "converted": 0}
        files = []
        total = len(aliases) * len(project["resources"])
        for channel, guard in project["resources"].items():
            entry = binding if channel == "D" else {"sourceResource": guard}
            entry["tiles"] = {}
            for alias in aliases:
                if check_cancelled:
                    check_cancelled()
                source = Path(project["tiles"][alias][channel])
                stem = f"{project['prefix']}_{Path(alias).stem.lower()}_{channel.lower()}"
                resource = _safe_name(stem + ".dds")
                if resource.casefold() in {v.casefold() for v in project["resources"].values()}:
                    raise ValueError(f"HD resource {resource} collides with an original atlas guard; choose another prefix")
                action = _convert(source, staging / "resources" / resource, channel,
                                  project["tileSize"], project.get("normalSpace", "directx"))
                actions[action] += 1
                master = "sources/" + stem + source.suffix.lower()
                shutil.copyfile(source, staging / master)
                recipe["tiles"].setdefault(alias, {})[channel] = master
                entry["tiles"][str(indices[alias])] = resource
                files.append(resource)
                if progress:
                    progress(len(files) / total, f"{alias} {CHANNELS[channel]}: {action}")
            entry["fallback"] = entry["tiles"][str(indices[_alias(project["defaultAlias"])])]
            if channel != "D":
                if channel == "N":
                    entry["encoding"] = "rgb-xyz-linear"
                binding[CHANNELS[channel]] = entry
        manifest = {"schema": RUNTIME_SCHEMA, "materials": {project["material"]: binding}}
        _write_json(staging / MANIFEST, manifest)
        _write_json(staging / "authoring.json", recipe)
        report = check_bundle(staging)
        report["conversion"] = actions
        _write_json(staging / "bundle_report.json", report)
        (staging / "README.txt").write_text(BUNDLE_README, encoding="utf-8")
        if check_cancelled:
            check_cancelled()
        staging.rename(output)
        return {**report, "output": str(output)}
    finally:
        if staging.exists() and staging.resolve().parent == output.parent:
            shutil.rmtree(staging)  # only this invocation's fresh temporary directory


def check_bundle(folder):
    """Validate this tool's complete bundle, guards, mappings, DDS and source recipe."""
    folder = Path(folder).resolve()
    project = load_project(folder / "authoring.json")
    rows, aliases = _validated(project)
    manifest = _json(folder / MANIFEST)
    if manifest.get("schema") != RUNTIME_SCHEMA or set(manifest.get("materials", {})) != {project["material"]}:
        raise ValueError("Runtime material/schema differs from authoring recipe")
    binding = manifest["materials"][project["material"]]
    indices = {a: i for i, a in enumerate(aliases)}
    expected = [{"rect": r["rect"], "slice": indices[r["alias"]]} for r in rows]
    if (binding.get("sliceCount") != len(aliases) or binding.get("tileRects") != expected
            or "sliceRemap" in binding or binding.get("diffuseResource") != project["resources"]["D"]
            or binding.get("releaseSourceTextures") is not True):
        raise ValueError("Runtime mapping/guards differ from authoring recipe")
    enabled = set(project["resources"])
    if any((key in binding) != (c in enabled) for c, key in CHANNELS.items() if c != "D"):
        raise ValueError("Runtime channels differ from authoring recipe")
    files, seen, disk_bytes, gpu_bytes = [], set(), 0, 0
    for channel, guard in project["resources"].items():
        entry = binding if channel == "D" else binding[CHANNELS[channel]]
        if channel != "D" and entry.get("sourceResource") != guard:
            raise ValueError("Runtime channel source guard mismatch")
        if channel == "N" and entry.get("encoding") != "rgb-xyz-linear":
            raise ValueError("Normal encoding must be rgb-xyz-linear")
        tiles = entry.get("tiles", {})
        if set(tiles) != {str(i) for i in range(len(aliases))}:
            raise ValueError("Every enabled channel must define every physical slice")
        if entry.get("fallback") != tiles[str(indices[_alias(project["defaultAlias"])])]:
            raise ValueError("Fallback must select defaultAlias")
        for alias in aliases:
            name = tiles[str(indices[alias])]
            expected_name = f"{project['prefix']}_{Path(alias).stem.lower()}_{channel.lower()}.dds"
            if name != expected_name:
                raise ValueError(f"Resource mapping differs from recipe for {alias} {channel}")
            _safe_name(name)
            if name.casefold() in {g.casefold() for g in project["resources"].values()}:
                raise ValueError("HD resource collides with original atlas")
            if name.casefold() in seen:
                raise ValueError("HD resources must have unique names")
            seen.add(name.casefold())
            files.append(name)
            path = folder / "resources" / name
            info = inspect_dds(path)
            size = project["tileSize"]
            if (info["width"] != size or info["height"] != size or info["mips"] != size.bit_length()
                    or info["format"] != ("RGB24" if channel == "N" else "DXT1")):
                raise ValueError(f"Inconsistent dimensions, format or mip chain: {name}")
            disk_bytes += info["bytes"]
            gpu_bytes += (sum(max(1, size >> i) ** 2 * 4 for i in range(size.bit_length()))
                          if channel == "N" else sum(info["sizes"]))
    # Hash actual emitted resources, useful when importing an already validated pack.
    hashes = {}
    for name in files:
        with (folder / "resources" / name).open("rb") as stream:
            digest = hashlib.sha256()
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        hashes[name] = digest.hexdigest()
    return {"schema": "bzr-terrain-hd-bundle-report-v1", "material": project["material"],
            "tileSize": project["tileSize"], "slices": len(aliases), "rectangles": len(rows),
            "channels": list(project["resources"]), "resourceCount": len(files), "ddsBytes": disk_bytes,
            "estimatedGpuArrayBytes": gpu_bytes, "processRamEstimate": None,
            "memoryNote": "GPU storage is not 32-bit process RAM. Profile private bytes, peak and largest free VA in game.",
            "sha256": hashes}


BUNDLE_README = """OpenShim HD terrain authoring bundle

Shipping: copy the CONTENTS of resources/ into your mod's Ogre resource folder;
copy terrain_hd_tiles.json beside your mod content. Keep the ordinary material,
atlas, CSV, TRN and MAT installed for fallback. Sources/ and authoring.json are
editable masters, not required at runtime. Respect the source art's license.

Requires an OpenShim build with native HD material packs (v2), authored tiles,
matching material/source-resource guards, and effective DX11 Enhanced rendering.
EXU is not required. This tooling does not install or enable anything in game.

In openshim.ini, use [Terrain]:
TerrainHdEnabled=1
TerrainHdManifest=addon\\YOUR_MOD\\terrain_hd_tiles.json

The manifest path is relative to the game executable (or use an absolute path).
In OpenShim settings enable HD Terrain Tiles and DX11 Enhanced. With HD disabled
or Enhanced inactive, OpenShim retains the normal stock atlas rendering.
Keep native terrain enabled; do not turn on the experimental terrain proxy.

The material and original atlas names in the manifest are exact identity guards.
Copying files alone will not apply HD to unrelated maps. Assign this material
and matching CSV through the map's existing TRN [Atlases] MaterialName.

Rebuild anywhere after editing sources:
  bztoolbox terrain hd-tiles build authoring.json --out ../my-next-bundle
Validate before packaging:
  bztoolbox terrain hd-tiles check . --json

Normal inputs are linear RGB XYZ. normalSpace=directx retains Y; opengl flips
green during export. Output normal mips are RGB24; generated mips renormalize
vectors. D/S/E export as opaque BC1. Existing suitable DDS mip chains are kept.
Start with 1024px. GPU array estimates in bundle_report.json do not predict
32-bit process RAM; measure private bytes, peaks and largest free VA in game.
See the Toolbox guide docs/world/HD_TERRAIN_TILES.md for authoring details.
"""
