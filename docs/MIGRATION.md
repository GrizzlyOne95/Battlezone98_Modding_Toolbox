# Consolidation record

This repository replaces eleven standalone repositories. This file records
what was imported, what changed on the way in, and what is left to do.

## Imported sources

Imported by `scripts/migration/import_legacy_tools.py` (mechanical copy +
flat-import rewrite), then adapted in ordinary commits.

| Repository | Version | Commit | Now |
| --- | --- | --- | --- |
| Battlezone98Redux_BZN_Toolbox | 1.3.1 | `ff21445` | `battlezone/odf`, `battlezone/bzn`, `bztoolbox/modules/missions` |
| Battlezone98Redux_WorldBuilder | 1.0.17 | `6dae743` | `bztoolbox/modules/world` (+ `scripts/world/cc_atlas`) |
| Battlezone98Redux_HeightmapGen | 1.0.3 | `ee15b77` | `bztoolbox/modules/terrain_generator` |
| Battlezone98Redux_LocalizationTool | 2.1.1 | `279115a` | `bztoolbox/modules/localization` |
| Battlezone98Redux_WorkshopUploader | 1.7.0 | `cb0cce8` | `bztoolbox/modules/publishing`, `battlezone/validation/mod_scanner.py` |
| Battlezone98Redux_HoloTextGen | 2.1.1 | `f89b88b` | `bztoolbox/modules/holotext` |
| Battlezone98ReduxFontGenerator | 2.4.3 | `359f030` | `bztoolbox/modules/fonts` |
| Battlezone98Redux_OgreMeshTools | 1.2.4 | `9462c31` | `bztoolbox/modules/meshes` |
| Battlezone98Redux_ZFSSpecialist | 3.1.5 | `b811b2f` | replaced by `battlezone/archives` + `bztoolbox/modules/archives` (MIT) |
| Battlezone98Redux_TextureManager | 2.4.1 | `055409d` | `bztoolbox/modules/textures` |
| Battlezone98Redux_AudioTool | 1.2.4 | `3a4e66a` | `bztoolbox/modules/audio` |

Not imported: per-repo CI/release workflows, PyInstaller specs, icon/version
generators (replaced by `packaging/`), `world_builder_temp.py` (an unused
copy), `benchmark_datetime_import.py`, HeightmapGen's 70 MB `samples/`
corpus, and release notes. Tool READMEs and format docs are under `docs/<module>/`.

All **406** tests from the source repositories run unchanged in `tests/<module>/`
(the Workshop tests now install their headless stubs only while importing the
uploader, so they no longer break the other suites).

## Changes made while integrating

### On import

Behaviour-preserving adaptations only; no conversion logic was rewritten.

* **All modules** - resources are looked up beside the module (works from
  source and in the bundle); config/profile files moved from the executable
  folder / working directory to the per-user toolbox data folder.
* **BZN Toolbox** - GUI-free modules moved to `battlezone`; `bzn_scan.py`
  split into the core parser (`battlezone/bzn/scan.py`) and the Tk analyzer.
* **Workshop Uploader** - `ModScanner` moved to `battlezone/validation`
  (bundled rule lists move with it); `validate_content_structure` gained a
  read-only mode; upload profiles *are* toolbox project profiles and saving
  merges instead of overwriting fields owned by other modules.
* **AudioTool** - `BZRadio` is an embeddable frame instead of a `tk.Tk`
  subclass.
* **OgreMeshTools** - the GUI is an embeddable `CTkFrame`; stdout capture
  only captures the tool's own worker thread when embedded; the frozen
  "script proxy" argv hack is replaced by `bztoolbox meshes ...` commands.
* **HeightmapGen** - `run_gui(root=None)` builds into a given root and leaves
  the ttk theme and main loop to the shell when embedded.
* **WorldBuilder** - the global `bind_all("<MouseWheel>")` goes through the
  shared wheel dispatcher, so it no longer scrolls from other pages.
