"""Lossless 256 x 256 LUM editing and Redux's palette-based atmosphere.

Redux GOG 2.2.301, 0x780160: normal fog uses ACT[LUM[223]], sky uses
ACT[223]. FogDirection=0 uses ACT[0] for both. Explicit TRN SkyColor and
FogColor override these defaults. This does not recolour DDS terrain.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PIL import Image

TABLE_SIZE = 256 * 256


def validate_act(data: bytes) -> bytes:
    """Validate RGB payload, retaining an optional four-byte Adobe footer."""
    if len(data) not in (768, 772):
        raise ValueError("ACT must contain 768 RGB bytes, optionally followed by a 4-byte footer")
    return bytes(data)


def _index(value: int) -> int:
    if not isinstance(value, int) or not 0 <= value <= 255:
        raise ValueError("Table rows, columns and palette indices must be integers from 0 to 255")
    return value


@dataclass
class LumaTable:
    data: bytearray

    def __post_init__(self):
        if len(self.data) != TABLE_SIZE:
            raise ValueError("LUM must contain exactly 65,536 bytes (256 rows x 256 columns)")
        self.data = bytearray(self.data)

    @classmethod
    def read(cls, path):
        return cls(bytearray(Path(path).read_bytes()))

    @classmethod
    def identity(cls, fog_index: int = 223):
        """Neutral table for authoring; not a generated legacy lighting curve."""
        table = cls(bytearray(bytes(range(256)) * 256))
        table.set_cell(0, 223, fog_index)
        return table

    def write(self, path):
        Path(path).write_bytes(bytes(self.data))

    def cell(self, row: int, column: int) -> int:
        return self.data[_index(row) * 256 + _index(column)]

    def set_cell(self, row: int, column: int, palette_index: int):
        self.data[_index(row) * 256 + _index(column)] = _index(palette_index)

    def image(self, act: bytes | None = None) -> Image.Image:
        image = Image.frombytes("L", (256, 256), bytes(self.data))
        if act is not None:
            image = Image.frombytes("P", (256, 256), bytes(self.data))
            image.putpalette(validate_act(act)[:768])
        return image

    def export_png(self, path, act: bytes | None = None):
        self.image(act).save(path, format="PNG")

    @classmethod
    def from_png(cls, path):
        with Image.open(path) as image:
            if image.format != "PNG" or image.size != (256, 256) or image.mode not in ("P", "L"):
                raise ValueError("Use a 256 x 256 indexed (P) or 8-bit grayscale (L) PNG; RGB loses table indices")
            return cls(bytearray(image.tobytes()))


def atmosphere(act: bytes, table: LumaTable | None = None, fog_direction: int = 1,
               *, sky_color=None, fog_color=None) -> dict:
    """Resolve the defaults the Redux loader actually selects, not a fixed 209."""
    palette = validate_act(act)
    sky_index = 0 if fog_direction == 0 else 223
    fog_index = 0 if fog_direction == 0 else (table.cell(0, 223) if table else 223)

    def rgb(index, override):
        if override is None:
            return tuple(palette[index * 3:index * 3 + 3])
        values = tuple(override)
        if len(values) != 3:
            raise ValueError("RGB overrides require three integers from 0 to 255")
        return tuple(_index(v) for v in values)

    return dict(sky_index=sky_index, fog_index=fog_index,
                sky_rgb=rgb(sky_index, sky_color), fog_rgb=rgb(fog_index, fog_color))
