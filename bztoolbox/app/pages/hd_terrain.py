"""Native World & Terrain page for portable HD terrain authoring bundles."""
from __future__ import annotations

import json
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from bztoolbox.app.widgets import Card, LogView, PathPicker, ScrollableFrame


class HdTerrainPage(ScrollableFrame):
    def __init__(self, master, shell):
        super().__init__(master)
        self.shell = shell
        self.job = None
        self.project = None
        self._loaded_source = ""
        defaults = {"sources": "", "layout": "", "material": "", "diffuse_resource": "",
                    "normal_resource": "", "specular_resource": "", "emissive_resource": "",
                    "default_alias": "", "tile_size": "1024", "prefix": "hd",
                    "normal_space": "directx", "out": ""}
        self.vars = {key: tk.StringVar(value=value) for key, value in defaults.items()}
        body = ttk.Frame(self.body, style="Toolbox.TFrame", padding=(18, 4, 18, 18))
        body.pack(fill="both", expand=True)
        card = Card(body, "HD Terrain Tiles",
                    "Package independent tile images for OpenShim's DX11 Enhanced terrain. "
                    "Authored assets and matching map configuration are required. "
                    "Keep the ordinary atlas for fallback when Enhanced or HD tiles are off.")
        card.pack(fill="x", pady=(0, 12))
        form = card.body
        PathPicker(form, "Source images", self.vars["sources"], kind="dir", surface=True,
                   on_change=self._source_chosen).pack(fill="x", pady=2)
        ttk.Label(form, text="New project: ALIAS_d.png, ALIAS_n.png, ALIAS_s.png, ALIAS_e.png (also TGA/DDS). "
                            "Or select a ready CR source-tile export.",
                  style="Toolbox.SurfaceMuted.TLabel", wraplength=850).pack(anchor="w", pady=3)
        PathPicker(form, "Atlas layout CSV", self.vars["layout"], kind="file", surface=True,
                   filetypes=(("Atlas layout", "*.csv"),)).pack(fill="x", pady=2)
        grid = ttk.Frame(form, style="Toolbox.Surface.TFrame")
        grid.pack(fill="x", pady=6)
        grid.columnconfigure(1, weight=1)
        fields = [("material", "Ogre material", "Exact TRN atlas material"),
                  ("diffuse_resource", "Original diffuse atlas", "Required identity guard; not an image input"),
                  ("normal_resource", "Original normal atlas", "Optional; blank keeps stock normals"),
                  ("specular_resource", "Original specular atlas", "Optional; blank keeps stock specular"),
                  ("emissive_resource", "Original emissive atlas", "Optional; blank keeps stock emissive"),
                  ("default_alias", "Default tile alias", "Tile for the blank CSV row, e.g. MA00SA0.MAP"),
                  ("prefix", "Resource prefix", "Use a unique mod-specific name")]
        for row, (key, label, hint) in enumerate(fields):
            ttk.Label(grid, text=label, style="Toolbox.Surface.TLabel", width=24).grid(row=row, column=0, sticky="w", pady=3)
            ttk.Entry(grid, textvariable=self.vars[key], style="Toolbox.TEntry").grid(row=row, column=1, sticky="ew", pady=3)
            ttk.Label(grid, text=hint, style="Toolbox.SurfaceMuted.TLabel").grid(row=row, column=2, sticky="w", padx=8)
        options = ttk.Frame(form, style="Toolbox.Surface.TFrame")
        options.pack(fill="x", pady=5)
        ttk.Label(options, text="Tile size", style="Toolbox.Surface.TLabel").pack(side="left")
        ttk.Combobox(options, textvariable=self.vars["tile_size"], values=(256, 512, 1024, 2048, 4096),
                     width=8, state="readonly", style="Toolbox.TCombobox").pack(side="left", padx=(8, 24))
        ttk.Label(options, text="Normal convention", style="Toolbox.Surface.TLabel").pack(side="left")
        ttk.Combobox(options, textvariable=self.vars["normal_space"], values=("directx", "opengl"),
                     width=10, state="readonly", style="Toolbox.TCombobox").pack(side="left", padx=8)
        ttk.Label(form, text="Normals: linear RGB XYZ. OpenGL flips green on export. Start with 1024px; "
                            "GPU size does not predict 32-bit game RAM.",
                  style="Toolbox.SurfaceMuted.TLabel").pack(anchor="w", pady=3)
        PathPicker(form, "New bundle folder", self.vars["out"], kind="dir", surface=True,
                   on_browse=self._choose_output).pack(fill="x", pady=4)
        actions = ttk.Frame(form, style="Toolbox.Surface.TFrame")
        actions.pack(fill="x", pady=(10, 0))
        for label, command in (("Load recipe…", self._load), ("Save recipe…", self._save),
                               ("Build bundle", self._build), ("Check bundle…", self._check)):
            ttk.Button(actions, text=label, command=command, style="Toolbox.TButton").pack(side="left", padx=(0, 6))
        self.log = LogView(body, height=12)
        self.log.pack(fill="both", expand=True)
        self.log.write("Choose source images or load an existing authoring.json recipe. "
                       "Build creates a fresh bundle with resources, editable masters and setup instructions.", "muted")

    def _choose_output(self):
        parent = filedialog.askdirectory(parent=self, title="Choose parent for a NEW HD terrain bundle")
        if parent:
            self.vars["out"].set(str(Path(parent) / "hd-terrain-bundle"))

    def _source_chosen(self, value):
        from battlezone.terrain.hd_tiles import load_project
        root = Path(value)
        self.project = None
        self._loaded_source = value
        if not self.vars["out"].get():
            self.vars["out"].set(str(root.parent / (root.name + "-bundle")))
        if (root / "authoring.json").is_file() or (root / "source_tiles.json").is_file():
            try:
                self._populate(load_project(root))
            except (OSError, ValueError, KeyError, TypeError) as exc:
                messagebox.showerror("HD terrain import", str(exc), parent=self)
        else:
            self.project = None

    def _populate(self, project):
        self.project = project
        keys = {"layout": "layout", "material": "material", "defaultAlias": "default_alias",
                "tileSize": "tile_size", "prefix": "prefix", "normalSpace": "normal_space"}
        for source, key in keys.items():
            self.vars[key].set(str(project.get(source, "directx" if source == "normalSpace" else "")))
        for channel, key in (("D", "diffuse_resource"), ("N", "normal_resource"),
                             ("S", "specular_resource"), ("E", "emissive_resource")):
            self.vars[key].set(project["resources"].get(channel, ""))

    def _form_project(self):
        from battlezone.terrain.hd_tiles import new_project
        import copy
        source = self.vars["sources"].get().strip()
        if source != self._loaded_source:
            self._source_chosen(source)
        form = {key: var.get().strip() for key, var in self.vars.items()}
        form["tile_size"] = int(form["tile_size"])
        if self.project is None:
            return new_project(form.pop("sources"), form.pop("layout"),
                               **{k: v for k, v in form.items() if k != "out"})
        project = copy.deepcopy(self.project)
        for field, key in (("material", "material"), ("layout", "layout"), ("defaultAlias", "default_alias"),
                           ("tileSize", "tile_size"), ("prefix", "prefix"), ("normalSpace", "normal_space")):
            project[field] = form[key]
        project["resources"] = {c: form[k] for c, k in (("D", "diffuse_resource"), ("N", "normal_resource"),
                                ("S", "specular_resource"), ("E", "emissive_resource")) if form[k]}
        return project

    def _load(self):
        from battlezone.terrain.hd_tiles import load_project
        path = filedialog.askopenfilename(parent=self, filetypes=(("Authoring recipe", "*.json"),))
        if path:
            try:
                self._populate(load_project(path))
                self.vars["sources"].set(str(Path(path).parent))
                self._loaded_source = str(Path(path).parent)
                self.vars["out"].set(str(Path(path).parent.parent / (Path(path).parent.name + "-rebuilt")))
            except (OSError, ValueError, KeyError, TypeError) as exc:
                messagebox.showerror("HD terrain recipe", str(exc), parent=self)

    def _save(self):
        from battlezone.terrain.hd_tiles import save_project
        try:
            project = self._form_project()
            path = filedialog.asksaveasfilename(parent=self, initialfile="authoring.json", defaultextension=".json")
            if path:
                save_project(path, project, overwrite=True)  # save dialog confirms replacement
                self.log.write(f"Recipe saved: {path}")
        except (OSError, ValueError, KeyError, TypeError) as exc:
            messagebox.showerror("HD terrain recipe", str(exc), parent=self)

    def _busy(self):
        return self.job is not None and self.job.status in ("queued", "running")

    def _build(self):
        from battlezone.terrain.hd_tiles import build_bundle
        if self._busy():
            return
        try:
            project = self._form_project()
            output = self.vars["out"].get().strip()
            if not output:
                raise ValueError("Choose a new bundle folder")
        except (OSError, ValueError, KeyError, TypeError) as exc:
            messagebox.showerror("HD terrain", str(exc), parent=self)
            return
        self.job = self.shell.jobs.submit("Build HD terrain bundle",
                    lambda job: build_bundle(project, output, progress=job.report, check_cancelled=job.check_cancelled),
                    on_done=self._done, on_error=self._failed)
        self.log.write("Building bundle… progress and Cancel are available in Jobs.")

    def _check(self):
        from battlezone.terrain.hd_tiles import check_bundle
        if self._busy():
            return
        folder = filedialog.askdirectory(parent=self, title="Check an exported HD terrain bundle")
        if folder:
            self.job = self.shell.jobs.submit("Check HD terrain bundle", lambda job: check_bundle(folder),
                                              on_done=self._done, on_error=self._failed)

    def _done(self, report):
        self.log.clear()
        self.log.write(json.dumps({k: v for k, v in report.items() if k != "sha256"}, indent=2))
        self.log.write("Validated. See the bundle's README.txt for installation and fallback setup.", "success")
        self.shell.status("HD terrain bundle validated")

    def _failed(self, error):
        self.log.write(error, "error")
        self.shell.status("HD terrain bundle failed")
