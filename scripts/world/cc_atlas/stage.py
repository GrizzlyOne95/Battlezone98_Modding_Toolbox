"""Copy the built tree into the Google Drive staging folder and prove it arrived.

Staging into Drive has twice produced correctly-sized, all-zero files -- right
length, right timestamp, no data -- so every file is md5'd on both sides after
the copy and a mismatch is a hard failure, not a warning.
"""
import hashlib, os, shutil, sys


def md5(p, buf=1 << 20):
    h = hashlib.md5()
    with open(p, "rb") as f:
        while True:
            b = f.read(buf)
            if not b:
                return h.hexdigest()
            h.update(b)


def stage(src_root, dst_root):
    bad, n, total = [], 0, 0
    for d in sorted(os.listdir(src_root)):
        s = os.path.join(src_root, d)
        if not os.path.isdir(s):
            continue
        t = os.path.join(dst_root, d)
        os.makedirs(t, exist_ok=True)
        for f in sorted(os.listdir(s)):
            sp, tp = os.path.join(s, f), os.path.join(t, f)
            shutil.copy2(sp, tp)
            a, b = md5(sp), md5(tp)
            n += 1
            total += os.path.getsize(sp)
            if a != b:
                bad.append(f"{d}/{f}: {a} != {b}")
        print(f"{d:26s} {len(os.listdir(s)):2d} files", flush=True)
    print(f"\n{n} files, {total/1048576:.1f} MB, {len(bad)} mismatched")
    for x in bad:
        print("  MISMATCH", x)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(stage(sys.argv[1], sys.argv[2]))
