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

Use it from:

* **Assets > Legacy Model Port** in the app;
* `bztoolbox meshes port-legacy MODEL.vdf|.sdf [--out DIR] [--textures DIR]
  [--game15 DIR] [--zfs FILE] [--palette ACT|name] [--bands 0,4]
  [--material-names model|texture] [--normals smooth|flat|stored]
  [--format png|dds|none]`;
* Python: `port_legacy_model(path, out_dir, search=..., archives=..., palette=...)`,
  or `build_port()` (pure, nothing written) then `write_port()`.

Parts and textures are looked up case-insensitively beside the model, then in
`--textures` folders, then in ZFS archives (`--zfs`, or every archive of a 1.5
install with `--game15`, patch archive first and the 16-bit texture set before
the 8-bit ones).

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
* **Cockpit parents.** A cockpit part whose parent is not in its band
  (avtank's `AGR21bga` under the absent `AGR21TUR`) hangs from the band's
  root part; that lands within 0.07 of where Redux's avtank has `AGR21bga`.
  This is reported as a warning.
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

## Verification

* The mesh writer rewrites 217 of Redux's 240 stock meshes byte for byte from
  what `read_mesh` decodes; 21 of the other 23 differ only in the
  submesh-name table, the last 2 in chunks the reader skips. The skeleton reader/writer
  round-trips all 241 stock skeletons byte for byte.
* A ported avtank loads in OgreXMLConverter 1.11.6 (the version that wrote
  Redux's files) and converts to XML like a stock mesh.
* `tests/meshes/test_legacy_port.py`: synthetic VDF/SDF/GEO/MAP files cover
  the transforms, winding, bands, materials and the CLI; the stock comparison
  runs when Redux is installed.

## Not done / not verified

* **Not tried in game.** Nothing here has been loaded by Redux itself yet.
* **Animation.** ANIM chunks are not converted to skeleton animations. Stock
  straight conversions carry empty `seq00`/`seq01` animations; ours carry
  none. Whether Redux needs either is unverified; the game is expected to
  drive the named bones from the VDF/SDF ANIM data.
* **LOD and damage.** Low-detail (band 8) and damage-state parts are not
  ported; Redux's stock meshes have none either.
* **Scaled part matrices** are written as bone scale and warned about;
  untested in game.
* **Hardpoint orientation.** Bones take the legacy matrix; some remastered
  stock skeletons (svtank) rotate hardpoint bones -90 degrees about X instead.
  The straight conversions give no evidence either way.
* **Transparency.** MAP alpha is kept in the texture, but the material does not
  enable blending or alpha rejection; GEO shade/texture/translucency flags are
  ignored.
* No normal, specular or emissive maps are generated.
