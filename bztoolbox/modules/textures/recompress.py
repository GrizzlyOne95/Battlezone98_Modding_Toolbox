"""Batch-recompress a mod folder of uncompressed DDS art to DXT1/DXT5.

    python recompress.py <folder> --backup <dir> [--dry-run] [--only NAME ...]

Uncompressed DDS is the default output of most art pipelines and it is what
ships in a lot of Battlezone mods: ISDF Chronicles carries 6.4 GB of it against
1.35 GB of already-compressed art. Block compression is fixed-ratio and decoded
in hardware, so it is 4-8x less VRAM and bandwidth for a cost that has to be
measured per file rather than assumed -- which is what the verification pass
here is for.

What it does per file:

* picks DXT1 or DXT5 from whether mip 0 has any alpha below 255, so the very
  common "RGBA32 whose alpha channel is 255 everywhere" case costs 0.5 bpp
  rather than 1.0 and loses nothing, because there is nothing there to lose;
* transcodes the source mip levels rather than resampling new ones, and
  generates a chain only when the source has none;
* backs the original up before touching anything;
* re-reads the file it just wrote, decodes it, and reports the error against the
  source pixels. A table of intended settings is not evidence; on heavy-tailed
  art the applied setting and the achieved result are different quantities.

Normal maps get an extra column, because that is the class where BC1 is most
often assumed to be unsafe: mean angular deviation of the decoded normal. For
reference, R5G6B5 -- the format most of these normal maps are already stored in
-- quantises a flat-facing normal in steps of 3.7 degrees.

Cases that need more than "encode it", found converting six mods (2026-10-03):

* **Terrain atlases are left alone.** Their size is chosen to fit the tile grid
  and their mip chain is deliberately short so low mips do not bleed one tile
  into its neighbours. Anything named *atlas*, or named by a .trn in the folder,
  is skipped.
* **The top level must be 4-aligned.** D3D9 and D3D11 both refuse a BC texture
  whose mip 0 is not a multiple of 4 -- the 1254x1254 BZ 1.5 ports would simply
  fail to create. Above RESAMPLE_MIN_PIXELS the image is resampled up to the
  next multiple of 4 (UVs are normalised, so mapping is unchanged); below it --
  in practice effect sprite sheets, where resampling shifts frame edges -- the
  file is skipped.
* **Already-compressed files without a mip chain get one.** Level 0 is kept
  byte-for-byte; levels 1..n are generated from its decode and encoded in the
  same format. An 8192-square BC1 with no chain is otherwise sampled at full
  resolution at every distance.
* **A quality gate.** Some normal maps are pure high-frequency noise and BC1
  cannot hold them (25 degrees mean error was seen). A file whose result is
  past the gate -- normal maps by angle, DXT5 by alpha-weighted colour error
  (colour under alpha 0 is never seen), anything else by plain RMSE -- is put
  back: the original file if it already had a chain, otherwise the original
  pixels with a generated chain, uncompressed. --no-quality-gate disables it.
* **UI art is also recognised by name** (reticle, hud, cursor, font, icon,
  crosshair, radar) for sprite sheets that are drawn without a HUD material,
  and --materials lets the UI scan read a separate materials folder (CR keeps
  its materials apart from its textures).
"""
import argparse
import hashlib
import os
import re
import shutil
import struct
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bztoolbox.modules.textures import bcpack                                                    # noqa: E402
from bztoolbox.modules.textures import uiscan                                                    # noqa: E402

MIN_PIXELS = 64          # below this the saving is noise and the risk is not
SUSPECT_RMSE = 12.0      # flag for eyeballing, do not fail
RESAMPLE_MIN_PIXELS = 1_000_000
UI_NAME = re.compile(r"reticle|hud|cursor|font|icon|crosshair|radar", re.I)
# Quality gate. Normals: R5G6B5 already steps at 3.7 deg; ordinary art lands
# at 2-6 deg in BC1, noise-like normal maps at 8-30.
GATE_NORMAL_DEG = 8.0
GATE_ALPHA_WEIGHTED_RMSE = 14.0
GATE_RMSE = 20.0
_FOURCC_FMT = {b"DXT1": "DXT1", b"DXT5": "DXT5"}


