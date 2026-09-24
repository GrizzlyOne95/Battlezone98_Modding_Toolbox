"""Mirror the Forgotten Enemies Remastered source art a world needs.

Mercury is the one world in WORLDS that is not Combat Commander art -- it comes
from github.com/BlackDragonN001/FERemastered under FE_RM_Source/Worlds/, which is
not in the CC tree and is far too large to vendor. This pulls just the textures,
verifies each against the size the GitHub tree API reports (a short read and a
zero-filled file both look like a working download otherwise), and renames the
diffuse to the convention build_world.load_source expects.

FE names its diffuse `<name>_d` and its siblings `_n` / `_s` / `_e`; the CC tree
and therefore load_source want the diffuse bare with the same suffixes beside it,
so `Mercury1_d.tga` lands as `Mercury1.tga`. Nothing else is renamed.
"""
import json, os, sys, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from worlds2 import FE_ROOT

REPO = "BlackDragonN001/FERemastered"
REF = "master"
PREFIX = "FE_RM_Source/"
KEEP = (".tga", ".png", ".dds", ".bmp")
WANT = ("Worlds/Mercury",)          # extend as worlds are added


def tree():
    url = "https://api.github.com/repos/%s/git/trees/%s?recursive=1" % (REPO, REF)
    with urllib.request.urlopen(url, timeout=120) as r:
        d = json.load(r)
    if d.get("truncated"):
        raise SystemExit("tree listing truncated -- fetch per directory instead")
    return d["tree"]


def wanted(entries):
    for e in entries:
        if e["type"] != "blob" or not e["path"].startswith(PREFIX):
            continue
        rel = e["path"][len(PREFIX):]
        if any(rel.startswith(w) for w in WANT) and os.path.splitext(rel)[1].lower() in KEEP:
            yield e, rel


def local(rel):
    """FE's `_d` diffuse becomes the bare name load_source looks for."""
    stem, ext = os.path.splitext(rel)
    if stem.endswith("_d"):
        rel = stem[:-2] + ext
    return os.path.join(FE_ROOT, rel.replace("/", os.sep))


def get(job):
    e, rel = job
    out = local(rel)
    os.makedirs(os.path.dirname(out), exist_ok=True)
    if os.path.exists(out) and os.path.getsize(out) == e["size"]:
        return rel, e["size"], "cached"
    url = "https://raw.githubusercontent.com/%s/%s/%s" % (
        REPO, REF, urllib.parse.quote(e["path"]))
    with urllib.request.urlopen(url, timeout=300) as r, open(out, "wb") as fh:
        fh.write(r.read())
    n = os.path.getsize(out)
    return rel, n, "ok" if n == e["size"] else "SIZE MISMATCH %d != %d" % (n, e["size"])


def main():
    jobs = list(wanted(tree()))
    print("%d files, %.1f MB -> %s" % (
        len(jobs), sum(e["size"] for e, _ in jobs) / 1048576, FE_ROOT))
    bad = 0
    with ThreadPoolExecutor(6) as ex:
        for rel, n, st in ex.map(get, jobs):
            print("  %-46s %9d  %s" % (rel, n, st))
            bad += st.startswith("SIZE")
    print("%d file(s) did not verify" % bad if bad else "all verified")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
