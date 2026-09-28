# Legacy model port (1.5 `.vdf`/`.sdf` to Redux Ogre assets)

`battlezone/meshes/legacy_port.py` turns a Battlezone 1.5 model (a `.vdf`
vehicle or `.sdf` structure, its `.geo` parts and `.map` textures) into what
Redux loads for a unit:

| output | contents |
|---|---|
| `<model>.mesh` | binary `[MeshSerializer_v1.100]`, one submesh per material, vertices in model space, skeleton link and bounds |
| `<model>.skeleton` | binary `[Serializer_v1.80]`, one bone per part |
| `<model>.material` | `import * from "BZBase.material"`; one `BZBase` / `BZBaseCockpit` material per legacy texture |
| `<model>_<texture>_D.png` (or `.dds`) | the legacy `.map` decoded to RGBA |

The model name is the VDF/SDF file name, so the stock ODF (or any ODF named
after the model) needs no change. **Keep the `.vdf`/`.sdf` and all `.geo`
files in the mod**: Redux still ships and reads them (stock `avtank.vdf`,
`avtank.odf` and the `.geo` parts in Redux's `bzone.zfs` are byte-identical to
1.5's) for collision, hardpoints and the ANIM keys that move the bones.

Pilots (persons) also get `<model>_fp.mesh`/`.skeleton` (the first-person
arms and gun) and the named animations Redux plays on them; turrets,
howitzers and walkers get a separate cockpit mesh (`<model>_c` under the
stock names Redux asks for, see below).

Use it from:

* **1.5 Asset Porting > 1.5 → Redux Assets** in the app: select a VDF, SDF, GEO,
  ODF or MAP directly, or choose a folder to port all supported files. Folder
  batches place each result under `<output>/<relative path>/<name>_<type>/` to
  avoid collisions. The optional **Include subfolders** switch scans
  recursively. When tkinterdnd2 is installed, dropping a supported file,
  several files, or one folder on the page starts the matching port at once;
* **drag and drop**: drop any number of `.vdf`/`.sdf`/`.odf`/`.geo`/`.map`
  files on `scripts/meshes/port_legacy_drop.cmd`; each converts into a
  `<name>_redux` folder beside itself, with stock parts and textures taken
  from the detected 1.5 install (`--game15 auto`). Options for dropped files
  go in `scripts/meshes/port_legacy_drop.args` (one per line) or in a copy of
  the script's `PORT_FLAGS`;
* `bztoolbox meshes port-legacy FILE... [options]`, or `@FILE` to read
  options from a file, one per line;
* Python: `port_file(path, out_dir, search=..., archives=..., palette=...,
  options=PortOptions(...))`, or `build_port()` (pure, nothing written) then
  `write_port()`.

Inputs:

| file | what is ported |
|---|---|
| `.vdf` / `.sdf` | the model, named after the file |
| `.odf` | the model its `baseName` (or the ODF name) names, `.vdf` or `.sdf` by `classLabel`; `person` marks a pilot, `turret`/`turrettank`/`howitzer` a turret, `nation` places the fixed scope |
| `.geo` | one part as a one-bone mesh |
| `.map` | just the texture, `<name>_D.png` |

Options (`--help` has them all):

| option | effect |
|---|---|
| `--out DIR` | output folder (default `<name>_redux` beside each input) |
| `--name NAME` | output model name (one input only) |
| `--textures DIR`, `--zfs FILE`, `--game15 DIR\|auto` | where `.geo`/`.map` files are looked for |
| `--palette ACT\|name` | palette for 8-bit maps (default `moon.act`) |
| `--bands 0,4` | VDF/SDF bands to port |
| `--material-names model\|texture`, `--material-suffix TEXT` | material naming; `<model>TEXT.material` |
| `--normals smooth\|flat\|stored`, `--format png\|dds\|none` | normals; texture format |
| `--flat-colours` | every face coloured from its GEO face colour (a palette texture), no `.map` |
| `--no-headlights` | no `HLGT` bones |
| `--person`, `--animations`, `--cockpit`, `--turret`, `--scope` `auto\|yes\|no` | force the person, skeletal animation, separate cockpit, turret and sniper scope choices |
| `--scope-type auto\|fixed\|attached\|geometry` | fixed: a square on screen shown while crouched (1.5 style); attached: a square on the gun; geometry: faces textured `--scope-texture` (default `__scope`) |
| `--scope-nation`, `--scope-screen X Y Z SCALE BEHIND` | fixed scope placement |
| `--scope-gun PART`, `--scope-transform 12 floats` | attached scope placement |
| `--no-pov-rotations` | the eyepoint keeps its rotation in the four run animations |
| `--bounds-scale X Y Z` | scale the mesh bounds about their centre |
| `--skip-existing`, `--dry-run` | skip a model whose `.mesh` exists; build and report only |

Parts and textures are looked up case-insensitively beside the model, then in
`--textures` folders, then in ZFS archives (`--zfs`, or every archive of a 1.5
install with `--game15`, patch archive first and the 16-bit texture set before
the 8-bit ones).

### Compared with BZRModelPorter

DivisionByZero's BZRModelPorter (`port_models.py`, the basis of the Blender
add-on) is covered option for option: `--name`, `--suffix`
(`--material-suffix`), `--headlights` (on by default here), `--person`,
`--cockpit`, `--skeletalanims` (`--animations`), `--scope`, `--scopetype`,
`--scopenation`, `--scopescreen`, `--scopegun`, `--scopetransform`,
`--scopetexture`, `--nopovrots`, `--flatcolors` (both spellings accepted),
`--boundsmult` (`--bounds-scale`), `--act` (`--palette`), `--onlyonce`
(`--skip-existing`), `--nowrite` (`--dry-run`), `--dest` (`--out`) and its
`config.cfg` (palette plus search folders: `@FILE`, `--textures`, `--game15`).
Its `headlights.bat`, `pilot_scope.bat` and `pilot_aim_noscope.bat` are
option sets for `port_legacy_drop.args`. Its `--turret` flag was parsed but
unused ("TODO: Turret fix"); here it gives turrets their `_c` cockpit mesh.
Beyond it: ZFS lookup, stock-style Redux vertex layout and materials, PNG
textures, band choice, normals choice, and `seqNN` animations for non-person
models as Redux's own conversions carry.

