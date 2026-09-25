"""Model checks: legacy ``.geo`` / ``.vdf`` / ``.sdf`` and Ogre ``.mesh`` files.

The rules come from the BZ98R Blender ToolKit's exporter validation and its
decompile research (docs/GEO_TYPES_RESEARCH.md, GEO_FLAGS_RESEARCH.md), turned
into checks that run on the files a mod ships rather than on a Blender scene.
Stock assets are known by name from ``data/stock_models.json`` (built by
``scripts/research/build_stock_models.py``), so a part or material the game
already provides is not reported as missing.
"""

from __future__ import annotations

import json
import os
import re
from collections import Counter
from functools import lru_cache
from typing import Iterator

from battlezone.bzn.scan import STOCK_SET
from battlezone.meshes.legacy import BwdModel, GeoFile, ModelError, read_model
from battlezone.meshes.ogre import MeshError, read_mesh

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")

# Classes whose .geo the loader never opens (hardpoints, eyepoint, emitters...).
VEHICLE_INVISIBLE_CLASSES = frozenset({38, 40, 70, 71, 72, 73, 74, 75, 76, 77})
STRUCTURE_INVISIBLE_CLASSES = frozenset({38, 40, 70, 71, 72, 73, 74})
ODF_REMAP_CLASSES = {1: "HELICOPTER", 3: "POWERUP", 6: "VEHICLE"}
EYEPOINT, TURRET, WEAPON_HARDPOINT, SMOKE_EMITTER = 40, 65, 70, 76
FIXED_LIST_LIMIT = 8                  # Craft/Producer::FindSmokeSource arrays
FLAG_DESTROYED = 0x200
VDF_MODEL_BANDS = (0, 4, 8)           # lod slots 0-2 at damage state 0; the rest are damage reps
LEGACY_FACE_VERTS = 10
MAX_BONE_WEIGHTS = 4
_MATERIAL_DEF = re.compile(r"^\s*material\s+([^\s:{]+)", re.I | re.M)
_PLAIN_NAME = re.compile(r"^[\w\-]+$")


@lru_cache(maxsize=1)
def stock_models() -> dict:
    try:
        with open(os.path.join(DATA_DIR, "stock_models.json"), encoding="utf-8") as handle:
            return {key: frozenset(values) for key, values in json.load(handle).items()}
    except (OSError, ValueError):
        return {}


def _issue(severity, message, path, rule, suggestion=""):
    from battlezone.validation.engine import Issue
    return Issue(severity, "models", message, path, rule_id=rule, suggestion=suggestion)


def check_models(ctx) -> Iterator:
    stock = stock_models()
    have = ctx.names_lower
    for path in ctx.with_suffix(".geo", ".vdf", ".sdf"):
        ctx.check_cancel()
        rel = ctx.rel(path)
        try:
            model = read_model(path)
        except (ModelError, OSError) as exc:
            yield _issue("error", f"Could not read model: {exc}", rel, "model-read-error",
                         "Re-export the file; the game reads it the same way and may crash.")
            continue
        if isinstance(model, GeoFile):
            yield from _check_geo(model, rel)
        else:
            yield from _check_bwd(model, rel, have, stock)

    materials = set(stock.get("materials", ()))
    for path in ctx.with_suffix(".material"):
        try:
            text = path.read_text(encoding="latin-1", errors="ignore")
        except OSError:
            continue
        materials.update(name.strip('"').lower() for name in _MATERIAL_DEF.findall(text))
    skeletons = have | stock.get("skeleton", frozenset())
    for path in ctx.with_suffix(".mesh"):
        ctx.check_cancel()
        yield from _check_mesh(path, ctx.rel(path), materials, skeletons)


# ---------------------------------------------------------------------------
# GEO
# ---------------------------------------------------------------------------

def _check_geo(geo: GeoFile, rel: str) -> Iterator:
    if geo.vertex_count == 0 or not geo.faces:
        yield _issue("warning", f"GEO has {geo.vertex_count} vertices and {len(geo.faces)} faces",
                     rel, "geo-empty", "An empty part renders nothing and has no collision.")
    if geo.bad_vertices:
        yield _issue("error", f"{geo.bad_vertices} vertices have NaN or infinite coordinates", rel,
                     "geo-bad-vertex", "Fix the mesh and re-export; bad coordinates break bounds and collision.")
    out_of_range = [i for i, face in enumerate(geo.faces)
                    if any(v < 0 or v >= geo.vertex_count for v in face.vertices)]
    if out_of_range:
        yield _issue("error", f"{len(out_of_range)} faces use vertex numbers outside the "
                     f"{geo.vertex_count}-vertex list (first: face {out_of_range[0]})", rel, "geo-bad-index",
                     "Re-export the GEO; the engine reads past the vertex list for these faces.")
    degenerate = sum(1 for face in geo.faces if len(face.vertices) < 3)
    if degenerate:
        yield _issue("warning", f"{degenerate} faces have fewer than 3 vertices", rel, "geo-degenerate-face",
                     "The collision builder skips them; delete them in the model.")
    large = sum(1 for face in geo.faces if len(face.vertices) > LEGACY_FACE_VERTS)
    if large:
        yield _issue("info", f"{large} faces have more than {LEGACY_FACE_VERTS} vertices", rel,
                     "geo-large-face", "Legacy GEO tools reserve 10 vertex slots per face; split large n-gons.")


