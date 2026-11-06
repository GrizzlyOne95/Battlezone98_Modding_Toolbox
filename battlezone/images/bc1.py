"""Vectorised BC1/DXT1 encoder: PCA endpoint fit plus least-squares refinement.

Pillow's built-in encoder is a plain bounding-box fit, which costs about 5 dB on
high-chroma data such as a tangent-space normal map.  This does the standard
principal-axis fit and then re-solves the endpoints from the chosen indices,
keeping whichever candidate measures best per block.
"""
import numpy as np

_W = np.array([0.2126, 0.7152, 0.0722], dtype=np.float32)   # perceptual error weights


def _to565(c):
    c = np.clip(c, 0, 255)
    r = np.rint(c[..., 0] * 31.0 / 255.0).astype(np.int32)
    g = np.rint(c[..., 1] * 63.0 / 255.0).astype(np.int32)
    b = np.rint(c[..., 2] * 31.0 / 255.0).astype(np.int32)
    return (r << 11) | (g << 5) | b


def _from565(v):
    r = (v >> 11) & 31
    g = (v >> 5) & 63
    b = v & 31
    out = np.empty(v.shape + (3,), dtype=np.float32)
    out[..., 0] = (r << 3) | (r >> 2)
    out[..., 1] = (g << 2) | (g >> 4)
    out[..., 2] = (b << 3) | (b >> 2)
    return out


def _palette(c0, c1):
    """Four-colour opaque BC1 palette for quantised endpoints."""
    a, b = _from565(c0), _from565(c1)
    return np.stack([a, b, (2 * a + b) / 3.0, (a + 2 * b) / 3.0], axis=1)   # (N,4,3)


def _fit(blocks, e0, e1):
    """Quantise a candidate endpoint pair, pick indices, return (err, c0, c1, idx)."""
    c0, c1 = _to565(e0), _to565(e1)
    swap = c0 < c1                       # c0 > c1 selects the opaque 4-colour block
    c0, c1 = np.where(swap, c1, c0), np.where(swap, c0, c1)
    eq = c0 == c1                        # a degenerate pair still decodes, index 0
    pal = _palette(c0, c1)                                        # (N,4,3)
    d = blocks[:, :, None, :] - pal[:, None, :, :]                # (N,16,4,3)
    err = ((d * d) * _W).sum(-1)                                  # (N,16,4)
    idx = err.argmin(2)
    tot = np.take_along_axis(err, idx[..., None], 2)[..., 0].sum(1)
    idx = np.where(eq[:, None], 0, idx)
    return tot, c0, c1, idx


