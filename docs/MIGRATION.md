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
| Battlezone98Redux_ZFSSpecialist | 3.1.5 | `b811b2f` | `bztoolbox/modules/zfs` (GPL-2.0) |
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
  subclass; FFmpeg comes from Settings > External Tools / bundle / `PATH`.
* **OgreMeshTools** - the GUI is an embeddable `CTkFrame`; stdout capture
  only captures the tool's own worker thread when embedded; helper binaries
  moved to `bin/`, Blender scripts to `blender/` (unchanged); the frozen
  "script proxy" argv hack is replaced by `bztoolbox meshes ...` commands;
  Blender and OgreXMLConverter are resolved through external tool detection.
* **HeightmapGen** - `run_gui(root=None)` builds into a given root and leaves
  the ttk theme and main loop to the shell when embedded.
* **WorldBuilder** - the global `bind_all("<MouseWheel>")` goes through the
  shared wheel dispatcher, so it no longer scrolls from other pages.
* **TextureManager** - drag and drop is only registered when the root has
  tkdnd loaded.
* **Font Generator** - no longer fails outside Windows (`ctypes.windll`).
* **HoloTextGen** - the bundled font is the default instead of a
  working-directory relative `BZONE.ttf`.

## Roadmap

The migration order from the consolidation report, and where each step stands.

| # | Step | Status |
| --- | --- | --- |
| 1 | Unified repository and application shell | **Done** |
| 2 | Extract shared parsers/codecs without behaviour change | **Started**: ODF + BZN in `battlezone`. Next: one HG2 codec (`world/hg2_codec.py` vs `terrain_generator/hg2.py`), LGT, MAT, TRN, and one `stock_palettes` (WorldBuilder and TextureManager each carry one). |
| 3 | BZN Toolbox + ODF validation as the foundation | **Done**: core package, Mission Inspector page, validation engine |
| 4 | WorldBuilder | **Hosted** as World & Terrain > World Builder |
| 5 | Fold HeightmapGen into World & Terrain | **Hosted** as World & Terrain > Generate Terrain; code merge follows step 2's HG2/LGT unification |
| 6 | TextureManager as the graphics foundation | **Hosted** |
| 7 | Font Generator + HoloTextGen under Assets | **Hosted** |
| 8 | AudioTool | **Hosted**, FFmpeg via external tool detection |
| 9 | Localization on the shared project/ODF model | **Hosted** with project hook; next: replace its ODF scanner with `battlezone.odf` |
| 10 | ZFS with a licensing boundary | **Done**: isolated GPL module, MIT-only build variant |
| 11 | OgreMeshTools with optional external tools | **Done**: Blender/Ogre detection, optional Ogre preview |
| 12 | Workshop Uploader on the unified project/validation system | **Started**: shared project profiles, scanner in core. Next: its readiness check runs `battlezone.validation` (adds the ODF and mission checks) |

Beyond the list:

* **Asset dependency graph** (BZN -> ODF -> mesh -> material -> texture, TRN
  -> HG2/MAT) on top of the parsers in `battlezone`: unused/missing assets,
  "what breaks if I rename this", VRAM by texture, Workshop upload contents.
* Move the migrated UIs' own threads onto `app.jobs`, and their generic ttk
  styles onto `Toolbox.*` styles.
* Shared font loader: drop the per-module copies of `BZONE.ttf`.
* Archive the standalone repositories after the first toolbox release, with
  a pointer here.