# ---------------------------------------------------------------------------
# VDF / SDF
# ---------------------------------------------------------------------------

def _is_placeholder(name: str) -> bool:
    return name.lower() == "null" or not _PLAIN_NAME.match(name)


def _check_bwd(model: BwdModel, rel: str, have, stock) -> Iterator:
    vehicle = model.kind == "vdf"
    invisible = VEHICLE_INVISIBLE_CLASSES if vehicle else STRUCTURE_INVISIBLE_CLASSES
    base = [part for part in model.band(0) if not _is_placeholder(part.name)]
    names = Counter(part.name.lower() for part in base)
    stock_geo = stock.get("geo", frozenset())
    mesh_name = rel.rsplit("/", 1)[-1].rsplit(".", 1)[0].lower() + ".mesh"
    redux_mesh = mesh_name if mesh_name in have or mesh_name in stock.get("mesh", ()) else ""

    checked = set()
    for band in (VDF_MODEL_BANDS if vehicle else (0,)):
        for part in model.band(band):
            key = part.name.lower()
            if _is_placeholder(part.name) or part.klass in invisible or key in checked:
                continue
            checked.add(key)
            geo = key + ".geo"
            if geo not in have and geo not in stock_geo:
                where = "" if band == 0 else f" (LOD band {band})"
                message = f"Part '{part.name}'{where} needs {part.name}.geo, which is not in the mod or the stock game"
                if redux_mesh:
                    # untested whether Redux opens the GEO when the model has a mesh
                    yield _issue("info", message + f"; {redux_mesh} exists, so Redux may not need it", rel,
                                 "model-missing-part", "Ship the GEO if the model must also load without the mesh.")
                else:
                    yield _issue("warning", message, rel, "model-missing-part",
                                 "Ship the GEO, or rename the part to one that exists.")

    for part in base:
        label = ODF_REMAP_CLASSES.get(part.klass)
        if label and f"{part.name.lower()}.odf" not in have and f"{part.name.lower()}.odf" not in STOCK_SET:
            yield _issue("error", f"Part '{part.name}' has class {part.klass} ({label}), so the engine loads "
                         f"{part.name}.odf for it, and that ODF does not exist", rel, "model-part-odf-remap",
                         "Change the part's class (60 is an ordinary vehicle part); a missing ODF here crashes the game.")
        if part.flags & FLAG_DESTROYED:
            yield _issue("warning", f"Part '{part.name}' has object flag 0x200 set, which spawns it destroyed: "
                         "targeting skips it and it stops blocking paths", rel, "model-destroyed-flag",
                         "Clear the flag unless the part is meant to be a non-blocking deck.")
        if part.klass == TURRET and part.name[6:7].lower() not in ("x", "y"):
            yield _issue("warning", f"Turret part '{part.name}' (class 65) has '{part.name[6:7] or '?'}' as its "
                         "7th character; the engine reads x or y there to pick the rotation axis, and assumes y "
                         "otherwise", rel, "model-turret-name", "Rename it with tx#/ty# in characters 6-8.")
        parent = part.parent.lower()
        if parent and parent != "world" and parent not in names:
            yield _issue("warning", f"Part '{part.name}' is parented to '{part.parent}', which is not a part of "
                         "this model", rel, "model-bad-parent", "It will be attached to the model root instead.")

    for name, count in names.items():
        if count > 1:
            yield _issue("warning", f"{count} parts are named '{name}'", rel, "model-duplicate-part",
                         "Parts are found by name; only one of them is used as a parent or animation target.")

    smoke = sum(1 for part in base if part.klass == SMOKE_EMITTER)
    if smoke > FIXED_LIST_LIMIT:
        yield _issue("error", f"{smoke} smoke emitters (class 76); the engine keeps them in a fixed list of "
                     f"{FIXED_LIST_LIMIT} and writes past it", rel, "model-smoke-overflow",
                     f"Keep at most {FIXED_LIST_LIMIT}; more corrupts memory or crashes.")

    if vehicle:
        eyepoints = [part.name for part in base if part.klass == EYEPOINT]
        if not eyepoints:
            yield _issue("info", "Vehicle has no eyepoint part (class 40)", rel, "model-no-eyepoint",
                         "Fine for towers and powerups; a vehicle the player can drive needs one.")
        elif len(eyepoints) > 1:
            yield _issue("warning", f"{len(eyepoints)} eyepoint parts (class 40): {', '.join(eyepoints)}", rel,
                         "model-multiple-eyepoints", "The craft uses one; remove the extras.")
        if "COLP" not in model.chunks:
            yield _issue("warning", "Vehicle has no collision (COLP) block", rel, "model-no-collision",
                         "Every stock VDF has one; generate inner/outer collision before exporting.")
    else:
        hardpoints = sum(1 for part in base if part.klass == WEAPON_HARDPOINT)
        if hardpoints > FIXED_LIST_LIMIT:
            yield _issue("warning", f"{hardpoints} weapon hardpoints (class 70); a producing structure keeps them "
                         f"in a fixed list of {FIXED_LIST_LIMIT}", rel, "model-hardpoint-overflow",
                         f"Keep at most {FIXED_LIST_LIMIT} if this structure builds units.")
        if "VLOC" in model.chunks:
            yield _issue("warning", "Structure has a VLOC block; only the vehicle loader reads VLOC", rel,
                         "model-vloc-structure", "Move the injection to a VDF, or drop it.")
    if not model.canonical_header:
        yield _issue("info", "Non-standard BWD2 header values", rel, "model-header",
                     "Stock files use version 8; re-export if the game refuses the file.")


