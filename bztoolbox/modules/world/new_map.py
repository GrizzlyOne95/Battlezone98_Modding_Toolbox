"""Create a complete, playable map folder in one step.

A map the game can load needs a terrain (TRN, HG2, MAT, LGT), a mission BZN
whose class suits the menu it is in, and an INI that puts it in that menu.
This writes all of them, plus the BMP and DES the map list shows, into
``<parent>/<name>/`` so the folder can go straight into ``addon``.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import List

import numpy as np

from bztoolbox.modules.terrain_generator.lgt import compute_lgt_lightmap, write_lgt
from bztoolbox.modules.terrain_generator.settings import GeneratorSettings
from bztoolbox.modules.terrain_generator.starter_layouts import STARTER_LAYOUTS
from bztoolbox.modules.world import map_preview
from bztoolbox.modules.world.maketrn_compat import make_stock_geometry
from bztoolbox.modules.world.mat_codec import default_make_trn_rules
from bztoolbox.modules.world.msn2terrain import _worldbuilder_template
from bztoolbox.modules.world.new_map_bzn import write_new_map_bzn
from bztoolbox.modules.world.stock_map_creator import StockBuildConfig, build_stock_map

ZONE_METRES = 1280
SAMPLE_METRES = 5.0                 # 256 HG2 samples per zone
STOCK_MIN_Z = 99840                 # stock maps sit near z = 100000; so does the game's own /newmap
MAX_PLAYERS = 16
GAME_TYPES = {"D": "MultDMMission", "S": "MultSTMission"}
WORLDS = ("Moon", "Mars", "Venus", "Io", "Europa", "Ganymede", "Achilles", "Elysium", "Titan")


@dataclass(frozen=True)
class NewMap:
    folder: str
    files: List[str]


def ini_text(name: str, mode: str, *, min_players: int = 2, max_players: int = 4, game_type: str = "D") -> str:
    text = f'[DESCRIPTION]\nmissionName = "{name}"\n\n[WORKSHOP]\nmapType = "{mode}"\n;customtags = ""\n'
    if mode == "multiplayer":
        text += (f'\n[MULTIPLAYER]\nminPlayers = "{min_players}"\nmaxPlayers = "{max_players}"\n'
                 f'gameType = "{game_type}"\n; D=Deathmatch, S=Strategy\n')
    return text


def create_new_map(parent_dir: str, name: str, *, mode: str = "instant_action", world: str = "Moon",
                   zones: int = 3, layout: str = "Flat Field", seed: int = 1,
                   min_players: int = 2, max_players: int = 4, game_type: str = "D") -> NewMap:
    """Write a new map folder ``<parent_dir>/<name>`` and return what was written.

    ``mode`` is "instant_action" or "multiplayer"; ``zones`` is the side of the
    square map in 1280 m zones; ``layout`` is a starter layout name. A
    multiplayer map gets ``max_players`` spawn points.
    """
    if mode not in ("instant_action", "multiplayer"):
        raise ValueError(f"unknown map mode {mode!r}")
    if layout not in STARTER_LAYOUTS:
        raise ValueError(f"unknown layout {layout!r}")
    if game_type not in GAME_TYPES:
        raise ValueError(f"unknown game type {game_type!r}")
    if not 1 <= min_players <= max_players <= MAX_PLAYERS:
        raise ValueError(f"players must be 1 <= min <= max <= {MAX_PLAYERS}")
    folder = os.path.join(parent_dir, name)

    hg2 = STARTER_LAYOUTS[layout](GeneratorSettings(zones_x=zones, zones_z=zones, seed=seed))
    heights = np.asarray(hg2.heights, dtype=np.uint16)
    normal_view, static_trn = _worldbuilder_template(world)
    built = build_stock_map(StockBuildConfig(
        name=name, out_dir=folder, geometry=make_stock_geometry(zones * ZONE_METRES, zones * ZONE_METRES),
        empty_elevation=0, time_of_day=1100,
        music_track=27, music_loop_first=27, music_loop_last=27, music_loop_skip=-1,
        ambient=(1.0, 1.0, 1.0), diffuse=(1.0, 1.0, 1.0), specular=(1.0, 1.0, 1.0),
        normal_view=normal_view, static_trn=static_trn, paint_rules=default_make_trn_rules(),
        legacy_seed=seed, min_x=0, min_z=STOCK_MIN_Z, source_heights=heights))
    files = [built.trn_path, built.hg2_path, built.mat_path]

    lgt_path = os.path.join(folder, f"{name}.lgt")
    write_lgt(lgt_path, compute_lgt_lightmap(heights, zones, zones, lgt_zone_size=256), zones, zones)
    files.append(lgt_path)

    previews = map_preview.write_previews(built.trn_path)
    if previews:
        jpg, bmp = previews
        os.remove(jpg)              # the map list shows only the BMP
        files.append(bmp)

    des_path = os.path.join(folder, f"{name}.des")
    with open(des_path, "w", encoding="utf-8") as stream:
        stream.write(f"{name}\n")
    ini_path = os.path.join(folder, f"{name}.ini")
    with open(ini_path, "w", encoding="utf-8") as stream:
        stream.write(ini_text(name, mode, min_players=min_players, max_players=max_players, game_type=game_type))
    files += [des_path, ini_path]

    rows, cols = heights.shape

    def ground(x: float, z: float) -> float:   # HG2 row 0 is the south (min z) edge
        row = min(rows - 1, max(0, int((z - STOCK_MIN_Z) / SAMPLE_METRES)))
        col = min(cols - 1, max(0, int(x / SAMPLE_METRES)))
        return float(heights[row, col]) * 0.1

    size = float(zones * ZONE_METRES)
    bzn_path = os.path.join(folder, f"{name}.bzn")
    write_new_map_bzn(bzn_path, name, mode, (0.0, float(STOCK_MIN_Z), size, size), ground,
                      players=max_players,
                      mission_class=GAME_TYPES[game_type] if mode == "multiplayer" else None)
    files.append(bzn_path)
    return NewMap(folder, files)
