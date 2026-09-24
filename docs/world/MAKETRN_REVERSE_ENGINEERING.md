# MakeTRN 2.1.2 reverse-engineering notes

Reference binary: `MakeTRN.exe`

- Banner: `Battlezone98 MakeTRN Utility 2.1.2 (Mar 27 2017)`
- PE: 32-bit x86 Windows console executable
- SHA-256: `dc16de74f9d23e3ab6bd1c7d529f9b4dcef565e99f9b1bb5b8fda13a208b37c5`
- Embedded PDB path: `D:\code\BattleZoneTest\build\bin\Release\MakeTRN\MakeTRN.pdb`

These notes describe behavior recovered from the executable itself. Where the executable disagrees with its own help text, executable behavior is treated as authoritative.

## Command-line surface

MakeTRN accepts `/` or `-` option prefixes and case-insensitive option letters.

| Option / mode | Recovered behavior |
| --- | --- |
| `<name>.MSN` | Reads Interstate '76-style `MSN` + companion `TER`, extracts terrain, then writes TRN + HG2 + MAT. |
| `<name>.TRN` | Loads companion HG2 and repaints MAT. If HG2 is missing, falls back to HGT and converts it to HG2. |
| `<name> /c /w=N /h=N` | Creates a new blank terrain, then writes TRN + HG2 + MAT. |
| `/p=file` | Reads up to eight `[Layer0]` ... `[Layer7]` material-assignment rules. |
| `/e=N` | Empty/out-of-bounds elevation and blank-terrain fill value. The implementation accepts `0..4094`; the help text says `0..4095`. |
| `/w=N`, `/h=N` | Independent width/depth values. Internally meters are divided by 5, rounded up to a 256-sample boundary, then multiplied by 5, yielding 1280 m zone boundaries for normal inputs. |

The help mentions changing the dimensions of an existing TRN with `/w` and `/h`, but that branch prints `Error: this feature has not been completed` and exits.

A `BMP` extension is recognized and prints `Creating terrain from 24-bit grayscale BMP file`, but that branch also immediately reaches the same `feature has not been completed` error. It is not a working MakeTRN 2.1.2 feature.

## HG2 output

New terrain uses the Redux HG2 layout:

- structure version: `1`
- zone bits / depth: `8`
- samples per zone: `256 x 256`
- map version: `10`
- sample size: unsigned 16-bit storage
- zone-major payload ordering

One 1280 m terrain zone therefore corresponds to 256 height samples on each axis, or 5 m per HG2 sample.

For blank creation, every sample is initialized from `/e`. The default is zero.

## HGT compatibility path

When repainting a TRN, MakeTRN first attempts `<name>.HG2`. If it cannot load HG2, it attempts `<name>.HGT`.

The HGT path is legacy 128-samples-per-zone data (10 m per sample). MakeTRN:

1. reads dimensions from `[Size]` in the TRN;
2. validates the raw HGT byte count;
3. reads 128 x 128 zone blocks;
4. masks source values to 12 bits (`0x0FFF`);
5. doubles both axes to the Redux 256-samples-per-zone grid with a diagonal-triangle interpolation;
6. runs a 3 x 3 smoothing pass over the interpolated Redux raster;
7. writes an HG2.

At the exact half-sample positions used by the 2x conversion, the triangle interpolation reduces to four cases: original sample, horizontal average, vertical average, or the average of the source sample and its down-right diagonal. Right/bottom edges clamp to the current source sample before interpolation.

The smoothing pass uses only in-bounds neighbors (4 at corners, 6 at edges, 9 internally) and positive half-up rounding:

```text
rounded = (2 * sum + count) / (2 * count)
```

The HGT fallback return mask requests HG2 output; it does not perform the MAT repaint in the same legacy pass. WorldBuilder's UI deliberately continues through painting after writing the companion HG2 so the user does not need a second operation.

## Interstate '76 MSN + TER import

MakeTRN's working `.MSN` mode was recovered from the executable and is implemented by `msn_ter_codec.py` plus the `msn2terrain.py` frontend.

The `.MSN` file is a size-prefixed chunk stream. MakeTRN searches the top-level stream for a `TDEF` chunk, then searches inside that chunk for `ZMAP`. Each chunk uses:

```text
char  Tag[4]
int32 Size        // includes this 8-byte header
byte  Payload[]
```

The recovered `ZMAP` payload is:

```text
uint8 ZoneCount
uint8 ZoneId[80][80]
```

`0xFF` means that grid cell contains no terrain. Every other byte identifies one sequential terrain block in the companion `.TER` file.

The `.TER` file contains `ZoneCount` raw blocks. Every block is exactly:

```text
256 x 256 x uint16 little-endian = 0x20000 bytes
```

MakeTRN then:

1. finds the smallest occupied rectangle in the 80 x 80 `ZMAP` grid;
2. allocates a cropped Redux height raster for that rectangle;
3. scans TER zone IDs in ascending order and uses the first row-major matching `ZMAP` placement;
4. masks every TER height sample with `0x0FFF`;
5. copies each 256 x 256 block into its cropped output position;
6. leaves unassigned cells at zero;
7. writes TRN `MinX` and `MinZ` from the cropped ZMAP origin in 1280 m units;
8. writes the normal HG2 and runs the same MakeTRN MAT painter.

WorldBuilder exposes this recovered mode through:

```text
python msn2terrain.py mission.MSN --output Export --name I76MAP
```

The companion `.TER` is resolved from the MSN stem by default. `--ter` can override it, and `/p=` / `/e=` aliases are accepted for the recovered MakeTRN layer and empty-elevation controls. `--world` selects the WorldBuilder Redux environment template for the generated TRN. Synthetic TDEF/ZMAP/TER fixtures cover chunk parsing, crop/origin preservation, zone placement, 12-bit masking, missing zone IDs, truncation handling, and end-to-end TRN/HG2/MAT generation.

