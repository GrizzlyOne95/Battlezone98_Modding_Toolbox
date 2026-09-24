"""BZ2/BZCC terrain layer compositing semantics.

Source proof from original BZ2 editor decompilation:
- MapCluster::GetAlpha returns 255 for layer 0 and stored AlphaMap1..3 bytes
  for layers 1..3.
- MapRadar::FillTerrainMap starts with layer 0 and sequentially alpha-blends
  layers 1, 2, then 3 using integer /255 arithmetic.
- TerrainClass::ComputeLayer derives the per-cluster visibility mask from the
  alpha maps; visibility is a rendering/culling optimization, not a weight.

Therefore the effective normalized weights are:
  w0 = (1-a1)(1-a2)(1-a3)
  w1 = a1(1-a2)(1-a3)
  w2 = a2(1-a3)
  w3 = a3
where ai is AlphaMap i / 255.
"""
from __future__ import annotations

import numpy as np


def sequential_layer_weights(alphas: np.ndarray) -> np.ndarray:
    """Return effective layer-0..3 weights for AlphaMap1..3.

    alphas must have shape (3, height, width) and byte-like values 0..255.
    The returned float32 array has shape (4, height, width) and sums to 1 at
    every sample within floating-point precision.
    """
    values = np.asarray(alphas)
    if values.ndim != 3 or values.shape[0] != 3:
        raise ValueError("BZ2 alpha maps must have shape (3, height, width)")
    if np.issubdtype(values.dtype, np.floating):
        if not np.isfinite(values).all():
            raise ValueError("BZ2 alpha maps contain non-finite values")
    if values.size and (values.min() < 0 or values.max() > 255):
        raise ValueError("BZ2 alpha values must be in the range 0..255")

    a1, a2, a3 = values.astype(np.float64) / 255.0
    i1 = 1.0 - a1
    i2 = 1.0 - a2
    i3 = 1.0 - a3
    return np.stack([
        i1 * i2 * i3,
        a1 * i2 * i3,
        a2 * i3,
        a3,
    ]).astype(np.float32)


def blend_rgb_u8(layer_colors, alpha_values) -> tuple[int, int, int]:
    """Mirror BZ2 editor's integer terrain-color blend for one sample.

    layer_colors is four RGB triples. alpha_values is the three bytes for
    layers 1..3. Division intentionally truncates at each layer, matching the
    decompiled FillTerrainMap implementation.
    """
    colors = np.asarray(layer_colors, dtype=np.int64)
    alpha = np.asarray(alpha_values, dtype=np.int64)
    if colors.shape != (4, 3):
        raise ValueError("layer_colors must contain four RGB triples")
    if alpha.shape != (3,):
        raise ValueError("alpha_values must contain AlphaMap1..3")
    if (colors < 0).any() or (colors > 255).any():
        raise ValueError("RGB values must be in the range 0..255")
    if (alpha < 0).any() or (alpha > 255).any():
        raise ValueError("alpha values must be in the range 0..255")

    current = colors[0].copy()
    for layer, amount in enumerate(alpha, start=1):
        if amount:
            current = (colors[layer] * amount + current * (255 - amount)) // 255
    return tuple(int(value) for value in current)