## Conventions, and how they were established

All of these were measured on the stock Redux meshes that are straight
conversions of their 1.5 models: vertex and triangle counts equal the GEO
totals for hbptow, hbchar, hbcerb, obhavc, obheph, obstp1, hvsrb, hvrckt,
grccmi and about 30 more (the check kept in the repo is
`tests/meshes/test_legacy_port.py::StockComparisonTests`). Remastered units
(avtank, svtank, abwpow...) are new high-poly models and only their structure
is comparable.

* **Bones.** One per ported part, named exactly as the part (case kept),
  parented as in the VDF/SDF; parts under `WORLD` are root bones. Position and
  orientation are the part's local transform. No extra model-named root bone
  (the straight conversions have none; some remasters add one).
* **Part matrix.** The 12 floats are the right, up and front axes then the
  position, in the parent's space; model space is `parent_abs @ local`.
* **Handedness.** Ogre = legacy with X negated. Positions `(-x, y, z)`; bone
  orientation is the mirrored rotation `M R M`, `M = diag(-1, 1, 1)`, i.e.
  quaternion `(x, -y, -z, w)`. Checked against obhavc (45 degree and 180
  degree part rotations) and hbchar: bone positions and orientations match to
  1e-4.
* **Faces.** GEO polygons are fan-triangulated in stored order; the mirror
  makes that Ogre's counter-clockwise front face. Stock GEO plane normals
  point inward, so the Ogre face normal is `-(M n)`. Every straight-converted
  stock triangle matched ours with the same winding (none reversed).
* **Vertices.** One Ogre vertex per GEO vertex and UV per part, weighted 1.0
  to the part's bone, in bind (model) space. Counts equal Redux's.