A real Interstate '76 corpus fixture would still be valuable as an external validation artifact, but the implementation no longer depends on an inferred file layout: the structure above comes directly from the MakeTRN disassembly.

## Material layers

MakeTRN reserves exactly eight layer slots. A layer has five integer fields:

```ini
[LayerN]
ElevationStart = ...
ElevationEnd   = ...
SlopeStart     = ...
SlopeEnd       = ...
Material       = ...
```

Unused/default-initialized slots are `4095, 4095, 90, 90, 8`.

Rules are tested in ascending layer number. **First matching layer wins.** All four interval bounds are inclusive.

The built-in rules are:

```text
Layer 0: elevation 0..4095, slope 0..15 degrees  -> material 0
Layer 1: elevation 0..4095, slope 15..90 degrees -> material 3
```

The executable's help text still says the split is 10 degrees. That is stale. Because matching is first-match-wins and inclusive, an exact 15-degree result selects material 0.

Painter material IDs are effectively `0..7`. A sample with no matching layer is fatal.

## Exact elevation and slope metric

MAT classification is evaluated every four HG2 samples, producing a 64 x 64 classification grid per 256 x 256 HG2 zone.

For classification coordinate `(x, z)`, MakeTRN scans an 8 x 8 neighborhood with offsets `-4..+3` on each axis.

Elevation is the minimum signed 16-bit sample found in that neighborhood, divided by 5 with integer truncation toward zero:

```text
elevation = trunc(minimum_raw_height / 5)
```

Slope tracks the maximum adjacent edge delta observed over each four-corner cell in the same neighborhood. If that maximum is `d`, the integer slope is:

```text
slope = trunc(asin(d / sqrt(d*d + 2500.0)) * 57.295780181884766)
```

This is equivalent to `trunc(degrees(atan(d / 50)))`.

Out-of-bounds height samples use the `/e` value.

## MAT resolution and ordering

The material classification allocation is:

```text
ceil(HG2_width / 4) x ceil(HG2_height / 4)
```

Normal Redux terrain dimensions are multiples of 256 samples, so this is exactly:

```text
64 x 64 MAT entries per terrain zone
4096 uint16 entries per zone
8192 bytes per zone
```

MAT is emitted zone-major: zone Z outer, zone X inner, then 64 x 64 entries row-major inside each zone.

## MAT word encoding

Each MAT entry is a little-endian 16-bit word:

```text
bits 15..12  base material
bits 11..8   next material
bits  7..4   mix / transition code
bits  3..0   variant nibble
```

The recovered two-material corner-pattern table is:

```text
pattern 3  -> mix 0
pattern 6  -> mix 1
pattern 12 -> mix 2
pattern 9  -> mix 3
pattern 7  -> mix 8
pattern 14 -> mix 9
pattern 13 -> mix 10
pattern 11 -> mix 11
```

The remaining one-corner and checkerboard patterns collapse to the low material. Corner sets containing more than two distinct material IDs collapse to material 7.

## Legacy randomization

Immediately before MAT emission, MakeTRN executes:

```text
srand(clock())
```

It then consumes one MSVCR120 `rand()` value per MAT entry. The random value selects the variant nibble and mirror bit; it does not change the classified base/next materials.

For solid tiles, the random value also supplies the low mix orientation bits. Consequently two MakeTRN runs over identical terrain can produce byte-different MAT files while remaining materially equivalent.

WorldBuilder therefore defaults its compatibility path to a runtime seed derived from process CPU time, while retaining deterministic seed `1` as an explicit testing/reproducibility extension.

## Blank TRN creation

For a `/c` terrain, `[Size]` is written from the generated sample geometry:

```text
MinX = 0
MinZ = 0
Width = samples_x * 5
Depth = samples_z * 5
Height = EmptyElevation * 0.1
```

The binary then writes its stock Moon environment block (`NormalView`, Moon atlas, sky/stars/color and generated `TextureTypeN` entries). WorldBuilder intentionally extends this with selectable Redux world/biome templates, time, audio and lighting controls.

## Feature parity implemented in WorldBuilder

The Stock Map Creator, Auto-Painter compatibility core, and legacy conversion frontend now cover every working MakeTRN 2.1.2 terrain-generation path while clearly separating WorldBuilder extensions:

- [x] Redux HG2 depth-8 / 256-sample zones
- [x] MakeTRN 64 x 64 MAT-per-zone geometry
- [x] exact 8 x 8 elevation/slope metric
- [x] first-match, inclusive `[LayerN]` semantics
- [x] real 15-degree built-in split
- [x] recovered MAT transition encoding
- [x] MSVCR120 PRNG implementation
- [x] TRN transition metadata validation
- [x] Stock Map Creator emits TRN + HG2 + MAT in one build
- [x] independent stock width/depth controls equivalent to `/w` and `/h`
- [x] stock empty-elevation control equivalent to `/e`
- [x] stock parameter-file control equivalent to `/p`
- [x] legacy runtime-random MAT variants by default, with deterministic mode as an extension
- [x] HGT-to-HG2 compatibility workflow, including recovered interpolation and smoothing
- [x] Interstate '76 MSN + TER import, including TDEF/ZMAP crop/origin semantics
- [x] alphanumeric 1-8 character stock map-name validation

The recognized-but-unimplemented MakeTRN 2.1.2 BMP branch and existing-terrain resize branch are **not** parity requirements: the original binary itself exits with `feature has not been completed`, while WorldBuilder already has stronger image import/resampling facilities.
