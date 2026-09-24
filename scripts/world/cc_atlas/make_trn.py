"""Write the .trn side of each build: the TextureType blocks, and for the five
new worlds a complete .trn a map can actually be built on.

A tile nothing names is dead weight, so every tile the atlas carries gets a key
here -- including the ones this rebuild added, which are marked so it is obvious
what is new against the world's current .trn.
"""
import json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)
from build2 import plan_tiles
from worlds2 import WORLDS

SLOT = "ABCD"

# The stock editor template each new world borrows its environment from.  These
# carry a working [Sky], [Clouds], [Stars] and [Color] set that the base game
# already ships every texture for, which an invented header does not: an empty
# [Sky] leaves a new world with no sun, no sky and no clouds.
STOCK = {"ccmars_detail_atlas": "mars", "cctitan_detail_atlas": "titan",
         "ccearth_detail_atlas": "achilles", "ccmetal_detail_atlas": "moon",
         "cctunnel_detail_atlas": "moon"}

EDIT_TRN = os.environ.get("REDUX_EDIT_TRN", os.path.join(
    os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
    "Steam", "steamapps", "common", "Battlezone 98 Redux", "Edit", "trn"))

# A custom map is its own square starting at the origin; the stock templates sit
# at the offsets their own campaign missions used (moon.trn starts at z=96000).
SIZE = """[Size]
MinX=0
MinZ=0
Width=5120
Depth=5120
Height=0.000000

"""


def stock_head(mat):
    """The stock template's header with our material swapped in, or None.

    Everything but [Size] and [Atlases] is taken as it stands -- fog, sky,
    clouds, stars, palette and music are a working set someone tuned, and a
    rebuild has no better guess."""
    path = os.path.join(EDIT_TRN, STOCK[mat] + ".trn")
    if not os.path.exists(path):
        return None
    text = open(path, "r", encoding="latin-1", newline="").read().replace("\r\n", "\n")
    head = re.split(r"(?m)^\[TextureType", text)[0]
    out = []
    for part in re.split(r"(?m)^(?=\[)", head):
        if re.match(r"\[Size\]", part, re.I):
            continue
        out.append(re.sub(r"(?im)^(MaterialName\s*)=.*$", r"\1= " + mat, part))
    return SIZE + "".join(out).rstrip("\n") + "\n\n"

PALETTE = {"ccmars_detail_atlas": "MARS", "cctitan_detail_atlas": "TITAN",
           "ccearth_detail_atlas": "ACHILLES", "ccmetal_detail_atlas": "MOON",
           "cctunnel_detail_atlas": "MOON"}

# Fallback only, for a machine with no Redux install to read templates from.
HEAD = """[Size]
MinX=0
MinZ=0
Width=5120
Depth=5120
Height=0.000000

[NormalView]
Time=900
FogStart=120
FogEnd=350
FogBreak=60
VisibilityRange=350
Intensity=40
Ambient=0
FlatRange=350
ShadowLuma=0
FogDirection=1
TerrainShadowLuma=20
CarAmbient=20

[Atlases]
MaterialName = {mat}

[Sky]
SunTexture=
SkyHeight = 110
SkyTexture=
BackdropTexture =
BackdropDistance= 400
BackdropWidth   = 800
BackdropHeight  = 100

[Color]
Palette={pal}.ACT
Luma={pal}.LUM
Translucency={pal}.TBL
Alpha={pal}.ALB

[World]
MusicTrack=3

"""


def type_blocks(cfg, plan, already):
    """`already` is the set of tile names the world's .trn names today; anything
    outside it is new to that .trn, whether it came from the matrix or a fill."""
    by = {}
    for t in plan:
        by.setdefault(t["i"], []).append(t)
    out = []
    for i in sorted(by):
        src = cfg["types"][i]
        out.append("[TextureType%d]   // %s" % (i, os.path.basename(src)))
        out.append("FlatColor= 128")
        for t in sorted(by[i], key=lambda t: (t["kind"] != "s", t["j"], t["kind"], t["var"])):
            if t["var"] > len(SLOT):
                out.append("; %s.map -- variant %d, no .trn slot for it" % (t["name"], t["var"]))
                continue
            key = ("Solid%s" % SLOT[t["var"] - 1] if t["kind"] == "s" else
                   "%sTo%d_%s" % ("Cap" if t["kind"] == "c" else "Diagonal",
                                  t["j"], SLOT[t["var"] - 1]))
            mark = "" if (already is None or t["name"] in already) else "   // new"
            # all four mip keys name the mip-0 tile, which is what every .trn in
            # this mod already does -- the atlas carries the real mip chain
            for mip in range(4):
                out.append("%-18s= %s.map%s" % (key + str(mip), t["name"],
                                                mark if mip == 0 else ""))
            out.append("")
    return out


def main(out_root):
    req = json.load(open(os.path.join(HERE, "required.json")))
    for mat, cfg in WORLDS.items():
        d = os.path.join(out_root, mat)
        if not os.path.isdir(d):
            continue
        plan, grid = plan_tiles(mat, cfg, req.get(mat, []))
        body = type_blocks(cfg, plan,
                           None if cfg.get("new") else set(req.get(mat, [])))
        head = ["; TextureType entries for %s -- every tile the atlas carries." % mat,
                "; Lines marked 'new' are tiles this rebuild added; the world's current",
                "; .trn does not name them yet, and a tile nothing names never draws.",
                ";", "[Atlases]", "MaterialName = %s" % mat.upper(), ""]
        open(os.path.join(d, "TRN_Entries.txt"), "w", newline="\r\n").write(
            "\n".join(head + body) + "\n")
        if cfg.get("new"):
            # Named for the material, not the world: stock ships Edit\trn\
            # mars.trn and titan.trn, and a same-named file in a mod folder
            # would shadow the editor's own template for that world -- the same
            # trap the CCMARS_ATLAS_D.dds prefix exists to avoid.
            name = mat.rsplit("_detail", 1)[0] + ".trn"
            head = stock_head(mat)
            if head is None:
                print("  no stock template for %s, using the plain header" % mat)
                head = HEAD.format(mat=mat, pal=PALETTE[mat])
            txt = head + "\n".join(body) + "\n"
            open(os.path.join(d, name), "w", newline="\r\n").write(txt)
            print("wrote", os.path.join(d, name))
        print("%-24s %d type blocks" % (mat, len(cfg["types"])))


if __name__ == "__main__":
    main(sys.argv[1])
