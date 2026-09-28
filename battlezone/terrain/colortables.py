"""Legacy (Battlezone 1.x) palette work: quantising, world palettes, LUM/TBL/ALB.

Every stock world palette (achilles ... venus) shares entries 0-95 and 224-255
(interface, object and effect colours); only 96-223 are the world's own. Stock
terrain tiles only ever use 0-223. A world palette that keeps the shared entries
is therefore safe to drop into 1.5; one that does not (Redux never reads an ACT,
so Redux-era ACTs are often placeholders) recolours everything else in the game.

The three 64 KB colour tables beside each stock palette are palette-specific
256x256 lookups: ``.LUM`` (light level x colour), ``.TBL`` (colour x colour
translucency) and ``.ALB`` (alpha level x colour). :func:`transfer_table` moves a
stock table onto a new palette by mapping each new colour to its nearest stock
colour, looking the result up in the stock table and matching that colour back
into the new palette. Measured against the real tables (e.g. mars -> moon) it
cuts the colour error of reusing the stock table unchanged by a half to two
thirds for TBL and ALB. LUM keeps the base world's lighting curve.
"""

from __future__ import annotations

from typing import Iterable, Optional, Sequence

import numpy as np
from PIL import Image

__all__ = [
    "SHARED_INDICES", "WORLD_INDICES", "TERRAIN_INDICES", "STOCK_WORLDS", "TABLE_KINDS",
    "palette_array", "nearest_indices", "quantize", "palette_is_legacy_safe", "build_world_palette",
    "transfer_table", "act_bytes", "sample_pixels",
]

WORLD_INDICES = np.arange(96, 224)
SHARED_INDICES = np.concatenate([np.arange(0, 96), np.arange(224, 256)])
TERRAIN_INDICES = np.arange(0, 224)
STOCK_WORLDS = ("achilles", "elysium", "europa", "ganymede", "io", "mars", "moon", "titan", "venus")

# Which axes of each 256x256 table are palette indices: (rows, columns).
TABLE_KINDS = {"lum": (False, True), "tbl": (True, True), "alb": (False, True)}


