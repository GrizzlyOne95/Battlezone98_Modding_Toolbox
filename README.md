# Battlezone 98 Modding Toolbox

**An all-in-one modding workspace for Battlezone 98 Redux.**

Battlezone 98 Modding Toolbox brings the major Battlezone modding workflows into one application. Instead of keeping a collection of separate utilities around, you can open a mod project and work on missions, terrain, textures, audio, localization, archives, validation, and Steam Workshop publishing from the same place.

The toolbox is designed to be useful whether you are building a complete campaign, converting an older map, preparing a few custom assets, diagnosing a broken mod, or publishing an update.

> **One project. One toolbox. One workflow.**

## What can it do?

The toolbox is organized around the way a mod is actually built rather than around individual file formats.

| Area | What it covers |
| --- | --- |
| **Projects** | Open and manage mod folders, keep Workshop metadata together, validate content, and inspect dependencies. |
| **Missions** | Inspect BZN files, find mission ODF dependencies, validate Redux ODFs, and assist with BZ2/BZCC mission ports. |
| **World & Terrain** | Build and convert terrain, create atlases, generate heightmaps, auto-paint maps, work with skies, and preview missions. |
| **Textures & Graphics** | Convert and batch-process textures, edit ACT palettes, work with MAP/LGT/DXTBZ2 files, generate fonts, and create holographic text assets. |
| **Models & Meshes** | Inspect Ogre meshes, recalculate normals, preview models, and export static meshes to OBJ. |
| **Audio** | Prepare Battlezone-style radio voiceovers, engine/turbo WAVs, soundtrack OGGs, and timing manifests. |
| **Localization** | Scan mod ODFs for player-visible names and build Battlezone-compatible localization table entries. |
| **Archives** | Browse, search, extract, verify, and build ZFS archives, including supported legacy and encrypted formats. |
| **Workshop Publishing** | Check a mod before release, review changed files, fix common problems, and upload through SteamCMD. |

## A unified modding workflow

The main advantage of the toolbox is that these features understand the same project.

Open a Battlezone mod folder and the rest of the application can use it automatically. You can inspect a mission, follow its ODF and asset dependencies, edit terrain or textures, scan localization, run validation, and then move directly into Workshop publishing without repeatedly pointing different programs at the same files.

Project metadata such as the Workshop item, title, tags, preview image, and publish state is stored in the toolbox's own data folder rather than inside your mod, so toolbox bookkeeping is not accidentally included in the upload.

## Project validation

The toolbox includes a shared validation system for catching many common Battlezone mod problems before they become difficult-to-debug runtime issues.

It can check things such as:

- mod and Workshop content structure
- mission references to missing custom ODFs
- Redux ODF class labels, sections, and known loader keys
- missing mesh, material, and texture references
- malformed TRN files and line-ending issues
- obsolete legacy MAP files in Workshop content
- other common packaging and compatibility problems

The normal validation pass is read-only. It reports what it found and where the problem is so you can decide what to change.

The Workshop page uses the same validation engine as its readiness check, so publishing is based on the same information you see elsewhere in the toolbox.

## Dependency analysis

Large Battlezone mods can become difficult to maintain because a single file may be referenced several layers away.

The **Dependencies** view maps relationships such as:

```text
mission -> BZN -> ODF -> mesh -> material -> texture
terrain -> TRN -> HG2 / MAT / LGT / palette / textures
```

You can use it to answer questions like:

- What uses this file?
- What will break if I rename it?
- Which references are missing from the project?
- Which files appear to be unused?
- Is a reference probably stock content rather than a missing custom asset?
- Roughly how much texture memory does the project use?

This is especially useful when cleaning up old campaigns or consolidating large Workshop projects.

## Missions and ODFs

Mission checks live with the rest of the project checks: **Validation** reads ASCII and binary Redux BZN files and reports custom ODFs a mission places that are missing (it can also check another folder or a ZIP), and **Dependencies** shows everything a mission uses. **Missions › BZCC → Redux Port** converts BZ2/BZCC missions, terrain first and then the mission, with safe defaults and the full converter options under "Advanced".

