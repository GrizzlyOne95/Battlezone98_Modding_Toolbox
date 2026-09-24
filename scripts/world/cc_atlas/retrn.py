"""Rewrite the .trn files a mod already ships so they name every tile the
rebuilt atlas carries.

TRN_Entries.txt says what the new blocks *should* look like; this produces the
actual replacement file, which is a different job for two reasons.

A .trn's TextureType index is a paint index, not the atlas's matrix index.
core.trn declares TextureType 0, 2 and 5 and points them at core00, core11 and
core22 -- so a block cannot simply be pasted in, and a CapTo key has to name the
*target's TextureType index* while the tile name carries matrix indices. The
mapping is recovered per file from each block's own Solid key.

Everything above the first [TextureType is copied through byte for byte: [Size],
[NormalView], [Sky], [Stars], [Color] and the fog are the map author's, not
ours, and a rebuild has no business touching them. Byte for byte is meant
literally -- the line endings in this mod are not uniform (dunes.trn ends every
line CR CR LF, core.trn bare LF) and the engine parses both today, so the new
body is written with whatever terminator that file already used rather than
normalised to something tidier.

New types are added at their own matrix index whenever that index is free,
which is what every painted map in this mod already does. The .mat says how many
cells each newly declared index actually paints, so the report separates the
inert additions from the ones that change what a map draws -- 214 cells of
isdfms15 paint type 7, which its .trn never declared, so they have been drawing
the default tile while facility.trn names plut77s1 for the same world.
"""
import json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from build2 import plan_tiles
from worlds2 import MOD_DIR, WORLDS

SLOT = "ABCD"
HEAD_RE = re.compile(r"^\[TextureType(\d+)\](.*)$", re.I)
KEY_RE = re.compile(r"^\s*(Solid|CapTo\d+_|DiagonalTo\d+_)([A-D])(\d)\s*=\s*(\S+)", re.I)
TILE_RE = re.compile(r"^([a-z]+)(\d)(\d)([scd])(\d)$", re.I)
def painted_types(mat_path):
    """{type index: cells painted}, or None when there is no .mat.

    Each cell is two bytes; the odd one packs the pair of type nibbles that meet
    there. An index that appears in both nibbles in equal numbers is a solid run
    of that type, so 7 -- present in most of these maps and declared by none of
    them except facility.trn -- is a real paint drawing the default tile, not a
    sentinel."""
    if not os.path.exists(mat_path):
        return None
    b = open(mat_path, "rb").read()
    out = {}
    for v in b[1::2]:
        for n in {v >> 4, v & 15}:        # a solid cell names its type twice
            out[n] = out.get(n, 0) + 1
    return out


def eol_of(text):
    """The terminator this file actually uses -- the longest one that accounts
    for essentially every line, so CR CR LF is not mistaken for CR LF."""
    for cand in ("\r\r\n", "\r\n", "\n"):
        if text.count(cand) and text.count(cand) >= 0.9 * text.count("\n"):
            return cand
    return "\r\n"


def parse(path):
    """(head_text, eol, [{ttype, comment, flat, matrix}])."""
    text = open(path, "r", encoding="latin-1", newline="").read()
    eol = eol_of(text)
    lines = text.split(eol)
    cut = next((n for n, l in enumerate(lines) if HEAD_RE.match(l)), None)
    if cut is None:
        return text, eol, []
    head = eol.join(lines[:cut]) + eol
    blocks, cur = [], None
    for l in lines[cut:]:
        m = HEAD_RE.match(l)
        if m:
            cur = dict(ttype=int(m.group(1)), comment=m.group(2).rstrip(),
                       flat=None, matrix=None)
            blocks.append(cur)
            continue
        if cur is None:
            continue
        if l.lower().startswith("flatcolor"):
            cur["flat"] = l.rstrip()
            continue
        k = KEY_RE.match(l)
        if k and cur["matrix"] is None:
            t = TILE_RE.match(os.path.splitext(k.group(4))[0])
            if t:
                cur["matrix"] = int(t.group(2))
    return head, eol, blocks


