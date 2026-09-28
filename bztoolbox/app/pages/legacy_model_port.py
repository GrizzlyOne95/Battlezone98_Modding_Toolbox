"""1.5 Asset Porting: VDF/SDF/GEO assets to Redux Ogre assets."""

from __future__ import annotations

import os
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from bztoolbox.app.widgets import Card, LogView, PathPicker, ScrollableFrame

PORTABLE = (".vdf", ".sdf", ".odf", ".geo", ".map")
MODEL_TYPES = (("Legacy models", "*.vdf *.sdf *.odf *.geo *.map"), ("Vehicles", "*.vdf"), ("Structures", "*.sdf"),
               ("Object definitions", "*.odf"), ("Single part", "*.geo"), ("Texture", "*.map"), ("All files", "*.*"))
PALETTE_TYPES = (("ACT palette", "*.act"), ("All files", "*.*"))
TRISTATE = ("auto", "yes", "no")


def default_output(model: str) -> str:
    path = Path(model)
    return str(path.with_name(path.stem.lower() + "_redux")) if model else ""


def default_batch_output(folder: str) -> str:
    path = Path(folder)
    return str(path.with_name(path.name + "_redux")) if folder else ""


def batch_files(folder: str, output: str, recursive: bool = False) -> list[Path]:
    """Snapshot supported inputs before writing; never rescan the output tree."""
    source = Path(folder).resolve()
    destination = Path(output).resolve()
    output_inside_source = destination != source and destination.is_relative_to(source)
    matches = source.rglob("*") if recursive else source.iterdir()
    return sorted((path for path in matches if path.is_file() and path.suffix.lower() in PORTABLE
                   and (not output_inside_source or not path.resolve().is_relative_to(destination))),
                  key=lambda path: str(path).lower())


def dropped_paths(widget, data: str):
    """File paths from a tkdnd ``<<Drop>>`` event (braced when they contain spaces)."""
    try:
        return [str(p) for p in widget.tk.splitlist(data)]
    except tk.TclError:
        return [data.strip("{}")]


def _dnd_ready(widget) -> bool:
    """Drag and drop needs the tkdnd-enabled root the shell makes when tkinterdnd2 is installed."""
    try:
        import tkinterdnd2  # noqa: F401  # type: ignore

        widget.tk.call("package", "present", "tkdnd")
        return True
    except Exception:  # noqa: BLE001
        return False


def _tristate(value: str):
    return {"yes": True, "no": False}.get(value)