The ODF validator is based on recovered Battlezone 98 Redux loader behavior and supporting stock-content research rather than only on old documentation. It is intended to catch errors that can otherwise result in silently ignored parameters, incorrect behavior, or crashes.

There is also tooling for **BZ2/BZCC to Redux mission conversion**, including ODF/team mapping and conversion reports for areas that require manual review.

## World and terrain tools

The toolbox includes the major WorldBuilder and HeightmapGen workflows in one place.

You can:

- create new Battlezone terrain and supporting files
- generate procedural HG2 heightmaps with live terrain and lighting previews
- convert and work with legacy terrain
- create custom and legacy texture atlases
- auto-paint terrain using elevation and terrain rules
- convert heightmaps
- work with Battlezone sky assets
- visualize mission terrain
- use the evolving BZ2/BZCC terrain-port workflow where supported

Terrain formats such as HG2, LGT, MAT, and TRN are handled by shared codecs inside the toolbox so the different pages interpret the same files consistently.

## Textures and graphics

The graphics tools cover both modern Battlezone Redux assets and several original Battlezone formats.

Features include:

- PNG, TGA, and DDS conversion and batch processing
- DXT1/DXT5 compression, mipmaps, and power-of-two resizing
- optional normal, specular, and emissive texture generation
- ACT palette viewing and editing
- MAP image decoding, editing, and MakeMAP-compatible encoding
- LGT lightmap conversion
- DXTBZ2 texture conversion
- bulk DDS recompression and analysis
- channel packing and related texture utilities
- Battlezone font-atlas generation
- holographic-text sprite/material/ODF generation

The goal is to cover the common asset-preparation work without requiring a chain of separate converters.

## Models and meshes

The mesh tools work directly with Ogre binary `.mesh` files used by Battlezone Redux.

They can recalculate mesh normals to repair bad lighting and export static geometry to OBJ. The toolbox includes its own Ogre mesh reader, so normal repair and OBJ export do not require Ogre command-line utilities or Blender. The live 3D preview uses Ogre (`ogre-python`), which Windows and Linux release builds include.

## Audio

The Audio page provides Battlezone-oriented export profiles rather than acting as a generic audio editor.

It can prepare:

- radio and unit voiceovers with Battlezone-style filtering and optional squelch beeps
- engine/thrust/turbo WAV loops in engine-friendly formats
- clean stereo OGG soundtrack files
- CSV timing manifests for Lua subtitles, mission events, and voice timing

Single files and folders can both be processed.

## Localization

The localization tools can scan a project for player-visible `unitName` values, avoid duplicate keys, and generate entries compatible with Battlezone's localization-table conventions.

Bulk translation helpers are also available for preparing multilingual tables, while still allowing the generated text to be reviewed before it becomes part of a release.

## ZFS archives

The built-in ZFS tools can browse an archive without extracting it, search its contents, extract files, verify archives, and create new archives.

Support includes the normal ZFS format, legacy MakeZFS/LZO archives, compression, directories, and supported encrypted members. ZFS and LZO handling is implemented inside the toolbox and does not require a separate native DLL.

## Steam Workshop publishing

The Workshop page is intended to take a project from "looks ready" to uploaded without needing the old Battlezone uploader.

It can:

- detect or configure SteamCMD
- keep a local profile for each mod folder
- link a project to an existing owned Workshop item
- load Workshop metadata into the editor
- run Battlezone-specific readiness checks
- show files changed since the last publish
- apply supported one-click fixes for common content problems
- handle Steam Guard/mobile-approval states during upload
- publish through SteamCMD with expandable diagnostics

**SteamCMD is the only external program required by the toolbox, and only for Workshop uploads.**

## Installation

Prebuilt releases are available for **Windows, macOS, and Linux**.