def palette_array(palette) -> np.ndarray:
    """ACT bytes or a list of RGB triplets -> float (256, 3); short palettes are padded with black."""
    if isinstance(palette, (bytes, bytearray)):
        values = np.frombuffer(bytes(palette[:768]), dtype=np.uint8)
        values = values[: len(values) // 3 * 3].reshape(-1, 3)
    else:
        values = np.asarray(palette, dtype=np.float64).reshape(-1, 3)
    out = np.zeros((256, 3), dtype=np.float64)
    out[: min(256, len(values))] = values[:256]
    return out


def nearest_indices(colors: np.ndarray, palette: np.ndarray, allowed: Optional[Sequence[int]] = None,
                    chunk: int = 65536) -> np.ndarray:
    """Index of the nearest palette colour (squared RGB distance) for each row of ``colors``.

    Ties go to the lowest index, like MakeMAP. ``allowed`` limits the candidates.
    """
    colors = np.asarray(colors, dtype=np.float64).reshape(-1, 3)
    candidates = np.arange(256) if allowed is None else np.asarray(allowed, dtype=np.int64)
    choices = np.asarray(palette, dtype=np.float64)[candidates]
    out = np.empty(len(colors), dtype=np.int64)
    # |c - p|^2 = |c|^2 - 2 c.p + |p|^2; |c|^2 is the same for every p. Exact in
    # float64 for 8-bit colours, so ties still resolve to the lowest index.
    norms = (choices ** 2).sum(axis=1)
    for start in range(0, len(colors), chunk):
        block = colors[start:start + chunk]
        distance = norms[None, :] - 2.0 * (block @ choices.T)
        out[start:start + chunk] = candidates[distance.argmin(axis=1)]
    return out


def quantize(image: Image.Image, palette: np.ndarray, allowed: Optional[Sequence[int]] = None,
             dither: bool = False, transparent_index: Optional[int] = None) -> np.ndarray:
    """RGB(A) image -> (h, w) uint8 palette indices.

    Without dithering every pixel takes its exact nearest colour. With
    ``transparent_index``, pixels with alpha below 128 take that index and it
    is left out of the opaque candidates.
    """
    rgba = image.convert("RGBA")
    candidates = np.arange(256) if allowed is None else np.asarray(allowed, dtype=np.int64)
    if transparent_index is not None:
        candidates = candidates[candidates != transparent_index]
    if dither:
        indices = _dither(rgba.convert("RGB"), palette, candidates)
    else:
        pixels = np.asarray(rgba.convert("RGB"), dtype=np.float64).reshape(-1, 3)
        indices = nearest_indices(pixels, palette, candidates).reshape(rgba.height, rgba.width)
    indices = indices.astype(np.uint8)
    if transparent_index is not None:
        clear = np.asarray(rgba, dtype=np.uint8)[..., 3] < 128
        indices[clear] = transparent_index
    return indices


def _dither(rgb: Image.Image, palette: np.ndarray, candidates: np.ndarray) -> np.ndarray:
    """Floyd-Steinberg through Pillow, limited to ``candidates``."""
    colors = np.clip(np.rint(palette[candidates]), 0, 255).astype(np.uint8)
    padded = np.vstack([colors, np.repeat(colors[:1], 256 - len(colors), axis=0)])
    holder = Image.new("P", (1, 1))
    holder.putpalette(padded.tobytes())
    local = np.asarray(rgb.quantize(palette=holder, dither=Image.Dither.FLOYDSTEINBERG), dtype=np.int64)
    lookup = np.concatenate([candidates, np.full(256 - len(candidates), candidates[0])])
    return lookup[local]


def palette_is_legacy_safe(palette: np.ndarray, reference: np.ndarray, *, min_world_colors: int = 32) -> tuple[bool, str]:
    """Does ``palette`` keep ``reference``'s shared entries and carry real world colours?"""
    shared_match = float(np.all(palette[SHARED_INDICES] == reference[SHARED_INDICES], axis=1).mean())
    world_colors = len({tuple(c) for c in palette[WORLD_INDICES].astype(int)})
    if shared_match < 0.9:
        return False, (f"only {shared_match:.0%} of the shared entries (0-95, 224-255) match the stock palettes; "
                       "interface and object colours would change in 1.5")
    if world_colors < min_world_colors:
        return False, f"only {world_colors} distinct colours in the world range 96-223"
    return True, f"keeps the shared entries; {world_colors} world colours"


def build_world_palette(samples: np.ndarray, base: np.ndarray, *, iterations: int = 10, seed: int = 0) -> np.ndarray:
    """A 1.5 world palette for ``samples`` (N x 3 RGB): ``base`` with entries 96-223 refitted.

    Median cut seeds the 128 world colours; k-means then refines them while
    the shared terrain colours 0-95 stay fixed but still attract the pixels
    they already match well.
    """
    samples = np.asarray(samples, dtype=np.float64).reshape(-1, 3)
    palette = np.array(base, dtype=np.float64, copy=True)
    world = WORLD_INDICES
    count = len(world)
    if len(samples) == 0:
        return palette
    rng = np.random.default_rng(seed)
    if len(samples) > 200_000:
        samples = samples[rng.choice(len(samples), 200_000, replace=False)]
    strip = Image.fromarray(np.clip(np.rint(samples), 0, 255).astype(np.uint8).reshape(1, -1, 3), "RGB")
    seeded = strip.quantize(colors=count, method=Image.Quantize.MEDIANCUT)
    seeds = np.frombuffer(bytes(seeded.getpalette()[: count * 3]), dtype=np.uint8).reshape(-1, 3).astype(np.float64)
    if len(seeds) < count:
        extra = samples[rng.choice(len(samples), count - len(seeds), replace=len(samples) < count - len(seeds))]
        seeds = np.vstack([seeds, extra])
    palette[world] = seeds[:count]
    for _ in range(iterations):
        owner = nearest_indices(samples, palette, TERRAIN_INDICES)
        moved = False
        for index in world:
            members = samples[owner == index]
            if len(members):
                center = members.mean(axis=0)
                if not np.allclose(center, palette[index]):
                    palette[index] = center
                    moved = True
            else:
                # An unused world entry takes the worst-served sample.
                error = ((samples - palette[owner]) ** 2).sum(axis=1)
                palette[index] = samples[int(error.argmax())]
                moved = True
        if not moved:
            break
    palette[world] = np.clip(np.rint(palette[world]), 0, 255)
    return palette


def transfer_table(table: np.ndarray, base_palette: np.ndarray, new_palette: np.ndarray, kind: str) -> np.ndarray:
    """Re-express a stock 256x256 ``kind`` table (lum/tbl/alb) for ``new_palette``."""
    rows_are_colors, cols_are_colors = TABLE_KINDS[kind]
    table = np.asarray(table, dtype=np.int64).reshape(256, 256)
    to_base = nearest_indices(new_palette, base_palette)
    everything = np.arange(256)
    rows = to_base if rows_are_colors else everything
    cols = to_base if cols_are_colors else everything
    target = base_palette[table[np.ix_(rows, cols)]]
    return nearest_indices(target.reshape(-1, 3), new_palette).reshape(256, 256).astype(np.uint8)


def act_bytes(palette: np.ndarray) -> bytes:
    return np.clip(np.rint(palette), 0, 255).astype(np.uint8).tobytes()


def sample_pixels(images: Iterable[Image.Image], per_image: int = 4096, seed: int = 0) -> np.ndarray:
    """Up to ``per_image`` opaque RGB samples from each image, for :func:`build_world_palette`."""
    rng = np.random.default_rng(seed)
    parts = []
    for image in images:
        rgba = np.asarray(image.convert("RGBA"), dtype=np.uint8).reshape(-1, 4)
        rgba = rgba[rgba[:, 3] >= 128]
        if len(rgba) > per_image:
            rgba = rgba[rng.choice(len(rgba), per_image, replace=False)]
        parts.append(rgba[:, :3].astype(np.float64))
    return np.vstack(parts) if parts else np.zeros((0, 3))
