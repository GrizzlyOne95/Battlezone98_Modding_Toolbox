# Battlezone Modding Toolbox

One application for Battlezone 98 Redux modding. Open a mod folder, then build
terrain, inspect missions, edit assets, validate dependencies, localize,
package and publish it without leaving the toolbox.

It replaces eleven standalone tools. Their features are all still here, now
organised by workflow instead of by executable:

| Area | Page | Formerly |
| --- | --- | --- |
| **Project** | Overview | *(new)* |
| | Validation | *(new, combines the BZN Toolbox and Workshop Uploader checks)* |
| | Dependencies | *(new: asset graph, missing / unreferenced files, texture memory)* |
| | Localization | Localization Tool |
| | Workshop / Publish | Workshop Uploader |
| **Missions** | Mission Inspector | BZN Toolbox |
| **World & Terrain** | World Builder | WorldBuilder |
| | Generate Terrain | HeightmapGen |
| **Assets** | Textures & Images | TextureManager |
| | Fonts | Font Generator |
| | Holographic Text | HoloTextGen |
| | Models & Meshes | OgreMeshTools |
| | Audio | AudioTool |
| **Archives** | ZFS Archives | ZFS Specialist |
| **Tools / Settings** | Background Tasks, General, External Tools | *(new)* |

## Using it

Releases have an installer per platform. Nothing else needs to be installed:
no FFmpeg, Blender, Ogre tools or LZO library.

* **Windows:** run `BZModdingToolbox-<version>-windows-setup.exe`. It installs
  for your account without an administrator prompt (or for all users, if you
  choose), adds a Start menu entry, registers under *Settings > Apps* with its
  version and publisher, and can put the `bztoolbox` command line on `PATH`.
  Running a newer setup upgrades in place; uninstall from *Settings > Apps*,
  which also offers to delete your settings. The build is unsigned, so
  SmartScreen may ask you to confirm (*More info > Run anyway*).
  Prefer no install? `BZModdingToolbox-<version>-windows-portable.zip` is the
  same program: unzip it and run `BZModdingToolbox.exe`.
* **macOS:** open `BZModdingToolbox-<version>-macos.dmg` and drag
  `BZModdingToolbox.app` into *Applications* (the build is unsigned:
  right-click > Open the first time). The command line is
  `BZModdingToolbox.app/Contents/MacOS/bztoolbox`.
* **Linux:** extract `BZModdingToolbox-<version>-linux.tar.gz` and run
  `BZModdingToolbox/install.sh`. It installs for your user under `~/.local`
  (or for everyone under `/opt` with `sudo`), adds a menu entry and the
  `BZModdingToolbox` / `bztoolbox` commands. `install.sh --uninstall` removes
  it, `--purge` your settings too. You can also run
  `BZModdingToolbox/BZModdingToolbox` straight from the extracted folder.

Wherever it runs from, the toolbox never writes beside its executable. Your
settings, project profiles and caches live in one per-user folder
(`%APPDATA%\BattlezoneModdingToolbox`, `~/Library/Application Support/BattlezoneModdingToolbox`
or `~/.config/BattlezoneModdingToolbox`; set `BZTOOLBOX_HOME` to move it), shown
under *Settings > General*. `bztoolbox clean-user-data` deletes it along with
the saved Steam API key.

**From source** (Python 3.10+ with Tk):

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

The Mission Inspector combines the former BZN and ODF tooling.

It can read both ASCII and binary Redux BZN files, identify the ODFs used by a mission, separate stock and custom dependencies, and check whether required custom files are present.

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

They can recalculate mesh normals to repair bad lighting and export static geometry to OBJ. The toolbox includes its own Ogre mesh reader, so normal repair and OBJ export do not require Ogre command-line utilities or Blender.

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

Extract the Windows ZIP and run:

```text
bztoolbox                         open the GUI (same as `bztoolbox gui`)
bztoolbox gui --project DIR       open with a project
bztoolbox validate DIR [--json] [--strict] [--checks a,b] [--add odf-lint]
bztoolbox bzn-deps MISSION.bzn    ODFs a mission uses, stock/custom/missing
bztoolbox deps DIR [--why FILE] [--json]   asset dependency graph
bztoolbox zfs list|extract|verify|pack ARCHIVE ...   ZFS archives
bztoolbox tools [--versions]      external tools and game install detection
bztoolbox projects                known projects
bztoolbox clean-user-data [--yes] delete your settings, profiles, caches, saved key
bztoolbox selftest                open every page once (used by CI)

# The standalone tools' CLIs, arguments unchanged:
bztoolbox odf validate PATH             bztoolbox textures makemap ...
bztoolbox bzn port SRC TEMPLATE ...     bztoolbox textures recompress ...
bztoolbox bzn classes ...               bztoolbox meshes to-obj ...
bztoolbox terrain generate ...          bztoolbox meshes normals FILE
bztoolbox terrain paint ...             bztoolbox fonts dump-st FILE
bztoolbox terrain legacy-port ...       bztoolbox terrain msn2terrain ...
bztoolbox terrain preview ...
```

The command-line version is included as `bztoolbox.exe`.

### macOS

Extract the macOS ZIP and open `BZModdingToolbox.app`.

Current builds are unsigned, so macOS may require **right-click -> Open** the first time.

### Linux

Extract the Linux archive and run:

```text
battlezone/        GUI-free Battlezone core: formats, validation, project model
  archives/        ZFS archives and the LZO1X/LZO1Y codec
  assets/          asset dependency graph
  bzn/             BZN parsing, BZCC -> Redux port
  meshes/          Ogre binary .mesh reader (-> XML, normal patching)
  odf/             ODF parser, schema, evidence, validator, class labels, unit names
  terrain/         HG2, LGT, MAT, TRN and stock palettes: one codec each
  validation/      the unified validation engine
  project.py       project model and profile store
bztoolbox/         the application
  app/             shell, theme, embedding host, jobs, shared widgets, pages
  modules/         the migrated tools, one package per area, + registry
  cli.py           the bztoolbox command
  external.py      external tool / game install detection
tests/             all test suites (the tools' original tests + toolbox tests)
packaging/         PyInstaller spec, Windows installer (Inno Setup), Linux install script
scripts/           migration and research scripts
docs/              architecture, migration record, per-module docs
```

The `bztoolbox` command-line executable is included in the same folder.

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
pip install -r requirements.txt pytest
xvfb-run -a python -m pytest     # Linux; GUI tests need a display
python -m pytest                 # Windows / macOS
python -m PyInstaller packaging/bztoolbox.spec --noconfirm   # on each platform
dist/BZModdingToolbox/bztoolbox selftest
iscc /DAppVersion=0.1.0 packaging\windows\BZModdingToolbox.iss  # Windows installer (Inno Setup 6.3+)
```

For more information about the internals, see:

- [Architecture](docs/ARCHITECTURE.md)
- [Consolidation and migration notes](docs/MIGRATION.md)
- [Licensing](LICENSING.md)
- [Third-party notices](THIRD_PARTY_NOTICES.md)

Every pull request merged into `main` is released automatically
(`.github/workflows/ci.yml`). The workflow tests the merge commit, builds
Windows, macOS and Linux, installs and uninstalls the Windows setup and the
Linux script to check them, and publishes a GitHub release with the Windows
setup and portable zip, the macOS disk image, the Linux archive and notes
listing the merged pull requests.

Bug reports, compatibility findings, documentation improvements, and focused pull requests are welcome.

For format or engine-behavior issues, providing the smallest reproducible Battlezone asset or test case possible is especially useful.

## License

MIT. See [LICENSE](LICENSE), [LICENSING.md](LICENSING.md), and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