* **TextureManager** - drag and drop is only registered when the root has
  tkdnd loaded.
* **Font Generator** - no longer fails outside Windows (`ctypes.windll`).
* **HoloTextGen** - the bundled font is the default instead of a
  working-directory relative `BZONE.ttf`.

### Afterwards: no native helpers, shared codecs, every platform

These did change behaviour, on purpose:

* **ZFS Specialist** - replaced. The GPL LZO bridge is gone; archives are
  handled by a pure-Python LZO1X/LZO1Y codec and ZFS reader/writer
  (`battlezone/archives`), a native page and `bztoolbox zfs`. The packer now
  XORs member data *before* compressing (the order the reader and the game
  undo; the old packer did it after, so its encrypted archives did not
  round-trip), rejects names longer than 15 characters instead of silently
  truncating them, stores incompressible members raw, and records file times.
* **AudioTool** - FFmpeg is no longer used: soundfile does the decoding and
  encoding and the radio chain is NumPy/SciPy. M4A input is no longer accepted.
* **OgreMeshTools** - OgreXMLConverter, OgreMeshUpgrader, OgreMeshMagick and
  the Blender scripts are removed. `battlezone/meshes/ogre.py` reads binary
  meshes; recalculated normals are written into the `.mesh` in place. glTF
  export is removed; OBJ export stays.
* **Terrain formats** - HG2, LGT, MAT, TRN and the stock palettes each have
  one implementation in `battlezone/terrain`. TRN values come from the first
  `[Size]` section everywhere (as the engine reads it); a few readers used to
  take the last one.
* **Workshop Uploader** - the readiness check and publish plan include the
  validation engine's mission and ODF findings.
* **Localization** - `unitName` scanning uses `battlezone.odf`.
* **Fonts** - one bundled `BZONE.ttf`, registered on every platform; the
  per-module copies are gone.

## Roadmap

The migration order from the consolidation report, and where each step stands.

| # | Step | Status |
| --- | --- | --- |
| 1 | Unified repository and application shell | **Done** |
| 2 | Extract shared parsers/codecs without behaviour change | **Done**: ODF, BZN, HG2, LGT, MAT, TRN, palettes, ZFS/LZO, Ogre mesh in `battlezone` |
| 3 | BZN Toolbox + ODF validation as the foundation | **Done**: core package, Mission Inspector page, validation engine |
| 4 | WorldBuilder | **Hosted** as World & Terrain > World Builder |
| 5 | Fold HeightmapGen into World & Terrain | **Hosted** as World & Terrain > Generate Terrain; code merge follows step 2's HG2/LGT unification |
| 6 | TextureManager as the graphics foundation | **Hosted** |
| 7 | Font Generator + HoloTextGen under Assets | **Hosted** |
| 8 | AudioTool | **Hosted**, FFmpeg via external tool detection |
| 9 | Localization on the shared project/ODF model | **Done**: project hook, `battlezone.odf` unit names |
| 10 | ZFS with a licensing boundary | **Done, boundary removed**: pure-Python MIT implementation |
| 11 | OgreMeshTools with optional external tools | **Done**: no external tools; optional Ogre preview |
| 12 | Workshop Uploader on the unified project/validation system | **Done**: shared profiles, scanner in core, readiness runs `battlezone.validation` |

Beyond the list:

* ~~Asset dependency graph~~ - done: `battlezone.assets`, *Project >
  Dependencies*, `bztoolbox deps`. Next: a rename action that updates the
  referencing files.
* Move the migrated UIs' own threads onto `app.jobs`, and their generic ttk
  styles onto `Toolbox.*` styles.
* ~~Shared font loader~~ - done (`bztoolbox/app/fonts.py`).
* Code-sign / notarize the macOS build and sign the Windows build.
* Archive the standalone repositories after the first toolbox release, with
  a pointer here.
