"""LUM authoring panel sharing Texture Manager's ACT workspace."""
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageTk

from battlezone.archives.zfs import ZFSArchive
from battlezone.terrain.colortables import STOCK_WORLDS
from battlezone.terrain.atmosphere_presets import tune_world_act
from battlezone.terrain.lum import LumaTable, atmosphere


class LumaEditor(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, padding=12)
        self.app = app
        self.table = LumaTable.identity()
        self.source = tk.StringVar(value="New neutral table (no legacy shading curve)")
        self.world = tk.StringVar(value="mars")
        self.row = tk.StringVar(value="0")
        self.column = tk.StringVar(value="223")
        self.index = tk.StringVar(value="223")
        self.direction = tk.StringVar(value="1")
        self.colors = tk.StringVar()
        actions = ttk.Frame(self)
        actions.pack(fill="x")
        for title, action in [("New LUM", self.new), ("Open LUM...", self.open),
                              ("Save LUM As...", self.save), ("Import PNG...", self.import_png),
                              ("Export PNG...", self.export_png)]:
            ttk.Button(actions, text=title, command=action).pack(side="left", padx=3)
        stock = ttk.Frame(self)
        stock.pack(fill="x", pady=8)
        ttk.Label(stock, text="Stock world:").pack(side="left")
        ttk.Combobox(stock, values=STOCK_WORLDS, textvariable=self.world,
                     state="readonly", width=14).pack(side="left", padx=6)
        ttk.Button(stock, text="Load ACT + LUM from bzone.zfs...", command=self.load_stock).pack(side="left")
        ttk.Button(stock, text="Apply Tuned Atmosphere to ACT", command=lambda: self.run(self.apply_preset)).pack(side="left", padx=6)
        ttk.Label(self, textvariable=self.source, wraplength=1000).pack(anchor="w", pady=4)
        body = ttk.Frame(self)
        body.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(body, width=512, height=512, highlightthickness=1, bg="#111111")
        self.canvas.pack(side="left", anchor="n", padx=(0, 18))
        self.canvas.bind("<Button-1>", self.pick_cell)
        controls = ttk.Frame(body)
        controls.pack(side="left", fill="x", expand=True, anchor="n")
        ttk.Label(controls, text="Edit any table cell", font=(app.custom_font_name, 12, "bold")).pack(anchor="w")
        for title, variable in [("Row (Y)", self.row), ("Source index / column (X)", self.column),
                                ("Output palette index", self.index)]:
            ttk.Label(controls, text=title).pack(anchor="w", pady=(8, 2))
            ttk.Spinbox(controls, from_=0, to=255, textvariable=variable, width=12).pack(anchor="w")
        ttk.Button(controls, text="Read Cell", command=lambda: self.run(self.read_cell)).pack(anchor="w", pady=(8, 0))
        ttk.Button(controls, text="Apply Cell", command=lambda: self.run(self.apply_cell)).pack(anchor="w", pady=5)
        ttk.Button(controls, text="Jump to Redux Fog (row 0, column 223)", command=self.jump_fog).pack(anchor="w", pady=6)
        ttk.Label(controls, text="TRN FogDirection:").pack(anchor="w", pady=(10, 0))
        combo = ttk.Combobox(controls, values=("1", "0"), textvariable=self.direction,
                             state="readonly", width=12)
        combo.pack(anchor="w")
        combo.bind("<<ComboboxSelected>>", lambda _: self.refresh())
        ttk.Label(controls, textvariable=self.colors, wraplength=350).pack(anchor="w", pady=10)
        ttk.Button(controls, text="Edit Effective Fog Color in ACT", command=self.edit_fog).pack(anchor="w")
        ttk.Label(controls, wraplength=350, text=(
            "Preview uses the ACT Palette Editor workspace. Redux uses LUM[223] to select its default fog color. "
            "TRN FogColor and SkyColor overrides take precedence. ACT/LUM edits do not recolor DDS textures. "
            "ALB/TBL blending tables have no confirmed Redux consumer."
        )).pack(anchor="w", pady=12)
        self.refresh()

    def run(self, action):
        try:
            action()
        except (OSError, ValueError, KeyError) as exc:
            messagebox.showerror("LUM Editor", str(exc), parent=self)

    def act(self):
        return bytes(channel for rgb in self.app.palette for channel in rgb)

    def apply_preset(self):
        if self.direction.get() == "0":
            raise ValueError("These presets use normal fog. Set the preview FogDirection to 1 first; update the mission TRN separately.")
        raw = self.act() + self.app._act_footer
        self.app.set_workspace_palette(tune_world_act(self.world.get(), raw, fog_index=self.table.cell(0, 223)))

    def refresh(self):
        self.photo = ImageTk.PhotoImage(self.table.image(self.act()).resize((512, 512), Image.Resampling.NEAREST))
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, image=self.photo, anchor="nw")
        try:
            x, y = int(self.column.get()) * 2, int(self.row.get()) * 2
            self.canvas.create_rectangle(x, y, x + 2, y + 2, outline="#ff00ff")
        except ValueError:
            pass
        colors = atmosphere(self.act(), self.table, int(self.direction.get()))
        self.colors.set(f"Default sky: ACT[{colors['sky_index']}] = {colors['sky_rgb']}\n"
                        f"Default fog: ACT[{colors['fog_index']}] = {colors['fog_rgb']}")

    def read_cell(self):
        self.index.set(str(self.table.cell(int(self.row.get()), int(self.column.get()))))
        self.refresh()

    def apply_cell(self):
        self.table.set_cell(int(self.row.get()), int(self.column.get()), int(self.index.get()))
        self.refresh()

    def jump_fog(self):
        self.row.set("0")
        self.column.set("223")
        self.read_cell()

    def pick_cell(self, event):
        if 0 <= event.x < 512 and 0 <= event.y < 512:
            self.column.set(str(event.x // 2))
            self.row.set(str(event.y // 2))
            self.read_cell()

    def edit_fog(self):
        index = atmosphere(self.act(), self.table, int(self.direction.get()))["fog_index"]
        self.app.jump_to_index(index)
        self.app.notebook.select(self.app.tab_act)

    def new(self):
        self.table = LumaTable.identity()
        self.source.set("New neutral table (no legacy shading curve)")
        self.jump_fog()

    def open(self):
        path = filedialog.askopenfilename(filetypes=[("Luma table", "*.lum")], parent=self)
        if path:
            self.run(lambda: self.load(path))

    def load(self, path):
        table = LumaTable.read(path)
        self.table = table
        self.source.set(str(path))
        self.jump_fog()

    def save(self):
        path = filedialog.asksaveasfilename(defaultextension=".lum", filetypes=[("Luma table", "*.lum")], parent=self)
        if path:
            self.run(lambda: self.table.write(path))

    def import_png(self):
        path = filedialog.askopenfilename(filetypes=[("Indexed / grayscale PNG", "*.png")], parent=self)
        if path:
            def load():
                self.table = LumaTable.from_png(path)
                self.source.set(str(path))
                self.jump_fog()
            self.run(load)

    def export_png(self):
        path = filedialog.asksaveasfilename(defaultextension=".png", filetypes=[("PNG", "*.png")], parent=self)
        if path:
            self.run(lambda: self.table.export_png(path, self.act()))

    def load_stock(self):
        from bztoolbox.external import detect_game_installs
        games = detect_game_installs()
        path = filedialog.askopenfilename(title="Choose the stock bzone.zfs archive",
                    initialdir=str(games[0]) if games else None,
                    filetypes=[("Battlezone archive", "*.zfs")], parent=self)
        if not path:
            return
        def load():
            archive = ZFSArchive(Path(path))
            world = self.world.get()
            table = LumaTable(bytearray(archive.read(world + ".lum")))
            act = archive.read(world + ".act")
            self.app.set_workspace_palette(act)
            self.table = table
            self.source.set(f"{path} :: {world}.act + {world}.lum")
            self.jump_fog()
        self.run(load)
