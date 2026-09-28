"""Assets > Legacy Model Port: Battlezone 1.5 .vdf/.sdf models to Redux Ogre assets."""

from __future__ import annotations

import os
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from bztoolbox.app.widgets import Card, LogView, PathPicker, ScrollableFrame

PORTABLE = (".vdf", ".sdf", ".odf", ".geo", ".map")
MODEL_TYPES = (("Legacy models", "*.vdf *.sdf *.odf *.geo *.map"), ("Vehicles", "*.vdf"), ("Structures", "*.sdf"),
               ("Object definitions", "*.odf"), ("Single part", "*.geo"), ("Texture", "*.map"), ("All files", "*.*"))
PALETTE_TYPES = (("ACT palette", "*.act"), ("All files", "*.*"))
TRISTATE = ("auto", "yes", "no")


def default_output(model: str) -> str:
    path = Path(model)
    return str(path.with_name(path.stem.lower() + "_redux")) if model else ""


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
        card = Card(body, "1.5 model → Redux mesh",
                    "Builds <model>.mesh, .skeleton and .material plus a diffuse texture per legacy .map, the way "
                    "Redux's own converted stock models are laid out: one bone per VDF/SDF part, the cockpit "
                    "(VDF band 4) on BZBaseCockpit materials, pilots with Redux's named animations. An .odf ports "
                    "the model it names (its class marks pilots and turrets); a .geo becomes a one-bone mesh, a "
                    ".map just a texture. Keep the .vdf/.sdf and .geo files in the mod; Redux still reads them "
                    "for collision, hardpoints and animation.")
        card.pack(fill="x", pady=(0, 12))
        form = card.body
        picker = PathPicker(form, "Model file", self.model, kind="file", filetypes=MODEL_TYPES, surface=True,
                            on_change=lambda v: self.output.set(default_output(v)))
        picker.pack(fill="x", pady=2)
        PathPicker(form, "Output folder", self.output, kind="dir", surface=True).pack(fill="x", pady=2)
        PathPicker(form, "Extra .geo/.map folder", self.textures, kind="dir", surface=True).pack(fill="x", pady=2)
        PathPicker(form, "Battlezone 1.5 install", self.game15, kind="dir", surface=True).pack(fill="x", pady=2)
        PathPicker(form, "Palette (.act)", self.palette, kind="file", filetypes=PALETTE_TYPES,
                   surface=True).pack(fill="x", pady=2)
        hint = ("Parts and textures are looked up beside the model, then in the extra folder, then in the 1.5 "
                "install's ZFS archives. The palette only matters for 8-bit maps; empty uses moon.act (every stock "
                "world palette shares the object colours).")
        if _dnd_ready(self):
            from tkinterdnd2 import DND_FILES  # type: ignore

            for target in (picker, picker.entry):
                target.drop_target_register(DND_FILES)
                target.dnd_bind("<<Drop>>", self._on_drop)
            hint += " Drop a model file on the Model field to pick it."
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

        actions = ttk.Frame(form, style="Toolbox.Surface.TFrame")
        actions.pack(fill="x", pady=(10, 0))
        self.port_button = ttk.Button(actions, text="Port model", style="Toolbox.Accent.TButton", command=self.port)
        self.port_button.pack(side="left")

        ttk.Label(body, text="RESULT", style="Toolbox.Heading.TLabel").pack(anchor="w")
        self.log = LogView(body, height=14)
        self.log.pack(fill="both", expand=True, pady=(4, 0))
        self.log.write("Pick a .vdf, .sdf, .odf, .geo or .map.", "muted")

    def _detect_legacy_install(self) -> str:
        try:
            from bztoolbox import launch

            installs = launch.detect_installs(getattr(self.shell, "settings", None))
        except Exception:
            return ""
        return next((str(i.path) for i in installs if i.kind == "1.5"), "")

    def _on_drop(self, event) -> None:
        paths = [p for p in dropped_paths(self, event.data) if Path(p).suffix.lower() in PORTABLE]
        if not paths:
            self.log.write("Drop a .vdf, .sdf, .odf, .geo or .map file.", "warning")
            return
        self.model.set(os.path.normpath(paths[0]))
        self.output.set(default_output(self.model.get()))
        if len(paths) > 1:
            self.log.write(f"{len(paths)} files dropped; picked {Path(paths[0]).name}. For batches use "
                           "scripts/meshes/port_legacy_drop.cmd or bztoolbox meshes port-legacy.", "warning")

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
        self.log.write(error, "error")
