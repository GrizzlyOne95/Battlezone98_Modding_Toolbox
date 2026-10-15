"""Conservative, editable Redux atmosphere presets, not calibrated sky models.

Only the sky/fog entries change. DDS terrain and all other ACT bytes are kept.
Airless worlds stay near black; atmospheric worlds retain their stock identity.
"""
from .lum import validate_act

# RGB choices are art direction. Fog indices are the stock LUM[223] mappings.
WORLD_ATMOSPHERES = {
    "moon": dict(sky=(5, 5, 5), fog=(5, 5, 5), fog_index=223),
    "mars": dict(sky=(213, 160, 113), fog=(174, 112, 77), fog_index=209),
    "venus": dict(sky=(83, 66, 31), fog=(131, 106, 58), fog_index=209),
    "io": dict(sky=(3, 1, 0), fog=(3, 1, 0), fog_index=223),
    "europa": dict(sky=(1, 2, 3), fog=(1, 2, 3), fog_index=223),
    "titan": dict(sky=(112, 65, 27), fog=(153, 90, 35), fog_index=209),
    "achilles": dict(sky=(55, 66, 70), fog=(103, 113, 113), fog_index=209),
    "ganymede": dict(sky=(2, 2, 2), fog=(2, 2, 2), fog_index=223),
    "elysium": dict(sky=(48, 44, 50), fog=(48, 44, 50), fog_index=223),
}


def tune_world_act(world: str, base: bytes, *, fog_index: int | None = None) -> bytes:
    """Apply a world's two atmospheric colors, retaining all other bytes.

    Supply the actual LUM fog index for a custom table. One shared index cannot
    hold different sky and fog RGB values; fix the mapping explicitly first.
    """
    key = world.casefold().removesuffix(".act")
    if key not in WORLD_ATMOSPHERES:
        raise ValueError(f"Unknown world: {world}")
    preset = WORLD_ATMOSPHERES[key]
    index = preset["fog_index"] if fog_index is None else fog_index
    if not isinstance(index, int) or not 0 <= index <= 255:
        raise ValueError("Fog index must be an integer from 0 to 255")
    if index == 223 and preset["sky"] != preset["fog"]:
        raise ValueError("This preset needs separate sky and fog entries. Load the world's LUM or map LUM[223] to a different ACT entry first.")
    result = bytearray(validate_act(base))
    result[669:672] = bytes(preset["sky"])
    result[index * 3:index * 3 + 3] = bytes(preset["fog"])
    return bytes(result)