def emit(plan, t2m, order):
    """TextureType blocks for the mapping in `order` (list of ttype)."""
    m2t = {m: t for t, m in t2m.items()}
    by = {}
    for t in plan:
        by.setdefault(t["i"], []).append(t)
    out, skipped = [], []
    for tt in order:
        i = t2m[tt]
        out.append("[TextureType%d]%s" % (tt, order[tt]["comment"]))
        out.append(order[tt]["flat"] or "FlatColor= 128")
        for t in sorted(by.get(i, []),
                        key=lambda t: (t["kind"] != "s", t["j"], t["kind"], t["var"])):
            if t["var"] > len(SLOT):
                skipped.append(t["name"] + " (variant %d, no .trn slot)" % t["var"])
                continue
            if t["kind"] == "s":
                key = "Solid%s" % SLOT[t["var"] - 1]
            else:
                if t["j"] not in m2t:
                    skipped.append(t["name"] + " (target type not in this .trn)")
                    continue
                key = "%sTo%d_%s" % ("Cap" if t["kind"] == "c" else "Diagonal",
                                     m2t[t["j"]], SLOT[t["var"] - 1])
            for mip in range(4):
                out.append("%-18s= %s.map" % (key + str(mip), t["name"]))
            out.append("")
    while out and not out[-1]:
        out.pop()
    return out, skipped


def main(out_root, dest, mod_dir=MOD_DIR):
    req = json.load(open(os.path.join(HERE, "required.json")))
    plans = {}
    for mat, cfg in WORLDS.items():
        if os.path.isdir(os.path.join(out_root, mat)):
            plans[mat] = plan_tiles(mat, cfg, req.get(mat, []))[0]
    os.makedirs(dest, exist_ok=True)

    rows = []
    for fn in sorted(os.listdir(mod_dir)):
        if not fn.lower().endswith(".trn"):
            continue
        path = os.path.join(mod_dir, fn)
        txt = open(path, "r", encoding="latin-1", newline="").read()
        m = re.search(r"MaterialName\s*=\s*(\S+)", txt, re.I)
        mat = m.group(1).lower() if m else None
        if mat not in plans:
            continue
        plan = plans[mat]
        head, eol, blocks = parse(path)
        blocks = [b for b in blocks if b["matrix"] is not None]
        t2m = {b["ttype"]: b["matrix"] for b in blocks}
        order = {b["ttype"]: b for b in blocks}

        painted = painted_types(os.path.splitext(path)[0] + ".mat")
        renumber = painted is None and sorted(t2m) != sorted(t2m.values())
        if renumber:
            # A .trn with no .mat is a template nobody has painted against, so
            # its sparse indices are free to be straightened out.
            t2m = {i: mx for i, mx in enumerate(sorted(t2m.values()))}
            order = {i: dict(comment=order[t]["comment"], flat=order[t]["flat"])
                     for i, t in enumerate(sorted(order))}

        want = sorted({t["i"] for t in plan})
        added = []
        for mx in want:
            if mx in t2m.values():
                continue
            # Its own index when that is free -- every painted map in this mod
            # maps TextureType N to matrix N, so anything else would be a second
            # numbering for the same art.
            free = mx if mx not in t2m else next(n for n in range(16) if n not in t2m)
            t2m[free] = mx
            src = os.path.basename(WORLDS[mat]["types"][mx])
            cells = (painted or {}).get(free, 0)
            order[free] = dict(comment="   // %s  (added by the atlas rebuild)" % src,
                               flat="FlatColor= 128")
            added.append(dict(ttype=free, matrix=mx, source=src, painted_cells=cells))

        body, skipped = emit(plan, t2m, dict(sorted(order.items())))
        with open(os.path.join(dest, fn), "w", encoding="latin-1", newline="") as fh:
            fh.write(head + eol.join(body) + eol)

        rows.append(dict(trn=fn, material=mat, types=len(t2m), keys=len(body),
                         eol=repr(eol), added=added, skipped=skipped,
                         renumbered=renumber, painted=painted))
        note = ", ".join("TextureType%d=%s%s" % (
            a["ttype"], a["source"],
            "" if not a["painted_cells"] else " [%d cells painted]" % a["painted_cells"])
            for a in added)
        print("%-14s %-22s %2d types  %s%s" % (
            fn, mat, len(t2m),
            "renumbered  " if renumber else "",
            ("+ " + note) if added else "no new type"))
        for s in skipped:
            print("      skipped " + s)
    json.dump(rows, open(os.path.join(dest, "retrn_report.json"), "w"), indent=1)
    print("\n%d .trn rewritten into %s" % (len(rows), dest))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2],
         sys.argv[3] if len(sys.argv) > 3 else MOD_DIR)
