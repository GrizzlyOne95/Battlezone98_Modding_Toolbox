"""World & Terrain > Redux → 1.5 Port: a Redux world or mission folder rebuilt for Battlezone 1.5."""

from __future__ import annotations

import os
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from bztoolbox.app.widgets import Card, LogView, PathPicker, ScrollableFrame

PALETTE_CHOICES = (
    ("auto", "Automatic: the TRN's ACT if 1.5 can use it, else build one from the atlas"),
    ("trn", "The TRN's ACT, as it is"),
    ("rebuild", "Build a new palette from the atlas"),
    ("file", "This ACT:"),
)
WORLDS = ("from the TRN", "achilles", "elysium", "europa", "ganymede", "io", "mars", "moon", "titan", "venus")


def default_output(source: str) -> str:
    path = Path(source)
    return str(path.with_name(path.name + "_1.5")) if source else ""


def palette_from_form(choice: str, act: str) -> str:
    """The ``palette`` option: a mode name, or the chosen ACT file."""
    if choice != "file":
        return choice
    act = act.strip()
    if not act or not os.path.isfile(act):
        raise ValueError("Choose the .act file to use, or another palette option.")
    return act


class ReduxToLegacyPage(ScrollableFrame):
    def __init__(self, master, shell):
        super().__init__(master)
        self.shell = shell
        self.job = None
        self.source = tk.StringVar()
        self.output = tk.StringVar()
        self.game_dir = tk.StringVar(value=self._game_dir())
        self.legacy_dir = tk.StringVar(value=self._legacy_dir())
        self.sprites = tk.BooleanVar(value=True)
        self.search_dir = tk.StringVar()
        self.palette = tk.StringVar(value="auto")
        self.act = tk.StringVar()
        self.world = tk.StringVar(value=WORLDS[0])
        self.tile_size = tk.StringVar(value="256")
        self.map_format = tk.StringVar(value="indexed")
        self.missing_tiles = tk.StringVar(value="default")
        self.dither = tk.BooleanVar(value=False)
        self.tables = tk.BooleanVar(value=True)
        self.heightmaps = tk.BooleanVar(value=True)
        self.bzn = tk.BooleanVar(value=True)
        self.allow_loss = tk.BooleanVar(value=False)

        body = ttk.Frame(self.body, style="Toolbox.TFrame", padding=(18, 4, 18, 18))
        body.pack(fill="both", expand=True)
        card = Card(body, "Redux → Battlezone 1.5", "The legacy port run backwards. The [Atlases] texture is cut back "
                                                   "into the 1.5 tile MAPs the TRN names (256/128/64/32 px for levels "
                                                   "0-3), a palette and its LUM/TBL/ALB tables are made, the TRN, "
                                                   "sky, HG2, LGT and BZN are converted, and Redux-only files are "
                                                   "left out. A report is written next to the output.")
        card.pack(fill="x", pady=(0, 12))
        form = card.body
        PathPicker(form, "Redux folder", self.source, kind="dir", surface=True,
                   on_change=self._suggest_output).pack(fill="x", pady=2)
        PathPicker(form, "Output folder", self.output, kind="dir", surface=True).pack(fill="x", pady=2)
        PathPicker(form, "Redux game folder", self.game_dir, kind="dir", surface=True).pack(fill="x", pady=2)
        PathPicker(form, "1.5 game folder", self.legacy_dir, kind="dir", surface=True).pack(fill="x", pady=2)
        PathPicker(form, "Extra assets", self.search_dir, kind="dir", surface=True).pack(fill="x", pady=2)
        ttk.Label(form, text="Game folder: the stock colour tables (bzone.zfs) and stock atlases a map may use. "
                             "1.5 game folder: its stock sprite tables, extended with the map's Redux sprites (a custom "
                             "SunTexture). Extra assets: optional folder with materials, CSVs, textures or ODFs kept "
                             "elsewhere.",
                  style="Toolbox.SurfaceMuted.TLabel", wraplength=900, justify="left").pack(anchor="w", pady=(2, 6))

        ttk.Label(form, text="Palette", style="Toolbox.CardTitle.TLabel").pack(anchor="w", pady=(8, 2))
        choices = ttk.Frame(form, style="Toolbox.Surface.TFrame")
        choices.pack(fill="x")
        for row, (value, label) in enumerate(PALETTE_CHOICES):
            ttk.Radiobutton(choices, text=label, value=value, variable=self.palette,
                            style="Toolbox.Surface.TRadiobutton").grid(row=row, column=0, sticky="w")
        PathPicker(form, "ACT file", self.act, kind="file", filetypes=(("ACT palettes", "*.act"), ("All files", "*.*")),
                   surface=True).pack(fill="x", pady=2)
        ttk.Label(form, text="1.5 draws everything through the world palette: entries 0-95 and 224-255 are shared "
                             "with the interface and objects, 96-223 belong to the world. Redux never reads the "
                             "ACT, so Redux-era ACTs are often placeholders; automatic mode checks.",
                  style="Toolbox.SurfaceMuted.TLabel", wraplength=900, justify="left").pack(anchor="w", pady=(2, 4))

        grid = ttk.Frame(form, style="Toolbox.Surface.TFrame")
        grid.pack(fill="x", pady=(6, 2))
        rows = (("Base world", self.world, WORLDS, "shared palette entries and colour tables come from it"),
                ("Tile size", self.tile_size, ("256", "128", "512"), "level 0; stock 1.5 tiles are 256"),
                ("MAP format", self.map_format, ("indexed", "565"), "indexed works in every renderer; 565 is "
                                                                     "hardware 16-bit only"),
                ("Undefined tiles", self.missing_tiles, ("default", "solid", "none"),
                 "MAT slots the TRN lacks: Redux draws the atlas default tile, 1.5 a checkerboard"))
        for row, (label, var, values, hint) in enumerate(rows):
            ttk.Label(grid, text=label, style="Toolbox.Surface.TLabel", width=18).grid(row=row, column=0, sticky="w",
                                                                                     pady=2)
            ttk.Combobox(grid, textvariable=var, values=values, state="readonly", width=14,
                         style="Toolbox.TCombobox").grid(row=row, column=1, sticky="w", pady=2)
            ttk.Label(grid, text=hint, style="Toolbox.SurfaceMuted.TLabel").grid(row=row, column=2, sticky="w",
                                                                                padx=(8, 0))
        for var, label in ((self.tables, "Write LUM/TBL/ALB tables for a new palette"),
                           (self.dither, "Dither when reducing to the palette"),
                           (self.heightmaps, "Convert HG2 → HGT and LGT to 128 cells per zone"),
                           (self.bzn, "Convert BZN missions to version 1045"),
                           (self.sprites, "Add the folder's .sta sprites to 1.5's sprite tables"),
                           (self.allow_loss, "Write BZNs even if some values have no 1.5 field")):
            ttk.Checkbutton(form, text=label, variable=var, style="Toolbox.Surface.TCheckbutton").pack(anchor="w")

        actions = ttk.Frame(form, style="Toolbox.Surface.TFrame")
        actions.pack(fill="x", pady=(10, 0))
        self.convert_button = ttk.Button(actions, text="Port to 1.5", style="Toolbox.Accent.TButton",
                                         command=self.convert)
        self.convert_button.pack(side="left")

        ttk.Label(body, text="RESULT", style="Toolbox.Heading.TLabel").pack(anchor="w")
        self.log = LogView(body, height=16)
        self.log.pack(fill="both", expand=True, pady=(4, 0))
        self.log.write("Pick the Redux folder with the TRN and its atlas (material, CSV and texture).", "muted")

    def _game_dir(self) -> str:
        configured = ""
        try:
            configured = self.shell.settings.get("game_dir", "") or ""
        except AttributeError:
            pass
        if configured:
            return configured
        try:
            from bztoolbox import external

            found = external.detect_game_installs()
            return str(found[0]) if found else ""
        except Exception:
            return ""

    @staticmethod
    def _legacy_dir() -> str:
        from bztoolbox.modules.world.redux_to_legacy import default_legacy_dir

        return default_legacy_dir() or ""

    def _suggest_output(self, source: str) -> None:
        current = self.output.get().strip()
        if not current or current.endswith("_1.5"):
            self.output.set(default_output(source))

    def convert(self) -> None:
        if self.job is not None and self.job.status in ("queued", "running"):
            return
        source, output = self.source.get().strip(), self.output.get().strip()
        if not source or not os.path.isdir(source):
            messagebox.showerror("Redux → 1.5", "Select the Redux world or mission folder.")
            return
        if not output or os.path.abspath(output) == os.path.abspath(source):
            messagebox.showerror("Redux → 1.5", "Choose an output folder other than the source.")
            return
        try:
            palette = palette_from_form(self.palette.get(), self.act.get())
        except ValueError as exc:
            messagebox.showerror("Redux → 1.5", str(exc))
            return
        if os.path.isdir(output) and os.listdir(output) and not messagebox.askyesno(
                "Output not empty", f"Files in this folder with the same names will be replaced.\n\n{output}"):
            return
        from bztoolbox.modules.world.redux_to_legacy import LegacyExportOptions

        world = self.world.get()
        options = LegacyExportOptions(
            tile_size=int(self.tile_size.get()), map_format=self.map_format.get(), palette=palette,
            base_world=None if world == WORLDS[0] else world, dither=self.dither.get(),
            color_tables=self.tables.get(), game_dir=self.game_dir.get().strip() or None,
            search_dirs=tuple(d for d in (self.search_dir.get().strip(),) if d),
            heightmaps=self.heightmaps.get(), bzn=self.bzn.get(), allow_bzn_loss=self.allow_loss.get(),
            missing_tiles=self.missing_tiles.get(), sprites=self.sprites.get(),
            legacy_dir=self.legacy_dir.get().strip() or None)
        self.convert_button.state(["disabled"])
        self.log.clear()
        self.log.write(f"Porting {Path(source).name}…", "info")

        def work(_job):
            from bztoolbox.modules.world.redux_to_legacy import port_redux_to_legacy

            return port_redux_to_legacy(source, output, options)

        self.job = self.shell.jobs.submit(f"Port {Path(source).name} to 1.5", work,
                                          on_done=self._done, on_error=self._failed)

    def _done(self, report) -> None:
        self.convert_button.state(["!disabled"])
        for line in report.lines():
            tag = "error" if line.startswith("ERROR") else "warning" if line.startswith("WARNING") else ""
            self.log.write(line, tag)
        if report.ok:
            self.log.write(f"Done: {report.output}", "success")
            self.shell.status(f"1.5 port written to {report.output}")
        else:
            self.log.write("Finished with errors; see above and the report in the output folder.", "error")
            self.shell.status("1.5 port finished with errors")

    def _failed(self, error: str) -> None:
        self.convert_button.state(["!disabled"])
        self.log.write(error, "error")
