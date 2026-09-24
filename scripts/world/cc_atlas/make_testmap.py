"""Stand one of the new atlases up in a real addon map so the engine has to load it.

The point is the thing a contact sheet cannot show: whether Redux -- 32-bit, DX11 --
actually creates a 7168 or 8192 square DXT1 texture for terrain, and whether a
non-power-of-two atlas samples correctly. IAMP_DustBowl is the cheapest carrier:
one terrain zone, already launch-tested, and its .MAT paints types 0..4, which
every new world covers.

The BZN carries its own name and its terrain's name as length-prefixed strings,
so the copy is renamed by a same-length byte substitution -- 'dustbowl' ->
'cctest01' -- rather than by touching the file layout.
"""
import os, re, shutil, sys

ADDON = os.environ.get("REDUX_ADDON", os.path.join(
    "C:\\", "Program Files (x86)", "GOG Galaxy", "Games",
    "Battlezone 98 Redux", "addon"))
DEST = os.path.join(ADDON, "IAMP_CCAtlasTest")
OLD, NEW = "dustbowl", "cctest01"
assert len(OLD) == len(NEW)


def build(atlas_dir, material, trn_types):
    if os.path.exists(DEST):
        shutil.rmtree(DEST)
    shutil.copytree(SRC, DEST)
    for f in sorted(os.listdir(DEST)):
        stem, ext = os.path.splitext(f)
        if stem.lower() != OLD:
            continue
        os.rename(os.path.join(DEST, f), os.path.join(DEST, NEW + ext))
    b = open(os.path.join(DEST, NEW + ".bzn"), "rb").read()
    n = b.count(OLD.encode())
    open(os.path.join(DEST, NEW + ".bzn"), "wb").write(b.replace(OLD.encode(), NEW.encode()))

    # the .trn keeps its header (size, fog, sky, palette) and swaps only the
    # atlas binding and the texture table
    trn = os.path.join(DEST, NEW + ".TRN")
    txt = open(trn, errors="ignore", newline="").read()
    head = re.split(r"^\s*\[TextureType\d+\]", txt, maxsplit=1, flags=re.M)[0]
    head = re.sub(r"(MaterialName\s*=\s*)\S+", r"\g<1>" + material, head, flags=re.I)
    open(trn, "w", newline="").write(head.rstrip() + "\n\n" + trn_types)

    for f in sorted(os.listdir(atlas_dir)):
        if f.endswith((".dds", ".csv", ".material")):
            shutil.copy2(os.path.join(atlas_dir, f), os.path.join(DEST, f))
    ini = os.path.join(DEST, NEW + ".ini")
    t = open(ini, errors="ignore", newline="").read()
    t = re.sub(r'(missionName\s*=\s*)"[^"]*"', r'\g<1>"CC Atlas Test"', t)
    open(ini, "w", newline="").write(t)
    print(f"{DEST}: {material}, {n} bzn name fixups, "
          f"{len([f for f in os.listdir(DEST) if f.endswith('.dds')])} atlases")


if __name__ == "__main__":
    atlas_dir = sys.argv[1]
    material = os.path.basename(atlas_dir)
    types = open(os.path.join(atlas_dir, "TRN_Entries.txt"), errors="ignore").read()
    types = re.split(r"^\[TextureType0\]", types, maxsplit=1, flags=re.M)[1]
    build(atlas_dir, material, "[TextureType0]" + types)
