"""Assets > Sprites: view and edit Redux sprite tables (.sta), preview sprites, write 1.5 tables."""

from __future__ import annotations

import os
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from battlezone.images.sprites import StaDocument, StaEntry, validate_sta_entry
from bztoolbox.app import theme
from bztoolbox.app.widgets import Card, LogView, PathPicker, ScrollableFrame, add_scrollbars

STA_TYPES = (("Sprite tables", "*.sta *.st"), ("All files", "*.*"))
COLUMNS = (("name", "Name", 200), ("material", "Material", 130), ("rect", "u, v, w × h", 150),
           ("ref", "Reference", 90), ("flags", "Flags", 90))
FIELDS = (("name", "Name"), ("material", "Material"), ("u", "u"), ("v", "v"), ("width", "Width"),
          ("height", "Height"), ("image_width", "Ref. width"), ("image_height", "Ref. height"), ("flags", "Flags"))
PREVIEW_SIZE = 192


def entry_from_form(values: dict) -> StaEntry:
    """Form strings -> a checked StaEntry (ValueError explains the first problem)."""
    try:
        numbers = {key: int(str(values[key]).strip(), 0) for key in
                   ("u", "v", "width", "height", "image_width", "image_height", "flags")}
    except ValueError as exc:
        raise ValueError("u, v, sizes and flags must be whole numbers (flags may be 0x...)") from exc
    entry = StaEntry(str(values["name"]).strip(), str(values["material"]).strip(), **numbers)
    problems = validate_sta_entry(entry)
    if problems:
        raise ValueError("; ".join(problems))
    return entry


def entry_row(entry: StaEntry) -> tuple:
    return (entry.name, entry.material, f"{entry.u}, {entry.v}, {entry.width} × {entry.height}",
            f"{entry.image_width} × {entry.image_height}", f"0x{entry.flags:08x}")


