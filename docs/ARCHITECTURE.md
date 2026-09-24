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
            |  project model . validation engine . bzn . odf            |
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
* `jobs.py` - one background task system. Work runs on a thread pool;
  progress, completion and errors are delivered on the Tk thread. The
  *Background Tasks* page and the status bar show everything that runs.
* `theme.py` / `widgets.py` - the design system (colour tokens, fonts,
  `Toolbox.*` ttk styles) and shared widgets (cards, path pickers, issue
  table, log view, jobs panel, scrollable frames with a single mouse-wheel
  dispatcher).
* `pages/` - native pages: Home, Project overview, Validation, Tasks,
  Settings, External Tools.

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

A page whose package is missing from a build is hidden (this is how the
MIT-only build drops the ZFS module).

## Core (`battlezone`)

* `project.py` - `Project` and `ProjectStore`. Profiles live in the user data
  folder, keyed by mod folder, in the same JSON layout the Workshop Uploader
  used; fields a writer does not manage are preserved on save.
* `validation/` - the validation engine. `validate_project(root, checks)`
  indexes the folder once and runs independent checks that all return
  `Issue(severity, check, message, path, line, rule_id, suggestion, ...)`.
* `odf/`, `bzn/` - ODF parser/schema/evidence/validator and BZN parsing /
  BZCC port, moved unchanged from BZN Toolbox.

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
CI.
