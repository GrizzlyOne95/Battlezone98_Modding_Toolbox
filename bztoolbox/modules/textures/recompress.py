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
"""
import argparse
import hashlib
import os
import shutil
import sys
import time

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bztoolbox.modules.textures import bcpack                                                    # noqa: E402
from bztoolbox.modules.textures import uiscan                                                    # noqa: E402

MIN_PIXELS = 64          # below this the saving is noise and the risk is not
SUSPECT_RMSE = 12.0      # flag for eyeballing, do not fail


def md5(path, chunk=1 << 20):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(chunk), b""):
            h.update(b)
    return h.hexdigest()


def is_normal_map(name):
    b = os.path.splitext(name)[0].lower()
    return b.endswith("_n") or b.endswith("_nm") or b.endswith("norm")


def angular_error(src, dec):
    """Mean angle between two tangent-space normal images, in degrees."""
    def unit(a):
        v = a[:, :, :3].astype(np.float32) / 127.5 - 1.0
        n = np.linalg.norm(v, axis=-1, keepdims=True)
        return v / np.maximum(n, 1e-6)
    d = np.clip((unit(src) * unit(dec)).sum(-1), -1.0, 1.0)
    return float(np.degrees(np.arccos(d)).mean())


build_chain = bcpack.build_chain      # shared with the GUI's save path


def convert(path, backup_dir, dry_run=False, ui=()):
    name = os.path.basename(path)
    before = os.path.getsize(path)
    if name.lower() in ui:
        return dict(file=name, skipped="drawn as UI (%s)" % ui[name.lower()],
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
        return dict(file=name, skipped=str(e), before=before)
    w, h = info["width"], info["height"]
    if max(w, h) < MIN_PIXELS:
        return dict(file=name, skipped="%dx%d, below the size floor" % (w, h),
                    before=before)

    fmt = "DXT5" if bcpack.has_real_alpha(levels) else "DXT1"
    chain, mipnote = build_chain(levels, w, h)
    if dry_run:
        after = 128 + sum(max(1, (max(1, w >> i) + 3) // 4)
                          * max(1, (max(1, h >> i) + 3) // 4)
                          * (8 if fmt == "DXT1" else 16) for i in range(len(chain)))
        return dict(file=name, before=before, after=after, fmt=fmt, px=(w, h),
                    mips=mipnote, levels=len(chain), dry=True)

    # back up first, and prove the copy before overwriting the only original
    os.makedirs(backup_dir, exist_ok=True)
    if not os.path.exists(dest):
        shutil.copy2(path, dest)
        if md5(dest) != md5(path):
            os.remove(dest)
            return dict(file=name, skipped="BACKUP HASH MISMATCH, left alone",
                        before=before)

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
    src = levels[0]
    err = np.abs(dec[:, :, :3].astype(np.int16) - src[:, :, :3].astype(np.int16))
    rmse = float(np.sqrt((err.astype(np.float64) ** 2).mean()))
    aerr = None
    if is_normal_map(name):
        aerr = angular_error(src, dec)
    ae = None
    if fmt == "DXT5":
        ae = float(np.abs(dec[:, :, 3].astype(np.int16)
                          - src[:, :, 3].astype(np.int16)).mean())
    return dict(file=name, before=before, after=os.path.getsize(path), fmt=fmt,
                px=(w, h), mips=mipnote, levels=len(chain), rmse=rmse,
                ang=aerr, alpha_err=ae)


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
    a = ap.parse_args()

    ui = {} if a.compress_ui else uiscan.ui_textures(a.folder)
    if ui:
        print("leaving %d UI texture(s) uncompressed: %s\n"
              % (len(ui), ", ".join(sorted(ui))))

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
        print("  [%4d/%4d] %-38s %7.1f -> %6.2f MB  %s%s" % (
            done, len(names), r["file"], r["before"] / 1048576, r["after"] / 1048576,
            r["fmt"], "" if r.get("dry") else "  rmse %.2f%s" % (
                r["rmse"], "  %.2f deg" % r["ang"] if r["ang"] is not None else "")),
            flush=True)

    if a.jobs > 1 and not a.dry_run:
        from concurrent.futures import ProcessPoolExecutor, as_completed
        with ProcessPoolExecutor(max_workers=a.jobs) as ex:
            futs = [ex.submit(convert, os.path.join(a.folder, n), a.backup, False, ui)
                    for n in names]
            for f in as_completed(futs):
                record(f.result())
    else:
        for n in names:
            record(convert(os.path.join(a.folder, n), a.backup, a.dry_run, ui))

    print("\n%d files   %.0f MB -> %.0f MB   (%.1fx, %.0f MB saved)   %.0fs" % (
        len(rows), total_before / 1048576, total_after / 1048576,
        total_before / max(1, total_after), (total_before - total_after) / 1048576, time.time() - t0))
    if not a.dry_run and rows:
        bad = sorted((r for r in rows if r["rmse"] > SUSPECT_RMSE),
                     key=lambda r: -r["rmse"])
        nm = [r for r in rows if r["ang"] is not None]
        print("colour rmse: median %.2f, p95 %.2f, max %.2f" % (
            np.median([r["rmse"] for r in rows]),
            np.percentile([r["rmse"] for r in rows], 95),
            max(r["rmse"] for r in rows)))
        if nm:
            print("normal maps (%d): mean angular error median %.2f deg, max %.2f deg"
                  "   [R5G6B5 already quantises at 3.70 deg/step]" % (
                      len(nm), np.median([r["ang"] for r in nm]),
                      max(r["ang"] for r in nm)))
        al = [r for r in rows if r.get("alpha_err") is not None]
        if al:
            print("DXT5 alpha (%d): mean|e| median %.3f, max %.3f" % (
                len(al), np.median([r["alpha_err"] for r in al]),
                max(r["alpha_err"] for r in al)))
        gen = [r for r in rows if r["mips"] == "generated"]
        if gen:
            print("mip chains generated for %d file(s) that shipped without one: %s"
                  % (len(gen), ", ".join(r["file"] for r in gen)))
        if bad:
            print("\nabove rmse %.0f, worth eyeballing:" % SUSPECT_RMSE)
            for r in bad[:15]:
                print("   %-38s rmse %6.2f  %dx%d %s"
                      % (r["file"], r["rmse"], r["px"][0], r["px"][1], r["fmt"]))
    if skipped:
        print("\nskipped %d:" % len(skipped))
        for r in skipped[:20]:
            print("   %-38s %s" % (r["file"], r["skipped"]))


if __name__ == "__main__":
    main()
