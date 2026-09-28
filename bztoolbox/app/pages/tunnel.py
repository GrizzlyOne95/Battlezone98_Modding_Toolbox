"""World & Terrain > Tunnels: carve a cut-and-cover trench into an HG2 and shade its LGT under the roof."""

from __future__ import annotations

import os
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from bztoolbox.app import theme
from bztoolbox.app.widgets import Card, LogView, PathPicker, ScrollableFrame

PREVIEW_SIZE = 480


def spec_from_form(form: dict):
    """Form strings -> TunnelSpec (ValueError explains the first problem)."""
    from bztoolbox.modules.terrain_generator.tunnel import (
        TunnelSpec, parse_point, parse_points, parse_rect, trn_origin,
    )

    def number(key, label, optional=False):
        text = str(form.get(key, "")).strip()
        if not text and optional:
            return None
        try:
            return float(text)
        except ValueError as exc:
            raise ValueError(f"{label} must be a number") from exc

    path = parse_points(str(form["path"]))
    if len(path) < 2:
        raise ValueError("The path needs at least two points: x,z x,z ...")
    width = number("width", "Width")
    value = number("amount", "Depth" if form["mode"] == "depth" else "Floor height")
    origin = (0.0, 0.0)
    if form["coords"] == "world":
        if str(form.get("trn", "")).strip():
            origin = trn_origin(form["trn"])
        elif str(form.get("origin", "")).strip():
            origin = parse_point(form["origin"])
        else:
            raise ValueError("World coordinates need the TRN (for MinX/MinZ) or an origin.")
    try:
        shade = int(str(form["shade"]).strip())
    except ValueError as exc:
        raise ValueError("The roof shade must be a whole number 0..255") from exc
    return TunnelSpec(path=path, width=width,
                      depth=value if form["mode"] == "depth" else None,
                      floor=value if form["mode"] == "floor" else None,
                      ramp=number("ramp", "Ramp length", True) or 0.0, ramps=form["ramps"],
                      wall_slope=number("wall_slope", "Wall slope", True) or None,
                      roof_rects=[parse_rect(item) for item in str(form["roofs"]).split()],
                      shade_path=bool(form["shade_path"]), shade=shade,
                      feather=number("feather", "Feather", True) or 0.0, origin=origin)


