# HD terrain authoring bundles

Use **World & Terrain → HD Terrain Tiles** to package independent diffuse,
normal, specular and emissive tile images for OpenShim's native HD terrain
arrays. The CLI exposes the same builder as `bztoolbox terrain hd-tiles`.
This is a new workflow alongside the existing atlas tools.

You need an OpenShim build supporting `bzr-openshim-terrain-hd-v2`
([implementation PR](https://github.com/GrizzlyOne95/Battlezone98Redux_Shim/pull/520)),
effective **DX11 Enhanced**, authored images and matching map configuration.
EXU is not required. The Toolbox exports files; it does not install, launch or
change game settings. Keep the map's ordinary atlas and material for fallback
when Enhanced or HD tiles are off.

## Start from independent images

1. Keep the map's normal atlas CSV. Only its rectangle metadata is read;
   no pixels are extracted from an atlas. Repeated aliases at different
   rectangles are retained. Native tile IDs are resolved from rectangles,
   rather than assumed to be CSV row numbers.
2. Put source images in a folder using the MAP alias stem and channel suffix:
   `ma00sa0_d.png`, `ma00sa0_n.png`, `ma00sa0_s.png`, `ma00sa0_e.png`.
   PNG, TGA, TIFF, BMP and supported DDS inputs work. Use one file format per
   basename. Every alias used by the CSV needs its own source in every enabled
   channel. Different aliases may reference the same image in a saved recipe.
3. Choose the exact Ogre terrain material and its **original** diffuse atlas
   resource name. These are runtime identity guards, not image inputs.
   Enter the original normal/specular/emissive atlas names only for channels
   you want to replace. Blank channels retain the material's existing inputs.
   The material must already bind the corresponding channel; this tool does
   not invent lighting inputs for a diffuse-only material.
4. Set the default MAP alias explicitly. It supplies the nameless CSV row and
   fallback slice. Start with 1024px and a unique mod-specific resource prefix.
5. Choose a **new** output folder and build. Existing output folders are
   protected. Save an authoring recipe to reuse your inputs and settings.

Sources must be square and at least the requested export resolution. Export
sizes are powers of two, up to 4096px. The builder downsamples larger masters
but refuses to upscale smaller ones. There are at most 256 physical slices
and 256 distinct layout rectangles per material. Each bundle targets one
material; OpenShim's runtime manifest can contain multiple material bindings.

Example (PowerShell, from a Toolbox install/source environment):

```powershell
bztoolbox terrain hd-tiles init ./mars-art `
  --layout ./MY_MARS.csv --material MY_MARS `
  --diffuse-resource mars_atlas_d.dds `
  --normal-resource mars_atlas_n.dds `
  --specular-resource mars_atlas_s.dds `
  --default-alias MA00SA0.MAP --prefix mymod_mars `
  --tile-size 1024 --out ./mars-authoring.json

bztoolbox terrain hd-tiles build ./mars-authoring.json --out ./mars-bundle
bztoolbox terrain hd-tiles check ./mars-bundle --json
```

In a source checkout, `python -m bztoolbox` can replace `bztoolbox`.
Each subcommand accepts `--json`; invalid input returns exit code 2 with an
`error` object. `build --tile-size` and `build --prefix` override the recipe.

## Import the existing CR tile export

Select the ready source-tile folder in the page's **Source images** picker.
The builder recognizes its `source_tiles.json`, `native_layout.csv` and
`cr_mars_hd.json`. It reads those data files and their independent DDS tiles;
it does not execute CR scripts or depend on a CR checkout.

```powershell
bztoolbox terrain hd-tiles build ./MarsHdSourceExample `
  --prefix mymod_mars --out ./mars-authoring-bundle
```

This imports the `cr-mars-hd-source-tiles-v1` export generated from the HD
source recipe behind the Mars atlas. It does **not** split the generated atlas
back into tiles. Suitable existing DDS resources are copied byte for byte.
The original source-recipe generation and game profiling harness remain in CR.

## Bundle contents and customization

| Path | Purpose |
| --- | --- |
| `resources/*.dds` | Runtime ordinary 2D textures; OpenShim builds the arrays |
| `terrain_hd_tiles.json` | Runtime v2 manifest, source guards, channels and rectangle mapping |
| `sources/*` | Copies of your editable masters; originals remain unchanged |
| `layout.csv` | Original atlas layout metadata |
| `authoring.json` | Portable recipe referencing the copied sources |
| `bundle_report.json` | Resource hashes, conversion counts and GPU storage estimate |
| `README.txt` | Installation, fallback and rebuild instructions |

Move the bundle wherever you like, edit the copied masters, then rebuild into
a new folder. Relative paths keep the bundle independent of the original
machine. Art is not bundled with the Toolbox; respect your source licenses.
Only the runtime DDS and manifest need shipping with the mod.

The recipe is ordinary JSON. `resources` enables channels and names their
original atlas guards; `tiles` maps uppercase aliases to source image paths:

```json
{
  "schema": "bzr-terrain-hd-authoring-v1",
  "material": "MY_MARS",
  "layout": "layout.csv",
  "defaultAlias": "MA00SA0.MAP",
  "tileSize": 1024,
  "prefix": "mymod_mars",
  "normalSpace": "directx",
  "resources": {"D": "mars_atlas_d.dds", "N": "mars_atlas_n.dds"},
  "tiles": {
    "MA00SA0.MAP": {"D": "sources/rock_d.png", "N": "sources/rock_n.png"}
  }
}
```

The example needs additional `tiles` entries if its CSV names other aliases.
Exact paths can be customized in the recipe rather than renaming source art.

## Channels and mipmaps

- **Diffuse, specular, emissive:** opaque RGB, exported as BC1 with a complete
  mip chain. Transparency or packed alpha data must be repacked explicitly
  before conversion; it is not silently discarded. No normal or specular
  maps are synthesized from diffuse art.
- **Normals:** linear tangent-space RGB XYZ. `directx` keeps the green channel;
  `opengl` flips green on export. Choose the convention of your actual source
  art. Packed BC5/AG and compressed DDS normals are rejected; unpack them to
  RGB first. Output is lossless RGB24 DDS; newly generated mip levels filter
  signed vectors and renormalize them. Matching authored mip levels are kept.
- Suitable full-chain DDS at the export resolution are preserved byte for
  byte. Other supported inputs are converted, retaining matching authored
  mip levels and generating the missing tail down to 1×1. Classic BC1/BC3 and
  tightly packed BGR24/BGRA32 DDS are supported; DX10 arrays, cubemaps, volume
  textures, other masks and malformed/truncated payloads are rejected.

Source normal orientation still needs a visual check under the map's lighting.
This tool cannot infer an arbitrary texture library's convention from pixels.

## Install and fall back

Copy the **contents** of `resources/` into your mod's enabled Ogre resource
directory and the manifest into your mod folder. Preserve its ordinary atlas,
material, CSV, TRN and MAT. The TRN's `[Atlases] MaterialName` must select the
guarded material and its corresponding CSV. The original normal/specular/etc.
resource names must match the effective material's bindings.

Configure `openshim.ini`:

```ini
[Terrain]
TerrainHdEnabled=1
TerrainHdManifest=addon\YOUR_MOD\terrain_hd_tiles.json
```

Relative manifest paths resolve from the game executable directory. An absolute
path also works for local testing. Enable **HD Terrain Tiles** and effective
**DX11 Enhanced** in OpenShim settings. Use native terrain, not the experimental
proxy renderer. Without the authored pack, matching guards and configuration,
OpenShim retains ordinary atlas rendering. Turning HD tiles or Enhanced off
also retains the ordinary atlas path.

## Memory and validation

`check` verifies recipe/layout agreement, every enabled slice, exact resource
guards, canonical dimensions/formats, full mip chains and actual payload sizes.
The export report hashes all runtime DDS. Builds stage into a fresh temporary
folder and publish the completed bundle only after validation; a failure or
cancellation removes that invocation's temporary output.

`estimatedGpuArrayBytes` estimates the additional array payload: BC1 colour
channels and RGBA8 normal arrays. It excludes ordinary fallback resources,
driver allocation, semantic vertex buffers and other engine state.
**It is not a 32-bit process RAM estimate.** `processRamEstimate` stays null.
Authoring processes one tile/channel at a time and limits BC1 encoder batches.

For context, the CR Mars prototype measured approximately 353 MiB settled
private bytes with stock atlases versus 443 MiB with 1K independent tiles and
442 MiB with 2K tiles. Launch peaks were approximately 430/612/883 MiB.
Those are one map and OpenShim build, not a general budget. Begin with 1K,
then measure game private bytes, peak private bytes and largest free virtual
address range for your map. Include repeated Enhanced/Redux profile switches
to catch retained allocations. CR's game profiling harness remains the place
for that live measurement; this Toolbox command does not launch the game.
