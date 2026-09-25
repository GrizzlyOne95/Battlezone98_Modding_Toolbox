"""Missions > BZCC to Redux Port: terrain first, then the mission, with safe defaults."""

from __future__ import annotations

import contextlib
import io
import os
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from battlezone.bzn.port_form import build_port_arguments
from bztoolbox.app.widgets import Card, LogView, PathPicker, ScrollableFrame

BZN_TYPES = (("BZN missions", "*.bzn"), ("All files", "*.*"))
JSON_TYPES = (("JSON", "*.json"), ("All files", "*.*"))

# Defaults a first conversion can rely on: class-compatible auto-mapping only;
# nothing approximate, unsafe or partial is written unless asked for.
SAFE_FLAGS = {"auto_map": True, "allow_approximate": False, "allow_unsafe_classes": False, "allow_skips": False}
FLAG_LABELS = (
    ("auto_map", "Auto-map unmapped ODFs to a class-compatible template object"),
    ("allow_approximate", "Allow approximate classes (e.g. terrain props become buildings)"),
    ("allow_unsafe_classes", "Write the mission even when the class check finds unsafe objects"),
    ("allow_skips", "Write a partial mission when objects have no Redux prototype"),
)


class BZCCPortPage(ScrollableFrame):
    def __init__(self, master, shell):
        super().__init__(master)
        self.shell = shell
        self.job = None
        self.fields = {key: tk.StringVar(value="LuaMission" if key == "mission" else "")
                       for key in ("source", "template", "output", "mapping", "team_map", "offset_from",
                                   "offset_x", "offset_y", "offset_z", "report", "terrain", "mission",
                                   "source_odfs", "redux_odfs")}
        self.flags = {key: tk.BooleanVar(value=value) for key, value in SAFE_FLAGS.items()}
        self.advanced_var = tk.BooleanVar(value=False)

        body = ttk.Frame(self.body, style="Toolbox.TFrame", padding=(18, 4, 18, 18))
        body.pack(fill="both", expand=True)

        terrain = Card(body, "1. Terrain", "Port the BZ2/BZCC terrain first. The port writes <name>_port.json, "
                                           "which holds the offset that lines the mission's objects up with "
                                           "the new terrain.")
        terrain.pack(fill="x", pady=(0, 12))
        ttk.Button(terrain.body, text="Open World Builder › BZ2 → BZ1 Map Port", style="Toolbox.TButton",
                   command=self.open_terrain_port).pack(anchor="w")

        mission = Card(body, "2. Mission", "Pick the files and press Convert. Nothing is written until then.")
        mission.pack(fill="x", pady=(0, 12))
        form = mission.body
        for key, label, kind, types in (
                ("source", "BZCC source BZN", "file", BZN_TYPES),
                ("template", "Redux template BZN", "file", BZN_TYPES),
                ("output", "Output Redux BZN", "save", BZN_TYPES),
                ("offset_from", "Terrain port report", "file", JSON_TYPES)):
            PathPicker(form, label, self.fields[key], kind=kind, filetypes=types, surface=True,
                       on_change=lambda _v, k=key: self._path_chosen(k)).pack(fill="x", pady=2)
        ttk.Label(form, text="Template: an ASCII Redux mission that contains one object of every kind the "
                             "port may place. Terrain port report: optional, but without it objects keep "
                             "their BZCC positions.", style="Toolbox.SurfaceMuted.TLabel", wraplength=900,
                  justify="left").pack(anchor="w", pady=(4, 6))

        ttk.Checkbutton(form, text="Show advanced options", variable=self.advanced_var,
                        style="Toolbox.Surface.TCheckbutton", command=self._toggle_advanced).pack(anchor="w")
        self.advanced = ttk.Frame(form, style="Toolbox.Surface.TFrame", padding=(0, 6, 0, 0))
        self._build_advanced(self.advanced)

        self.actions = ttk.Frame(form, style="Toolbox.Surface.TFrame")
        self.actions.pack(fill="x", pady=(10, 0))
        self.convert_button = ttk.Button(self.actions, text="Convert", style="Toolbox.Accent.TButton",
                                         command=self.convert)
        self.convert_button.pack(side="left")
        self.validate_button = ttk.Button(self.actions, text="Validate output", style="Toolbox.TButton",
                                          command=self.validate_output, state="disabled")
        self.validate_button.pack(side="left", padx=6)
        ttk.Button(self.actions, text="Reset to safe defaults", style="Toolbox.TButton",
                   command=self.reset_defaults).pack(side="left")

        ttk.Label(body, text="RESULT", style="Toolbox.Heading.TLabel").pack(anchor="w")
        self.log = LogView(body, height=12)
        self.log.pack(fill="both", expand=True, pady=(4, 0))
        self.log.write("Select a BZCC mission, a Redux template and an output file, then press Convert.", "muted")

    # ------------------------------------------------------------------ form
    def _build_advanced(self, parent) -> None:
        for key, label, kind, types in (
                ("mapping", "ODF mapping JSON", "file", JSON_TYPES),
                ("team_map", "Team mapping JSON", "file", JSON_TYPES),
                ("report", "Conversion report", "save", JSON_TYPES)):
            PathPicker(parent, label, self.fields[key], kind=kind, filetypes=types, surface=True).pack(fill="x", pady=2)
        for key, label in (("source_odfs", "Source ODF folders"), ("redux_odfs", "Redux ODF folders")):
            PathPicker(parent, label, self.fields[key], kind="dir", surface=True,   # "; " separated list
                       on_browse=lambda k=key: self._add_folder(k)).pack(fill="x", pady=2)
        grid = ttk.Frame(parent, style="Toolbox.Surface.TFrame")
        grid.pack(fill="x", pady=(4, 2))
        ttk.Label(grid, text="Terrain name override", style="Toolbox.Surface.TLabel", width=18).grid(row=0, column=0, sticky="w")
        ttk.Entry(grid, textvariable=self.fields["terrain"], style="Toolbox.TEntry", width=24).grid(row=0, column=1, sticky="w")
        ttk.Label(grid, text="Redux mission class", style="Toolbox.Surface.TLabel").grid(row=0, column=2, sticky="w", padx=(16, 6))
        ttk.Entry(grid, textvariable=self.fields["mission"], style="Toolbox.TEntry", width=18).grid(row=0, column=3, sticky="w")
        ttk.Label(grid, text="Manual offset X/Y/Z", style="Toolbox.Surface.TLabel", width=18).grid(row=1, column=0, sticky="w", pady=(4, 0))
        offsets = ttk.Frame(grid, style="Toolbox.Surface.TFrame")
        offsets.grid(row=1, column=1, columnspan=3, sticky="w", pady=(4, 0))
        for key in ("offset_x", "offset_y", "offset_z"):
            ttk.Entry(offsets, textvariable=self.fields[key], style="Toolbox.TEntry", width=10).pack(side="left", padx=(0, 6))
        ttk.Label(offsets, text="(instead of a terrain port report)", style="Toolbox.SurfaceMuted.TLabel").pack(side="left")
        for key, label in FLAG_LABELS:
            ttk.Checkbutton(parent, text=label, variable=self.flags[key],
                            style="Toolbox.Surface.TCheckbutton").pack(anchor="w")
        ttk.Label(parent, text="Teams outside 0–15 need a team map. Setting Redux ODF folders turns on the "
                               "class check.", style="Toolbox.SurfaceMuted.TLabel").pack(anchor="w", pady=(4, 0))

    def _toggle_advanced(self) -> None:
        if self.advanced_var.get():
            self.advanced.pack(fill="x", before=self.actions)
        else:
            self.advanced.pack_forget()

    def _add_folder(self, key: str) -> None:
        from tkinter import filedialog

        folder = filedialog.askdirectory(title=f"Add {key.replace('_', ' ')} folder", mustexist=True)
        if folder:
            previous = self.fields[key].get().strip()
            self.fields[key].set(previous + ("; " if previous else "") + os.path.normpath(folder))

    def _path_chosen(self, key: str) -> None:
        """Fill in the obvious follow-ups so the basic form needs as few picks as possible."""
        source = self.fields["source"].get().strip()
        if key == "source" and source:
            stem = Path(source).stem
            project = self.shell.project
            if not self.fields["output"].get().strip() and project is not None:
                self.fields["output"].set(os.path.join(project.mod_path, f"{stem}.bzn"))
            if not self.fields["offset_from"].get().strip():
                report = self._find_terrain_report(stem)
                if report:
                    self.fields["offset_from"].set(report)
        output = self.fields["output"].get().strip()
        if key in ("source", "output") and output:
            self.fields["report"].set(str(Path(output).with_name(Path(output).stem + "_port_report.json")))

    def _find_terrain_report(self, stem: str):
        roots = [Path(self.fields["source"].get()).parent]
        if self.shell.project is not None:
            roots.append(Path(self.shell.project.mod_path))
        wanted = f"{stem}_port.json".lower()
        for root in roots:
            try:
                for path in root.rglob("*_port.json"):
                    if path.name.lower() == wanted:
                        return str(path)
            except OSError:
                continue
        return None

    def reset_defaults(self) -> None:
        for key, value in SAFE_FLAGS.items():
            self.flags[key].set(value)
        for key in ("mapping", "team_map", "terrain", "offset_x", "offset_y", "offset_z",
                    "source_odfs", "redux_odfs"):
            self.fields[key].set("")
        self.fields["mission"].set("LuaMission")
        self._path_chosen("output")

    # --------------------------------------------------------------- actions
    def open_terrain_port(self) -> None:
        self.shell.navigate("world.builder")
        app = self.shell._pages["world.builder"].app
        tab = getattr(app, "tab_bz2_port", None)
        if tab is not None:
            app.notebook.select(tab)

    def convert(self) -> None:
        if self.job is not None and self.job.status in ("queued", "running"):
            return
        try:
            args = build_port_arguments({k: v.get() for k, v in self.fields.items()},
                                        {k: v.get() for k, v in self.flags.items()})
        except ValueError as exc:
            messagebox.showerror("BZCC to Redux Port", str(exc))
            return
        output = Path(self.fields["output"].get().strip())
        if output.exists() and not messagebox.askyesno("Replace output?", f"Replace the existing file?\n\n{output}"):
            return
        self.convert_button.state(["disabled"])
        self.log.clear()
        self.log.write(f"Converting {Path(args[0]).name} → {output.name}…", "info")

        def work(_job):
            from battlezone.bzn.bzcc_port import main as port_main

            stdout, stderr = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = port_main(args)
            text = "\n".join(part.strip() for part in (stdout.getvalue(), stderr.getvalue()) if part.strip())
            return code, text

        self.job = self.shell.jobs.submit(f"Port {Path(args[0]).name}", work,
                                          on_done=self._converted, on_error=self._failed)

    def _converted(self, result) -> None:
        code, text = result
        self.convert_button.state(["!disabled"])
        if text:
            self.log.write(text, "error" if code else "")
        if code:
            self.log.write("Conversion failed. Nothing usable was written; see the messages above.", "error")
            self.shell.status("BZCC port failed.")
            return
        output = self.fields["output"].get().strip()
        self.log.write(f"Done: {output}", "success")
        self.validate_button.state(["!disabled"])
        self.shell.status(f"Ported mission written to {output}")

    def _failed(self, error: str) -> None:
        self.convert_button.state(["!disabled"])
        self.log.write(error, "error")

    def validate_output(self) -> None:
        output = self.fields["output"].get().strip()
        if not output or not os.path.isfile(output):
            return
        project = self.shell.project
        inside = project is not None and os.path.normcase(os.path.abspath(output)).startswith(
            os.path.normcase(os.path.abspath(project.mod_path)) + os.sep)
        self.shell.navigate("project.validation")
        validation = self.shell._pages["project.validation"].widget
        if inside:
            validation.run()
        else:
            validation.validate_folder(os.path.dirname(output))
