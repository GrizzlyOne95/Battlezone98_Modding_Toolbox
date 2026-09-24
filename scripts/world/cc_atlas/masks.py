"""Procedural cap / diagonal blend masks matching the stock Redux edge contract.

Measured across the nine shipped atlases (nearest-of-two classification of each
transition tile against its two solids):

  cap       N ~0%   S 63-99%   W ~0%   E 0-2%     - material B is a lens hugging
                                                    the south edge, pinched to
                                                    nothing at both side columns
  diagonal  N 0-1%  S 98-100%  W 0-1%  E 97-100%  - B fills the south-east, so
                                                    both shared edges read B

The pinch is what makes the tiles interchangeable: whatever sits to the west or
east of a cap sees solid A at the seam, so no pair of neighbours has to agree on
a boundary they were not authored together.
"""
import numpy as np
from PIL import Image, ImageFilter


def _fbm(n, seed, octaves=5, persistence=0.5):
    """Value-noise fractal in [0,1], smooth enough to threshold into blobs."""
    rng = np.random.default_rng(seed)
    acc = np.zeros((n, n), np.float32)
    amp, tot = 1.0, 0.0
    for o in range(octaves):
        res = 2 << o
        g = (rng.random((res, res)) * 255).astype(np.uint8)
        up = np.asarray(Image.fromarray(g).resize((n, n), Image.BICUBIC), np.float32) / 255.0
        acc += amp * up
        tot += amp
        amp *= persistence
    a = acc / tot
    return (a - a.min()) / max(float(np.ptp(a)), 1e-6)


def _feather(m, px):
    if px <= 0:
        return m
    img = Image.fromarray((np.clip(m, 0, 1) * 255).astype(np.uint8))
    return np.asarray(img.filter(ImageFilter.GaussianBlur(px)), np.float32) / 255.0


def cap_mask(n, seed, depth=0.40):
    """B enters from the south only, pinched to nothing at the west and east columns."""
    y = np.linspace(0.0, 1.0, n, dtype=np.float32)[:, None]        # 0 north .. 1 south
    x = (np.arange(n, dtype=np.float32) + 0.5) / n
    window = np.sin(np.pi * x)[None, :] ** 0.45                     # 0 at both side edges
    # a 2D fractal front, not a 1D profile: the extra octaves are what give the
    # ragged edge and the detached blobs the stock masks have
    profile = 0.30 + 1.45 * _fbm(n, seed, octaves=6, persistence=0.62)
    front = 1.0 - depth * window * profile
    m = (y > front).astype(np.float32)
    return _finish(m, n, south=True, east=False)


def diagonal_mask(n, seed, bias=0.02):
    """B fills the south-east, so both the south and east seams read B.

    The boundary is an anti-diagonal that has to *start* at the north-east
    corner and *end* at the south-west one, otherwise the east column or the
    south row loses its material-B cover part of the way up.  Damping the noise
    near those two corners pins the curve to them and lets it wander freely in
    between, which is what the stock diagonals do.
    """
    y = np.linspace(0.0, 1.0, n, dtype=np.float32)[:, None]
    x = np.linspace(0.0, 1.0, n, dtype=np.float32)[None, :]
    d_ne = np.hypot(1.0 - x, y)
    d_sw = np.hypot(x, 1.0 - y)
    pin = np.clip(np.minimum(d_ne, d_sw) / 0.42, 0.0, 1.0)
    field = 0.5 * (x + y) + 0.52 * pin * (_fbm(n, seed, octaves=6, persistence=0.60) - 0.5)
    m = (field > 0.5 - bias).astype(np.float32)
    return _finish(m, n, south=True, east=True)


def _finish(m, n, south, east):
    """Feather the interior, then re-assert the seam rows and columns exactly."""
    band = max(1, n // 128)
    m = _feather(m, max(1.0, n / 256.0))
    m[:band, :] = 0.0                       # north is always material A
    m[:, :band] = 0.0                       # so is west
    if not east:
        m[:, -band:] = 0.0
    if south:
        m[-band:, :] = 1.0
    if east:
        m[:, -band:] = 1.0
    return np.clip(m, 0.0, 1.0)
