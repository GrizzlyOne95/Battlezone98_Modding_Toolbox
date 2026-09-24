"""Bring a mod's terrain detail maps inside the envelope the Redux shader assumes.

A detail map is not an ordinary texture. The terrain shader samples it and
multiplies: `detail.xyz * 2`, lerped toward white by `saturate(vDepth * 0.025)`.
Two consequences drive everything here.

**Its mean is a calibration constant, not art.** 0.5 is the value that makes the
`* 2` a no-op. A map averaging 0.26 multiplies by 0.52 instead of 1.0.

**And the error is local.** The lerp saturates at 40 units, so a wrong mean is
not a global tint -- it is a brightness disc roughly 40 m across, centred on the
camera, that slides along with the player. That is why this is worth fixing even
where the tint looks deliberate: whatever the author wanted, the detail map can
only apply it within 40 m of the viewer. Per-world brightness belongs in the
material's $diffuse/$ambient or in the atlas, where it applies at every range.

**Its standard deviation is how much detail actually reaches the screen.** The
seven stock maps sit between 0.139 and 0.203. Below that band the map is doing
almost nothing (ISDF Chronicles' pluto_detail is 0.054); above it the grain
reads as noise rather than surface.

So: mean to 0.50, and contrast moved *only if it falls outside the stock band* --
a map already inside it keeps its author's contrast untouched. Gain is applied
around the mean and backed off before it saturates more than stock does -- and
the two ends are budgeted separately, because a texel at 1.0 becomes a 2x
brightness multiplier (glare) while one at 0.0 becomes 0x (dark speckle). If
even a pure DC shift would exceed those, the mean is corrected with a gamma
curve instead, which cannot clip at all.

Confirmed against the consuming code, not inferred from the stock art. Stock
`terrain-sm4.hlsl:402` is `detailMap.Sample(detailSam, frac(vTexCoord * 8)).xyz * 2`,
and OpenShim's Enhanced terrain shader pins the same neutral point deliberately --
`detail_modulation()` is `1 + (raw*2 - 1) * 0.55`, with a comment noting that an
sRGB decode would move neutral to ~0.43 and "the whole terrain would darken by
more than half". Enhanced then weights the result by 0.35 and multiplies in a
second octave sampled at `vTexCoord * 32`. So: 0.5 is neutral in both paths, the
Redux profile applies the full +-2x swing while Enhanced damps it to roughly a
fifth, and because the shader fixes the tiling rate, the file's resolution is
what sets on-screen detail density -- the *32 octave makes that matter four
times more under Enhanced than under stock.

Resolution and format are separate defects with a separate fix: these ship as
uncompressed 8192-square RGB, 256 MB each, against stock's 2048-square DXT1 at
2.67 MB. A tiling detail texture under a `* 2` multiply does not need either, so
they come out DXT1 at MAX_SIZE with a full mip chain.
"""
import os, struct, sys

import numpy as np
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import bc1
from ddswrite import write_dxt1
from worlds2 import MOD_DIR

Image.MAX_IMAGE_PIXELS = None

TARGET_MEAN = 0.50
# measured over the seven stock detail maps under BZ_ASSETS/pc/textures/
# TerrainTextures/Detail: means 0.4634..0.5479, stds 0.1389..0.2029
STOCK_STD = (0.1389, 0.2029)
STOCK_MEDIAN_STD = 0.1617
# Stock saturates 0.010%-1.567% of its texels (median 0.268%) -- it uses the
# full 0..1 range, so a budget below that is tighter than the art it imitates
# and was what stopped the under-driven maps short of the band on the first run.
#
# Split, because the two ends are not the same risk. A texel at 1.0 becomes a
# 2x brightness multiplier and is what "blinding" means; a texel at 0.0 becomes
# 0x, which reads as dark speckle. So the bright end is held to stock's own
# worst case (ac_detail, 1.03% at 255) while the dark end gets more room --
# which is the whole reason bane_detail can reach full band contrast at all:
# its saturation is 3% dark and 0.00% bright, peaking at 1.49x against stock's
# 2.00x. A symmetric budget spent it all on the dark end and stopped short.
BRIGHT_BUDGET = 0.011
DARK_BUDGET = 0.035
MAX_SIZE = int(os.environ.get("DETAIL_MAX_SIZE", "4096"))


def read_mip0(path):
    """(HxWx3 float array in 0..1, native width). Uncompressed DDS only --
    a map that already ships DXT1 is left alone by main()."""
    head = open(path, "rb").read(128)
    if head[:4] != b"DDS ":
        return None, None
    _, _, h, w, _, _, _ = struct.unpack("<7I", head[4:32])
    pfflags, fourcc = struct.unpack("<I4s", head[80:88])
    if pfflags & 0x4:
        return None, w
    bpp = struct.unpack("<I", head[88:92])[0] // 8
    a = np.fromfile(path, np.uint8, count=w * h * bpp, offset=128)
    a = a.reshape(h, w, bpp)[:, :, :3][:, :, ::-1]      # DDS is BGR
    return a.astype(np.float32) / 255.0, w


