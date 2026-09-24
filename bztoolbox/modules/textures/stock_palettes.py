"""Stock ACT palettes; the implementation is :mod:`battlezone.terrain.palettes`."""

from battlezone.terrain.palettes import STOCK_PALETTE_NAMES, get_stock_palette_bytes  # noqa: F401


def get_stock_palette(name: str) -> list[tuple[int, int, int]]:
    """A stock palette as 256 RGB tuples; KeyError if unknown."""
    raw = get_stock_palette_bytes(name)
    return [tuple(raw[i:i + 3]) for i in range(0, 768, 3)]