class LegacyModelPortPage(ScrollableFrame):
    def __init__(self, master, shell):
        super().__init__(master)
        self.shell = shell
        self.job = None
        self.model = tk.StringVar()
        self.output = tk.StringVar()
        self.batch_folder = tk.StringVar()
        self.batch_output = tk.StringVar()
        self.recursive = tk.BooleanVar(value=False)
        self.textures = tk.StringVar()
        self.game15 = tk.StringVar(value=self._detect_legacy_install())
        self.palette = tk.StringVar()
        self.texture_names = tk.BooleanVar(value=False)
        self.format = tk.StringVar(value="png")
        self.normals = tk.StringVar(value="smooth")
        self.headlights = tk.BooleanVar(value=True)
        self.flat_colours = tk.BooleanVar(value=False)
        self.person = tk.StringVar(value="auto")
        self.cockpit = tk.StringVar(value="auto")
        self.turret = tk.StringVar(value="auto")
        self.scope = tk.StringVar(value="auto")
        self.scope_type = tk.StringVar(value="auto")

        body = ttk.Frame(self.body, style="Toolbox.TFrame", padding=(18, 4, 18, 18))
        body.pack(fill="both", expand=True)
        single = Card(body, "Single asset", "Choose a VDF, SDF or GEO directly; ODF and MAP are also supported. "
                      "An ODF ports its referenced model; a MAP creates a Redux model diffuse texture. "
                      "For general MAP ↔ PNG conversion, use Assets › Textures & Images.")
        single.pack(fill="x", pady=(0, 12))
        form = single.body
        quick = ttk.Frame(form, style="Toolbox.Surface.TFrame")
        quick.pack(fill="x", pady=(0, 6))
        for label, suffix in (("Select VDF…", ".vdf"), ("Select SDF…", ".sdf"),
                              ("Select GEO…", ".geo"), ("Select ODF…", ".odf"),
                              ("Select MAP…", ".map")):
            ttk.Button(quick, text=label, command=lambda ext=suffix: self.select_file(ext),
                       style="Toolbox.TButton").pack(side="left", padx=(0, 6))
        picker = PathPicker(form, "Model file", self.model, kind="file", filetypes=MODEL_TYPES, surface=True,
                            on_change=lambda v: self.output.set(default_output(v)))
        picker.pack(fill="x", pady=2)
        PathPicker(form, "Output folder", self.output, kind="dir", surface=True).pack(fill="x", pady=2)
        self.port_button = ttk.Button(form, text="Port selected file", style="Toolbox.Accent.TButton", command=self.port)
        self.port_button.pack(anchor="w", pady=(8, 0))

        batch = Card(body, "Folder batch", "Ports every VDF, SDF, ODF, GEO and MAP in a folder. Each source gets "
                     "a separate output subfolder so similarly named assets cannot overwrite one another.")
        batch.pack(fill="x", pady=(0, 12))
        batch_form = batch.body
        PathPicker(batch_form, "Source folder", self.batch_folder, kind="dir", surface=True,
                   on_change=lambda v: self.batch_output.set(default_batch_output(v))).pack(fill="x", pady=2)
        PathPicker(batch_form, "Output folder", self.batch_output, kind="dir", surface=True).pack(fill="x", pady=2)
        ttk.Checkbutton(batch_form, text="Include subfolders", variable=self.recursive,
                        style="Toolbox.Surface.TCheckbutton").pack(anchor="w", pady=(4, 0))
        self.batch_button = ttk.Button(batch_form, text="Port folder", style="Toolbox.Accent.TButton",
                                       command=self.port_batch)
        self.batch_button.pack(anchor="w", pady=(8, 0))

        drop = Card(body, "Drop to port", "Drop one or more supported files, or a folder. The toolbox selects "
                    "the matching port and starts it automatically.")
        drop.pack(fill="x", pady=(0, 12))
        drop_label = ttk.Label(drop.body, text="Drop VDF · SDF · ODF · GEO · MAP files or a folder here",
                               style="Toolbox.Surface.TLabel", anchor="center", padding=14)
        drop_label.pack(fill="x")
        if _dnd_ready(self):
            from tkinterdnd2 import DND_FILES  # type: ignore

            for target in (drop, drop.body, drop_label, picker, picker.entry, batch, batch.body):
                target.drop_target_register(DND_FILES)
                target.dnd_bind("<<Drop>>", self._on_drop)
        else:
            drop_label.configure(text="Drag and drop requires tkinterdnd2; use the file and folder buttons above.")

        settings = Card(body, "Conversion settings", "Shared by single file, batch, and drop ports. "
                        "Keep source VDF/SDF and GEO files in your mod for Redux collision and hardpoints.")
        settings.pack(fill="x", pady=(0, 12))
        form = settings.body
        PathPicker(form, "Extra .geo/.map folder", self.textures, kind="dir", surface=True).pack(fill="x", pady=2)
        PathPicker(form, "Battlezone 1.5 install", self.game15, kind="dir", surface=True).pack(fill="x", pady=2)
        PathPicker(form, "Palette (.act)", self.palette, kind="file", filetypes=PALETTE_TYPES,
                   surface=True).pack(fill="x", pady=2)
        hint = ("Parts and textures are looked up beside the model, then in the extra folder, then in the 1.5 "
                "install's ZFS archives. The palette only matters for 8-bit maps; empty uses moon.act (every stock "
                "world palette shares the object colours).")
        ttk.Label(form, text=hint, style="Toolbox.SurfaceMuted.TLabel", wraplength=900,
                  justify="left").pack(anchor="w")

        grid = ttk.Frame(form, style="Toolbox.Surface.TFrame")
        grid.pack(fill="x", pady=(6, 2))
        combos = (("Texture format", self.format, ("png", "dds", "none")),
                  ("Normals", self.normals, ("smooth", "flat", "stored")),
                  ("Person (pilot)", self.person, TRISTATE),
                  ("Cockpit mesh", self.cockpit, TRISTATE),
                  ("Turret", self.turret, TRISTATE),
                  ("Sniper scope", self.scope, TRISTATE),
                  ("Scope type", self.scope_type, ("auto", "fixed", "attached", "geometry")))
        for i, (label, variable, values) in enumerate(combos):
            row, column = i % 4, (i // 4) * 2
            ttk.Label(grid, text=label, style="Toolbox.Surface.TLabel", width=18).grid(
                row=row, column=column, sticky="w", pady=(0 if row == 0 else 4, 0), padx=(0 if column == 0 else 24, 0))
            ttk.Combobox(grid, textvariable=variable, values=values, state="readonly", width=9,
                         style="Toolbox.TCombobox").grid(row=row, column=column + 1, sticky="w",
                                                         pady=(0 if row == 0 else 4, 0))
        ttk.Label(form, text="auto: a person is a pilot ODF class (or a ?s???? name); the cockpit gets its own "
                             "_fp/_c/_cockpit mesh when it animates or the model is a turret/howitzer; persons get "
                             "a scope, textured on __scope faces if there are any, else a fixed screen square.",
                  style="Toolbox.SurfaceMuted.TLabel", wraplength=900, justify="left").pack(anchor="w", pady=(4, 0))
        ttk.Checkbutton(form, text="Headlight bones (HLGT) at headlight parts", variable=self.headlights,
                        style="Toolbox.Surface.TCheckbutton").pack(anchor="w")
        ttk.Checkbutton(form, text="Flat colours: every face from its GEO face colour instead of its .map",
                        variable=self.flat_colours, style="Toolbox.Surface.TCheckbutton").pack(anchor="w")
        ttk.Checkbutton(form, text="Name materials after the legacy texture (stock style; clashes with a stock "
                                   "material of the same name)",
                        variable=self.texture_names, style="Toolbox.Surface.TCheckbutton").pack(anchor="w")

        ttk.Label(body, text="RESULT", style="Toolbox.Heading.TLabel").pack(anchor="w")
        self.log = LogView(body, height=14)
        self.log.pack(fill="both", expand=True, pady=(4, 0))
        self.log.write("Choose a file or folder, or drop assets to port.", "muted")

    def _detect_legacy_install(self) -> str:
        try:
            from bztoolbox import launch

            installs = launch.detect_installs(getattr(self.shell, "settings", None))
        except Exception:
            return ""
        return next((str(i.path) for i in installs if i.kind == "1.5"), "")

    def select_file(self, suffix: str) -> None:
        current = self.model.get().strip()
        chosen = filedialog.askopenfilename(title=f"Select {suffix.upper()} asset",
                                            initialdir=str(Path(current).parent) if current else None,
                                            filetypes=((f"{suffix.upper()} files", f"*{suffix}"),
                                                       ("All files", "*.*")))
        if chosen:
            self.model.set(os.path.normpath(chosen))
            self.output.set(default_output(self.model.get()))

    def _on_drop(self, event) -> None:
        paths = [Path(p) for p in dropped_paths(self, event.data)]
        folders = [p for p in paths if p.is_dir()]
        files = [p for p in paths if p.is_file() and p.suffix.lower() in PORTABLE]
        if len(folders) == 1 and not files and len(paths) == 1:
            self.batch_folder.set(os.path.normpath(str(folders[0])))
            self.batch_output.set(default_batch_output(self.batch_folder.get()))
            self.port_batch()
            return
        if not files or folders:
            self.log.write("Drop supported files or one folder at a time.", "warning")
            return
        if len(files) == 1:
            self.model.set(os.path.normpath(str(files[0])))
            self.output.set(default_output(self.model.get()))
            self.port()
            return
        parent = files[0].parent
        self.batch_folder.set(str(parent))
        self.batch_output.set(default_batch_output(str(parent)))
        self.port_batch(files=files)

    def options(self):
        from battlezone.meshes.legacy_port import PortOptions

        return PortOptions(material_names="texture" if self.texture_names.get() else "model",
                           normals=self.normals.get(), texture_format=self.format.get(),
                           headlights=self.headlights.get(), flat_colours=self.flat_colours.get(),
                           person=_tristate(self.person.get()), cockpit_files=_tristate(self.cockpit.get()),
                           turret=_tristate(self.turret.get()), scope=_tristate(self.scope.get()),
                           scope_type=self.scope_type.get())

    def port(self) -> None:
        if self.job is not None and self.job.status in ("queued", "running"):
            return
        model, output = self.model.get().strip(), self.output.get().strip()
        if not model or not os.path.isfile(model) or Path(model).suffix.lower() not in PORTABLE:
            messagebox.showerror("Legacy model port", "Select a .vdf, .sdf, .odf, .geo or .map file.")
            return
        if not output:
            messagebox.showerror("Legacy model port", "Choose an output folder.")
            return
        if os.path.isdir(output) and os.listdir(output) and not messagebox.askyesno(
                "Output folder is not empty", f"Files of the same name will be replaced in\n\n{output}"):
            return
        textures, game15, palette = self.textures.get().strip(), self.game15.get().strip(), self.palette.get().strip()
        options = self.options()
        self.port_button.state(["disabled"])
        self.batch_button.state(["disabled"])
        self.log.clear()

        def work(_job):
            from battlezone.meshes.legacy_port import legacy_archives, port_file, resolve_palette

            return port_file(model, output, search=[textures] if textures else [],
                             archives=legacy_archives(game15) if game15 else [],
                             palette=resolve_palette(palette or None), options=options)

        self.job = self.shell.jobs.submit(f"Port {Path(model).name}", work, on_done=self._done,
                                          on_error=self._failed)

    def _done(self, result) -> None:
        self.port_button.state(["!disabled"])
        self.batch_button.state(["!disabled"])
        if result.kind == "map":
            self.log.write(f"Texture {result.texture_files[result.name]}", "")
            ok = bool(result.written)
        else:
            for line in result.summary().splitlines():
                self.log.write(line, "warning" if line.strip().startswith("warning") else "")
            ok = any(m.submeshes for _, m in result.meshes())
        self.log.write(f"Done: {len(result.written)} files", "success" if ok else "warning")
        self.shell.status(f"Ported {result.name}")

    def _failed(self, error: str) -> None:
        self.port_button.state(["!disabled"])
        self.batch_button.state(["!disabled"])
        self.log.write(error, "error")

    def port_batch(self, files: list[Path] | None = None) -> None:
        if self.job is not None and self.job.status in ("queued", "running"):
            return
        folder = self.batch_folder.get().strip()
        output = self.batch_output.get().strip()
        if not folder or not Path(folder).is_dir():
            messagebox.showerror("Redux asset port", "Select a source folder.")
            return
        if not output:
            messagebox.showerror("Redux asset port", "Choose an output folder.")
            return
        sources = files if files is not None else batch_files(folder, output, self.recursive.get())
        sources = [p.resolve() for p in sources if p.is_file() and p.suffix.lower() in PORTABLE]
        if not sources:
            messagebox.showerror("Redux asset port", "No VDF, SDF, ODF, GEO or MAP files found.")
            return
        root = Path(folder).resolve()
        destination = Path(output).resolve()
        if root == destination:
            messagebox.showerror("Redux asset port", "Choose an output folder different from the source folder.")
            return
        targets = []
        for source in sources:
            try:
                relative = source.relative_to(root)
            except ValueError:
                relative = Path(source.name)
            targets.append(destination / relative.parent / f"{relative.stem}_{relative.suffix[1:].lower()}")
        if len(set(targets)) != len(targets):
            messagebox.showerror("Redux asset port", "The selected files have duplicate output names.")
            return
        occupied = [target for target in targets if target.is_dir() and any(target.iterdir())]
        if occupied and not messagebox.askyesno(
                "Output folders are not empty", f"{len(occupied)} asset output folders contain files. "
                f"Files of the same name may be replaced in\n\n{output}"):
            return
        textures, game15, palette = self.textures.get().strip(), self.game15.get().strip(), self.palette.get().strip()
        options = self.options()
        self.port_button.state(["disabled"])
        self.batch_button.state(["disabled"])
        self.log.clear()
        self.log.write(f"Porting {len(sources)} assets to {destination}")

        def work(job):
            from battlezone.meshes.legacy_port import legacy_archives, port_file, resolve_palette

            archives = legacy_archives(game15) if game15 else []
            resolved_palette = resolve_palette(palette or None)
            results = []
            for index, (source, target) in enumerate(zip(sources, targets)):
                job.check_cancelled()
                job.report(index / len(sources), f"Porting {source.name} ({index + 1}/{len(sources)})")
                try:
                    result = port_file(source, target, search=[textures] if textures else [],
                                       archives=archives, palette=resolved_palette, options=options)
                    results.append((source, result, ""))
                except Exception as exc:  # keep remaining assets moving; report each failure below
                    results.append((source, None, f"{exc.__class__.__name__}: {exc}"))
            return results

        self.job = self.shell.jobs.submit(f"Port {len(sources)} legacy assets", work,
                                          on_done=self._batch_done, on_error=self._failed)

    def _batch_done(self, results) -> None:
        self.port_button.state(["!disabled"])
        self.batch_button.state(["!disabled"])
        success = 0
        for source, result, error in results:
            if error:
                self.log.write(f"{source.name}: {error}", "error")
            else:
                success += 1
                self.log.write(f"{source.name}: {len(result.written)} files", "success")
                for warning in result.warnings:
                    self.log.write(f"  {warning}", "warning")
        self.log.write(f"Finished: {success}/{len(results)} assets ported",
                       "success" if success == len(results) else "warning")
        self.shell.status(f"Ported {success}/{len(results)} legacy assets")