def correct(a):
    """Mean to 0.50, then contrast into the stock band. Returns (out, note).

    The two are done as separate steps on purpose. Folding them into one gain
    means a map whose mean is badly off can only be corrected by a curve, and a
    curve moves the contrast as a side effect -- which is how mire_detail came
    out at 0.236, above the stock band, on the first pass.
    """
    notes = []

    # --- 1. mean -> 0.50, by the gentlest method that stays inside the budget.
    mu = float(a.mean())
    out = a + (TARGET_MEAN - mu)
    if float((out > 1).mean()) > BRIGHT_BUDGET or float((out < 0).mean()) > DARK_BUDGET:
        lo_g, hi_g = 0.05, 8.0                 # a curve cannot clip at all
        for _ in range(60):
            g = (lo_g + hi_g) / 2
            if float((a ** g).mean()) > TARGET_MEAN:
                lo_g = g
            else:
                hi_g = g
        g = (lo_g + hi_g) / 2
        out = a ** g
        notes.append("gamma %.3f" % g)
    else:
        notes.append("offset %+.3f" % (TARGET_MEAN - mu))
    out = np.clip(out, 0, 1)

    # --- 2. contrast into the band.
    sd = float(out.std())
    lo, hi = STOCK_STD
    if sd < lo:
        # A dead map has to actually do something, so aim for a typical stock
        # value rather than scraping the floor; a hot one only has to stop
        # being noisy, so it comes down to the edge.
        target = STOCK_MEDIAN_STD
    elif sd > hi:
        target = hi
    else:
        notes.append("contrast %.3f left alone" % sd)
        return out, ", ".join(notes)

    # Search on the contrast actually achieved, not on the gain applied. On a
    # heavy-tailed map (bane_detail is sparse bright speckle) a gain that should
    # reach the target instead pushes the tail out of range, and clipping claws
    # most of the added variance straight back -- 1.98x "to 0.162" really landed
    # at 0.117. Walk the gain up while the budget holds and keep what it gets.
    mid = float(out.mean())

    # Trimming a hot map is a gain below 1.0, which cannot clip, so it needs no
    # search at all. Only lifting needs one -- and searching upward from 1.0 is
    # exactly what cannot bring a hot map down, which is the bug this replaces.
    if target <= sd:
        trial = np.clip((out - mid) * (target / sd) + TARGET_MEAN, 0, 1)
        notes.append("gain %.2fx -> %.3f, trimmed to band" % (target / sd, trial.std()))
        return trial, ", ".join(notes)

    best, best_sd, best_k = out, sd, 1.0
    best_dark = best_bright = 0.0
    for k in np.linspace(1.0, max(4.0, target / sd * 2), 60):
        raw = (out - mid) * k + TARGET_MEAN
        dark = float((raw < 0).mean())
        bright = float((raw > 1).mean())
        sat = dark + bright
        if bright > BRIGHT_BUDGET or dark > DARK_BUDGET:
            break
        trial = np.clip(raw, 0, 1)
        best, best_sd, best_k = trial, float(trial.std()), k
        best_dark, best_bright = dark, bright
        if best_sd >= target:
            break
    notes.append("gain %.2fx -> %.3f%s, %.2f%% dark / %.2f%% bright" % (
        best_k, best_sd,
        "" if best_sd >= target * 0.98 else " (budget-limited, target %.3f)" % target,
        100 * best_dark, 100 * best_bright))
    return best, ", ".join(notes)


def mips(a, size):
    """BC1 levels, mip 0 first, down to 4x4 -- the encoder needs whole blocks."""
    im = Image.fromarray(np.rint(a * 255).astype(np.uint8))
    out, n = [], size
    while n >= 4:
        lv = im if n == size else im.resize((n, n), Image.LANCZOS)
        out.append(bc1.encode_bc1(np.asarray(lv)))
        n //= 2
    return out


def one(src, dest):
    a, native = read_mip0(src)
    name = os.path.basename(src)
    if a is None:
        return dict(file=name, skipped="already compressed" if native else "not a DDS")
    before = dict(mean=float(a.mean()), std=float(a.std()), px=native,
                  mb=os.path.getsize(src) / 1048576)

    size = min(MAX_SIZE, native)
    if size != native:
        a = np.asarray(Image.fromarray(np.rint(a * 255).astype(np.uint8))
                       .resize((size, size), Image.LANCZOS)).astype(np.float32) / 255.0

    out, note = correct(a)
    path = os.path.join(dest, name)
    write_dxt1(path, size, size, mips(out, size))

    # Verify against what the file actually decodes to, not against `out` --
    # BC1 moves the mean, and the mean is the whole point of the exercise.
    blob = open(path, "rb").read()
    dec = bc1.decode_bc1(blob[128:128 + size * size // 2], size, size).astype(np.float32) / 255
    return dict(file=name, before=before, note=note, px=size,
                mb=os.path.getsize(path) / 1048576,
                mean=float(dec.mean()), std=float(dec.std()),
                nul=blob.count(b"\0") == len(blob))


def main(dest, mod_dir=MOD_DIR):
    os.makedirs(dest, exist_ok=True)
    srcs = sorted(f for f in os.listdir(mod_dir)
                  if f.lower().endswith(".dds") and "detail" in f.lower()
                  and "atlas" not in f.lower())
    print("%-22s %-14s %-15s %-15s %s" % ("detail map", "size", "mean", "std", "what was done"))
    was = now = 0.0
    for f in srcs:
        r = one(os.path.join(mod_dir, f), dest)
        if "skipped" in r:
            print("  %-20s %s" % (r["file"], r["skipped"]))
            continue
        b = r["before"]
        was += b["mb"]; now += r["mb"]
        print("  %-20s %5d->%-5d %6.3f->%-6.3f %6.3f->%-6.3f %s%s" % (
            r["file"], b["px"], r["px"], b["mean"], r["mean"], b["std"], r["std"],
            r["note"], "   ALL-NUL OUTPUT" if r["nul"] else ""))
    print("\n%.0f MB -> %.0f MB" % (was, now))


if __name__ == "__main__":
    main(sys.argv[1], *(sys.argv[2:3] or []))
