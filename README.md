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

**Windows:** download `BZModdingToolbox-<version>-windows.zip` from Releases,
unzip, and run `BZModdingToolbox.exe`. The same folder contains
`bztoolbox.exe` for the command line. A `-mit` variant without the GPL ZFS
component is published too (see [LICENSING.md](LICENSING.md)).

**From source** (Python 3.10+ with Tk):

```bash
pip install -r requirements.txt
python -m bztoolbox              # open the toolbox
python -m bztoolbox help         # every command
```

### Projects

A project is a mod content folder. Its metadata (title, Workshop item, tags,
preview, ...) is stored in your toolbox data folder, never inside the mod, so
it is not uploaded with it. Project profiles are the same files the Workshop
Uploader used, so the Publish page and the rest of the toolbox always agree.
Old upload profiles can be imported from *Settings > General*.

When a project is open, modules pick it up automatically (for example
Publish selects the content folder and Localization scans it).

### Validation

*Project > Validation* and `bztoolbox validate` run one engine:

| Check | What it looks at | From |
| --- | --- | --- |
| `structure` | content-root `.ini`, `mapType`, required map files | Workshop Uploader |
| `bzn` | custom ODFs referenced by missions exist | BZN Toolbox |
| `odf` | evidence-based Redux ODF loader rules | BZN Toolbox |
| `assets` | geometry/texture files named by ODFs and materials | Workshop Uploader |
| `trn` | CRLF line endings, duplicate `[Size]` | Workshop Uploader |
| `legacy` | old `.map` textures left in the upload | Workshop Uploader |
| `odf-lint` *(opt-in)* | older list-based ODF header/field scan | Workshop Uploader |

Validation never modifies the mod folder.

### Command line

```text
bztoolbox                         open the GUI (same as `bztoolbox gui`)
bztoolbox gui --project DIR       open with a project
bztoolbox validate DIR [--json] [--strict] [--checks a,b] [--add odf-lint]
bztoolbox bzn-deps MISSION.bzn    ODFs a mission uses, stock/custom/missing
bztoolbox tools [--versions]      external tools and game install detection
bztoolbox projects                known projects
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

### External tools

The toolbox runs without any of these; only the features listed need them.
*Settings > External Tools* shows what was found and lets you pick paths.

| Tool | Needed for |
| --- | --- |
| FFmpeg | Audio conversion and radio VO mastering |
| SteamCMD | Workshop uploads |
| Blender | Ogre mesh to glTF export |
| OgreXMLConverter / OgreMeshUpgrader | bundled (Windows) |
| LZO bridge | compressed ZFS archives (bundled, Windows) |

## Repository layout

```text
battlezone/        GUI-free Battlezone core: formats, validation, project model
  bzn/             BZN parsing, BZCC -> Redux port
  odf/             ODF parser, schema, evidence, validator, class labels
  validation/      the unified validation engine
  project.py       project model and profile store
bztoolbox/         the application
  app/             shell, theme, embedding host, jobs, shared widgets, pages
  modules/         the migrated tools, one package per area, + registry
  cli.py           the bztoolbox command
  external.py      external tool / game install detection
tests/             all test suites (the tools' original tests + toolbox tests)
packaging/         PyInstaller spec and helpers
scripts/           migration and research scripts
docs/              architecture, migration record, per-module docs
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and
[docs/MIGRATION.md](docs/MIGRATION.md).

## Development

```bash
pip install -r requirements.txt pytest
xvfb-run -a python -m pytest     # Linux; GUI tests need a display
python -m pytest                 # Windows / macOS
python -m PyInstaller packaging/bztoolbox.spec --noconfirm
dist/BZModdingToolbox/bztoolbox selftest
```

## License

MIT, except the ZFS module (GPL-2.0) and the Blender-side Ogre importer. See
[LICENSING.md](LICENSING.md) and [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
