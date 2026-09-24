"""Project > Dependencies: the asset graph from :mod:`battlezone.assets`."""

from __future__ import annotations

import json
import os
import tkinter as tk
from tkinter import filedialog, ttk

from battlezone.assets import build_graph
from battlezone.assets.graph import GraphCancelled
from bztoolbox.app import theme
from bztoolbox.app.widgets import StatBox, humanize_bytes, open_in_file_manager


def _table(parent, columns):
    frame = ttk.Frame(parent, style="Toolbox.TFrame")
    tree = ttk.Treeview(frame, columns=[c[0] for c in columns], show="headings", style="Toolbox.Treeview",
                        selectmode="browse")
    for key, heading, width in columns:
        tree.heading(key, text=heading)
        tree.column(key, width=width, anchor="w", stretch=key == columns[0][0])
    scroll = ttk.Scrollbar(frame, orient="vertical", command=tree.yview, style="Toolbox.Vertical.TScrollbar")
    tree.configure(yscrollcommand=scroll.set)
    tree.pack(side="left", fill="both", expand=True)
    scroll.pack(side="right", fill="y")
    tree.tag_configure("missing", foreground=theme.ERROR)
    tree.tag_configure("external", foreground=theme.MUTED)
    return frame, tree


class DependenciesPage(ttk.Frame):
    def __init__(self, master, shell):
        super().__init__(master, style="Toolbox.TFrame", padding=(18, 4, 18, 12))
        self.shell = shell
        self.graph = None
        self.job = None
        self.filter_var = tk.StringVar()
        self.filter_var.trace_add("write", lambda *_: self._render_files())

        top = ttk.Frame(self, style="Toolbox.TFrame")
        top.pack(fill="x")
        self.target_label = ttk.Label(top, text="", style="Toolbox.TLabel")
        self.target_label.pack(side="left")
        self.run_button = ttk.Button(top, text="Build graph", style="Toolbox.Accent.TButton", command=self.run)
        self.run_button.pack(side="right")
        ttk.Button(top, text="Other folder…", style="Toolbox.TButton", command=self.run_other).pack(side="right", padx=6)
        self.export_button = ttk.Button(top, text="Export JSON…", style="Toolbox.TButton", command=self.export,
                                        state="disabled")
        self.export_button.pack(side="right")

        stats = ttk.Frame(self, style="Toolbox.TFrame")
        stats.pack(fill="x", pady=8)
        self.stat_files = StatBox(stats, "Files", "–")
        self.stat_refs = StatBox(stats, "References", "–")
        self.stat_missing = StatBox(stats, "Missing", "–", theme.ERROR)
        self.stat_unused = StatBox(stats, "Unreferenced", "–", theme.WARNING)
        self.stat_vram = StatBox(stats, "Texture memory", "–")
        for box in (self.stat_files, self.stat_refs, self.stat_missing, self.stat_unused, self.stat_vram):
            box.pack(side="left", padx=(0, 8))

        tabs = ttk.Notebook(self, style="Toolbox.TNotebook")
        tabs.pack(fill="both", expand=True)

        # Files: pick one to see what it needs and what uses it
        files_tab = ttk.Frame(tabs, style="Toolbox.TFrame", padding=(0, 6))
        tabs.add(files_tab, text="Files")
        search = ttk.Frame(files_tab, style="Toolbox.TFrame")
        search.pack(fill="x", pady=(0, 4))
        ttk.Label(search, text="Filter", style="Toolbox.Muted.TLabel").pack(side="left", padx=(0, 6))
        ttk.Entry(search, textvariable=self.filter_var, width=30, style="Toolbox.TEntry").pack(side="left")
        panes = ttk.PanedWindow(files_tab, orient="horizontal")
        panes.pack(fill="both", expand=True)
        frame, self.files = _table(panes, (("file", "File", 280), ("kind", "Kind", 80), ("uses", "Uses", 50),
                                           ("used", "Used by", 60), ("size", "Size", 80)))
        panes.add(frame, weight=3)
        self.files.bind("<<TreeviewSelect>>", self._file_selected)
        self.files.bind("<Double-1>", lambda e: self._reveal())
        detail = ttk.Frame(panes, style="Toolbox.TFrame")
        panes.add(detail, weight=2)
        ttk.Label(detail, text="USED BY (breaks if renamed or removed)", style="Toolbox.Heading.TLabel").pack(anchor="w")
        frame, self.used_by = _table(detail, (("file", "File", 220), ("how", "Reference", 140)))
        frame.pack(fill="both", expand=True, pady=(2, 8))
        ttk.Label(detail, text="NEEDS", style="Toolbox.Heading.TLabel").pack(anchor="w")
        frame, self.needs = _table(detail, (("file", "File", 220), ("how", "Reference", 140)))
        frame.pack(fill="both", expand=True, pady=(2, 0))

        # Missing / not in project
        missing_tab = ttk.Frame(tabs, style="Toolbox.TFrame", padding=(0, 6))
        tabs.add(missing_tab, text="Not in project")
        ttk.Label(missing_tab, text="Red: certainly missing (not in the project and not a stock ODF or palette). "
                                     "Grey: not in the project; the toolbox cannot tell stock models and "
                                     "textures from missing ones.", style="Toolbox.Muted.TLabel",
                  wraplength=900, justify="left").pack(anchor="w", pady=(0, 4))
        frame, self.missing = _table(missing_tab, (("name", "Name", 200), ("kind", "Kind", 80),
                                                   ("from", "Referenced by", 420)))
        frame.pack(fill="both", expand=True)

        unused_tab = ttk.Frame(tabs, style="Toolbox.TFrame", padding=(0, 6))
        tabs.add(unused_tab, text="Unreferenced")
        ttk.Label(unused_tab, text="Files nothing in the project refers to. They are still uploaded; some "
                                    "(for example ODFs only built from stock menus) are used by the game directly.",
                  style="Toolbox.Muted.TLabel", wraplength=900, justify="left").pack(anchor="w", pady=(0, 4))
        frame, self.unused = _table(unused_tab, (("file", "File", 360), ("kind", "Kind", 80), ("size", "Size", 80)))
        frame.pack(fill="both", expand=True)

        tex_tab = ttk.Frame(tabs, style="Toolbox.TFrame", padding=(0, 6))
        tabs.add(tex_tab, text="Texture memory")
        frame, self.textures = _table(tex_tab, (("file", "Texture", 360), ("vram", "Estimated memory", 120),
                                                ("used", "Used by", 60)))
        frame.pack(fill="both", expand=True)

        self.project_changed(shell.project)

    # ------------------------------------------------------------------
    def project_changed(self, project) -> None:
        if project is None:
            self.target_label.configure(text="Open a project to map its dependencies, or pick a folder.")
            self.run_button.configure(state="disabled")
        else:
            self.target_label.configure(text=f"Target: {project.mod_path}")
            self.run_button.configure(state="normal")

    def run(self) -> None:
        if self.shell.project:
            self._start(self.shell.project.mod_path)

    def run_other(self) -> None:
        folder = filedialog.askdirectory(title="Map dependencies of folder", mustexist=True)
        if folder:
            self._start(folder)

    def _start(self, folder: str) -> None:
        if self.job is not None and self.job.status in ("queued", "running"):
            self.job.cancel()
        self.target_label.configure(text=f"Target: {folder}")
        self.run_button.configure(state="disabled")

        def work(job):
            try:
                return build_graph(folder, progress=job.report, cancel=job.cancel_event)
            except GraphCancelled:
                job.check_cancelled()
                raise

        def failed(error):
            self.run_button.configure(state="normal" if self.shell.project else "disabled")
            self.shell.status(f"Dependency scan failed: {error}")

        self.job = self.shell.jobs.submit(f"Dependencies of {os.path.basename(folder) or folder}", work,
                                          on_done=self._done, on_error=failed)

    def _done(self, graph) -> None:
        self.graph = graph
        self.run_button.configure(state="normal" if self.shell.project else "disabled")
        self.export_button.configure(state="normal")
        summary = graph.summary()
        self.stat_files.set(summary["files"])
        self.stat_refs.set(summary["references"])
        self.stat_missing.set(summary["missing"])
        self.stat_unused.set(summary["unreferenced"])
        self.stat_vram.set(humanize_bytes(summary["texture_bytes"]))
        self._render_files()
        self.missing.delete(*self.missing.get_children())
        missing = {node.key for node, _ in graph.missing()}
        for node, refs in graph.not_in_project():
            sources = ", ".join(sorted({e.source for e in refs}))
            self.missing.insert("", "end", values=(node.name, node.kind, sources),
                                tags=("missing" if node.key in missing else "external",))
        self.unused.delete(*self.unused.get_children())
        for node in graph.unreferenced():
            self.unused.insert("", "end", values=(node.key, node.kind, humanize_bytes(node.size)))
        self.textures.delete(*self.textures.get_children())
        for node in graph.textures_by_memory():
            self.textures.insert("", "end", values=(node.key, humanize_bytes(node.texture_bytes),
                                                    len(graph.used_by(node.key))))
        self.shell.status(f"{summary['files']} files, {summary['missing']} missing reference(s), "
                          f"{summary['unreferenced']} unreferenced file(s).")

    def _render_files(self) -> None:
        self.files.delete(*self.files.get_children())
        if self.graph is None:
            return
        query = self.filter_var.get().strip().lower()
        for node in self.graph.files:
            if query and query not in node.key.lower():
                continue
            self.files.insert("", "end", iid=node.key, values=(
                node.key, node.kind, len(self.graph.uses(node.key)), len(self.graph.used_by(node.key)),
                humanize_bytes(node.size)))

    def _file_selected(self, _event=None) -> None:
        selection = self.files.selection()
        for table in (self.used_by, self.needs):
            table.delete(*table.get_children())
        if not selection or self.graph is None:
            return
        key = selection[0]
        for edge in self.graph.used_by(key):
            self.used_by.insert("", "end", values=(edge.source, _describe(edge)))
        for edge in self.graph.uses(key):
            node = self.graph.nodes.get(edge.target)
            tag = () if node is None or node.in_project else ("external",)
            self.needs.insert("", "end", values=(node.key if node and node.in_project else node.name if node else
                                                 edge.target, _describe(edge)), tags=tag)

    def _reveal(self) -> None:
        selection = self.files.selection()
        if selection and self.graph is not None:
            path = os.path.join(self.graph.root, selection[0])
            open_in_file_manager(os.path.dirname(path))

    def export(self) -> None:
        if self.graph is None:
            return
        path = filedialog.asksaveasfilename(title="Export dependency graph", defaultextension=".json",
                                            filetypes=[("JSON", "*.json")])
        if path:
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(self.graph.to_dict(), handle, indent=2)
            self.shell.status(f"Graph written to {path}")


def _describe(edge) -> str:
    label = edge.kind.replace("-", " → ")
    return f"{label} ({edge.detail})" if edge.detail else label