def encode_bc1(img, max_blocks=1 << 18):
    """img: HxWx3 uint8 (H,W multiples of 4). Returns packed BC1 bytes.

    Encoded in horizontal bands so an 8192^2 atlas does not need a 3 GB
    intermediate: BC1 block order is row-major, so concatenating bands in order
    reproduces the whole-image result exactly.
    """
    a = np.asarray(img)
    h, w = a.shape[:2]
    rows_per_band = max(4, (max_blocks // max(1, w // 4)) * 4)
    if h > rows_per_band:
        return b"".join(_encode(a[y:y + rows_per_band])
                        for y in range(0, h, rows_per_band))
    return _encode(a)


def _encode(img):
    a = np.asarray(img, dtype=np.float32)
    h, w = a.shape[:2]
    bh, bw = h // 4, w // 4
    blocks = (a.reshape(bh, 4, bw, 4, 3).transpose(0, 2, 1, 3, 4)
               .reshape(bh * bw, 16, 3))

    mean = blocks.mean(1, keepdims=True)
    cen = blocks - mean
    cov = np.einsum("nki,nkj->nij", cen, cen) / 16.0
    # principal axis by power iteration, seeded away from any single channel
    v = np.broadcast_to(np.array([0.9, 1.0, 0.7], np.float32), (blocks.shape[0], 3)).copy()
    for _ in range(8):
        v = np.einsum("nij,nj->ni", cov, v)
        n = np.linalg.norm(v, axis=1, keepdims=True)
        v = np.where(n > 1e-9, v / np.maximum(n, 1e-9), np.array([1.0, 0, 0], np.float32))
    t = np.einsum("nki,ni->nk", cen, v)
    lo, hi = t.min(1)[:, None], t.max(1)[:, None]
    pca0 = mean[:, 0] + v * hi
    pca1 = mean[:, 0] + v * lo

    def keep(best, cand):
        better = cand[0] < best[0]
        return (np.where(better, cand[0], best[0]),
                np.where(better, cand[1], best[1]),
                np.where(better, cand[2], best[2]),
                np.where(better[:, None], cand[3], best[3]))

    best = _fit(blocks, pca0, pca1)
    # bounding box is occasionally better on flat blocks
    best = keep(best, _fit(blocks, blocks.max(1), blocks.min(1)))
    # least-squares re-solve of the endpoints from the current index assignment
    e0, e1 = _from565(best[1]), _from565(best[2])
    for _ in range(3):
        idx = best[3]
        wgt = np.choose(idx, [1.0, 0.0, 2.0 / 3.0, 1.0 / 3.0]).astype(np.float32)   # weight of e0
        u = wgt[..., None]
        a11 = (u * u).sum(1)[:, 0]
        a22 = ((1 - u) * (1 - u)).sum(1)[:, 0]
        a12 = (u * (1 - u)).sum(1)[:, 0]
        b1 = (u * blocks).sum(1)
        b2 = ((1 - u) * blocks).sum(1)
        det = a11 * a22 - a12 * a12
        ok = np.abs(det) > 1e-6
        d = np.where(ok, det, 1.0)[:, None]
        n0 = (a22[:, None] * b1 - a12[:, None] * b2) / d
        n1 = (a11[:, None] * b2 - a12[:, None] * b1) / d
        n0 = np.where(ok[:, None], n0, e0)
        n1 = np.where(ok[:, None], n1, e1)
        best = keep(best, _fit(blocks, n0, n1))
        e0, e1 = _from565(best[1]), _from565(best[2])

    c0, c1, idx = best[1], best[2], best[3]
    packed = (idx.astype(np.uint32) << (2 * np.arange(16, dtype=np.uint32))[None, :]).sum(1)
    out = np.empty((blocks.shape[0], 8), dtype=np.uint8)
    out[:, 0] = c0 & 0xFF
    out[:, 1] = (c0 >> 8) & 0xFF
    out[:, 2] = c1 & 0xFF
    out[:, 3] = (c1 >> 8) & 0xFF
    p = packed.astype(np.uint32)
    out[:, 4] = p & 0xFF
    out[:, 5] = (p >> 8) & 0xFF
    out[:, 6] = (p >> 16) & 0xFF
    out[:, 7] = (p >> 24) & 0xFF
    return out.tobytes()


def decode_bc1(data, w, h):
    """Round-trip helper used by the tests and the quality report."""
    b = np.frombuffer(data, dtype=np.uint8).reshape(-1, 8)
    c0 = b[:, 0].astype(np.int32) | (b[:, 1].astype(np.int32) << 8)
    c1 = b[:, 2].astype(np.int32) | (b[:, 3].astype(np.int32) << 8)
    pal = _palette(c0, c1)
    bits = (b[:, 4].astype(np.uint32) | (b[:, 5].astype(np.uint32) << 8)
            | (b[:, 6].astype(np.uint32) << 16) | (b[:, 7].astype(np.uint32) << 24))
    idx = (bits[:, None] >> (2 * np.arange(16, dtype=np.uint32))[None, :]) & 3
    px = np.take_along_axis(pal, idx[..., None], 1)
    bh, bw = h // 4, w // 4
    return (px.reshape(bh, bw, 4, 4, 3).transpose(0, 2, 1, 3, 4)
              .reshape(h, w, 3).astype(np.uint8))
