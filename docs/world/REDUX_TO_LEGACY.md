# Redux → Battlezone 1.5 port

**World & Terrain › Redux → 1.5 Port**, or on the command line:

```
bztoolbox terrain to-legacy <redux folder> <output folder> [--palette auto|trn|rebuild|file.act]
    [--base-world mars] [--tile-size 256] [--format indexed|565] [--dither] [--no-tables]
    [--game-dir <Redux install>] [--search <dir>]... [--no-heightmaps] [--no-bzn] [--allow-bzn-loss]
```

This is the legacy port (Legacy Atlas Creator) run in reverse. The source is a Redux world or mission folder: the TRN, the
`[Atlases]` material, its CSV and texture, and optionally the HG2, LGT, MAT and BZN. Materials, CSVs and textures that
live elsewhere are found through `--search` or, for stock atlases, the Redux install's `BZ_ASSETS`. The output folder is
ready for 1.5's `addon` folder. A report, `redux_to_legacy_report.txt`, is written into it.

## What it does

| Redux | 1.5 | How |
|---|---|---|
| `[Atlases] MaterialName` + atlas texture + CSV | one MAP per tile name in `[TextureTypeN]` | The CSV rectangle is cut from the material's `DiffuseMap`, resized with Lanczos to 256/128/64/32 px for levels 0–3, flipped vertically (MAP rows are bottom-up), and reduced to the palette. |
| TRN | TRN | `[Atlases]` is removed. A level-0 entry whose section lacks levels 1–3 gets them (`SolidA0 = XX00S0.MAP` → `SolidA1..3`). `[Color]` names the new palette and tables. Everything else stays as written. `CR CR LF` line endings are repaired. |
| (no usable ACT) | ACT | See **Palette** below. |
| stock LUM/TBL/ALB | `<palette>.lum/.tbl/.alb` | Transferred onto a new palette from the base world's tables in the game's `bzone.zfs`. |
| Sky/backdrop, `[Clouds]`, `[Stars]` textures with a material in the folder | MAPs, 256 px | Clouds and stars keep index 0 as clear (alpha < 128). Names without a material are 1.5 stock files and are left alone. |
| HG2 | HGT | The legacy vertices (`convert_hg2_to_hgt`). The report says how much detail between vertices had no place in the 10 m grid. Flags come from a same-named HGT when one is present. |
| LGT (256 cells per zone) | LGT (128 cells per zone, with the border block) | Every other cell. Checked against stock misn05/misns1, where Redux's relit LGTs correlate 0.97 with 1.5's. |
| BZN 2016 (or 1046–1047) | BZN 1045 | `battlezone.bzn.version_convert`. Losses are refused unless `--allow-bzn-loss` is given. |
| MAT | MAT | Copied. The files are byte-identical between the games. See **Undefined tiles** below. |
| `.ini`, `.lua`, `.material`, `.dds`, `.csv`, meshes, PNG/TGA… | — | Left out. A `.lua` gets a warning: 1.5 has no Lua. |

Tile orientation was checked against the stock data. The Redux Mars atlas cell `MA01DA0.MAP`, flipped vertically,
correlates 0.997 with 1.5's `ma01da0.map`, and the sky `mars.map` correlates 0.94 with Redux's `mars.tga`.

A round trip of stock `misn05` (Redux atlas → 1.5 tiles, stock `MARS.ACT`) compared with 1.5's own tiles gives these
results. The Redux atlas was recompressed, so the indices cannot match exactly.

| Level | PSNR |
|---|---|
| 0 | 35.7 dB |
| 1 | 35.5 dB |
| 2 | 34.1 dB |
| 3 | 33.6 dB |

## Palette

1.5 draws every surface through the world palette. Across all nine stock worlds, entries **0–95 and 224–255 are
identical**: these are the interface, object and effect colours. Only **96–223** belong to the world. Stock terrain
tiles only use 0–223, and the port quantises to the same range.

- `auto` (default):
  - A stock palette named by the TRN (e.g. `MARS.ACT`) is used as is.
  - An ACT in the folder that keeps the shared entries and has at least 32 world colours is used and copied.
  - Otherwise a new palette is built. Redux never reads the ACT, so Redux-era ACTs are often placeholders.
    `polrmars.act` has 4 distinct colours.
- `rebuild`: the base world's shared entries plus 128 colours fitted to the atlas tiles and sky. Median cut seeds the
  colours, then k-means refines them while 0–95 stay fixed.
