# BZ2/BZCC → BZR terrain port (terrain pipeline implemented; validation pending)

The separate **BZ2 → BZ1 Map Port** tab now has two paths:

- **CONVERT TER + HG2 + MAT DIAGNOSTICS** decodes a BZ2/BZCC TERR v3/v4/v5
  file without requiring source textures and records the terrain conversion for
  research/debugging.
- **BUILD RESOLVED TERRAIN BUNDLE** additionally takes the companion TRN and a
  texture asset root, resolves the authored terrain textures, and builds the
  current Redux terrain-side validation package.

The diagnostic path writes:

- `NAME.hg2`: canonical 256-sample/1,280 m Redux zones at 5 m sample spacing;
- `NAME_ter_channels.npz`: decoded meter heights, RGB, three alpha planes,
  cell flags, raw cluster info and texture indices;
- `NAME_mat_reduction.npz`: 20 m Redux-cell material coverage, strongest
  materials and source-derived corner materials;
- `NAME_reduced.MAT`: a zone-packed Redux MAT candidate;
- `NAME_port.json`: geometry, provenance, material-reduction and transition
  diagnostics;
- `NAME_height.png` and `NAME_cells.png`: diagnostic previews.

The resolved bundle first performs texture resolution as a read-only preflight,
so a missing required asset fails without leaving a partial output folder. It
reads the exact `TileTextureN` paths under the GUI's **Texture asset root**.
Selecting a TER checks nearby folders, including the BZCC game install and its
`worlds` folder, and fills this field when every required texture is available.
Loose files take precedence; otherwise the converter retrieves exact members
from DOCP v2 `.pak` archives in the selected folder. It decompresses only the
needed files. If a named legacy TGA is absent, a unique same-stem diffuse DDS
under the game's `bz2r_res/baked/Worlds` folder is used and recorded as a
substitution in the source manifest. ISDF01 uses this for `pluto9.tga`. The
**EXTRACT REQUIRED PAK TEXTURES** button can write packed files
to a separate folder for inspection or reuse. The converter stops and lists
unresolved slots if assets are
missing. It then rewrites the manifest with the resolved companion-TRN mapping, suppresses
undeclared upper-layer slot 0 as the BZ2/BZCC no-texture sentinel, re-encodes
the MAT, and writes:

- a diffuse terrain atlas plus material-matching CSV;
- a neutral detail/specular asset for the Redux terrain shader;
- only the cap and diagonal transition atlas entries referenced by the encoded
  MAT;
- `PREFIX_CONFIG.TRN`, the generated Redux atlas/TextureType fragment;
- `NAME.trn`, a terrain-validation TRN candidate that preserves non-terrain
  source TRN sections, rewrites `[Size]` for Redux geometry, removes the
  source `[Texture]`/terrain bindings, and installs the Redux atlas bindings.
- `NAME.mat`, the final MAT with the same zero-based material IDs as the TRN.

The GUI's **Target MinX / MinZ** fields default to `0,0`. Leave either field
blank to retain that axis's source padded origin. The same values are used by
inspection, diagnostics, and the resolved bundle, and `NAME_port.json` reports
the resulting offset for BZN objects and paths. The diagnostics-only action
still writes `NAME_reduced.MAT` with source slot numbers; the resolved bundle
writes only the final `NAME.mat`.

## Proven format behavior

The parser follows `Nielk1/bz2terraineditor`'s TERR v3-v5 cluster layout.
Pre-v4 terrain uses 0.1 m heights and 8 m/sample; v4+ uses meter floats and
2 m/sample. In v5 the compression bits are independent for height, RGB, each
alpha plane and cell data. Headerless v0-v2 terrain is not yet supported.

