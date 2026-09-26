"""World & Terrain > Heightmap Convert: legacy .HGT <-> Redux .HG2."""

from __future__ import annotations

import os
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from bztoolbox.app.widgets import Card, LogView, PathPicker, ScrollableFrame

HEIGHTMAP_TYPES = (("Heightmaps", "*.hgt *.hg2"), ("Legacy HGT", "*.hgt"), ("Redux HG2", "*.hg2"),
                   ("All files", "*.*"))
ROUNDING = ("half-up", "engine")


def parse_zones(text: str):
    """``"4x3"`` -> (4, 3); empty -> None (use the TRN)."""
    text = text.strip().lower()
    if not text:
        return None
    try:
        x, z = (int(part) for part in text.split("x"))
    except ValueError as exc:
        raise ValueError("Zones look like 4x3 (X by Z), or leave the field empty to use the TRN.") from exc
    if x <= 0 or z <= 0:
        raise ValueError("Zone counts must be positive.")
    return x, z


def output_for(source: str) -> str:
    path = Path(source)
    return str(path.with_suffix(".hg2" if path.suffix.lower() == ".hgt" else ".hgt"))


class HeightmapConvertPage(ScrollableFrame):
    def __init__(self, master, shell):
        super().__init__(master)
        self.shell = shell
        self.job = None
        self.source = tk.StringVar()
        self.output = tk.StringVar()
        self.zones = tk.StringVar()
        self.trn = tk.StringVar()
        self.flags_from = tk.StringVar()
        self.rounding = tk.StringVar(value=ROUNDING[0])
        self.smooth = tk.BooleanVar(value=False)
        self.clamp = tk.BooleanVar(value=False)

        body = ttk.Frame(self.body, style="Toolbox.TFrame", padding=(18, 4, 18, 18))
        body.pack(fill="both", expand=True)
        card = Card(body, "HGT ↔ HG2", "Battlezone 1.x stores terrain as .HGT (128 samples per 1280 m zone, "
                                     "12-bit heights, no header); Redux uses .HG2 (256 samples per zone). "
                                     "HGT → HG2 is Redux's own upsample without its smoothing pass; HG2 → HGT "
                                     "keeps the legacy vertices and reports any detail between them.")
        card.pack(fill="x", pady=(0, 12))
        form = card.body
        PathPicker(form, "Source heightmap", self.source, kind="file", filetypes=HEIGHTMAP_TYPES, surface=True,
                   on_change=lambda v: self.output.set(output_for(v))).pack(fill="x", pady=2)
        PathPicker(form, "Output", self.output, kind="save", filetypes=HEIGHTMAP_TYPES, surface=True).pack(fill="x", pady=2)

        ttk.Label(form, text="HGT → HG2", style="Toolbox.CardTitle.TLabel").pack(anchor="w", pady=(8, 2))
        PathPicker(form, "TRN (size)", self.trn, kind="file", filetypes=(("TRN", "*.trn"), ("All files", "*.*")),
                   surface=True).pack(fill="x", pady=2)
        grid = ttk.Frame(form, style="Toolbox.Surface.TFrame")
        grid.pack(fill="x", pady=2)
        ttk.Label(grid, text="Zones (X x Z)", style="Toolbox.Surface.TLabel", width=18).grid(row=0, column=0, sticky="w")
        ttk.Entry(grid, textvariable=self.zones, style="Toolbox.TEntry", width=10).grid(row=0, column=1, sticky="w")
        ttk.Label(grid, text="empty: the TRN beside the HGT", style="Toolbox.SurfaceMuted.TLabel").grid(
            row=0, column=2, sticky="w", padx=(8, 0))
        ttk.Label(grid, text="Rounding", style="Toolbox.Surface.TLabel", width=18).grid(row=1, column=0, sticky="w",
                                                                                      pady=(4, 0))
        ttk.Combobox(grid, textvariable=self.rounding, values=ROUNDING, state="readonly", width=10,
                     style="Toolbox.TCombobox").grid(row=1, column=1, sticky="w", pady=(4, 0))
        ttk.Label(grid, text="half-up matches Redux's shipped HG2 files; engine is the runtime cook",
                  style="Toolbox.SurfaceMuted.TLabel").grid(row=1, column=2, sticky="w", padx=(8, 0), pady=(4, 0))
        ttk.Checkbutton(form, text="Apply Redux's 3x3 smoothing (what the game does without -nohgtsmoothing)",
                        variable=self.smooth, style="Toolbox.Surface.TCheckbutton").pack(anchor="w")

        ttk.Label(form, text="HG2 → HGT", style="Toolbox.CardTitle.TLabel").pack(anchor="w", pady=(8, 2))
        PathPicker(form, "Flags from HGT", self.flags_from, kind="file", filetypes=(("Legacy HGT", "*.hgt"),),
                   surface=True).pack(fill="x", pady=2)
        ttk.Label(form, text="Optional: the original HGT, to carry over its flag nibble for a byte-exact round "
                             "trip. Without it the flags are zero; 1.5 recomputes them on load.",
                  style="Toolbox.SurfaceMuted.TLabel", wraplength=900, justify="left").pack(anchor="w")
        ttk.Checkbutton(form, text="Clamp heights above 4095 (HGT is 12-bit) instead of refusing",
                        variable=self.clamp, style="Toolbox.Surface.TCheckbutton").pack(anchor="w")

        actions = ttk.Frame(form, style="Toolbox.Surface.TFrame")
        actions.pack(fill="x", pady=(10, 0))
        self.convert_button = ttk.Button(actions, text="Convert", style="Toolbox.Accent.TButton", command=self.convert)
        self.convert_button.pack(side="left")

        ttk.Label(body, text="RESULT", style="Toolbox.Heading.TLabel").pack(anchor="w")
        self.log = LogView(body, height=10)
        self.log.pack(fill="both", expand=True, pady=(4, 0))
        self.log.write("Pick an .hgt or .hg2; the extension decides the direction.", "muted")

    def convert(self) -> None:
        if self.job is not None and self.job.status in ("queued", "running"):
            return
        source, output = self.source.get().strip(), self.output.get().strip()
        if not source or not os.path.isfile(source):
            messagebox.showerror("Heightmap convert", "Select a source .hgt or .hg2.")
            return
        if Path(source).suffix.lower() not in (".hgt", ".hg2"):
            messagebox.showerror("Heightmap convert", "The source must be an .hgt or .hg2 file.")
            return
        if not output or os.path.abspath(output) == os.path.abspath(source):
            messagebox.showerror("Heightmap convert", "Choose an output file other than the source.")
            return
        try:
            zones = parse_zones(self.zones.get())
        except ValueError as exc:
            messagebox.showerror("Heightmap convert", str(exc))
            return
        if os.path.exists(output) and not messagebox.askyesno("Replace output?", f"Replace the existing file?\n\n{output}"):
            return
        options = dict(zones=zones, trn=self.trn.get().strip() or None, rounding=self.rounding.get(),
                       smoothing=self.smooth.get(), flags_from=self.flags_from.get().strip() or None,
                       overflow="clamp" if self.clamp.get() else "error")
        self.convert_button.state(["disabled"])
        self.log.clear()

        def work(_job):
            from bztoolbox.modules.terrain_generator.heightmap_convert import convert_heightmap

            return convert_heightmap(source, output, **options)

        self.job = self.shell.jobs.submit(f"Convert {Path(source).name}", work,
                                          on_done=self._done, on_error=self._failed)

    def _done(self, report) -> None:
        self.convert_button.state(["!disabled"])
        for line in report.lines():
            self.log.write(line, "warning" if line.startswith("WARNING") else "")
        self.log.write(f"Done: {report.target}", "success")
        self.shell.status(f"Heightmap written to {report.target}")

    def _failed(self, error: str) -> None:
        self.convert_button.state(["!disabled"])
        self.log.write(error, "error")