- `trn`: the TRN's ACT as it is, with a warning if it would recolour the game.
- An `.act` path uses that file.

The base world (`--base-world`) defaults to the stock world named by the TRN's `Luma`/`Palette`, otherwise `mars`.

### LUM / TBL / ALB

Each file is a 256×256 lookup:

- `.LUM`: light level × colour
- `.TBL`: colour × colour, for translucency
- `.ALB`: alpha level × colour

For a new palette each stock table is moved across in three steps:

1. Every new colour is matched to its nearest base colour.
2. The base table gives the result.
3. The resulting colour is matched back into the new palette.

Moving the mars tables onto the moon, venus and titan palettes and comparing with those worlds' real tables shows the
mean colour error:

| Table | Reusing the stock table unchanged | Transferred |
|---|---|---|
| TBL | 26–37 | 10–15 |
| ALB | 22–32 | 7–11 |

LUM carries each world's own lighting curve, so the transferred LUM keeps the base world's curve. Without a game folder
the TRN keeps its old table names, and the report warns.

## Undefined tiles

1.5 builds a table of type × transition × variant from the TRN. For each `[TextureTypeN]` it reads
`Solid<A-D>0` and `CapTo<M>_<A-D>0`/`DiagonalTo<M>_<A-D>0` for M = 0–7 (see `Load_Terrain_Texture_Info` in the 1.5
decompilation). A variant that is not defined falls back to a lower letter. Any other slot the MAT uses but the TRN
leaves out stays at entry 0, the built-in `badTexture`, and **1.5 draws a checkerboard there**.

Redux instead draws the atlas's default tile: the CSV's nameless first row (`,0,0,0.25,0.25`). The stock Mars atlas
reserves its own unnamed cell at (0, 0) for this.

Auto-painted MAPs hit this often. Non-adjacent transitions (0→3, 1→4, …) and unused type numbers are common, and ROTBD
mission 4 uses 20 such slots in 5,161 cells. `--missing-tiles` controls the fix:

| Value | What it does |
|---|---|
| `default` (default) | Adds the missing `SolidA`, `CapToM_A` or `DiagonalToM_A` keys, levels 0–3, pointing at the default cell. When a TRN tile family already sits on that cell (Polar Mars: `PM11S`), it is reused. Otherwise the cell is written as `<prefix>DEF0-3.MAP`. |
| `solid` | Fills each slot with its type's own `SolidA` tile, falling back to the default cell for types without one. |
| `none` | Only reports the slots. |

## Sprites (custom sun and others)

Redux reads sprites from a text `.sta` table. Each line names an Ogre material and a rectangle in that material's
texture, and the TRN's `SunTexture` is a sprite name. ROTBD's `sunblue`, for example, uses the `BLUESUN` material.

1.5 looks a sprite name up in a binary table instead: `spritea.stb` for Direct3D, `sprite8.stb` for software. Both come
from `bzone152.zfs`. An unknown name resolves to entry 0, the engine's bad sprite, so a custom sun does not draw.

Each record is 52 bytes:

| Offset | Field |
|---|---|
| 0x00 | name, 32 bytes |
| 0x20 | texture, 8 characters; loaded as `<texture>.MAP` |
| 0x28 | u, v, width, height, each a u16 in pixels |
| 0x30 | flags, u32; in Direct3D the low 4 bits pick a tint colour |

Sprite MAPs are stored top-down. The sun is drawn at its table size in screen pixels (`sun.0` is 63×63), using
`D3D_Flat_Alpha_Blend_Texture_Polygon`.

With a 1.5 install (`--legacy-dir`; the usual install folders are detected), the port converts every `.sta` entry
whose material and texture it can find:

- Each sheet is scaled from the `.sta`'s declared image size to a power of two, at most 256 px. A sheet with the sun is
  scaled so the sun is 64 px.
- Each sheet is written twice:
  - `<name>.MAP`, A4R4G4B4, for `spritea.stb`. It keeps alpha, like the stock 16-bit sheets.
  - `<name>8.MAP`, 8-bit with index 255 as the transparent key, for `sprite8.stb`.
- Both tables are written as the full stock table plus the new entries. An entry replaces a stock sprite of the same
  name. The sun takes `sun.0`'s flags.

A table in `addon` replaces the stock one for every mission while it is installed. The tables carry every stock entry,
so nothing else changes, but they must be merged by hand with another mod's tables.

Without a 1.5 install, or without the sun's `.sta` entry or texture, a custom `SunTexture` is set to the stock `sun.0`.
`--no-sprites` skips sprites.