def md5(path, chunk=1 << 20):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(chunk), b""):
            h.update(b)
    return h.hexdigest()


def is_normal_map(name):
    b = os.path.splitext(name)[0].lower()
    return (b.endswith("_n") or b.endswith("_nm") or b.endswith("norm")
            or "normal" in b)


def angular_error(src, dec):
    """Mean angle between two tangent-space normal images, in degrees."""
    def unit(a):
        v = a[:, :, :3].astype(np.float32) / 127.5 - 1.0
        n = np.linalg.norm(v, axis=-1, keepdims=True)
        return v / np.maximum(n, 1e-6)
    d = np.clip((unit(src) * unit(dec)).sum(-1), -1.0, 1.0)
    return float(np.degrees(np.arccos(d)).mean())


def terrain_textures(folder):
    """Lower-cased stems of every token any .trn in the folder mentions."""
    stems = set()
    for f in os.listdir(folder):
        if f.lower().endswith(".trn"):
            with open(os.path.join(folder, f), encoding="latin1") as fh:
                for tok in re.findall(r"[A-Za-z0-9_\-\.]+", fh.read()):
                    stems.add(os.path.splitext(tok)[0].lower())
    return stems


def is_protected_terrain(name, trn_stems):
    return "atlas" in name.lower() or os.path.splitext(name)[0].lower() in trn_stems


build_chain = bcpack.build_chain      # shared with the GUI's save path


def _backup(path, dest):
    """Copy path to dest once and prove the copy. -> None, or a skip reason."""
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    if not os.path.exists(dest):
        shutil.copy2(path, dest)
        if md5(dest) != md5(path):
            os.remove(dest)
            return "BACKUP HASH MISMATCH, left alone"
    return None


def _compressed_info(path):
    with open(path, "rb") as f:
        h = f.read(128)
    flags, height, width = struct.unpack("<3I", h[8:20])
    mips = struct.unpack("<I", h[28:32])[0] if flags & bcpack.DDSD_MIPMAPCOUNT else 1
    return dict(fmt=_FOURCC_FMT.get(h[84:88]), fourcc=h[84:88], w=width, h=height,
                mips=max(1, mips), cube=bool(struct.unpack("<I", h[112:116])[0] & 0x200))


