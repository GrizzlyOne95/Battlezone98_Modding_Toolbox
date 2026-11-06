"""The BZN of a brand-new map, laid out like the one the game writes for ``/newmap /edit``.

The game's own fresh map holds one object, the player's tank, and no paths or
AOIs. A multiplayer map also needs ``spawnpnt`` objects, as stock maps have.
Fields left out here are filled with defaults by ``write_bzn``.
"""
from __future__ import annotations

import math
from typing import Callable, Sequence, Tuple

from battlezone.bzn.bz1 import BZNFile, BZNObject, Field

REDUX_VERSION = 2016
PLAYER_ODF = "avtank"            # stock Grizzly: maxHealth 3000, maxAmmo 1200
SPAWN_ODF = "pspwn_1"
OBJ_ADDR_BASE = 0x40EA6000        # the game's fresh map gives its tank 40EA7000
MISSION_CLASS = {"instant_action": "LuaMission", "multiplayer": "MultDMMission"}


def _transform(x: float, y: float, z: float, yaw: float) -> tuple:
    """A level matrix facing ``yaw`` radians (0 = +Z): right, up, front, position."""
    c, s = math.cos(yaw), math.sin(yaw)
    return (c, 0.0, -s, 0.0, 1.0, 0.0, s, 0.0, c, x, y, z)


def _object(prjid: str, seq: int, label: str, pos: Tuple[float, float, float], yaw: float,
            *, team: int, user: bool, health: int, ammo: int) -> BZNObject:
    x, y, z = pos
    alive = health > 0
    fields = {
        "PrjID": Field("id", prjid.encode("latin-1")),
        "seqno": Field("short", seq),
        "pos": Field("vec3", [(x, y, z)]),
        "team": Field("ulong", team),
        "label": Field("chars", label.encode("latin-1")),
        "isUser": Field("ulong", 1 if user else 0),
        "obj_addr": Field("ptr", OBJ_ADDR_BASE + seq * 0x1000),   # unique, as the game's own saves are
        "transform": Field("mat", _transform(x, y, z, yaw)),
        "illumination": Field("float", 1.0 if alive else 0.0),
        "pos2": Field("vec3", [(x, y, z)]),
        "euler": Field("euler", (1750.0, 1 / 1500, 0.0, 1e30, 1500.0, 1.0) + (0.0,) * 9 if alive
                       else (0.0, 1e30, 0.0, 1e30, 1.0) + (0.0,) * 10),
        "seqNo": Field("ulong", seq),
        "isVisible": Field("hexlong", 2 if alive else 1),
        "seen": Field("hexlong", 2 if alive else 1),
        "healthRatio": Field("float", 1.0 if alive else 0.0),
        "curHealth": Field("long", health),
        "maxHealth": Field("long", health),
        "ammoRatio": Field("float", 1.0 if alive else 0.0),
        "curAmmo": Field("long", ammo),
        "maxAmmo": Field("long", ammo),
        "aiProcess": Field("bool", alive),
        "independence": Field("ulong", 1),
        "perceivedTeam": Field("long", team),
    }
    return BZNObject("wingman" if alive else "spawnpnt", fields)


def spawn_points(centre: Tuple[float, float], radius: float, count: int) -> list:
    """``count`` points spaced evenly on a circle, each with the yaw that faces the centre."""
    cx, cz = centre
    points = []
    for i in range(count):
        angle = 2 * math.pi * i / count
        x, z = cx + radius * math.sin(angle), cz + radius * math.cos(angle)
        points.append((x, z, math.atan2(cx - x, cz - z)))
    return points


def new_map_bzn(name: str, mode: str, bounds: Tuple[float, float, float, float],
                ground: Callable[[float, float], float], players: int = 2,
                mission_class: str | None = None) -> BZNFile:
    """A fresh map BZN for terrain ``name``.

    ``mode`` is "instant_action" or "multiplayer". ``bounds`` is the TRN's
    (MinX, MinZ, Width, Depth). ``ground(x, z)`` gives the terrain height there.
    A multiplayer map gets ``players`` spawn points in a ring, and the player
    starts on the first one; an instant-action player starts in the centre.
    ``mission_class`` replaces the mode's default class (e.g. "MultSTMission").
    """
    if mode not in MISSION_CLASS:
        raise ValueError(f"unknown map mode {mode!r}")
    min_x, min_z, width, depth = bounds
    centre = (min_x + width / 2, min_z + depth / 2)
    spawns = spawn_points(centre, 0.35 * min(width, depth), players) if mode == "multiplayer" else []
    start = spawns[0] if spawns else (centre[0], centre[1], 0.0)

    def at(x, z):
        return (x, ground(x, z) + 1.0, z)

    objects = [_object(PLAYER_ODF, 1, f"{PLAYER_ODF}0_wingman", at(start[0], start[1]), start[2],
                       team=1, user=True, health=3000, ammo=1200)]
    for index, (x, z, yaw) in enumerate(spawns):
        objects.append(_object(SPAWN_ODF, index + 2, f"{SPAWN_ODF}{index}_spawnpnt", at(x, z), yaw,
                               team=0, user=False, health=0, ammo=0))
    header = {
        "msn_filename": Field("chars", f"{name}.bzn".encode("latin-1")),
        "seq_count": Field("ulong", len(objects) + 2),
        "TerrainName": Field("chars", name.encode("latin-1")),
    }
    mission = {"name": Field("chars", (mission_class or MISSION_CLASS[mode]).encode("latin-1"))}
    return BZNFile(REDUX_VERSION, False, False, header, objects, mission, [], [])


def write_new_map_bzn(path, *args, **kw) -> Sequence[str]:
    """Write :func:`new_map_bzn` to ``path``."""
    bzn = new_map_bzn(*args, **kw)
    with open(path, "wb") as stream:
        stream.write(bzn.write())
    return [obj.prjid for obj in bzn.objects]
