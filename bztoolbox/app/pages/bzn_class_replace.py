"""Missions > Replace object class: preview before changing mission records."""
from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from battlezone.bzn.class_replace import (
    apply_replacement, load_mission, object_rows, preview_replacement,
)
from bztoolbox.app.widgets import Card, LogView, PathPicker, ScrollableFrame

BZN_TYPES = (("BZN missions", "*.bzn"), ("All files", "*.*"))


class BZNClassReplacePage(ScrollableFrame):
    def __init__(self, master, shell):
        super().__init__(master)
        self.shell = shell
        self.job = None
        self.plan = None
        self.loaded_paths = None
        self.fields = {key: tk.StringVar() for key in ("source", "template", "target", "output")}
        for var in self.fields.values():
            var.trace_add("write", self._invalidate)
        body = ttk.Frame(self.body, style="Toolbox.TFrame", padding=(18, 4, 18, 18))
        body.pack(fill="both", expand=True)
        card = Card(body, "Replace object class", "Use a matching prototype to rebuild selected objects. "
                    "Identity, placement, team and labels are preserved. Health, ammo, physics and class "
                    "state come from the prototype; commands and copied references are cleared. "
                    "The target ODF supplies classLabel and is left unchanged.")
        card.pack(fill="x", pady=(0, 12))
        for key, title, kind, types in (
            ("source", "Mission BZN", "file", BZN_TYPES),
            ("template", "Prototype BZN", "file", BZN_TYPES),
            ("target", "Target Redux ODF", "file", (("ODF files", "*.odf"),)),
            ("output", "Output BZN", "save", BZN_TYPES),
        ):
            PathPicker(card.body, title, self.fields[key], kind=kind, filetypes=types, surface=True,
                       on_change=lambda _v, k=key: self._chosen(k)).pack(fill="x", pady=2)
        ttk.Label(card.body, text="Source and prototype must be Redux mission maps of the same version. "
                  "ASCII and binary are supported. Replacing an existing output creates a timestamped backup.",
                  style="Toolbox.SurfaceMuted.TLabel", wraplength=900, justify="left").pack(anchor="w", pady=6)
        self.load_button = ttk.Button(card.body, text="Load objects", command=self.load_objects)
        self.load_button.pack(anchor="w")
        self.source_tree = self._table(body, "Objects to replace (select one or more)", "extended", 7)
        self.prototype_tree = self._table(body, "Prototype object (select one)", "browse", 5)
        actions = ttk.Frame(body, style="Toolbox.TFrame")
        actions.pack(fill="x", pady=8)
        self.preview_button = ttk.Button(actions, text="Preview replacement", command=self.preview)
        self.preview_button.pack(side="left")
        self.apply_button = ttk.Button(actions, text="Write BZN", command=self.apply,
                                       style="Toolbox.Accent.TButton", state="disabled")
        self.apply_button.pack(side="left", padx=8)
        self.log = LogView(body, height=14)
        self.log.pack(fill="both", expand=True)
        self.log.write("Load the mission and prototype, select objects, then preview. No files change until Write BZN.", "muted")

    def _table(self, parent, title, mode, height):
        card = Card(parent, title)
        card.pack(fill="x", pady=(0, 10))
        tree = ttk.Treeview(card.body, columns=("index", "odf", "label", "seqno", "record_class"),
                            show="headings", selectmode=mode, height=height)
        for key, text, width in (("index", "Index", 55), ("odf", "ODF", 100), ("label", "Label", 220),
                                 ("seqno", "Sequence", 85), ("record_class", "Record layout", 160)):
            tree.heading(key, text=text)
            tree.column(key, width=width, stretch=key in ("label", "record_class"))
        scrollbar = ttk.Scrollbar(card.body, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        tree.pack(side="left", fill="both", expand=True)
        tree.bind("<<TreeviewSelect>>", self._invalidate)
        return tree

    def _invalidate(self, *_):
        self.plan = None
        if hasattr(self, "apply_button"):
            self.apply_button.state(["disabled"])

    def _chosen(self, key):
        if key == "source" and not self.fields["output"].get():
            path = Path(self.fields["source"].get())
            self.fields["output"].set(str(path.with_name(path.stem + "_reclass.bzn")))

    def _busy(self):
        return self.job is not None and self.job.status in ("queued", "running")

    def _buttons(self, busy):
        for button in (self.load_button, self.preview_button):
            button.state(["disabled" if busy else "!disabled"])
        self.apply_button.state(["!disabled" if not busy and self.plan else "disabled"])

    def _paths(self):
        return tuple(self.fields[key].get().strip() for key in ("source", "template"))

    def _signature(self):
        return (tuple(var.get().strip() for var in self.fields.values()),
                tuple(sorted(self.source_tree.selection())), tuple(self.prototype_tree.selection()))

    def load_objects(self):
        if self._busy():
            return
        paths = self._paths()
        if not all(paths):
            messagebox.showerror("Replace object class", "Choose a mission and prototype BZN.")
            return
        self._invalidate()
        self._buttons(True)
        self.log.clear()
        self.log.write("Reading mission objects…", "info")

        def work(_job):
            return [object_rows(load_mission(path)) for path in paths]

        def done(rows):
            if paths != self._paths():
                self._failed("Paths changed while loading. Load objects again.")
                return
            for tree, values in zip((self.source_tree, self.prototype_tree), rows):
                tree.delete(*tree.get_children())
                for row in values:
                    tree.insert("", "end", iid=str(row["index"]),
                                values=[row[key] for key in tree["columns"]])
            self.loaded_paths = paths
            self._buttons(False)
            self.log.write(f"Loaded {len(rows[0])} mission objects and {len(rows[1])} prototype objects.")

        self.job = self.shell.jobs.submit("Load BZN objects", work, on_done=done, on_error=self._failed)

    def preview(self):
        if self._busy():
            return
        if self.loaded_paths != self._paths():
            messagebox.showerror("Replace object class", "Load objects for the current files first.")
            return
        indices = [int(i) for i in self.source_tree.selection()]
        donor = self.prototype_tree.selection()
        target = self.fields["target"].get().strip()
        if not indices or len(donor) != 1 or not target:
            messagebox.showerror("Replace object class", "Select source objects, one prototype and a target ODF.")
            return
        source, template = self._paths()
        signature = self._signature()
        self._invalidate()
        self._buttons(True)
        self.log.clear()
        self.log.write("Building and verifying preview…", "info")

        def done(plan):
            if signature != self._signature():
                self._failed("Selection changed while previewing. Preview again.")
                return
            self.plan = plan
            self._buttons(False)
            self.log.clear()
            for line in plan.summary_lines():
                self.log.write(line)
            self.log.write("Preview verified. Write BZN applies these changes and backs up any existing output.", "success")

        self.job = self.shell.jobs.submit("Preview BZN class replacement",
            lambda _job: preview_replacement(source, template, indices, int(donor[0]), target),
            on_done=done, on_error=self._failed)

    def apply(self):
        if self._busy() or self.plan is None:
            return
        output = self.fields["output"].get().strip()
        if not output:
            messagebox.showerror("Replace object class", "Choose an output BZN.")
            return
        plan = self.plan
        self._buttons(True)

        def done(result):
            self._invalidate()
            self.loaded_paths = None
            self._buttons(False)
            self.log.write(f"Written: {result['output']}", "success")
            if result["backup"]:
                self.log.write(f"Backup: {result['backup']}")
            self.log.write(f"Report: {result.get('report', result.get('report_warning'))}")
            self.shell.status("BZN records replaced. Reload the map in Redux to check its behaviour.")

        self.job = self.shell.jobs.submit("Write BZN class replacement",
            lambda _job: apply_replacement(plan, output), on_done=done, on_error=self._failed)

    def _failed(self, error):
        self._invalidate()
        self._buttons(False)
        self.log.write(str(error), "error")