class TunnelPage(ScrollableFrame):
    def __init__(self, master, shell):
        super().__init__(master)
        self.shell = shell
        self.job = None
        self._photo = None
        from bztoolbox.modules.terrain_generator.tunnel import DEFAULT_SHADE, DEFAULT_WALL_SLOPE, RAMP_ENDS

        self.vars = {
            "hg2": tk.StringVar(), "trn": tk.StringVar(), "origin": tk.StringVar(), "coords": tk.StringVar(value="map"),
            "path": tk.StringVar(), "width": tk.StringVar(value="20"), "mode": tk.StringVar(value="depth"),
            "amount": tk.StringVar(value="12"), "ramp": tk.StringVar(value="60"), "ramps": tk.StringVar(value="both"),
            "wall_slope": tk.StringVar(value=f"{DEFAULT_WALL_SLOPE:g}"), "roofs": tk.StringVar(),
            "shade": tk.StringVar(value=str(DEFAULT_SHADE)), "feather": tk.StringVar(value="5"),
            "out": tk.StringVar(),
        }
        self.shade_path = tk.BooleanVar(value=False)
        self.update_lgt = tk.BooleanVar(value=True)

        body = ttk.Frame(self.body, style="Toolbox.TFrame", padding=(18, 4, 18, 18))
        body.pack(fill="both", expand=True)
        card = Card(body, "Cut-and-cover tunnel",
                    "A heightfield cannot overhang, so a tunnel is a trench with a roof building over it. This "
                    "carves the trench (ramps at the open ends, sloped walls, never raising the ground), rebakes the "
                    "light map over it and darkens it under the roof. See docs/world/TUNNELS.md.")
        card.pack(fill="x", pady=(0, 12))
        form = card.body
        PathPicker(form, "Heightmap (.hg2)", self.vars["hg2"], kind="file",
                   filetypes=(("Redux HG2", "*.hg2"), ("All files", "*.*")), surface=True,
                   on_change=self._hg2_chosen).pack(fill="x", pady=2)

        coords = ttk.Frame(form, style="Toolbox.Surface.TFrame")
        coords.pack(fill="x", pady=(6, 2))
        ttk.Label(coords, text="Coordinates", style="Toolbox.Surface.TLabel", width=18).pack(side="left")
        ttk.Radiobutton(coords, text="map-relative (from the south-west corner)", value="map",
                        variable=self.vars["coords"], style="Toolbox.Surface.TRadiobutton").pack(side="left")
        ttk.Radiobutton(coords, text="world (as in the mission)", value="world", variable=self.vars["coords"],
                        style="Toolbox.Surface.TRadiobutton").pack(side="left", padx=(12, 0))
        PathPicker(form, "TRN (MinX/MinZ)", self.vars["trn"], kind="file",
                   filetypes=(("TRN", "*.trn"), ("All files", "*.*")), surface=True).pack(fill="x", pady=2)

        grid = ttk.Frame(form, style="Toolbox.Surface.TFrame")
        grid.pack(fill="x", pady=(6, 0))
        grid.columnconfigure(1, weight=1)

        def row(r, label, widget, hint=""):
            ttk.Label(grid, text=label, style="Toolbox.Surface.TLabel", width=18).grid(row=r, column=0, sticky="w",
                                                                                     pady=2)
            widget.grid(row=r, column=1, sticky="we" if hint == "wide" else "w", pady=2)
            if hint and hint != "wide":
                ttk.Label(grid, text=hint, style="Toolbox.SurfaceMuted.TLabel").grid(row=r, column=2, sticky="w",
                                                                                   padx=(8, 0))

        def entry(key, width=10):
            return ttk.Entry(grid, textvariable=self.vars[key], style="Toolbox.TEntry", width=width)

        row(0, "Path (x,z …)", entry("path", 60), "wide")
        row(1, "Floor width (m)", entry("width"), "the drivable floor; walls slope out from its edges")
        amount = ttk.Frame(grid, style="Toolbox.Surface.TFrame")
        ttk.Entry(amount, textvariable=self.vars["amount"], style="Toolbox.TEntry", width=10).pack(side="left")
        ttk.Radiobutton(amount, text="m deep (follows the ground)", value="depth", variable=self.vars["mode"],
                        style="Toolbox.Surface.TRadiobutton").pack(side="left", padx=(8, 0))
        ttk.Radiobutton(amount, text="m floor height (level)", value="floor", variable=self.vars["mode"],
                        style="Toolbox.Surface.TRadiobutton").pack(side="left", padx=(8, 0))
        row(2, "Floor", amount)
        ramps = ttk.Frame(grid, style="Toolbox.Surface.TFrame")
        ttk.Entry(ramps, textvariable=self.vars["ramp"], style="Toolbox.TEntry", width=10).pack(side="left")
        ttk.Label(ramps, text="m at", style="Toolbox.Surface.TLabel").pack(side="left", padx=(6, 6))
        ttk.Combobox(ramps, textvariable=self.vars["ramps"], values=RAMP_ENDS, state="readonly", width=8,
                     style="Toolbox.TCombobox").pack(side="left")
        ttk.Label(ramps, text="end(s)", style="Toolbox.Surface.TLabel").pack(side="left", padx=(6, 0))
        row(3, "Ramps", ramps)
        row(4, "Wall slope", entry("wall_slope"), "metres down per metre across; 0 = as steep as the grid allows")
        row(5, "Roof footprints", entry("roofs", 60), "wide")
        ttk.Label(grid, text="x0,z0,x1,z1 rectangles, space separated; the light map is darkened under them",
                  style="Toolbox.SurfaceMuted.TLabel").grid(row=6, column=1, sticky="w")
        row(7, "Roof shade", entry("shade"), "LGT value under the roof (Redux's bake uses 56..255)")
        row(8, "Soft edge (m)", entry("feather"))
        ttk.Checkbutton(form, text="Also darken the whole trench floor along the path (a roof over all of it)",
                        variable=self.shade_path, style="Toolbox.Surface.TCheckbutton").pack(anchor="w", pady=(4, 0))
        ttk.Checkbutton(form, text="Update the light map beside the HG2 (rebake the carved area, then shade)",
                        variable=self.update_lgt, style="Toolbox.Surface.TCheckbutton").pack(anchor="w")
        PathPicker(form, "Output folder", self.vars["out"], kind="dir", surface=True).pack(fill="x", pady=(6, 2))
        ttk.Label(form, text="Empty: overwrite the HG2/LGT after copying them to a backup folder.",
                  style="Toolbox.SurfaceMuted.TLabel").pack(anchor="w")

        actions = ttk.Frame(form, style="Toolbox.Surface.TFrame")
        actions.pack(fill="x", pady=(10, 0))
        self.preview_button = ttk.Button(actions, text="Preview", style="Toolbox.TButton",
                                         command=lambda: self.run(write=False))
        self.preview_button.pack(side="left")
        self.carve_button = ttk.Button(actions, text="Carve", style="Toolbox.Accent.TButton",
                                       command=lambda: self.run(write=True))
        self.carve_button.pack(side="left", padx=(6, 0))

        ttk.Label(body, text="PREVIEW (north up, cut tinted by depth)", style="Toolbox.Heading.TLabel").pack(anchor="w")
        self.preview = tk.Label(body, bg=theme.BG, bd=0)
        self.preview.pack(anchor="w", pady=(4, 12))
        ttk.Label(body, text="RESULT", style="Toolbox.Heading.TLabel").pack(anchor="w")
        self.log = LogView(body, height=8)
        self.log.pack(fill="both", expand=True, pady=(4, 0))
        self.log.write("Pick an .hg2 and enter the tunnel's centre line; Preview carves a copy in memory.", "muted")

    def _hg2_chosen(self, value: str) -> None:
        from bztoolbox.modules.terrain_generator.tunnel import companion

        path = Path(value)
        if path.is_file() and not self.vars["trn"].get():
            trn = companion(path, ".trn")
            if trn is not None:
                self.vars["trn"].set(str(trn))

    def run(self, write: bool) -> None:
        if self.job is not None and self.job.status in ("queued", "running"):
            return
        hg2 = self.vars["hg2"].get().strip()
        if not hg2 or not os.path.isfile(hg2):
            messagebox.showerror("Tunnel", "Pick the map's .hg2.")
            return
        form = {key: var.get() for key, var in self.vars.items()}
        form["shade_path"] = self.shade_path.get()
        try:
            spec = spec_from_form(form)
        except (OSError, ValueError) as exc:
            messagebox.showerror("Tunnel", str(exc))
            return
        out = form["out"].strip() or None
        if write and out is None and not messagebox.askyesno(
                "Carve tunnel", "Overwrite the HG2 (and its LGT)? The originals are copied to a backup folder first."):
            return
        lgt = self.update_lgt.get()
        for button in (self.preview_button, self.carve_button):
            button.state(["disabled"])

        def work(_job):
            from bztoolbox.modules.terrain_generator.tunnel import apply_tunnel, preview_image, write_tunnel

            outcome = apply_tunnel(hg2, spec, lgt=lgt)
            image = preview_image(outcome.hg2.heights, outcome.result.carved, outcome.original,
                                  size=PREVIEW_SIZE, zone_size=outcome.hg2.zone_size)
            if write and (outcome.result.samples or outcome.lgt_changed):
                write_tunnel(hg2, outcome, out=out)
            return outcome, image

        self.job = self.shell.jobs.submit("Carve tunnel" if write else "Preview tunnel", work,
                                          on_done=lambda result: self._done(result, write), on_error=self._failed)

    def _done(self, result, write: bool) -> None:
        from PIL import ImageTk

        outcome, image = result
        for button in (self.preview_button, self.carve_button):
            button.state(["!disabled"])
        self._photo = ImageTk.PhotoImage(image)
        self.preview.configure(image=self._photo)
        self.log.clear()
        if outcome.result.samples == 0:
            self.log.write("Nothing was carved: check the coordinates (map-relative or world) and the depth.",
                           "warning")
        for line in outcome.lines():
            self.log.write(line, "warning" if line.startswith(("WARNING", "note")) else "")
        if write:
            self.log.write("Done." if outcome.written else "Nothing to write.", "success" if outcome.written else "")
            self.shell.status("Tunnel carved" if outcome.written else "Tunnel: nothing to write")
        else:
            self.log.write("Preview only: nothing was written.", "muted")

    def _failed(self, error: str) -> None:
        for button in (self.preview_button, self.carve_button):
            button.state(["!disabled"])
        self.log.write(error, "error")