InfoMap bits 0-15 are four texture-slot nibbles. Bits 16-19 are layer
visibility, 20-23 owner team and 24-25 build type. Companion TRN
`TileTextureN` declarations are resolved against their original source slots.
If the TRN begins at `TileTexture1`, Redux materials and TextureTypes are
shifted down one (`1→0`, `8→7`); an explicitly authored `TileTexture0` keeps
identity numbering. The mapping is recorded in the manifest and port report.
An undeclared source zero used only by upper layers is treated as
unbound/transparent.
Layer 0 needs a real material, but some BZCC maps use undeclared slot 0 there
too (isdf01 does in 6 of 16,384 clusters, under near-opaque upper layers).
Each such cluster takes the most common bound base slot in the nearest
surrounding window. The bundle report counts these under
`mat_reduction.unbound_base_clusters_filled`.

Original BZ2 `bz2edit.exe` decompilation proves that layer 0 is the opaque
base followed by sequential alpha blends of layers 1, 2 and 3 using
AlphaMap1..3. The equivalent effective weights are:

`w0=(1-a1)(1-a2)(1-a3)`

`w1=a1(1-a2)(1-a3)`

`w2=a2(1-a3)`

`w3=a3`

`ComputeLayer` derives the visibility bits from alpha coverage, so those bits
are culling/visibility metadata rather than additional blend weights.

The reducer integrates those weights over Redux's 20 m MAT cells and also
samples the source-derived dominant material at each cell corner. The MAT
encoder uses Redux's existing cap/diagonal corner patterns to preserve
transition orientation and records the exact material pairs required by the
atlas. Checkerboards, three-material corners, and other patterns that Redux
cannot represent directly are counted as ambiguous and conservatively collapse
to that cell's strongest integrated material rather than inventing a
transition.

## Geometry and rehoming

By default the source remains at the same meter coordinates inside Redux's
1,280 m zone padding. The padded origin is floored to a whole zone and the far
edge rounded up. Padding edge-clamps the nearest authored source sample.

A caller may rehome that padded terrain with `target_min_x` /
`target_min_z`. The source's original inset inside its padded zone is retained
for both HG2 and MAT sampling, so relocating the destination cannot shift
textures relative to heights.

BZ2 signed-decimeter and BZCC meter heights are interpolated onto Redux's 5 m
lattice without horizontal or vertical normalization. Negative heights receive
only the minimum whole-decimeter positive offset needed by HG2. A source whose
height span cannot fit the safe 0-409.5 m Redux range fails rather than being
silently rescaled.

`NAME_port.json` reports `object_offset_m: [dx, vertical_offset, dz]`: add it
to every source BZN position and path point so objects land where the heights
and MAT put the terrain. For a centred BZCC map (`-2048..2048`) re-homed to
`0,0` this is `[2560, vertical, 2560]`, which keeps the source's 512 m inset.
BZN Toolbox `bzcc_port.py --offset-from NAME_port.json` applies
it. isdf01 was checked this way: 90% of objects sit within 2 m of the ported
ground (median error 0.1 m); the outliers are cliff props sunk into the
ground in BZCC.

## Remaining validation/work

The **terrain-side conversion code is implemented**, but the generated bundle
is deliberately labelled a **validation candidate** until it has been loaded
against representative BZ2/BZCC maps in Battlezone 98 Redux. In-game checks
still need to establish compass orientation with asymmetric landmarks, confirm
MAT transition orientation/variant behavior, and inspect texture appearance at
cell boundaries.

This is also not yet a whole-mission converter. BZN objects and paths are
ported by BZN Toolbox `bzcc_port.py` (see above). Mission logic, water, hazards and other
BZ2/BZCC gameplay semantics remain separate porting work. The BZN terrain name does not have to equal the mission filename.

Tests:

`python -m unittest tests.test_bz2_terrain_port tests.test_bz2_terrain_bundle tests.test_bz2_mat_reducer tests.test_bz2_mat_encoder tests.test_bz2_texture_resolver tests.test_custom_atlas_builder tests.test_bz2_atlas_port tests.test_bz2_texture_blend -v`
