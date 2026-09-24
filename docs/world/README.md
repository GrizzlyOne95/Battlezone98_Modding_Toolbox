<p align="center">
  <img src="branding/repo_icon.svg" width="180" alt="Battlezone World Builder icon">
</p>

# Battlezone World Builder
A powerful world building tool that auto creates custom atlases, material files, TRN entries, cubemaps, HG2/HGT conversion, and more.

## BZ2/BZCC Terrain Port (in progress)

The dedicated **BZ2 → BZ1 Map Port** tab can inspect TERR v3–v5 files. Its
resolved bundle action takes the companion TRN and texture assets, then writes
Redux HG2, MAT, atlas, TRN, and an object-offset report. Target MinX/MinZ
default to `0,0` so centred BZCC maps can be placed in the Redux world. The
bundle still needs in-game visual validation and separate BZN/mission porting.
See [the port status and format notes](docs/BZ2_TO_BZR_PORT.md).

## Release Builds

Download the latest platform archive from the GitHub Releases page. Public application names are intentionally stable and versionless:

- Windows GUI: `BZWorldBuilder.exe`
- Windows CLI: `BZWorldBuilderCLI.exe`
- Linux GUI: `BZWorldBuilder`
- macOS app: `BZWorldBuilder.app`

Release archives carry the version and platform, for example:

- `Battlezone98Redux_WorldBuilder-v1.0.16-windows.zip`
- `Battlezone98Redux_WorldBuilder-v1.0.16-windows-cli.zip`
- `Battlezone98Redux_WorldBuilder-v1.0.16-linux.tar.gz`
- `Battlezone98Redux_WorldBuilder-v1.0.16-macos.zip`

Official Windows builds use the shared **Battlezone Modding Tools** product identity. The GUI executable uses:

```text
FileDescription: Battlezone World Builder
ProductName: Battlezone Modding Tools
CompanyName: GrizzlyOne95
OriginalFilename: BZWorldBuilder.exe
```

The separate CLI uses `FileDescription: Battlezone World Builder CLI` and `OriginalFilename: BZWorldBuilderCLI.exe`. `FileVersion` and `ProductVersion` are derived from the release tag.

## Stock Map Creator
Auto generates TRN, HG2, and MAT files based on default worlds without needing to use MakeTRN. Implements the useful MakeTRN 2.1.2 controls recovered from the original executable, including independent width/depth, EmptyElevation, `[LayerN]` parameter files, and legacy runtime-random MAT variants. WorldBuilder also keeps its selectable Redux worlds, time, audio, and lighting controls.

The generated terrain uses canonical Redux 256x256 HG2 samples per zone and the recovered MakeTRN 64x64 MAT entries per zone. Blank builds now emit the complete TRN + HG2 + MAT set in one operation.

The original MakeTRN also has a working Interstate '76 `.MSN` + `.TER` import mode. That format is now supported by the open-source converter:

```powershell
python msn2terrain.py mission.MSN --output Export --name I76MAP
```

The converter recovers `TDEF/ZMAP`, crops the occupied I76 zone rectangle, imports 256x256 TER blocks, preserves the source map origin in TRN `MinX/MinZ`, and writes TRN + HG2 + MAT through the same compatibility core. It also accepts `/p=layers.ini` and `/e=N` aliases.

See [`docs/MAKETRN_REVERSE_ENGINEERING.md`](docs/MAKETRN_REVERSE_ENGINEERING.md) for the executable-level findings and parity matrix.

<img width="1402" height="982" alt="python_el54uNiI0s" src="https://github.com/user-attachments/assets/057925a0-8737-4771-8830-6548a5c439d9" />


## Custom Atlas Creator
Creating a custom atlas with manually painted transitions can be very time consuming. This tool lets you point to a folder of solid textures, and it will arrange them on a grid, generate cap/diagonal transitions with many adjustment paramters, and exports with all the correct entries for TRN, CSV, Material, etc. 

<img width="1402" height="982" alt="python_0sHojush7m" src="https://github.com/user-attachments/assets/e8114ca7-ae38-49b0-99dc-30fe433b2714" />

## Legacy Atlas Creator
Ports custom worlds from 1.5 format into Redux. Auto converts the .MAP files into an atlas, and exports the proper TRN, CSV, Material.

