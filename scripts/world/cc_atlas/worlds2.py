"""Every Combat Commander world, as a terrain atlas Redux can bind.

`types` is the TextureType index -> source texture map.  For the nine worlds
ISDF Chronicles already ships, indices 0..n are exactly the ones recovered by
correlating each existing solid tile against the CC tree (tools/mapping.json) --
they are what the .mat files already paint with, so they are not negotiable.
Anything added here is added *after* those, so no existing painted cell changes
meaning.

`blend` is the set of types that get the full cap/diagonal matrix.  n blend
types produce exactly n*n tiles (n solids + 2 per unordered pair), which is why
a square grid comes out full rather than 39% full.

`pool` is source art the world ships and the atlas never used.  It becomes extra
solid variants (SolidB/SolidC in the .trn), which is the cheapest way to break up
tiling repetition and costs nothing while the grid has cells left.
"""

import os

# Where the Combat Commander source art tree lives (the folder holding Worlds/),
# and the Redux mod whose existing .csv / .material / .trn the nine already
# shipped worlds are rebuilt against.  Both are per-machine, so they come from
# the environment and only fall back to the author's own layout.
CC_ROOT = os.environ.get("CC_ROOT", os.path.expanduser(os.path.join(
    "~", "Documents", "Google Drive", "Ian Files", "Battlezone Files",
    "BZ2 Files", "CombatCommanderSourceMaterialModsv2")))
MOD_DIR = os.environ.get("CC_MOD_DIR", os.path.expanduser(os.path.join(
    "~", "Documents", "Google Drive", "Ian Files", "Battlezone Files",
    "Redux Maps", "ISDF Chronicles")))

# Mercury is not Combat Commander art. It comes from Forgotten Enemies
# Remastered (github.com/BlackDragonN001/FERemastered, FE_RM_Source/Worlds/
# Mercury), mirrored locally by fetch_fe.py, so that world carries its own
# `root`. Anything without a `root` still resolves against the CC tree.
FE_ROOT = os.environ.get("FE_ROOT", os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "fe_source"))

W = "Worlds/"