Download the latest build from the [Releases page](https://github.com/GrizzlyOne95/Battlezone98_Modding_Toolbox/releases/latest).

### Windows

Run `BZModdingToolbox-<version>-windows-setup.exe`.

- It installs for your account without an administrator prompt, or for all users if you choose.
- It adds a Start menu entry and registers under **Settings -> Apps** with its version and publisher.
- It can add an **Open in BZ Modding Toolbox** entry to the right-click menu of folders, and put the `bztoolbox` command line on `PATH`.
- To upgrade, run a newer setup; it replaces the old version in place.
- Uninstall from **Settings -> Apps**. It asks whether to delete your settings too.

Prefer not to install? `BZModdingToolbox-<version>-windows-portable.zip` is the same program: extract it and run `BZModdingToolbox.exe`. The command-line version is `bztoolbox.exe` in the same folder.

### macOS

Open `BZModdingToolbox-<version>-macos.dmg` and drag `BZModdingToolbox.app` into **Applications**.

Current builds are unsigned, so macOS may require **right-click -> Open** the first time.

### Linux

Extract the Linux archive and run `BZModdingToolbox/install.sh`. It installs for your user under `~/.local` (or for everyone under `/opt` with `sudo`) and adds a menu entry and the `BZModdingToolbox` / `bztoolbox` commands. `install.sh --uninstall` removes it and `install.sh --purge` removes your settings too.

You can also run `BZModdingToolbox/BZModdingToolbox` straight from the extracted folder.

### Updates

The toolbox checks for a new release at most once a day and shows a banner when there is one. An installed Windows copy can update itself from the banner; other copies get a link to the right download. Turn the check off, or check now, under **Settings -> General**.

### Where your settings live

The toolbox never writes next to its program files. Settings, project profiles and caches are kept in one folder per user:

- Windows: `%APPDATA%\BattlezoneModdingToolbox`
- macOS: `~/Library/Application Support/BattlezoneModdingToolbox`
- Linux: `~/.config/BattlezoneModdingToolbox`

**Settings -> General** shows the folder. Set `BZTOOLBOX_HOME` to use a different one, or run `bztoolbox clean-user-data` to delete it along with the saved Steam API key.

### No extra modding utilities required

Release builds are intended to be self-contained. You do **not** need to separately install Python, FFmpeg, Blender, Ogre command-line tools, or an LZO library for the normal toolbox features.

SteamCMD is only needed if you want to publish to the Steam Workshop.

## Command line

Most users can stay entirely in the GUI, but the toolbox also exposes the shared core through `bztoolbox` for automation and batch work.

A few examples:

```text
bztoolbox
bztoolbox help

bztoolbox validate MyMod
bztoolbox deps MyMod
bztoolbox bzn-deps mission.bzn
bztoolbox gui --project MyMod

bztoolbox zfs list archive.zfs
bztoolbox zfs extract archive.zfs
bztoolbox zfs verify archive.zfs

bztoolbox terrain ...
bztoolbox textures ...
bztoolbox meshes ...
bztoolbox odf ...
```

Run `bztoolbox help` or the help command for a specific module to see the available options.

## What happened to the standalone tools?

This project consolidates the functionality of eleven Battlezone modding utilities:

- BZN Toolbox
- WorldBuilder
- HeightmapGen
- Localization Tool
- Workshop Uploader
- HoloTextGen
- Font Generator
- OgreMeshTools
- ZFS Specialist
- TextureManager
- AudioTool

They now share one application shell, project model, validation system, file-format core, packaging process, and cross-platform release.

The original per-tool documentation has been retained under [`docs/`](docs/) for anyone who needs detailed format notes, conversion references, reverse-engineering research, or module-specific usage information.

## Running from source

Python 3.10+ with Tk is required.

```bash
pip install -r requirements.txt
python -m bztoolbox
```

To run the test suite:

```bash
pip install pytest
python -m pytest
```

For more information about the internals, see:

- [Architecture](docs/ARCHITECTURE.md)
- [Consolidation and migration notes](docs/MIGRATION.md)
- [Licensing](LICENSING.md)
- [Third-party notices](THIRD_PARTY_NOTICES.md)

## Contributing

Bug reports, compatibility findings, documentation improvements, and focused pull requests are welcome.

For format or engine-behavior issues, providing the smallest reproducible Battlezone asset or test case possible is especially useful.

## License

MIT. See [LICENSE](LICENSE), [LICENSING.md](LICENSING.md), and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