The Legacy Atlas page also includes an **authored HGT -> Redux HG2** terrain upgrader. Select the original `.hgt`; WorldBuilder reads the companion `.trn` dimensions, preserves the low 12-bit legacy height samples and zone ordering, performs the recovered 128 -> 256 samples-per-zone triangle interpolation, and writes a canonical Redux `.hg2`. It deliberately skips the post-upgrade 3x3 smoothing pass, matching the terrain-upgrade behavior requested by Redux's `-nohgtsmoothing` launch option. No Gaussian filtering or height renormalization is applied.

<img width="1402" height="982" alt="python_TDaQIDixe7" src="https://github.com/user-attachments/assets/0ad9a060-8804-4e1e-b81d-e146e3d4d908" />

## Heightmap Converter
Ports HGT or HG2 to PNG, or PNG back to HGT/HG2. Experimental World Machine implementation. 

The Heightmap Converter also includes a **Terrain OBJ Round-Trip** workflow inspired by the legacy TerraZone utility. It exports a Redux HG2 as a regular Wavefront OBJ grid, previews imported OBJ heightfields, and writes them back to HG2 without requiring Blender or `bpy` inside WorldBuilder. The OBJ includes WorldBuilder metadata for zone dimensions and sample spacing. On import, the X/Z grid is validated and used to reconstruct the heightfield, so vertex order may change; sculpting should modify Y/height while leaving the X/Z grid intact. OBJ files without WorldBuilder metadata can still be converted when their grid dimensions map cleanly to Redux's 256 samples per zone.

This makes a practical workflow possible with any OBJ-capable modeler:

```text
HG2 -> OBJ -> sculpt terrain in Blender / 3ds Max / Maya / etc. -> OBJ -> HG2
```

<img width="1402" height="982" alt="python_KBNkOhWxwZ" src="https://github.com/user-attachments/assets/5acc659f-bc2e-4d3e-87c5-1edeb8a86576" />


## Skybox Tools
You just need a single HDRI/Equirectangular Projected Skybox image and this will convert it into cubemap faces, and generate all the material/DDS/TRN entries you need to make some awesome BZR skies.

<img width="1402" height="982" alt="python_Upj2ePSle0" src="https://github.com/user-attachments/assets/ad05eb5a-20c2-4604-9779-5bb8057dd7cc" />


## Mission Visualizer
Experimental mission layout summarizer that loads the heightmap and BZN.

<img width="1402" height="982" alt="python_RPojjiNh4q" src="https://github.com/user-attachments/assets/4628aece-bd05-43c3-ae00-51fc11ad95cc" />


## Auto-Painter
Lets you define painting rules for custom painting, and manually writes the MAT file. Full replacement for MakeTRN /p.

The painter core is reverse-engineered from the historical MakeTRN executable and shared by both the GUI and the open-source `bzpaint.py` command-line frontend. It preserves MakeTRN's layer ordering, elevation/slope sampling, cap/diagonal synthesis, MAT layout, and MSVCR120 variant logic while adding deterministic output and diagnostics.

Legacy-style usage:

```powershell
python bzpaint.py mapname.trn /p=moon.ini
```

`bzpaint.py` automatically loads `mapname.hg2` and writes `mapname.mat`. If `/p=` is omitted it uses the actual built-in MakeTRN defaults recovered from the executable.

Modern options can be mixed with the legacy syntax:

```powershell
python bzpaint.py mapname.trn /p=moon.ini --seed 1 --dry-run
python bzpaint.py mapname.trn --params moon.ini --output custom.mat --json
python bzpaint.py mapname.trn /p=moon.ini /e=0
```

Useful options:

- `--seed N` selects a deterministic MSVCR120-compatible texture-variant seed. The historical executable used `srand(clock())`; the Stock Map Creator compatibility path follows that runtime-random behavior by default, while deterministic seed `1` remains available for reproducible testing/builds.
- `--dry-run` performs the complete paint and transition validation without writing a MAT.
- `--json` prints machine-readable statistics and diagnostics.
- `--output FILE` chooses a MAT path instead of replacing the TRN suffix with `.mat`.
- `/e=N` or `--empty-elevation N` controls the legacy out-of-bounds EmptyElevation value.

See [`docs/MAT_FORMAT_VALIDATION.md`](docs/MAT_FORMAT_VALIDATION.md) for the recovered MAT format and painter behavior.

<img width="1402" height="982" alt="python_1O4aYb26T2" src="https://github.com/user-attachments/assets/d91b2377-129a-46c3-9942-a8695927f0f4" />