WORLDS = {
    # ---------------------------------------------------------------- existing
    # Ten types, five of them the interior plates of the ISDF facility, which
    # blend with nothing -- so the matrix is over 0..4 only and the grid comes
    # out 6x6 with four cells to spare.
    "pl_detail_atlas2": dict(
        prefix="PLUTO", tile="plut", world="Pluto",
        types={0: W+"Pluto/pluto9.tga", 1: W+"Pluto/pluto2.tga",
               2: W+"Pluto/pluto4.tga", 3: W+"Pluto/pluto5.tga",
               4: W+"Pluto/pluto3.tga", 5: W+"Pluto/ibfoun00.tga",
               6: W+"Pluto/Props/Textures/pbintw00.png",
               7: W+"Pluto/Props/Textures/pbintc00.png",
               8: W+"Pluto/Props/Textures/pbintc03.png",
               9: W+"Pluto/Props/Textures/pbintf00.png"},
        blend=[0, 1, 2, 3, 4],
        # pluto8 is byte-identical to pluto3 and plutoice is a 256px stub, so
        # neither is worth a cell
        pool=[W+"Pluto/pluto6.tga", W+"Pluto/pluto7.tga", W+"Pluto/pluto.tga",
              W+"Pluto/ibfoun01.tga"],
    ),
    # Type 5 was the prop plate, solid-only.  Promoting it to a blend type is
    # exactly the ten tiles needed to fill 6x6.
    "ba_detail_atlas": dict(
        prefix="BANE", tile="bane", world="Bane",
        types={0: W+"Bane/bane4.tga", 1: W+"Bane/bane3.tga",
               2: W+"Bane/bane2.tga", 3: W+"Bane/bane.tga",
               4: W+"Bane/bane5.tga",
               5: W+"Bane/Props/Textures/bbintf02.png"},
        blend=[0, 1, 2, 3, 4, 5],
        pool=[],
    ),
    # core.trn asks for four solid variants the atlas never carried, so they
    # currently draw the default tile.  Core_2 and Core_6 are the world's two
    # unused 2048 sources and are what those variants should have been.
    "co_detail_atlas": dict(
        prefix="CORE", tile="core", world="Core",
        types={0: W+"Core/Core_1.tga", 1: W+"Core/Core_3.tga",
               2: W+"Core/Core_4.tga", 3: W+"Core/Core_5.tga",
               4: W+"Core/Props/Textures/cbextw01.tga"},
        blend=[0, 1, 2, 3, 4],
        explicit={"core00s2": W+"Core/Core_2.tga",
                  "core11s2": W+"Core/Core_6.tga"},
        pool=[],
    ),
    # dark44s1 is the circuit-board grid that matches nothing in the CC tree; it
    # is cut out of the shipped atlas instead ("keep").  dark2 fills 6x6.
    "da_detail_atlas": dict(
        prefix="DARK", tile="dark", world="Dark",
        types={0: W+"Dark/dark.tga", 1: W+"Dark/dark7.tga",
               2: W+"Dark/dark4.tga", 3: W+"Dark/dark9.tga", 4: "keep",
               5: W+"Dark/dark2.tga"},
        blend=[0, 1, 2, 3, 4, 5],
        pool=[W+"Dark/dark3.tga", W+"Dark/dark5.tga", W+"Dark/dark8.tga",
              W+"Dark/dark10.tga"],
    ),
    "dune_detail_atlas": dict(
        prefix="DUNE", tile="dune", world="Dune",
        types={0: W+"Dune/Dune9.tga", 1: W+"Dune/Dune7.tga",
               2: W+"Dune/Dune6.tga", 3: W+"Dune/Dune3.tga",
               4: W+"Dune/Dune1.tga", 5: W+"Dune/Dune5.tga"},
        blend=[0, 1, 2, 3, 4, 5],
        pool=[W+"Dune/Dune2.tga", W+"Dune/Dune8.tga", W+"Dune/dune4.tga"],
    ),
    "mi_detail_atlas": dict(
        prefix="MIRE", tile="mire", world="Mire",
        types={0: W+"Mire/mbextf02.tga", 1: W+"Mire/mire7.tga",
               2: W+"Mire/mire2.tga", 3: W+"Mire/mire6.tga",
               4: W+"Mire/mire5.tga", 5: W+"Mire/mire3.tga"},
        blend=[0, 1, 2, 3, 4, 5],
        pool=[W+"Mire/mire.tga", W+"Mire/mire4.tga"],
    ),
    # ------------------------------------------------------------- Mercury
    # Six types, and FE ships exactly six surfaces -- four terrain plus the rock
    # and volcano prop textures, which is what isdfms05 already paints with:
    # correlating the six solids of the shipped atlas against the FE tree scores
    # 0.975 / 0.996 / 0.770 / 0.815 / 0.915 for types 0-4, and type 5 is a pure
    # black tile (one unique colour), so the volcano is a free upgrade rather
    # than a change -- isdfms05.mat paints type 5 nowhere.
    #
    # Promoting 5 to a blend type makes 6*6 = 36 tiles, which fills a 6x6 grid
    # exactly. The shipped atlas is 8x8 with 26 of 64 cells used.
    "mc_detail_atlas": dict(
        prefix="MERCURY", tile="merc", world="Mercury", root=FE_ROOT,
        types={0: "Worlds/Mercury/Terrain/Mercury1.tga",
               1: "Worlds/Mercury/Terrain/Mercury2.tga",
               2: "Worlds/Mercury/Terrain/Mercury3.tga",
               3: "Worlds/Mercury/Terrain/Mercury4.tga",
               4: "Worlds/Mercury/Props/Rocks/Mercury_Rock_01.png",
               5: "Worlds/Mercury/Props/Volcano/Mercury_Volcano.tga"},
        blend=[0, 1, 2, 3, 4, 5],
    ),
    "re_detail_atlas": dict(
        prefix="REND", tile="rend", world="Rend",
        types={0: W+"Rend/rend5.tga", 1: W+"Rend/rend.tga",
               2: W+"Rend/rend2.tga", 3: W+"Rend/rend3.tga",
               4: W+"Rend/rend4.tga", 5: W+"Rend/rend6.tga"},
        blend=[0, 1, 2, 3, 4, 5],
        pool=[W+"Rend/rend7.tga", W+"Rend/rend8.tga", W+"Rend/rend9.tga",
              W+"Rend/rend10.tga"],
    ),
    "to_detail_atlas": dict(
        prefix="TOXIC", tile="toxc", world="Toxic",
        types={0: W+"Toxic/toxic_2.tga", 1: W+"Toxic/toxic_3.tga",
               2: W+"Toxic/toxic_4.tga", 3: W+"Toxic/toxic_7.tga",
               4: W+"Toxic/toxic_8.tga", 5: W+"Metal/Metal13.tga"},
        blend=[0, 1, 2, 3, 4, 5],
        pool=[W+"Toxic/toxic_5.tga", W+"Toxic/toxic_9.tga"],
    ),
    "waste_detail_atlas": dict(
        prefix="WASTE", tile="wast", world="Wasteland",
        types={0: W+"Wasteland/wasteland1.tga", 1: W+"Wasteland/wasteland2.tga",
               2: W+"Wasteland/wasteland6.tga", 3: W+"Wasteland/wasteland4.tga",
               4: W+"Wasteland/wasteland5.tga", 5: W+"Wasteland/wasteland3.tga"},
        blend=[0, 1, 2, 3, 4, 5],
        pool=[],
    ),

    # --------------------------------------------------------------------- new
    # No .trn binds these yet, so the type order is ours to choose and the
    # matrix is complete by construction.  The DDS prefix is CC* because stock
    # Redux already ships MARS_ATLAS_D.dds and TITAN_ATLAS_D.dds -- a same-named
    # file in a mod folder would shadow the stock atlas for every stock map.
    "ccmars_detail_atlas": dict(
        prefix="CCMARS", tile="mars", world="Mars", new=True, detail="ma_detail.dds",
        types={0: W+"Mars/mars1.tga", 1: W+"Mars/mars2.tga",
               2: W+"Mars/mars5.tga", 3: W+"Mars/mars6.tga",
               4: W+"Mars/mars7.tga"},
        blend=[0, 1, 2, 3, 4], pool=[],
        lighting=dict(diffuse="1 1 1", ambient="1 1 1",
                      specular=".4 .35 .3", shininess="120"),
    ),
    "cctitan_detail_atlas": dict(
        prefix="CCTITAN", tile="titn", world="Titan", new=True, detail="ti_detail.dds",
        types={0: W+"Titan/Titan.tga", 1: W+"Titan/Titan2.tga",
               2: W+"Titan/Titan3.tga", 3: W+"Titan/Titan4.tga"},
        blend=[0, 1, 2, 3], pool=[],
        lighting=dict(diffuse="1 1 1", ambient="1 1 1",
                      specular=".3 .35 .4", shininess="140"),
    ),
    # grass first so TextureType0 -- what an unpainted cell falls back to -- is
    # ground rather than road surface.
    "ccearth_detail_atlas": dict(
        prefix="CCEARTH", tile="erth", world="EarthCity", new=True, detail="ac_detail.dds",
        types={0: W+"EarthCity/grass.tga", 1: W+"EarthCity/street_1.tga",
               2: W+"EarthCity/street_2.tga", 3: W+"EarthCity/street_3.tga",
               4: W+"EarthCity/Street_4.tga", 5: W+"EarthCity/street_5.tga",
               6: W+"EarthCity/street_6.tga"},
        blend=[0, 1, 2, 3, 4, 5, 6], pool=[],
        lighting=dict(diffuse="1 1 1", ambient="1 1 1",
                      specular=".5 .5 .5", shininess="90"),
    ),
    # Thirteen sources, and a 13-type matrix is 169 tiles -- a 13x13 grid that
    # would force 512 px tiles.  Seven as types and the other six as solid
    # variants keeps every texture and keeps 1024.
    "ccmetal_detail_atlas": dict(
        prefix="CCMETAL", tile="metl", world="Metal", new=True, detail="mn_detail.dds",
        types={0: W+"Metal/metal.tga", 1: W+"Metal/Metal2.tga",
               2: W+"Metal/Metal3.tga", 3: W+"Metal/Metal4.tga",
               4: W+"Metal/metal5.tga", 5: W+"Metal/metal6.tga",
               6: W+"Metal/metal7.tga"},
        blend=[0, 1, 2, 3, 4, 5, 6],
        pool=[W+"Metal/metal8.tga", W+"Metal/metal9.tga", W+"Metal/metal10.tga",
              W+"Metal/metal11.tga", W+"Metal/metal12.tga"],
        lighting=dict(diffuse="1 1 1", ambient="1 1 1",
                      specular=".8 .8 .85", shininess="200"),
    ),
    # Same shape: seven types leaves Tunnel_7 and Tunnel_8 as variants rather
    # than pushing the grid to 9x9.
    "cctunnel_detail_atlas": dict(
        prefix="CCTUNNEL", tile="tunl", world="Tunnels", new=True, detail="mn_detail.dds",
        types={0: W+"Tunnels/Tunnel_0.tga", 1: W+"Tunnels/Tunnel_1.tga",
               2: W+"Tunnels/Tunnel_2.tga", 3: W+"Tunnels/Tunnel_3.tga",
               4: W+"Tunnels/Tunnel_4.tga", 5: W+"Tunnels/Tunnel_5.tga",
               6: W+"Tunnels/Tunnel_6.tga"},
        blend=[0, 1, 2, 3, 4, 5, 6],
        pool=[W+"Tunnels/Tunnel_7.tga", W+"Tunnels/Tunnel_8.tga"],
        lighting=dict(diffuse="1 1 1", ambient="1 1 1",
                      specular=".7 .7 .7", shininess="180"),
    ),
}
