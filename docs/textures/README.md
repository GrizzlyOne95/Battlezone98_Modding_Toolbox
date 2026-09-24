# Battlezone Texture Manager

A comprehensive utility suite designed for **Battlezone 98 Redux** modders. This tool streamlines the asset pipeline by providing specialized converters and editors for the game's unique file formats.

## Features

### ACT Palette Editor
The ACT Editor is purpose-built for the Battlezone `.ACT` format (256-color indexed palette). Unlike generic editors, this includes a **Quick Jump** system for critical engine-reserved indices.

* **Reserved Index Awareness**: Instant access and labeling for key indices:
    * **Index 223**: Skybox color and Sniperscope lens tint.
    * **Index 209**: Global Fog color (horizon transition).
    * **Indices 0-95 / 224-255**: Primary and Secondary Object ranges. These seem to be ignored by Redux.
    * **Indices 96-222**: Planet-specific terrain smoothing range. These seem to be ignored by Redux.
* **Visual Feedback**: Selected colors are highlighted in a 16x16 grid with real-time RGB and Hex editing.
* **Sync Logic**: Changes to the palette automatically update the preview in the MAP Converter tab.

<img width="1152" height="932" alt="image" src="https://github.com/user-attachments/assets/f5c0f11f-5506-4652-b143-fe2e90e712c9" />

### Texture Manager (DDS/TGA/PNG)
An advanced processor for standard game textures, optimized for VRAM management and engine compatibility.

* **Format Conversion**: Custom "Convert From" and "Convert To" logic supporting PNG, TGA, and DDS with batch capabilities.
* **Smart Compression**: Support for DXT1 (Opaque) and DXT5 (Interpolated Alpha), or a setting for no compression.
* **Alpha Auto-Detection**: Scans images during batch processing to automatically choose the most efficient compression codec.
* **Power of 2 Rescaling**: Conditional downscaling logic (512 to 4096) to ensure textures fit within performance budgets.
* **Mipmap Generation**: Optional mipmap creation to prevent distant texture shimmering.
* **Automatic Normal/Specular/Emissive Generation**: Optional additional texture generation with flip normals option, and sliders for thresholds.
* **Overwrite Existing Option**
* **Multithreading Support**: Main window won't freeze during long batch processes.
* **Progress Bar**: Shows progress for large batches.

<img width="1152" height="932" alt="image" src="https://github.com/user-attachments/assets/a6776632-7358-432d-9f2d-a34df1ed48c1" />

### MAP Texture Serializer
Handles the conversion of `.MAP` files, which are the specialized textures used by the legacy Battlezone game system.

* **Bidirectional Conversion**: Convert `.MAP` to `.PNG` for editing and back to `.MAP` for the game.
* **Palette Serialization**: Correctly applies your active `.ACT` palette to indexed MAP files during export. Has built-in palette data so you don't need an ACT file.
* **Correct MAP decoding**: The integrated compatibility codec reads all five MAP pixel formats rather than assuming every non-indexed MAP is 32-bit BGRA.
* **Redux Support**: The simple workflow packs imported images as ARGB8888 for high-definition assets.
* **Advanced MakeMAP dialog**: Full MakeMAP-compatible controls are available directly from the MAP tab.

<img width="1152" height="932" alt="image" src="https://github.com/user-attachments/assets/4567e542-3944-4e12-8581-ff79bdd0d517" />

### MakeMAP Compatibility

The application integrates a clean-room compatibility implementation of the original **Battlezone MakeMAP (Mar 27 2017)**. The core is `src/makemap_compat.py`; `src/tex_man_entry.py` routes the graphical MAP tab through that codec and adds an **Advanced MakeMAP** dialog. Release builds also package the standalone `BZMakeMAPCompat` command-line utility for scripting and batch pipelines.

The compatibility layer covers the complete MakeMAP option surface found in the reference executable:

* **All MAP formats**: type 0 indexed, type 1 A4R4G4B4, type 2 R5G6B5, type 3 A8R8G8B8, and type 4 X8R8G8B8.
* **BMP/TGA output** with target-format quantization.
* **Alpha tools**: `-recoveralpha`, `-chromakey`, `-transindex`, and `-undopma`.
* **Color remapping and grading**: `-remap`, `-colorize`, `-desat`, per-channel `-pow*`, `-mul*`, and `-add*` controls.
* **Orientation and quantization**: `-flipx`, `-flipy`, and MakeMAP-style `-diff` error diffusion.
* **Batch behavior**: multiple paths, wildcard patterns, recursive directories, and the original `/option` spelling.

Example CLI usage:

```powershell
BZMakeMAPCompat.exe -8888 texture.png
BZMakeMAPCompat.exe -pal moon.act -transindex 0 -diff 100 terrain.png
BZMakeMAPCompat.exe -4444 -undopma effect.tga
```

See [`docs/MAKEMAP_COMPATIBILITY.md`](docs/MAKEMAP_COMPATIBILITY.md) for the full parity matrix, reverse-engineered format details, transform order, and validation notes.

### LGT Light Converter
A dedicated tool for converting `.LGT` lightmap files into editable `.PNG` images.

* **LGT to PNG**: Decodes game lightmaps into editable grayscale images.
* **PNG to LGT**: Repacks the PNG to an LGT file.
* **Batch Workflow**: Process entire mission folders of lightmaps simultaneously.

<img width="1152" height="932" alt="image" src="https://github.com/user-attachments/assets/8cf4b58a-7c69-4609-8123-ef11d783878e" />

