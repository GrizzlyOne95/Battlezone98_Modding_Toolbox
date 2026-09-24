# CC atlas builder — Combat Commander terrain art into Redux terrain atlases

Batch version of what the **Custom Atlas Creator** tab does interactively: take a
set of source textures, cut the solids and the cap/diagonal transition tiles,
pack them into one square atlas per channel, and write the `.csv` of UV rects,
the `.material`, and the `[TextureType]` blocks a `.trn` needs.

Two things it adds over the tab.

**It packs tight.** The hand-built ISDF Chronicles atlases are 8×8 grids holding
25–32 tiles — 39–50% of the cells carry art and the rest is black, because the
layout was drawn in an image editor and the CSV written to match it. Here the
grid is `ceil(sqrt(tiles))` and every spare cell is filled with a tile worth
having, so atlas area buys texels rather than padding. The arithmetic is kind:
*n* blend types produce exactly *n*² tiles (n solids, plus a cap and a diagonal
per unordered pair), so a world whose types all blend comes out an exactly full
*n* × *n* grid.

**It composites all four channels through one shared mask.** Normal, specular
and emissive come from the authored `_n` / `_s` / `_e` maps rather than being
derived from the finished diffuse, so a transition tile's normal describes the
surface instead of describing the diffuse's luminance.

## Files

| | |
|---|---|
| `worlds2.py` | every world: TextureType → source texture, which types blend, unused art |
| `build2.py` | the builder — planning, masking, mip chain, DDS/CSV/material output |
| `runall.py` | build several worlds in parallel, resumable |
| `prefetch.py` | mirror the CC source art locally first (see *Drive*, below) |
| `fetch_fe.py` | mirror the Forgotten Enemies Remastered art Mercury is built from |
| `make_trn.py` | `[TextureType]` blocks, and a complete `.trn` for a brand-new world |
| `retrn.py` | rewrite a mod's own `.trn` files to name every tile the new atlas holds |
| `check_all.py` | seam contract, header/mip agreement, CSV shape, zero-file check |
| `check_trn.py` | a `.trn` against its CSV: phantom names, unnamed cells, header drift |
| `Install-CCAtlases.ps1` | install into a mod folder, backing up and hashing every copy |
| `verify_atlas.py` | the seam contract on its own, against the decoded DXT1 |
| `stage.py` | copy to a deliverable folder and md5 both sides |
| `table.py`, `compare_old_new.py`, `make_testmap.py` | reporting and in-game test carrier |
| `bc1.py`, `ddswrite.py`, `masks.py`, `build_world.py` | encoder, DDS writer, masks, shared helpers |

## Running it

```
set CC_ROOT=...\CombatCommanderSourceMaterialModsv2
set CC_MOD_DIR=...\Redux Maps\ISDF Chronicles
python prefetch.py
python fetch_fe.py          # Mercury only -- see "Not all of it is CC art"
python runall.py out
python make_trn.py out
python retrn.py out trn
python check_all.py out
python check_trn.py trn out
```

`make_trn.py` reads the stock editor templates from `Edit	rn` under the Redux
install (`REDUX_EDIT_TRN` overrides the path) so a new world gets a working
`[Sky]`, `[Clouds]` and `[Color]` instead of an empty header.

`CC_WORKERS` sets the parallelism (default 2). `CC_OLD_ATLASES` and
`REDUX_ADDON` only matter to the reporting and test-map scripts.

## Not all of it is CC art

Mercury is the exception. Its source is **Forgotten Enemies Remastered**
(`github.com/BlackDragonN001/FERemastered`, `FE_RM_Source/Worlds/Mercury`), not
the Combat Commander tree, so `mc_detail_atlas` carries its own `root` and
`fetch_fe.py` mirrors it. Everything without a `root` still resolves against
`CC_ROOT`. `fe_source/` is gitignored — it is 219 MB and re-fetchable.

FE names its diffuse `<name>_d` with `_n` / `_s` / `_e` beside it; `load_source`
wants the diffuse bare, so `fetch_fe.py` drops the `_d` on the way in and leaves
the siblings alone. That is the only accommodation the two trees need.

Which FE texture is which TextureType was **recovered, not guessed** — the six
solids of the shipped atlas correlate against the FE tree at 0.975 / 0.996 /
0.770 / 0.815 / 0.915 for types 0–4, with types 4 and 5 turning out to be the
rock and volcano *prop* textures rather than terrain. Type 5's shipped tile is
one unique colour (pure black), and `isdfms05.mat` paints type 5 nowhere, so
giving it the volcano art is an upgrade rather than a change.

## Things that cost a day each

**The tile size is a property of the `.trn` key, not the filename.** Stock sets
make the two agree (`SolidA0 = ac00sA0.map`), but an author naming their own
tiles is under no obligation to.

**A transition in slot B has to blend the *B* solids of its two types**, because
that is the pair the engine puts either side of it when it picks slot B for a
cell. Blending the A art into a B cap fails the seam classifier outright.

**Read the source art from local disk.** With the CC tree on Google Drive, seven
encoder processes sat at 16% CPU while GoogleDriveFS burned 820 seconds
streaming 2048-square TGAs on demand. `prefetch.py` pulls each file once, in
parallel, and writes a tile-sized PNG into a local mirror that keeps the tree's
relative paths — so `load_source` finds it with nothing else to change.

**Validate output after a crash, not just after a write.** A host lock leaves
correctly-sized, all-NUL files: NTFS flushed the metadata and not the data. The
tell is that `build_report.json` is written last, so a world whose report parses
is a world that landed; `check_all.py` looks for NUL runs directly.

**A repacked atlas is not a drop-in for its own DDS.** Every UV rect changes when
the grid does, so the `.csv` must be copied with the `.dds`. Shipping the atlas
alone puts every tile in the wrong place.

**A .trn's TextureType index is a paint index, not the atlas's matrix index.**
`core.trn` declares TextureType 0, 2 and 5 and points them at `core00`, `core11`
and `core22`, so a generated block cannot be pasted into an existing file — the
mapping has to be recovered per file from each block's own `Solid` key, and a
`CapTo` key names the target's *TextureType* number while the tile name carries
matrix numbers. `retrn.py` does that; `TRN_Entries.txt` is documentation.

**The line endings in a mod are not uniform.** In ISDF Chronicles `dunes.trn`
ends every line CR CR LF and `core.trn` bare LF, and the engine parses both.
Writing a rewritten file with a normalised terminator is a diff on every line of
someone's map for no reason, so `retrn.py` copies the header through byte for
byte and writes its own body with whatever that file already used.

**Adding a TextureType is only free if nothing paints that index.** The `.mat`
packs the pair of types meeting at each cell into one byte's two nibbles, so it
says exactly which indices a map uses. Across the fifteen maps here only one
addition lands on a painted index — `isdfms15` paints type 7 on 214 cells its
`.trn` never declared, which have been drawing the default tile.

**Stock ships `Edit	rn\mars.trn` and `titan.trn`** as well as
`MARS_ATLAS_D.dds` and `TITAN_ATLAS_D.dds`. Anything a mod drops in under those
names shadows the stock file for every stock map, which is why the new worlds are
`ccmars`, `cctitan`, `ccearth`, `ccmetal` and `cctunnel` throughout.