# ---------------------------------------------------------------------------
# Ogre .mesh
# ---------------------------------------------------------------------------

def _check_mesh(path, rel: str, materials, skeletons) -> Iterator:
    if path.stat().st_size == 0:
        yield _issue("error", "Mesh file is empty (0 bytes)", rel, "mesh-read-error",
                     "Re-export the mesh or remove it; Ogre fails to load an empty file.")
        return
    try:
        mesh = read_mesh(path)
    except (MeshError, OSError, ValueError) as exc:
        yield _issue("error", f"Could not read mesh: {exc}", rel, "mesh-read-error",
                     "Re-export the mesh; Ogre fails to load it the same way.")
        return
    if not mesh.submeshes:
        yield _issue("warning", "Mesh has no submeshes", rel, "mesh-empty", "Nothing will render.")
    missing = sorted({sub.material for sub in mesh.submeshes if sub.material.lower() not in materials})
    for material in missing:
        yield _issue("warning", f"Submesh material '{material}' is not defined in any .material file of the mod "
                     "or the stock game", rel, "mesh-missing-material",
                     "Ogre draws it with its white/pink fallback; define the material or fix the name.")
    if mesh.skeleton and mesh.skeleton.lower() not in skeletons:
        yield _issue("warning", f"Mesh links skeleton '{mesh.skeleton}', which is not in the mod or the stock game",
                     rel, "mesh-missing-skeleton", "Ship the skeleton or fix the link.")
    weighted = bool(mesh.bone_assignments) or any(sub.bone_assignments for sub in mesh.submeshes)
    if weighted and not mesh.skeleton:
        yield _issue("warning", "Mesh has bone weights but links no skeleton", rel, "mesh-bones-no-skeleton",
                     "The weights are ignored and the mesh will not animate.")
    for index, sub in enumerate(mesh.submeshes):
        geometry = mesh.shared_geometry if sub.uses_shared_vertices else sub.geometry
        count = geometry.vertex_count if geometry else 0
        if sub.indices and max(sub.indices) >= count:
            yield _issue("error", f"Submesh {index} ({sub.material}) indexes vertex {max(sub.indices)} of "
                         f"{count}", rel, "mesh-bad-index", "Re-export; out-of-range indices crash the renderer.")
    per_vertex = Counter()
    for vertex, _bone, _weight in mesh.bone_assignments:
        per_vertex[("shared", vertex)] += 1
    for index, sub in enumerate(mesh.submeshes):
        for vertex, _bone, _weight in sub.bone_assignments:
            per_vertex[(index, vertex)] += 1
    heavy = sum(1 for count in per_vertex.values() if count > MAX_BONE_WEIGHTS)
    if heavy:
        yield _issue("warning", f"{heavy} vertices have more than {MAX_BONE_WEIGHTS} bone weights", rel,
                     "mesh-too-many-weights", f"Ogre keeps {MAX_BONE_WEIGHTS} per vertex; limit weights before export.")