### DXTBZ2 Texture Converter
A tool to convert proprietary BZ2 encoded textures to PNG or DDS.

* **DXTBZ2 to DDS**
* **DXTBZ2 to PNG**
* **Single or Batch Processing**
* **Thanks to VEARIE for the DXTBZ2 direct Python code!**

<img width="1152" height="932" alt="image" src="https://github.com/user-attachments/assets/fcf80b0f-364f-4cb3-830c-717cd568f0ca" />

### DDS Compression

The Texture Manager writes DDS in-process rather than shelling out to
`texconv.exe`. That binary used to be a required download placed next to the exe;
it is no longer used anywhere, and every DDS the tool writes -- the texture
processor, the generated emissive/specular/normal maps, and the DXTBZ2
converter -- goes through `src/bcpack.py` instead.

What that changes:

* **No external binary, no temp file, no subprocess.** Pure Python on the
  numpy/Pillow dependencies already declared.
* **The author's mip chain survives.** Pillow exposes mip 0 of a DDS and nothing
  else (no `n_frames`; `seek(1)` raises EOFError), so the old path had to
  regenerate the whole chain with a filter nobody chose. Source levels are now
  read and transcoded in place, and a chain is generated only for files that
  shipped without one, or when the image was rescaled and the old levels no
  longer match it.
* **Pillow's own DDS writer was never an option** for the other half: it emits an
  uncompressed surface with the FourCC zeroed and mipCount 0.

### Bulk DDS Recompressor

The same encoder drives a whole-mod pass, in the GUI under **Bulk DDS Recompress
(in place)** on the Texture tab, or from the command line:

```
python src/recompress.py "<mod folder>" --backup "<somewhere safe>" [--dry-run]
```

This is the one that moves the needle on a big mod: ISDF Chronicles shipped
**7.8 GB of DDS, of which 6.4 GB was uncompressed**, and this takes the folder to
roughly 2.8 GB without changing a single resolution. It rewrites in place, so a
backup folder is required and must be outside the tree being rewritten.

#### What it decides, and why

**DXT1 vs DXT5** comes from whether mip 0 has alpha the renderer could act on.
The common "RGBA32 whose alpha is 255 everywhere" case is very common — 247 of
429 in that mod — and costs 0.5 bpp instead of 1.0 with nothing lost, because
there is nothing in the channel to lose. The test has a tolerance: those mission
loading screens are alpha 255 everywhere except 2432 texels at exactly 254, out
of 8.4 million. Reading `min < 255` literally there doubles the file to preserve
one part in 255 of blend on 0.03% of an image that is drawn opaque and
fullscreen.

**UI art is skipped** (`src/uiscan.py`, override with `--compress-ui`). BC1
quantises each 4×4 block to two endpoints, which on a glyph edge or a thin HUD
rule reads as ringing where the same error on a diffuse map is invisible. The
scan finds them by the material scheme they inherit — `BZSprite/AlphaHUD` and
`BZSprite/AlphaHUDPixel` — not by filename, so it catches `bzfont` and
`numbers2` without also catching `BZBaseCockpit`, which is a world-space model.
The whole UI set is under 1% of the art, so this costs nothing worth having.

**Every file is verified by decoding what was written**, not by trusting the
settings that were applied, and the summary reports colour RMSE plus two extra
columns:

* normal maps get mean angular deviation of the decoded normal. For scale, BC1
  measured 0.28–0.47° on real art, against the **3.70° per code step** that
  R5G6B5 — the format most of these normal maps already ship in — imposes
  anyway. BC1 is four times smaller *and* an order of magnitude inside the
  existing error floor.
* DXT5 files get mean alpha error. The BC4 encoder is exact on binary alpha,
  which is the cutout case that actually matters.

**Originals are copied out and hash-checked before anything is overwritten**, and
later runs re-derive from that backup rather than from the already-compressed
live file — so changing a setting and re-running replays the whole job cleanly
instead of compounding on itself.

---

## Installation & Requirements

### For Users
Download the latest platform archive from the Releases section. The archive contains the graphical **Battlezone Texture Manager** and the standalone **Battlezone MakeMAP Compatibility Tool**:

- Windows: `BZTextureManager.exe` and `BZMakeMAPCompat.exe`
- Linux/macOS: `BZTextureManager` and `BZMakeMAPCompat`

Executable names are intentionally stable and versionless. Release archives carry the version, for example `Battlezone98Redux_TextureManager-v2.4-windows.zip`.

### Windows application metadata

Release builds use the shared **Battlezone Modding Tools** product identity.

`BZTextureManager.exe`:

```text
FileDescription: Battlezone Texture Manager
ProductName: Battlezone Modding Tools
CompanyName: GrizzlyOne95
OriginalFilename: BZTextureManager.exe
```

`BZMakeMAPCompat.exe`:

```text
FileDescription: Battlezone MakeMAP Compatibility Tool
ProductName: Battlezone Modding Tools
CompanyName: GrizzlyOne95
OriginalFilename: BZMakeMAPCompat.exe
```

`FileVersion` and `ProductVersion` are generated from the release tag.

### For Developers

1. Clone the repo:

   ```bash
   git clone https://github.com/GrizzlyOne95/Battlezone98Redux_TextureManager.git
   ```

2. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

3. Run the integrated graphical application:

   ```bash
   python src/tex_man_entry.py
   ```

4. Run the MakeMAP-compatible CLI directly:

   ```bash
   python src/makemap_compat.py -8888 texture.png
   ```

5. Run the regression suite:

   ```bash
   python -m unittest discover -s tests -v
   ```