* **UVs.** Copied unchanged. `.map` rows are top first like DDS; the
  converted stock DDS textures correlate with the legacy maps unflipped
  (0.65-0.85) and not flipped (about 0). Redux's own files store V + 1, which
  is the same texel with wrap addressing.
* **Normals.** GEO vertex normals are not what Redux used. The default
  (`smooth`) averages the face normals meeting at a position within a part,
  the closest of the variants tried: mean cosine to Redux's normals 0.82-0.99
  per model. `flat` and `stored` (the GEO's own normals, mirrored) are options.
* **Vertex format.** As stock: buffer 0 float3 position + float3 normal,
  buffer 1 ARGB colour + float2 UV. Colour is white, like the straight
  conversions (`face_colours` would use the GEO face colour instead).
* **Bands.** VDF bands are `lod * 4 + damage`. Band 0 is the model, band 4
  the cockpit, band 8 the low-detail model; stock files use no others. VDFs
  port bands 0 and 4 (Redux's avtank/svtank carry the cockpit parts as bones
  and a cockpit submesh; the low-detail parts are absent), SDFs band 0.
  Cockpit geometry gets `BZBaseCockpit` materials (`<material>_cockpit`).
* **Cockpit parents.** The game draws a cockpit part with the matrix of the
  model part in the same slot, so each one is a child of that part at
  identity (BZRModelPorter does the same; Redux's avartl has its four cockpit
  guns within 0.03 of the model guns, and avtank's `AGR21bga` lands 0.11 from
  Redux's). A cockpit part with no model part in its slot and a parent its
  band lacks hangs from the band's root part, with a warning.
* **Non-drawn parts.** Headlight masks (38), eyepoint (40), hardpoints
  (70-74) and emitters (75-77) become bones with no geometry. Each headlight
  mask also gets an `HLGT<n>_ffffff` bone at its transform, as in the
  remastered stock skeletons (`--no-headlights` to skip).
* **Materials.** Stock conversions name the material after the GEO texture
  (`HBFACT00`, `Hvsav00`, case kept) and set `DiffuseMap`, `NormalMap
  flat_N.dds`, `SpecularMap`/`EmissiveMap` (often `black.dds`). The porter
  does the same but prefixes the model name by default (`<model>_<texture>`)
  because Ogre material names are global: a ported `avtank00` would replace
  the stock tank's material. `--material-names texture` gives the stock
  naming. `flat_N.dds` and `black.dds` ship with Redux.
* **Textures.** Indexed maps carry no palette. Stock unit textures use the
  object range all stock world palettes share (decoding with any world ACT
  equals the 16-bit copy in `bzhw16q.zfs` to within 3/255 on average); the
  default is `moon.act`. 16/32-bit maps need none. PNG is written by default
  (Redux loads PNG; stock `abtowe.material` uses one); `--format dds` writes
  uncompressed A8R8G8B8 DDS without mipmaps.

## Animation, cockpits, scope

* **ANIM chunk.** Read into sequences (index, start frame, signed length,
  loop, frames per second) and per-part rotation/position/scale keys on one
  shared timeline; a negative length plays backwards. Keys are the part's
  full parent-space transform, the rotation stored as the conjugate
  quaternion (see `battlezone/meshes/legacy.py`).
* **Non-person models** get one empty `seqNN` animation per sequence index,
  exactly what Redux's straight conversions carry (hbptow, obhavc: same
  names, lengths and zero tracks); the game moves the bones from the VDF/SDF.
* **Persons** (ODF class `person`, else a `?s????` VDF name like aspilo) get
  Redux's named animations keyed from their sequences, with
  BZRModelPorter's mapping and timing: `stand2Kneel` 0, `kneel2stand` 1,
  `idle` 2, `fireRecoilSniper` 3 (the crouched pose), `runForward`/`Backward`/
  `Left`/`Right` 4-7, `death1` 8; `idleParachute`, `landParachute` and
  `jump` are Redux additions with no 1.5 sequence and are written empty.
  Keys are offsets from the bind pose; the eyepoint's pitch is flipped
  (BZRModelPorter's in-game fix); hardpoints sit on the gun's origin.
* **Separate cockpit mesh.** When the cockpit or eyepoint animates (pilots,
  walkers) or the model is a turret/howitzer, band 4 goes to its own mesh
  and skeleton named as Redux asks for it: `_fp` for pilots, `_c` for
  `*vartl`, `*vturr`, `*vwalk`, else `_cockpit`. Each cockpit part rides the
  model part of its slot; the eyepoint rides the cockpit. Otherwise the
  cockpit is a `BZBaseCockpit` submesh of the one mesh.
* **Sniper scope** (persons, `--scope`): `fixed` puts a square on the
  camera, hidden behind it and brought in front by the crouched pose, placed
  for the nation (American or Soviet, `--scope-screen` to override);
  `attached` hangs a square from a gun part; `geometry` gives faces textured
  `__scope` the stock `scope` material. `auto` is geometry when such faces
  exist, else fixed.
* **Headlights.** Each headlight-mask part also gets an `HLGT<n>_ffffff`
  bone (BZRModelPorter made them only with `--headlights`, named `_ff0000`).

## Verification

* The mesh writer rewrites 217 of Redux's 240 stock meshes byte for byte from
  what `read_mesh` decodes; 21 of the other 23 differ only in the
  submesh-name table, the last 2 in chunks the reader skips. The skeleton reader/writer
  round-trips all 241 stock skeletons byte for byte.
* A ported avtank loads in OgreXMLConverter 1.11.6 (the version that wrote
  Redux's files) and converts to XML like a stock mesh.
* Against Redux's straight conversions (hbptow, obhavc; kept in
  `StockComparisonTests`): vertex and triangle counts equal, bounds to 0.01,
  bone positions to 1e-3 and orientations to a dot of 0.9999, `seqNN`
  animations identical.
* Against Redux's remastered units, structure only: the ported
  aspilo/bspilo/sspilo write `<model>_fp` and avwalk/avartl/avturr write
  `<model>_c`, names Redux ships; every pilot animation name we write is one
  of Redux's aspilo animations, and 8 of 12 lengths agree within 0.04 s (the
  run cycles are 0.63/0.9 s from BZRModelPorter, Redux's remasters use
  0.8-0.83 s); avartl's cockpit guns sit on the model guns of their slots,
  as in Redux.
* Against BZRModelPorter's own output for aspilo, sspilo, svturr, avtank and
  sbcomm: identical triangle counts, bounds and position sets (ours has
  fewer vertices: equal vertices are shared), same bones with positions
  equal and orientations within 1-|dot| 4e-8, same animation names, lengths
  and track counts; 2032 aspilo and 1815 sspilo keys agree to 3e-8 s in
  time, 4e-5 in 1-|dot| of rotation and 2e-7 in translation. The only
  difference is that its one-frame `fireRecoilSniper` tracks carry the same
  key twice.
* `tests/meshes/test_legacy_port.py`: synthetic VDF/SDF/GEO/MAP/ODF files
  cover the transforms, winding, bands, materials, animations, cockpit,
  scope, the inputs and the CLI; the stock comparisons run when Redux is
  installed. `tests/app/test_legacy_model_port_page.py` covers the page.

## Not done / not verified

* **Not tried in game.** Nothing here has been loaded by Redux itself yet.
* **LOD and damage.** Low-detail (band 8) and damage-state parts are not
  ported by default (`--bands` can add them, into the same mesh); Redux's
  stock meshes have none either. BZRModelPorter ported the same two bands.
* **Person animations Redux adds** (`idleParachute`, `landParachute`,
  `jump`) have no 1.5 source and are empty.
* **Scaled part matrices** are written as bone scale and warned about;
  untested in game.
* **Hardpoint orientation.** Bones take the legacy matrix; some remastered
  stock skeletons (svtank) rotate hardpoint bones -90 degrees about X instead.
  The straight conversions give no evidence either way.
* **Transparency.** MAP alpha is kept in the texture, but the material does not
  enable blending or alpha rejection; GEO shade/texture/translucency flags are
  ignored.
* No normal, specular or emissive maps are generated.
