"""Assets > ODF Explorer: effective ODF fields and craft/weapon stat tables (:mod:`battlezone.odf.explorer`)."""

from __future__ import annotations

import os
import tkinter as tk
from dataclasses import dataclass
from tkinter import filedialog, ttk
from typing import List, Optional

from battlezone.odf.explorer import CRAFT_COLUMNS, WEAPON_COLUMNS, ODFLibrary, Problem, sort_key, write_csv
from battlezone.project import folder_fingerprint
from bztoolbox.app import theme
from bztoolbox.app.widgets import add_scrollbars
from bztoolbox.odf_explorer import default_game_dir

PAGE_ID = "assets.odf"
_STATUS_TEXT = {"set": "ODF", "default": "default", "unread": "unread"}


@dataclass
class _Result:
    folder: str
    fingerprint: tuple
    library: ODFLibrary
    listing: list          # (name, file, classLabel, class)
    craft: List[dict]
    weapons: List[dict]
    problems: List[Problem]


def _table(parent, columns, show="headings", selectmode="browse"):
    frame = ttk.Frame(parent, style="Toolbox.TFrame")
    tree = ttk.Treeview(frame, columns=[c[0] for c in columns], show=show, style="Toolbox.Treeview",
                        selectmode=selectmode)
    for key, heading, width in columns:
        tree.heading(key, text=heading)
        tree.column(key, width=width, anchor="w", stretch=False)
    add_scrollbars(frame, tree)
    return frame, tree


class _StatTable:
    """A sortable stat table (click a heading) with CSV export of what is shown."""

    def __init__(self, parent, columns, on_heading):
        self.columns = columns
        self.rows: List[dict] = []
        self.sort_column = ""
        self.descending = False
        shown = [(name, name, 70 if name not in ("odf", "file", "unitName", "wpnName", "weapons", "defaulted")
                  else 150) for name, _ in columns]
        self.frame, self.tree = _table(parent, shown)
        self._on_heading = on_heading
        for name, _ in columns:
            self.tree.heading(name, command=lambda n=name: self.sort(n))

    def set_rows(self, rows: List[dict]) -> None:
        self.rows = list(rows)
        self._render()

    def sort(self, column: str) -> None:
        self.descending = not self.descending if column == self.sort_column else column not in (
            "odf", "file", "unitName", "wpnName", "classLabel", "class", "ordName")
        self.sort_column = column
        self._render()
        self._on_heading(column, dict(self.columns).get(column, ""))

    def _render(self) -> None:
        self.tree.delete(*self.tree.get_children())
        rows = self.rows
        if self.sort_column:
            rows = sorted(rows, key=lambda r: sort_key(str(r.get(self.sort_column, ""))), reverse=self.descending)
            # Keep blanks last in both directions.
            rows = [r for r in rows if r.get(self.sort_column, "") != ""] + \
                   [r for r in rows if r.get(self.sort_column, "") == ""]
        for name, _ in self.columns:
            arrow = (" ▼" if self.descending else " ▲") if name == self.sort_column else ""
            self.tree.heading(name, text=name + arrow)
        for row in rows:
            self.tree.insert("", "end", values=[row.get(name, "") for name, _ in self.columns],
                             tags=("defaulted",) if row.get("defaulted") else ())

    def visible_rows(self) -> List[dict]:
        names = [name for name, _ in self.columns]
        return [dict(zip(names, self.tree.item(iid, "values"))) for iid in self.tree.get_children()]


