"""Downscale oversized mission preview BMPs (<mission>.bmp beside <mission>.bzn).

    bztoolbox textures shrink-previews <mod folder> --backup <dir> [--max 1024] [--dry-run]

The shell's mission list opens <mission>.bmp by name to fill a 200 px preview
window. The editor's large-map dump writes that file at (map size x 4)^2 -- an
8104x8104, 197 MB bitmap for a 2026-metre map -- and the shell decodes all of
it, plus a mip chain, every time the mission is highlighted. bz64port shipped
40 of these, 3.3 GB in total; at 1024 px they are 124 MB.

Keeps the file name and the 24-bit BMP format (the shell looks the file up by
exact name), keeps the aspect ratio, backs every original up with a hash check,
and re-opens the written file before replacing the original.
"""
import argparse
import hashlib
import os
import shutil

from PIL import Image

Image.MAX_IMAGE_PIXELS = None


def _md5(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def shrink(folder, backup, limit=1024, dry_run=False, log=print):
    """-> (files changed, bytes before, bytes after)."""
    files = os.listdir(folder)
    missions = {os.path.splitext(f)[0].lower() for f in files if f.lower().endswith(".bzn")}
    changed = before = after = 0
    for f in sorted(files):
        stem, ext = os.path.splitext(f)
        if ext.lower() != ".bmp" or stem.lower() not in missions:
            continue
        path = os.path.join(folder, f)
        with Image.open(path) as im:
            w, h = im.size
            if max(w, h) <= limit:
                continue
            scale = limit / max(w, h)
            nw, nh = max(1, round(w * scale)), max(1, round(h * scale))
            size = os.path.getsize(path)
            log("  %-20s %5dx%-5d -> %4dx%-4d  %7.1f MB" % (f, w, h, nw, nh, size / 1048576))
            changed += 1
            before += size
            if dry_run:
                continue
            small = im.convert("RGB").resize((nw, nh), Image.LANCZOS)
        os.makedirs(backup, exist_ok=True)
        dest = os.path.join(backup, f)
        if not os.path.exists(dest):
            shutil.copy2(path, dest)
            if _md5(dest) != _md5(path):
                os.remove(dest)
                raise SystemExit("backup hash mismatch, stopped: " + f)
        tmp = path + ".part.bmp"
        small.save(tmp, format="BMP")
        with Image.open(tmp) as check:
            check.load()
            if check.size != (nw, nh):
                os.remove(tmp)
                raise SystemExit("written preview did not verify: " + f)
        os.replace(tmp, path)
        after += os.path.getsize(path)
    return changed, before, after


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[1])
    ap.add_argument("folder")
    ap.add_argument("--backup", required=True)
    ap.add_argument("--max", type=int, default=1024, help="longest side, pixels")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    n, before, after = shrink(a.folder, a.backup, a.max, a.dry_run)
    if a.dry_run:
        print("%d preview(s), %.0f MB would shrink" % (n, before / 1048576))
    else:
        print("%d preview(s): %.0f MB -> %.0f MB" % (n, before / 1048576, after / 1048576))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