def add_mip_chain(path, backup_dir, dry_run=False):
    """BC file shipped without mips: keep level 0's blocks, append a chain."""
    name = os.path.basename(path)
    before = os.path.getsize(path)
    info = _compressed_info(path)
    fmt, w, h = info["fmt"], info["w"], info["h"]
    if info["mips"] > 1:
        return dict(file=name, skipped="already compressed (%s)" % info["fourcc"].decode(
            "ascii", "replace"), before=before)
    if fmt is None or info["cube"]:
        return dict(file=name, skipped="compressed %s without mips; cannot re-encode that format"
                    % info["fourcc"].decode("ascii", "replace"), before=before)
    if w % 4 or h % 4 or max(w, h) < MIN_PIXELS:
        return dict(file=name, skipped="compressed %dx%d without mips, not 4-aligned or tiny"
                    % (w, h), before=before)
    stride = 8 if fmt == "DXT1" else 16
    n0 = (w // 4) * (h // 4) * stride
    levels_n = int(np.log2(max(w, h))) + 1
    if dry_run:
        after = 128 + sum(max(1, (max(1, w >> i) + 3) // 4) * max(1, (max(1, h >> i) + 3) // 4)
                          * stride for i in range(levels_n))
        return dict(file=name, before=before, after=after, fmt=fmt, px=(w, h),
                    mips="appended", levels=levels_n, dry=True)
    dest = os.path.join(backup_dir, name)
    why = _backup(path, dest)
    if why:
        return dict(file=name, skipped=why, before=before)
    blob = open(dest, "rb").read()
    level0 = blob[128:128 + n0]
    rgba = bcpack.decode_level(level0, w, h, fmt)
    chain, _ = build_chain([rgba], w, h)
    encoded = [level0] + [bcpack.encode_level(lv, fmt) for lv in chain[1:]]
    bcpack.write_dds(path, w, h, encoded, fmt)
    written = open(path, "rb").read()
    if written[128:128 + n0] != level0 or written.count(b"\0") == len(written):
        shutil.copy2(dest, path)
        return dict(file=name, skipped="mip append did not verify, original restored",
                    before=before)
    return dict(file=name, before=before, after=len(written), fmt=fmt, px=(w, h),
                mips="appended", levels=len(encoded), rmse=0.0, ang=None, alpha_err=None)


def _gate(name, fmt, src, dec):
    """-> (measurements, reason or None)."""
    err = (dec[:, :, :3].astype(np.float64) - src[:, :, :3].astype(np.float64)) ** 2
    m = dict(rmse=float(np.sqrt(err.mean())), ang=None, alpha_err=None, rmse_aw=None)
    if is_normal_map(name):
        m["ang"] = angular_error(src, dec)
    if fmt == "DXT5":
        m["alpha_err"] = float(np.abs(dec[:, :, 3].astype(np.int16)
                                      - src[:, :, 3].astype(np.int16)).mean())
        a = src[:, :, 3].astype(np.float64) / 255.0
        m["rmse_aw"] = float(np.sqrt((err.mean(-1) * a).sum() / max(a.sum(), 1.0)))
    if m["ang"] is not None:
        bad = m["ang"] > GATE_NORMAL_DEG and "normal error %.1f deg" % m["ang"]
    elif m["rmse_aw"] is not None:
        bad = (m["rmse_aw"] > GATE_ALPHA_WEIGHTED_RMSE
               and "alpha-weighted rmse %.1f" % m["rmse_aw"])
    else:
        bad = m["rmse"] > GATE_RMSE and "rmse %.1f" % m["rmse"]
    return m, (bad or None)


def convert(path, backup_dir, dry_run=False, ui=(), trn_stems=(), quality_gate=True):
    name = os.path.basename(path)
    before = os.path.getsize(path)
    if name.lower() in ui:
        return dict(file=name, skipped="drawn as UI (%s)" % ui[name.lower()],
                    before=before)
    if UI_NAME.search(name):
        return dict(file=name, skipped="UI by name", before=before)
    if is_protected_terrain(name, trn_stems):
        return dict(file=name, skipped="terrain texture (atlas or named by a .trn)",
                    before=before)

    # Source from the backup when one exists, so the whole run is replayable:
    # changing a setting and re-running re-derives every file from its original
    # instead of finding the live copy already compressed and skipping it (or,
    # worse, compressing an already-compressed file a second time).
    dest = os.path.join(backup_dir, name)
    replayed = os.path.exists(dest)
    src_path = dest if replayed else path
    if replayed:
        before = os.path.getsize(dest)      # report against the true original
    try:
        levels, info = bcpack.read_dds(src_path)
    except bcpack.Unsupported as e:
        if str(e).startswith("already compressed") and not replayed:
            return add_mip_chain(path, backup_dir, dry_run)
        return dict(file=name, skipped=str(e), before=before)
    w, h = info["width"], info["height"]
    if max(w, h) < MIN_PIXELS:
        return dict(file=name, skipped="%dx%d, below the size floor" % (w, h),
                    before=before)

    src_levels, ow, oh = levels, w, h
    resampled = None
    if w % 4 or h % 4:
        if w * h <= RESAMPLE_MIN_PIXELS:
            return dict(file=name, skipped="%dx%d not 4-aligned; below the resample floor"
                        % (w, h), before=before)
        from PIL import Image
        w, h = w + (-w) % 4, h + (-h) % 4
        levels = [np.asarray(Image.fromarray(levels[0], "RGBA").resize((w, h), Image.LANCZOS))]
        resampled = "%dx%d->%dx%d" % (ow, oh, w, h)

    fmt = "DXT5" if bcpack.has_real_alpha(levels) else "DXT1"
    chain, mipnote = build_chain(levels, w, h)
    if resampled:
        mipnote = "resampled " + resampled
    if dry_run:
        after = 128 + sum(max(1, (max(1, w >> i) + 3) // 4)
                          * max(1, (max(1, h >> i) + 3) // 4)
                          * (8 if fmt == "DXT1" else 16) for i in range(len(chain)))
        return dict(file=name, before=before, after=after, fmt=fmt, px=(w, h),
                    mips=mipnote, levels=len(chain), dry=True)

    # back up first, and prove the copy before overwriting the only original
    why = _backup(path, dest)
    if why:
        return dict(file=name, skipped=why, before=before)

    encoded = [bcpack.encode_level(lv, fmt) for lv in chain]
    bcpack.write_dds(path, w, h, encoded, fmt)

    # verify against the bytes on disk, not against what we meant to write
    blob = open(path, "rb").read()
    if blob.count(b"\0") == len(blob):
        shutil.copy2(dest, path)
        return dict(file=name, skipped="WROTE ALL-NUL, original restored",
                    before=before)
    nblocks = max(1, (w + 3) // 4) * max(1, (h + 3) // 4)
    stride = 8 if fmt == "DXT1" else 16
    dec = bcpack.decode_level(blob[128:128 + nblocks * stride], w, h, fmt)
    m, bad = _gate(name, fmt, levels[0], dec)
    if bad and quality_gate:
        if len(src_levels) > 1:
            shutil.copy2(dest, path)                      # it already had a chain
            kept = "original kept"
        else:
            full, _ = build_chain(src_levels, ow, oh)
            bcpack.write_dds_uncompressed(path, full)
            kept = "kept uncompressed, mips added"
        return dict(file=name, before=before, after=os.path.getsize(path), fmt="none",
                    px=(ow, oh), mips=mipnote, levels=0, rmse=m["rmse"], ang=m["ang"],
                    alpha_err=m["alpha_err"], gated="%s (%s)" % (kept, bad))
    return dict(file=name, before=before, after=os.path.getsize(path), fmt=fmt,
                px=(w, h), mips=mipnote, levels=len(chain), rmse=m["rmse"],
                ang=m["ang"], alpha_err=m["alpha_err"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("--backup", required=True)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only", nargs="*", default=None,
                    help="basenames to restrict to, for a trial run")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--jobs", type=int, default=8,
                    help="worker processes; an 8192-square level needs about a "
                         "gigabyte of working set, so this is memory-bound")
    ap.add_argument("--compress-ui", action="store_true",
                    help="also compress textures drawn through a HUD/font "
                         "material. Off by default: BC ringing on a glyph edge "
                         "is visible where the same error on a diffuse map is "
                         "not, and the whole UI set is well under 1%% of the art")
    ap.add_argument("--materials", action="append", default=[],
                    help="extra folder of .material files for the UI scan "
                         "(repeatable); the texture folder is always scanned")
    ap.add_argument("--no-quality-gate", action="store_true",
                    help="keep every BC result, however large its error")
    a = ap.parse_args()

    ui = {}
    if not a.compress_ui:
        for folder in [a.folder] + a.materials:
            ui.update(uiscan.ui_textures(folder))
    if ui:
        print("leaving %d UI texture(s) uncompressed: %s\n"
              % (len(ui), ", ".join(sorted(ui))))
    trn = terrain_textures(a.folder)
    gate = not a.no_quality_gate

    names = sorted(f for f in os.listdir(a.folder) if f.lower().endswith(".dds"))
    if a.only:
        want = {n.lower() for n in a.only}
        names = [n for n in names if n.lower() in want]
    if a.limit:
        names = names[:a.limit]
    # biggest first: one 8192-square file left until last would run alone for
    # minutes after every worker had gone idle
    names.sort(key=lambda n: -os.path.getsize(os.path.join(a.folder, n)))

    total_before = total_after = 0
    rows, skipped, t0 = [], [], time.time()
    done = 0

    def record(r):
        nonlocal total_before, total_after, done
        done += 1
        if "skipped" in r:
            if "already compressed" not in r["skipped"]:
                skipped.append(r)
            return
        rows.append(r)
        total_before += r["before"]
        total_after += r["after"]
        print("  [%4d/%4d] %-38s %7.1f -> %6.2f MB  %s%s%s" % (
            done, len(names), r["file"], r["before"] / 1048576, r["after"] / 1048576,
            r["fmt"], "" if r.get("dry") else "  rmse %.2f%s" % (
                r["rmse"], "  %.2f deg" % r["ang"] if r["ang"] is not None else ""),
            "  GATED: " + r["gated"] if r.get("gated") else ""),
            flush=True)

    if a.jobs > 1 and not a.dry_run:
        from concurrent.futures import ProcessPoolExecutor, as_completed
        with ProcessPoolExecutor(max_workers=a.jobs) as ex:
            futs = [ex.submit(convert, os.path.join(a.folder, n), a.backup, False, ui, trn, gate)
                    for n in names]
            for f in as_completed(futs):
                record(f.result())
    else:
        for n in names:
            record(convert(os.path.join(a.folder, n), a.backup, a.dry_run, ui, trn, gate))

    print("\n%d files   %.0f MB -> %.0f MB   (%.1fx, %.0f MB saved)   %.0fs" % (
        len(rows), total_before / 1048576, total_after / 1048576,
        total_before / max(1, total_after), (total_before - total_after) / 1048576, time.time() - t0))
    if not a.dry_run and rows:
        enc = [r for r in rows if not r.get("gated")]
        bad = sorted((r for r in enc if r["rmse"] > SUSPECT_RMSE),
                     key=lambda r: -r["rmse"])
        nm = [r for r in rows if r["ang"] is not None]
        if enc:
            print("colour rmse: median %.2f, p95 %.2f, max %.2f" % (
                np.median([r["rmse"] for r in enc]),
                np.percentile([r["rmse"] for r in enc], 95),
                max(r["rmse"] for r in enc)))
        if nm:
            print("normal maps (%d): mean angular error median %.2f deg, max %.2f deg"
                  "   [R5G6B5 already quantises at 3.70 deg/step]" % (
                      len(nm), np.median([r["ang"] for r in nm]),
                      max(r["ang"] for r in nm)))
        al = [r for r in enc if r.get("alpha_err") is not None]
        if al:
            print("DXT5 alpha (%d): mean|e| median %.3f, max %.3f" % (
                len(al), np.median([r["alpha_err"] for r in al]),
                max(r["alpha_err"] for r in al)))
        gen = [r for r in rows if r["mips"] == "generated"]
        if gen:
            print("mip chains generated for %d file(s) that shipped without one: %s"
                  % (len(gen), ", ".join(r["file"] for r in gen)))
        app = [r for r in rows if r["mips"] == "appended"]
        if app:
            print("mip chains appended to %d compressed file(s), level 0 unchanged: %s"
                  % (len(app), ", ".join(r["file"] for r in app)))
        rs = [r for r in rows if str(r["mips"]).startswith("resampled")]
        if rs:
            print("resampled to a 4-aligned size: %s"
                  % ", ".join("%s (%s)" % (r["file"], r["mips"][10:]) for r in rs))
        gated = [r for r in rows if r.get("gated")]
        if gated:
            print("\nquality gate kept %d file(s) uncompressed:" % len(gated))
            for r in gated:
                print("   %-38s %s" % (r["file"], r["gated"]))
        if bad:
            print("\nabove rmse %.0f, worth eyeballing:" % SUSPECT_RMSE)
            for r in bad[:15]:
                print("   %-38s rmse %6.2f  %dx%d %s"
                      % (r["file"], r["rmse"], r["px"][0], r["px"][1], r["fmt"]))
    if skipped:
        print("\nskipped %d:" % len(skipped))
        for r in skipped[:40]:
            print("   %-38s %s" % (r["file"], r["skipped"]))


if __name__ == "__main__":
    main()
