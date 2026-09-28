"""Assets > Legacy Model Port: Battlezone 1.5 .vdf/.sdf models to Redux Ogre assets."""

from __future__ import annotations

import os
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from bztoolbox.app.widgets import Card, LogView, PathPicker, ScrollableFrame

MODEL_TYPES = (("Legacy models", "*.vdf *.sdf"), ("Vehicles", "*.vdf"), ("Structures", "*.sdf"),
               ("All files", "*.*"))
PALETTE_TYPES = (("ACT palette", "*.act"), ("All files", "*.*"))


def default_output(model: str) -> str:
    path = Path(model)
    return str(path.with_name(path.stem.lower() + "_redux")) if model else ""


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

        body = ttk.Frame(self.body, style="Toolbox.TFrame", padding=(18, 4, 18, 18))
        body.pack(fill="both", expand=True)
        card = Card(body, "1.5 model → Redux mesh",
                    "Builds <model>.mesh, .skeleton and .material plus a diffuse texture per legacy .map, the way "
                    "Redux's own converted stock models are laid out: one bone per VDF/SDF part, the cockpit "
                    "(VDF band 4) on BZBaseCockpit materials. Keep the .vdf/.sdf and .geo files in the mod; "
                    "Redux still reads them for collision, hardpoints and animation.")
        card.pack(fill="x", pady=(0, 12))
        form = card.body
        PathPicker(form, "Model (.vdf/.sdf)", self.model, kind="file", filetypes=MODEL_TYPES, surface=True,
                   on_change=lambda v: self.output.set(default_output(v))).pack(fill="x", pady=2)
        PathPicker(form, "Output folder", self.output, kind="dir", surface=True).pack(fill="x", pady=2)
        PathPicker(form, "Extra .geo/.map folder", self.textures, kind="dir", surface=True).pack(fill="x", pady=2)
        PathPicker(form, "Battlezone 1.5 install", self.game15, kind="dir", surface=True).pack(fill="x", pady=2)
        PathPicker(form, "Palette (.act)", self.palette, kind="file", filetypes=PALETTE_TYPES,
                   surface=True).pack(fill="x", pady=2)
        ttk.Label(form, text="Parts and textures are looked up beside the model, then in the extra folder, then in "
                             "the 1.5 install's ZFS archives. The palette only matters for 8-bit maps; empty uses "
                             "moon.act (every stock world palette shares the object colours).",
                  style="Toolbox.SurfaceMuted.TLabel", wraplength=900, justify="left").pack(anchor="w")

        grid = ttk.Frame(form, style="Toolbox.Surface.TFrame")
        grid.pack(fill="x", pady=(6, 2))
        ttk.Label(grid, text="Texture format", style="Toolbox.Surface.TLabel", width=18).grid(row=0, column=0, sticky="w")
        ttk.Combobox(grid, textvariable=self.format, values=("png", "dds", "none"), state="readonly", width=8,
                     style="Toolbox.TCombobox").grid(row=0, column=1, sticky="w")
        ttk.Label(grid, text="Normals", style="Toolbox.Surface.TLabel", width=18).grid(row=1, column=0, sticky="w",
                                                                                     pady=(4, 0))
        ttk.Combobox(grid, textvariable=self.normals, values=("smooth", "flat", "stored"), state="readonly",
                     width=8, style="Toolbox.TCombobox").grid(row=1, column=1, sticky="w", pady=(4, 0))
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
        self.log.write("Pick a .vdf or .sdf.", "muted")

    def _detect_legacy_install(self) -> str:
        try:
            from bztoolbox import launch

            installs = launch.detect_installs(getattr(self.shell, "settings", None))
        except Exception:
            return ""
        return next((str(i.path) for i in installs if i.kind == "1.5"), "")

    def port(self) -> None:
        if self.job is not None and self.job.status in ("queued", "running"):
            return
        model, output = self.model.get().strip(), self.output.get().strip()
        if not model or not os.path.isfile(model) or Path(model).suffix.lower() not in (".vdf", ".sdf"):
            messagebox.showerror("Legacy model port", "Select a .vdf or .sdf file.")
            return
        if not output:
            messagebox.showerror("Legacy model port", "Choose an output folder.")
            return
        if os.path.isdir(output) and os.listdir(output) and not messagebox.askyesno(
                "Output folder is not empty", f"Files of the same name will be replaced in\n\n{output}"):
            return
        textures, game15, palette = self.textures.get().strip(), self.game15.get().strip(), self.palette.get().strip()
        fmt, normals, texture_names = self.format.get(), self.normals.get(), self.texture_names.get()
        self.port_button.state(["disabled"])
        self.log.clear()

        def work(_job):
            from battlezone.meshes.legacy_port import (PortOptions, resolve_palette, legacy_archives,
                                                       port_legacy_model)

            options = PortOptions(material_names="texture" if texture_names else "model", normals=normals,
                                  texture_format=fmt)
            return port_legacy_model(model, output, search=[textures] if textures else [],
                                     archives=legacy_archives(game15) if game15 else [],
                                     palette=resolve_palette(palette or None), options=options)

        self.job = self.shell.jobs.submit(f"Port {Path(model).name}", work, on_done=self._done,
                                          on_error=self._failed)

    def _done(self, result) -> None:
        self.port_button.state(["!disabled"])
        for line in result.summary().splitlines():
            self.log.write(line, "warning" if line.strip().startswith("warning") else "")
        self.log.write(f"Done: {len(result.written)} files", "success" if result.mesh.submeshes else "warning")
        self.shell.status(f"Ported {result.name}")

    def _failed(self, error: str) -> None:
        self.port_button.state(["!disabled"])
        self.log.write(error, "error")
