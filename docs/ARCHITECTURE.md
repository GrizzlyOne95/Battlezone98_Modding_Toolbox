# Architecture

```text
            +--------------------------+      +-----------------------+
            |  bztoolbox.app (Tk GUI)  |      |  bztoolbox.cli        |
            |  shell, pages, jobs,     |      |  validate, tools, ... |
            |  theme, embedding host   |      |  + tool CLIs          |
            +------------+-------------+      +-----------+-----------+
                         |                                |
            +------------v--------------------------------v-----------+
            |  bztoolbox.modules  (feature modules, one per area)      |
            |  registry.py: navigation model, lazy page loading        |
            +------------+---------------------------------------------+
                         |
            +------------v---------------------------------------------+
            |  battlezone  (GUI-free core)                              |
            |  project . validation . assets . bzn . odf . terrain      |
            |  archives (ZFS/LZO) . meshes (Ogre)                       |
            +-----------------------------------------------------------+
```

The rule the layers follow: **`battlezone` never imports `bztoolbox` or
tkinter.** Anything a CLI, a test or a future module needs without a window
belongs there.

## Shell (`bztoolbox/app`)

* `shell.py` - the main window: header with the open project, sidebar
  navigation built from `modules/registry.py`, page area, status bar. Pages
  are created on first visit and then kept alive, so a tool keeps its state
  while the user moves around.
* `host.py` - lets a migrated tool run inside a page. The tools were written
  as top-level apps: they call `root.title()`, `geometry()`, `protocol(...)`,
  `config(menu=...)`, or subclass `tk.Tk` / `customtkinter.CTk`.
  `EmbeddedRoot` is a frame with that API: window-manager calls become
  no-ops, the close handler is kept and called when the toolbox exits (so
  each tool still saves its settings), and a menubar is drawn as a button
  row. Constructed without a master, the same class opens its own window, so
  modules stay runnable on their own during the migration.
* `fonts.py` - registers the bundled Battlezone font for the running process
  (GDI / fontconfig / CoreText); the shell and every tool take header fonts
  from it.
* `jobs.py` - one background task system. Work runs on a thread pool;
  progress, completion and errors are delivered on the Tk thread. The
  *Background Tasks* page and the status bar show everything that runs.
* `theme.py` / `widgets.py` - the design system (colour tokens, fonts,
  `Toolbox.*` ttk styles) and shared widgets (cards, path pickers, issue
  table, log view, jobs panel, scrollable frames with a single mouse-wheel
  dispatcher).
* `pages/` - native pages: Home, Project overview, Validation, Dependencies,
  Tasks, Settings, External Tools. (The ZFS page is native too, in
  `modules/archives`.)

### Styling and migrated modules

Shell widgets use only `Toolbox.*` style names. The migrated modules still
configure the generic ttk styles (`TButton`, `Treeview`, ...) themselves,
with the same palette; the shell sets a dark baseline for those styles first
so modules that never styled themselves (the terrain generator) match. ttk
styles are global, so a module loaded later can still adjust a generic style
used by another module; moving modules onto `Toolbox.*` styles removes that
last bit of cross-talk.

## Modules (`bztoolbox/modules`)

One package per area. `registry.py` declares every page (`PageSpec`: id,
section, title, factory, origin, required external tools, project hook).
Factories are import strings, so starting the toolbox does not import SciPy,
customtkinter or Ogre until a page needs them. `legacy.py` holds the loaders
that mount the migrated tools and the *project hooks* that push the open
project into them.

A page whose package is missing from a build is hidden.

## Core (`battlezone`)

* `project.py` - `Project` and `ProjectStore`. Profiles live in the user data
  folder, keyed by mod folder, in the same JSON layout the Workshop Uploader
  used; fields a writer does not manage are preserved on save.
* `validation/` - the validation engine. `validate_project(root, checks)`
  indexes the folder once and runs independent checks that all return
  `Issue(severity, check, message, path, line, rule_id, suggestion, ...)`.
* `odf/`, `bzn/` - ODF parser/schema/evidence/validator and BZN parsing /
  BZCC port, moved unchanged from BZN Toolbox; `odf/names.py` reads the
  player-visible `unitName` (Localization).
* `terrain/` - one reader/writer per terrain format: `hg2`, `lgt`, `mat`,
  `trn` (a TRN document model: sections, duplicates, line endings, the first
  `[Size]` as the engine reads it) and the stock ACT `palettes`. The older
  module files (`world/hg2_codec.py`, `terrain_generator/hg2.py`, ...)
  re-export these names.
* `archives/` - ZFS archives (read, extract, verify, write; encrypted and
  legacy LZO205 archives) on a pure-Python LZO1X/LZO1Y codec.
* `meshes/ogre.py` - Ogre binary `.mesh` reader (serializer v1.0-v1.100, both
  byte orders) that writes OgreXMLConverter's XML layout and patches normals
  back into the binary.
* `assets/` - the dependency graph built from all of the above.

Because none of this needs a native helper program, every feature works on
Windows, macOS and Linux.

## Per-user state

`bztoolbox.paths.user_data_dir()` (`%APPDATA%\BattlezoneModdingToolbox`,
`~/Library/Application Support/...`, `~/.config/...`; override with
`BZTOOLBOX_HOME`) holds `settings.json`, `projects/` and
`modules/<module>/` for each migrated tool's own config. Previously every
tool wrote next to its executable or the current directory.

## Resources and packaging

Resources live beside the module that uses them and are looked up relative
to the module file. The PyInstaller spec (`packaging/bztoolbox.spec`) keeps
the package layout inside the bundle, so the same lookup works frozen.
`bztoolbox selftest` opens every page and is run against the frozen build in
CI on Windows, macOS and Linux.