class SpritesPage(ScrollableFrame):
    def __init__(self, master, shell):
        super().__init__(master)
        self.shell = shell
        self.doc = StaDocument()
        self.stock = False                   # showing Redux's stock table (read-only)
        self.dirty = False
        self._from_project = False
        self.sheets = None                   # SpriteSheets once indexed
        self._sheets_key = None
        self._photo = None
        self.job = None
        self.path = tk.StringVar()
        self.filter = tk.StringVar()
        self.filter.trace_add("write", lambda *_: self._refresh())
        self.form = {key: tk.StringVar() for key, _label in FIELDS}
        self.export_dir = tk.StringVar()
        self.legacy_dir = tk.StringVar(value=self._legacy_dir())
        self.world = tk.StringVar(value="moon")

        body = ttk.Frame(self.body, style="Toolbox.TFrame", padding=(18, 4, 18, 18))
        body.pack(fill="both", expand=True)
        card = Card(body, "Sprite table", "Redux reads sprites from text tables (.sta; the stock one is spritea.st "
                                          "in bzone.zfs). Each entry is a rectangle of the texture of an Ogre "
                                          "material, measured in the stated reference image size.")
        card.pack(fill="x", pady=(0, 12))
        PathPicker(card.body, "Table (.sta)", self.path, kind="file", filetypes=STA_TYPES, surface=True,
                   on_change=lambda v: self.open(v)).pack(fill="x", pady=2)
        actions = ttk.Frame(card.body, style="Toolbox.Surface.TFrame")
        actions.pack(fill="x", pady=(8, 0))
        ttk.Button(actions, text="Open", style="Toolbox.TButton",
                   command=lambda: self.open(self.path.get().strip())).pack(side="left")
        self.save_button = ttk.Button(actions, text="Save", style="Toolbox.Accent.TButton", command=self.save)
        self.save_button.pack(side="left", padx=(6, 0))
        ttk.Button(actions, text="Save as…", style="Toolbox.TButton", command=self.save_as).pack(side="left", padx=(6, 0))
        ttk.Button(actions, text="Show stock sprites", style="Toolbox.TButton",
                   command=self.show_stock).pack(side="left", padx=(18, 0))
        self.status = ttk.Label(card.body, text="", style="Toolbox.SurfaceMuted.TLabel", wraplength=900,
                                justify="left")
        self.status.pack(anchor="w", pady=(6, 0))

        search = ttk.Frame(body, style="Toolbox.TFrame")
        search.pack(fill="x", pady=(0, 4))
        ttk.Label(search, text="Filter", style="Toolbox.Muted.TLabel").pack(side="left", padx=(0, 6))
        ttk.Entry(search, textvariable=self.filter, width=30, style="Toolbox.TEntry").pack(side="left")

        panes = ttk.Frame(body, style="Toolbox.TFrame")
        panes.pack(fill="both", expand=True)
        table = ttk.Frame(panes, style="Toolbox.TFrame")
        table.pack(side="left", fill="both", expand=True)
        self.tree = ttk.Treeview(table, columns=[c[0] for c in COLUMNS], show="headings", style="Toolbox.Treeview",
                                 selectmode="browse", height=18)
        for key, heading, width in COLUMNS:
            self.tree.heading(key, text=heading)
            self.tree.column(key, width=width, anchor="w", stretch=key == "name")
        self.tree.tag_configure("nosheet", foreground=theme.MUTED)
        add_scrollbars(table, self.tree)
        self.tree.bind("<<TreeviewSelect>>", self._selected)

        side = Card(panes, "Sprite")
        side.pack(side="left", fill="y", padx=(12, 0))
        self.preview = tk.Label(side.body, bg=theme.BG, width=PREVIEW_SIZE, height=PREVIEW_SIZE, bd=0)
        self.preview.pack(anchor="w")
        self.preview_note = ttk.Label(side.body, text="", style="Toolbox.SurfaceMuted.TLabel", wraplength=260,
                                      justify="left")
        self.preview_note.pack(anchor="w", pady=(4, 8))
        grid = ttk.Frame(side.body, style="Toolbox.Surface.TFrame")
        grid.pack(anchor="w")
        for row, (key, label) in enumerate(FIELDS):
            ttk.Label(grid, text=label, style="Toolbox.Surface.TLabel", width=11).grid(row=row, column=0, sticky="w")
            ttk.Entry(grid, textvariable=self.form[key], style="Toolbox.TEntry",
                      width=24 if key in ("name", "material") else 10).grid(row=row, column=1, sticky="w", pady=1)
        edit = ttk.Frame(side.body, style="Toolbox.Surface.TFrame")
        edit.pack(anchor="w", pady=(8, 0))
        self.apply_button = ttk.Button(edit, text="Apply", style="Toolbox.TButton", command=self.apply)
        self.apply_button.pack(side="left")
        self.add_button = ttk.Button(edit, text="Add as new", style="Toolbox.TButton", command=self.add)
        self.add_button.pack(side="left", padx=(6, 0))
        self.delete_button = ttk.Button(edit, text="Delete", style="Toolbox.TButton", command=self.delete)
        self.delete_button.pack(side="left", padx=(6, 0))
        ttk.Button(side.body, text="Preview form values", style="Toolbox.TButton",
                   command=self._preview_form).pack(anchor="w", pady=(6, 0))

        card = Card(body, "Battlezone 1.5 tables", "Write spritea.stb and sprite8.stb (1.5's stock tables with "
                                                   "this table's entries added) and the sheet MAPs, as the Redux → "
                                                   "1.5 port does. 1.5 replaces its tables whole, so they need the "
                                                   "1.5 install's stock ones.")
        card.pack(fill="x", pady=(12, 12))
        PathPicker(card.body, "Output folder", self.export_dir, kind="dir", surface=True).pack(fill="x", pady=2)
        PathPicker(card.body, "1.5 game folder", self.legacy_dir, kind="dir", surface=True).pack(fill="x", pady=2)
        row = ttk.Frame(card.body, style="Toolbox.Surface.TFrame")
        row.pack(fill="x", pady=2)
        ttk.Label(row, text="Software palette", style="Toolbox.Surface.TLabel", width=18).pack(side="left")
        from battlezone.terrain.colortables import STOCK_WORLDS

        ttk.Combobox(row, textvariable=self.world, values=STOCK_WORLDS, state="readonly", width=12,
                     style="Toolbox.TCombobox").pack(side="left")
        ttk.Label(row, text="the world palette the 8-bit (software) sheets are drawn with",
                  style="Toolbox.SurfaceMuted.TLabel").pack(side="left", padx=(8, 0))
        self.export_button = ttk.Button(card.body, text="Write 1.5 tables", style="Toolbox.Accent.TButton",
                                        command=self.export_legacy)
        self.export_button.pack(anchor="w", pady=(8, 0))

        ttk.Label(body, text="LOG", style="Toolbox.Heading.TLabel").pack(anchor="w")
        self.log = LogView(body, height=6)
        self.log.pack(fill="both", expand=True, pady=(4, 0))
        self._update_buttons()
        self.project_changed(getattr(shell, "project", None))

    # --- loading --------------------------------------------------------------
    def project_changed(self, project) -> None:
        """Show the project's table unless another one is open or has unsaved changes."""
        if self.dirty or (self.path.get() and not self.stock and not self._from_project):
            return
        from bztoolbox.modules.textures.sprite_sheets import find_project_table

        found = find_project_table(getattr(project, "mod_path", None)) if project is not None else None
        if found is not None:
            self.open(str(found))
            self._from_project = True
            return
        if self._from_project:
            self.path.set("")
            self._from_project = False
            self._load(StaDocument(), stock=False, folder=None)
        if not self.path.get():
            self.status.configure(text="Open a .sta, or show the stock sprites.")

    def _confirm_discard(self) -> bool:
        return not self.dirty or messagebox.askyesno("Sprites", "Discard the unsaved changes to the sprite table?")

    def open(self, path: str) -> None:
        if not path:
            return
        if not os.path.isfile(path):
            messagebox.showerror("Sprites", f"No such file:\n{path}")
            return
        if not self._confirm_discard():
            return
        try:
            text = Path(path).read_bytes().decode("cp1252", errors="replace")
        except OSError as exc:
            messagebox.showerror("Sprites", str(exc))
            return
        self.path.set(os.path.normpath(path))
        self._from_project = False
        if not self.export_dir.get():
            self.export_dir.set(str(Path(path).parent / "1.5 sprites"))
        self._load(StaDocument(text), stock=False, folder=Path(path).parent)

    def show_stock(self) -> None:
        if not self._confirm_discard():
            return
        from bztoolbox.modules.textures.sprite_sheets import stock_sta_text

        game_dir = self._game_dir()
        text = stock_sta_text(game_dir) if game_dir else None
        if text is None:
            messagebox.showinfo("Sprites", "Battlezone 98 Redux was not found (set it in Settings › General), or "
                                           "its bzone.zfs has no spritea.st.")
            return
        self.path.set("")
        self._from_project = False
        self._load(StaDocument(text), stock=True, folder=None)

    def _load(self, doc: StaDocument, stock: bool, folder) -> None:
        self.doc, self.stock, self.dirty = doc, stock, False
        self._refresh()
        self._update_buttons()
        what = "Redux's stock spritea.st (read-only)" if stock else self.path.get()
        self.status.configure(text=f"{len(doc.entries)} sprite(s) in {what}")
        self._index_sheets(folder)

    def _index_sheets(self, folder) -> None:
        key = (str(folder) if folder else None, self._game_dir())
        if key == self._sheets_key:
            self._selected()
            return
        self._sheets_key, self.sheets = key, None
        materials = sorted({e.material for e in self.doc.entries}, key=str.lower)

        def work(_job):
            from bztoolbox.modules.textures.sprite_sheets import SpriteSheets

            sheets = SpriteSheets(key[0], key[1])
            missing = [m for m in materials if sheets.texture(m) is None]
            return key, sheets, missing

        self.job = self.shell.jobs.submit("Index sprite sheets", work, on_done=self._indexed, on_error=self._failed)

    def _indexed(self, outcome) -> None:
        key, sheets, missing = outcome
        if key != self._sheets_key:
            return
        self.sheets = sheets
        if missing:
            self.log.write(f"{len(missing)} material(s) have no sheet to preview: " + ", ".join(missing[:12])
                           + (" ..." if len(missing) > 12 else ""), "warning")
        self._refresh()
        self._selected()

    def _failed(self, error: str) -> None:
        self.export_button.state(["!disabled"])
        self.log.write(error, "error")

    # --- table ------------------------------------------------------------------
    def _refresh(self) -> None:
        selected = self._selected_index()
        wanted = self.filter.get().strip().lower()
        self.tree.delete(*self.tree.get_children())
        for index, entry in enumerate(self.doc.entries):
            if wanted and wanted not in entry.name.lower() and wanted not in entry.material.lower():
                continue
            tags = ("nosheet",) if self.sheets is not None and self.sheets.texture(entry.material) is None else ()
            self.tree.insert("", "end", iid=str(index), values=entry_row(entry), tags=tags)
        if selected is not None and self.tree.exists(str(selected)):
            self.tree.selection_set(str(selected))
            self.tree.see(str(selected))

    def _selected_index(self):
        chosen = self.tree.selection()
        return int(chosen[0]) if chosen else None

    def _selected(self, _event=None) -> None:
        index = self._selected_index()
        if index is None or index >= len(self.doc.entries):
            return
        entry = self.doc.entries[index]
        for key, _label in FIELDS:
            value = getattr(entry, key)
            self.form[key].set(f"0x{value:08x}" if key == "flags" else str(value))
        self._show_preview(entry)

    def _preview_form(self) -> None:
        try:
            self._show_preview(entry_from_form({k: v.get() for k, v in self.form.items()}))
        except ValueError as exc:
            self.preview_note.configure(text=str(exc))

    def _show_preview(self, entry: StaEntry) -> None:
        self.preview.configure(image="")
        self._photo = None
        if self.sheets is None:
            self.preview_note.configure(text="Finding the sprite sheets…")
            return
        try:
            image = self.sheets.crop(entry)
        except (OSError, ValueError) as exc:
            self.preview_note.configure(text=f"cannot read the sheet: {exc}")
            return
        if image is None:
            self.preview_note.configure(text=self.sheets.explain(entry.material))
            return
        from PIL import Image, ImageTk

        shown = image.copy()
        scale = PREVIEW_SIZE / max(shown.size)
        size = (max(1, round(shown.width * scale)), max(1, round(shown.height * scale)))
        shown = shown.resize(size, Image.Resampling.NEAREST if scale > 1 else Image.Resampling.LANCZOS)
        backdrop = Image.new("RGBA", shown.size, (40, 40, 40, 255))
        for y in range(0, shown.height, 16):                 # checkerboard behind transparency
            for x in range((y // 16) % 2 * 16, shown.width, 32):
                backdrop.paste((70, 70, 70, 255), (x, y, x + 16, y + 16))
        backdrop.alpha_composite(shown)
        self._photo = ImageTk.PhotoImage(backdrop.convert("RGB"))
        self.preview.configure(image=self._photo, width=PREVIEW_SIZE, height=PREVIEW_SIZE)
        path = self.sheets.texture(entry.material)
        self.preview_note.configure(text=f"{image.width} × {image.height} px of {path.name} "
                                         f"({self.sheets.image(path).width} × {self.sheets.image(path).height})")

    # --- editing -----------------------------------------------------------------
    def _form_entry(self):
        try:
            return entry_from_form({k: v.get() for k, v in self.form.items()})
        except ValueError as exc:
            messagebox.showerror("Sprites", str(exc))
            return None

    def _changed(self, select: int) -> None:
        self.dirty = True
        self._refresh()
        if self.tree.exists(str(select)):
            self.tree.selection_set(str(select))
            self.tree.see(str(select))
        self._update_buttons()
        self.status.configure(text=f"{len(self.doc.entries)} sprite(s) in {self.path.get() or 'a new table'} "
                                   "(unsaved changes)")

    def apply(self) -> None:
        index = self._selected_index()
        entry = self._form_entry()
        if index is None or entry is None or self.stock:
            return
        self.doc.replace(index, entry)
        self._changed(index)

    def add(self) -> None:
        entry = self._form_entry()
        if entry is None or self.stock:
            return
        if any(e.name.lower() == entry.name.lower() for e in self.doc.entries):
            if not messagebox.askyesno("Sprites", f"The table already has {entry.name}; the game uses the first "
                                                  "one. Add another anyway?"):
                return
        self._changed(self.doc.add(entry))

    def delete(self) -> None:
        index = self._selected_index()
        if index is None or self.stock:
            return
        self.doc.delete(index)
        self._changed(min(index, len(self.doc.entries) - 1))

    def save(self) -> None:
        path = self.path.get().strip()
        if self.stock or not path:
            self.save_as()
            return
        self._write(path)

    def save_as(self) -> None:
        current = self.path.get().strip()
        chosen = filedialog.asksaveasfilename(initialdir=os.path.dirname(current) if current else None,
                                              initialfile=os.path.basename(current) if current else "spritea.sta",
                                              defaultextension=".sta", filetypes=STA_TYPES)
        if chosen:
            self._write(os.path.normpath(chosen))

    def _write(self, path: str) -> None:
        try:
            Path(path).write_bytes(self.doc.text().encode("cp1252", errors="replace"))
        except OSError as exc:
            messagebox.showerror("Sprites", str(exc))
            return
        was_stock = self.stock
        self.path.set(path)
        self.stock, self.dirty = False, False
        self._update_buttons()
        self.status.configure(text=f"{len(self.doc.entries)} sprite(s) in {path}")
        self.log.write(f"Saved {path}", "success")
        self.shell.status(f"Sprite table saved to {path}")
        if was_stock:
            self._index_sheets(Path(path).parent)

    def _update_buttons(self) -> None:
        state = ["disabled"] if self.stock else ["!disabled"]
        for button in (self.apply_button, self.add_button, self.delete_button):
            button.state(state)
        self.save_button.state(["!disabled"] if self.dirty and not self.stock else ["disabled"])

    # --- 1.5 ------------------------------------------------------------------
    def export_legacy(self) -> None:
        if self.job is not None and self.job.status in ("queued", "running"):
            return
        path, output = self.path.get().strip(), self.export_dir.get().strip()
        if self.stock or not path or not os.path.isfile(path):
            messagebox.showerror("Sprites", "Open (and save) a .sta first; the stock table is already 1.5's.")
            return
        if self.dirty:
            messagebox.showerror("Sprites", "Save the table first; the 1.5 tables are made from the file.")
            return
        if not output:
            messagebox.showerror("Sprites", "Choose an output folder.")
            return
        options = dict(legacy_dir=self.legacy_dir.get().strip() or None, game_dir=self._game_dir() or None,
                       world=self.world.get())
        self.export_button.state(["disabled"])

        def work(_job):
            from bztoolbox.modules.world.redux_to_legacy import export_sprite_tables

            return export_sprite_tables(path, output, **options)

        self.job = self.shell.jobs.submit("Write 1.5 sprite tables", work, on_done=self._exported,
                                          on_error=self._failed)

    def _exported(self, report) -> None:
        self.export_button.state(["!disabled"])
        for line in report.lines():
            self.log.write(line, "error" if line.startswith("ERROR") else
                           "warning" if line.startswith("WARNING") else "")
        if report.ok:
            self.log.write(f"Done: {report.output}", "success")

    # --- installs ---------------------------------------------------------------
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