class ODFExplorerPage(ttk.Frame):
    """Tables fill the page, so it is a plain frame like Dependencies rather than a ScrollableFrame."""

    def __init__(self, master, shell):
        super().__init__(master, style="Toolbox.TFrame", padding=(18, 4, 18, 12))
        self.shell = shell
        self.job = None
        self.result: Optional[_Result] = None
        self.current = None                 # EffectiveODF on screen
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *_: self._render_list())
        self.defaults_var = tk.BooleanVar(value=True)
        self.unread_var = tk.BooleanVar(value=True)

        top = ttk.Frame(self, style="Toolbox.TFrame")
        top.pack(fill="x")
        self.target_label = ttk.Label(top, text="", style="Toolbox.TLabel")
        self.target_label.pack(side="left")
        self.run_button = ttk.Button(top, text="Reload", style="Toolbox.Accent.TButton", command=self.run)
        self.run_button.pack(side="right")
        ttk.Button(top, text="Other folder…", style="Toolbox.TButton", command=self.run_other).pack(side="right",
                                                                                                     padx=6)
        self.stock_label = ttk.Label(self, text="", style="Toolbox.Muted.TLabel", wraplength=1000, justify="left")
        self.stock_label.pack(anchor="w", pady=(2, 6))

        tabs = ttk.Notebook(self, style="Toolbox.TNotebook")
        tabs.pack(fill="both", expand=True)
        self._build_fields_tab(tabs)
        self._build_stats_tab(tabs)
        self._build_problems_tab(tabs)
        self.project_changed(shell.project)

    # --- layout ------------------------------------------------------------------
    def _build_fields_tab(self, tabs) -> None:
        tab = ttk.Frame(tabs, style="Toolbox.TFrame", padding=(0, 6))
        tabs.add(tab, text="Fields")
        ttk.Label(tab, text="Redux has no ODF-to-ODF inheritance: a field comes from the ODF itself, else from the "
                            "prototype its classLabel selects (grey). baseName does not load another ODF. A project "
                            "ODF replaces the stock ODF of the same name entirely.",
                  style="Toolbox.Muted.TLabel", wraplength=1000, justify="left").pack(anchor="w", pady=(0, 4))
        panes = ttk.PanedWindow(tab, orient="horizontal")
        panes.pack(fill="both", expand=True)

        left = ttk.Frame(panes, style="Toolbox.TFrame")
        panes.add(left, weight=1)
        search = ttk.Frame(left, style="Toolbox.TFrame")
        search.pack(fill="x", pady=(0, 4))
        ttk.Label(search, text="Search", style="Toolbox.Muted.TLabel").pack(side="left", padx=(0, 6))
        ttk.Entry(search, textvariable=self.search_var, style="Toolbox.TEntry").pack(side="left", fill="x",
                                                                                     expand=True)
        frame, self.odf_list = _table(left, (("name", "ODF", 120), ("label", "classLabel", 100),
                                             ("file", "File", 160)))
        frame.pack(fill="both", expand=True)
        self.odf_list.bind("<<TreeviewSelect>>", self._odf_selected)

        right = ttk.Frame(panes, style="Toolbox.TFrame")
        panes.add(right, weight=3)
        self.header = ttk.Label(right, text="Pick an ODF.", style="Toolbox.TLabel", wraplength=800, justify="left")
        self.header.pack(anchor="w")
        options = ttk.Frame(right, style="Toolbox.TFrame")
        options.pack(fill="x", pady=(2, 4))
        ttk.Checkbutton(options, text="Show prototype defaults", variable=self.defaults_var,
                        style="Toolbox.TCheckbutton", command=self._render_fields).pack(side="left")
        ttk.Checkbutton(options, text="Show unread keys", variable=self.unread_var,
                        style="Toolbox.TCheckbutton", command=self._render_fields).pack(side="left", padx=(12, 0))
        frame, self.fields = _table(right, (("value", "Value", 160), ("status", "Kind", 70), ("from", "From", 320)),
                                    show="tree headings")
        self.fields.heading("#0", text="Section / key")
        self.fields.column("#0", width=220, stretch=False)
        self.fields.tag_configure("default", foreground=theme.MUTED)
        self.fields.tag_configure("unread", foreground=theme.WARNING)
        self.fields.tag_configure("overridden", foreground=theme.ACCENT_2)
        self.fields.tag_configure("section", foreground=theme.ACCENT)
        self.fields.bind("<<TreeviewSelect>>", self._field_selected)
        frame.pack(fill="both", expand=True)
        self.chain_label = ttk.Label(right, text="", style="Toolbox.Muted.TLabel", wraplength=800, justify="left")
        self.chain_label.pack(anchor="w", pady=(4, 0))
        self._field_items: dict = {}

    def _build_stats_tab(self, tabs) -> None:
        tab = ttk.Frame(tabs, style="Toolbox.TFrame", padding=(0, 6))
        tabs.add(tab, text="Stats")
        row = ttk.Frame(tab, style="Toolbox.TFrame")
        row.pack(fill="x", pady=(0, 4))
        ttk.Label(row, text="Effective values of the project's craft and weapons (weapons joined with their "
                            "ordnance and its vehicle-hit explosion). Click a heading to sort.",
                  style="Toolbox.Muted.TLabel", wraplength=800, justify="left").pack(side="left")
        ttk.Button(row, text="Export CSV…", style="Toolbox.TButton", command=self.export_csv).pack(side="right")
        self.column_label = ttk.Label(tab, text="", style="Toolbox.TLabel", wraplength=1000, justify="left")
        self.column_label.pack(anchor="w", pady=(0, 4))
        self.stat_tabs = ttk.Notebook(tab, style="Toolbox.TNotebook")
        self.stat_tabs.pack(fill="both", expand=True)
        self.craft_table = _StatTable(self.stat_tabs, CRAFT_COLUMNS, self._heading_clicked)
        self.stat_tabs.add(self.craft_table.frame, text="Craft")
        self.weapon_table = _StatTable(self.stat_tabs, WEAPON_COLUMNS, self._heading_clicked)
        self.stat_tabs.add(self.weapon_table.frame, text="Weapons")

    def _build_problems_tab(self, tabs) -> None:
        tab = ttk.Frame(tabs, style="Toolbox.TFrame", padding=(0, 6))
        tabs.add(tab, text="Problems")
        ttk.Label(tab, text="Objects whose classLabel selects no Redux class, ODF names that neither the project nor "
                            "the stock game defines, and ODFs the project contains more than once.",
                  style="Toolbox.Muted.TLabel", wraplength=1000, justify="left").pack(anchor="w", pady=(0, 4))
        frame, self.problem_table = _table(tab, (("file", "File", 220), ("kind", "Kind", 80),
                                                 ("message", "Message", 700)))
        frame.pack(fill="both", expand=True)

    # --- project -----------------------------------------------------------------
    def project_changed(self, project) -> None:
        if project is None:
            self.target_label.configure(text="Open a project to explore its ODFs, or pick a folder.")
            self.run_button.configure(state="disabled")
        else:
            self.target_label.configure(text=f"Target: {project.mod_path}")
            self.run_button.configure(state="normal")
        if self.result is not None and (project is None or
                                        os.path.normcase(self.result.folder) != os.path.normcase(project.mod_path)):
            self._clear()
        if self.shell.current_page == PAGE_ID:
            self.on_show()

    def on_show(self) -> None:
        project = self.shell.project
        if project is None or (self.job is not None and self.job.status in ("queued", "running")):
            return
        if self.result is not None and os.path.normcase(self.result.folder) != os.path.normcase(project.mod_path):
            return   # an "Other folder…" result is on screen
        self._start(project.mod_path, only_if_changed=True)

    def run(self) -> None:
        if self.shell.project:
            self._start(self.shell.project.mod_path)

    def run_other(self) -> None:
        folder = filedialog.askdirectory(title="Explore the ODFs of folder", mustexist=True)
        if folder:
            self._start(folder)

    def _start(self, folder: str, only_if_changed: bool = False) -> None:
        if self.job is not None and self.job.status in ("queued", "running"):
            self.job.cancel()
        self.target_label.configure(text=f"Target: {folder}")
        self.run_button.configure(state="disabled")
        previous = self.result.fingerprint if self.result is not None else None
        game_dir = default_game_dir(self.shell.settings)

        def work(job):
            fingerprint = (os.path.normcase(folder), folder_fingerprint(folder), game_dir)
            if only_if_changed and fingerprint == previous:
                return None
            job.report(0, "Reading ODFs")
            library = ODFLibrary(folder, game_dir)
            listing = []
            for name in library.project_names():
                job.check_cancelled()
                eff = library.effective(name)
                if eff is not None:
                    listing.append((name, eff.entry.rel, eff.dispatch.label, eff.dispatch.cls))
            job.report(0.6, "Building stat tables")
            craft, weapons = library.craft_rows(), library.weapon_rows()
            return _Result(folder, fingerprint, library, listing, craft, weapons, library.problems())

        def failed(error):
            self.run_button.configure(state="normal" if self.shell.project else "disabled")
            self.shell.status(f"ODF explorer failed: {error}")

        self.job = self.shell.jobs.submit(f"ODFs of {os.path.basename(folder) or folder}", work,
                                          on_done=self._done, on_error=failed)

    def _done(self, result: Optional[_Result]) -> None:
        self.run_button.configure(state="normal" if self.shell.project else "disabled")
        if result is None:
            return
        self.result = result
        library = result.library
        if library.stock_source:
            stock = f"Stock ODFs: {len(library.stock)} from {library.stock_source}."
        else:
            stock = " ".join(library.warnings) or "Stock ODFs not loaded."
        self.stock_label.configure(text=f"{len(result.listing)} project ODF(s). {stock}")
        self._render_list()
        self.craft_table.set_rows(result.craft)
        self.weapon_table.set_rows(result.weapons)
        self.problem_table.delete(*self.problem_table.get_children())
        for problem in result.problems:
            self.problem_table.insert("", "end", values=(problem.odf, problem.kind, problem.message))
        self.shell.status(f"{len(result.listing)} ODFs, {len(result.craft)} craft, {len(result.weapons)} weapons, "
                          f"{len(result.problems)} problem(s).")

    def _clear(self) -> None:
        self.result = None
        self.current = None
        for tree in (self.odf_list, self.fields, self.problem_table):
            tree.delete(*tree.get_children())
        self.craft_table.set_rows([])
        self.weapon_table.set_rows([])
        self.header.configure(text="Pick an ODF.")
        self.chain_label.configure(text="")
        self.stock_label.configure(text="")

    # --- fields ------------------------------------------------------------------
    def _render_list(self) -> None:
        self.odf_list.delete(*self.odf_list.get_children())
        if self.result is None:
            return
        query = self.search_var.get().strip().lower()
        for name, rel, label, cls in self.result.listing:
            if query and query not in name and query not in label.lower() and query not in rel.lower():
                continue
            self.odf_list.insert("", "end", iid=name, values=(name, label, rel))

    def _odf_selected(self, _event=None) -> None:
        selection = self.odf_list.selection()
        if not selection or self.result is None:
            return
        self.show_odf(selection[0])

    def show_odf(self, name: str) -> None:
        if self.result is None:
            return
        self.current = self.result.library.effective(name)
        if self.current is None:
            self.header.configure(text=f"No {name}.odf")
            return
        eff = self.current
        lines = [f"{eff.entry.label}   class: {eff.dispatch.describe()}"]
        if eff.replaces_stock:
            lines.append(f"Replaces stock {eff.entry.filename}: keys only the stock copy sets are not used.")
        if eff.other_copies:
            lines.append("Other copies in the project: " + ", ".join(e.rel for e in eff.other_copies))
        self.header.configure(text="\n".join(lines))
        self._render_fields()

    def _render_fields(self) -> None:
        self.fields.delete(*self.fields.get_children())
        self._field_items.clear()
        self.chain_label.configure(text="")
        if self.current is None:
            return
        parents = {}
        for item in self.current.fields:
            if item.status == "default" and not self.defaults_var.get():
                continue
            if item.status == "unread" and not self.unread_var.get():
                continue
            if item.section not in parents:
                parents[item.section] = self.fields.insert("", "end", text=f"[{item.section}]", open=True,
                                                           tags=("section",))
            value = "(unknown)" if item.value is None else item.value
            origin = item.note if item.status == "unread" else item.source
            tag = "overridden" if item.overridden and any(o.kind == "stock" for o in item.chain) else item.status
            iid = self.fields.insert(parents[item.section], "end", text=item.key,
                                     values=(value, _STATUS_TEXT[item.status], origin), tags=(tag,))
            self._field_items[iid] = item

    def _field_selected(self, _event=None) -> None:
        selection = self.fields.selection()
        item = self._field_items.get(selection[0]) if selection else None
        if item is None:
            self.chain_label.configure(text="")
            return
        parts = []
        for index, origin in enumerate(item.chain):
            value = "(unknown)" if origin.value is None else (origin.value or '""')
            parts.append(("uses " if index == 0 and item.status != "unread" else "then ") + f"{value}  ({origin.source})")
        reader = f"Read by {item.reader}. " if item.reader else ""
        self.chain_label.configure(text=reader + "  ·  ".join(parts) + (f"\n{item.note}" if item.note else ""))

    # --- stats -------------------------------------------------------------------
    def _heading_clicked(self, column: str, description: str) -> None:
        self.column_label.configure(text=f"{column}: {description}")

    def export_csv(self) -> None:
        index = self.stat_tabs.index(self.stat_tabs.select())
        table, kind = (self.craft_table, "craft") if index == 0 else (self.weapon_table, "weapons")
        if not table.rows:
            self.shell.status("Nothing to export yet.")
            return
        path = filedialog.asksaveasfilename(title=f"Export {kind} stats", defaultextension=".csv",
                                            initialfile=f"{kind}.csv", filetypes=[("CSV", "*.csv")])
        if path:
            write_csv(table.visible_rows(), table.columns, path)
            self.shell.status(f"{len(table.rows)} {kind} row(s) written to {path}")
