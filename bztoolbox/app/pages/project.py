"""Project overview: shared metadata and what the mod folder contains."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from battlezone.project import GAMES, UNKNOWN_PLANET, ProjectSummary
from bztoolbox.app.widgets import Card, ScrollableFrame, StatBox, humanize_bytes, open_in_file_manager

FIELDS = (
    ("title", "Title"),
    ("author", "Author"),
    ("item_id", "Workshop item ID"),
    ("tags", "Workshop tags"),
    ("preview_path", "Preview image"),
)


class ProjectPage(ScrollableFrame):
    def __init__(self, master, shell):
        super().__init__(master)
        self.shell = shell
        self.vars = {key: tk.StringVar() for key, _ in FIELDS}
        self.game_var = tk.StringVar()
        self._summary_job = None
        self._loaded: dict = {}      # what the form showed when filled, to tell user edits apart

        self.empty = ttk.Frame(self.body, style="Toolbox.TFrame", padding=20)
        ttk.Label(self.empty, text="No project is open.", style="Toolbox.Heading.TLabel").pack(anchor="w")
        ttk.Label(self.empty, text="A project is a mod content folder. Its metadata is kept in your toolbox "
                                   "profile, never inside the folder, so it is not uploaded with the mod.",
                  style="Toolbox.Muted.TLabel", wraplength=700, justify="left").pack(anchor="w", pady=(4, 10))
        ttk.Button(self.empty, text="Open mod folder…", style="Toolbox.Accent.TButton",
                   command=shell.open_project_dialog).pack(anchor="w")

        self.content = ttk.Frame(self.body, style="Toolbox.TFrame", padding=(18, 4, 18, 18))
        self.content.columnconfigure(0, weight=1)
        self.content.columnconfigure(1, weight=1)

        meta = Card(self.content, "Project", "Shared by every module. Workshop fields are the same "
                                             "ones the Publish page uses.")
        meta.grid(row=0, column=0, sticky="nsew", padx=(0, 8), pady=(0, 12))
        form = meta.body
        form.columnconfigure(1, weight=1)
        self.path_label = ttk.Label(form, text="", style="Toolbox.SurfaceMuted.TLabel")
        self.path_label.grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 6))
        ttk.Label(form, text="Game", style="Toolbox.Surface.TLabel").grid(row=1, column=0, sticky="w", pady=2)
        ttk.Combobox(form, textvariable=self.game_var, values=list(GAMES.values()), state="readonly",
                     style="Toolbox.TCombobox").grid(row=1, column=1, sticky="ew", pady=2)
        for row, (key, label) in enumerate(FIELDS, start=2):
            ttk.Label(form, text=label, style="Toolbox.Surface.TLabel").grid(row=row, column=0, sticky="w", padx=(0, 10), pady=2)
            ttk.Entry(form, textvariable=self.vars[key], style="Toolbox.TEntry").grid(row=row, column=1, sticky="ew", pady=2)
        row = len(FIELDS) + 2
        ttk.Label(form, text="Description", style="Toolbox.Surface.TLabel").grid(row=row, column=0, sticky="nw", pady=2)
        self.description = tk.Text(form, height=6, bg="#050505", fg="#d4d4d4", insertbackground="#00ff00",
                                   relief="flat", wrap="word", highlightthickness=1, highlightbackground="#263026")
        self.description.grid(row=row, column=1, sticky="ew", pady=2)
        buttons = ttk.Frame(form, style="Toolbox.Surface.TFrame")
        buttons.grid(row=row + 1, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        ttk.Button(buttons, text="Save", style="Toolbox.Accent.TButton", command=self.save).pack(side="left")
        ttk.Button(buttons, text="Open folder", style="Toolbox.TButton",
                   command=lambda: open_in_file_manager(self.shell.project.mod_path) if self.shell.project else None
                   ).pack(side="left", padx=6)
        self.saved_label = ttk.Label(buttons, text="", style="Toolbox.SurfaceSuccess.TLabel")
        self.saved_label.pack(side="left", padx=6)

        contents = Card(self.content, "Contents")
        contents.grid(row=0, column=1, sticky="nsew", padx=(8, 0), pady=(0, 12))
        stats = ttk.Frame(contents.body, style="Toolbox.Surface.TFrame")
        stats.pack(fill="x")
        self.stat_files = StatBox(stats, "Files")
        self.stat_size = StatBox(stats, "Size")
        self.stat_missions = StatBox(stats, "Missions")
        self.stat_worlds = StatBox(stats, "Planets")
        for index, box in enumerate((self.stat_files, self.stat_size, self.stat_missions, self.stat_worlds)):
            box.grid(row=index // 2, column=index % 2, sticky="ew", padx=(0, 6), pady=(0, 6))
        stats.columnconfigure(0, weight=1)
        stats.columnconfigure(1, weight=1)
        self.kinds = ttk.Frame(contents.body, style="Toolbox.Surface.TFrame")
        self.kinds.pack(fill="x", pady=(10, 0))

        workflow = Card(self.content, "Next steps")
        workflow.grid(row=1, column=0, columnspan=2, sticky="ew")
        for text, page in (("Validate the project", "project.validation"),
                           ("Localize unit names", "project.localization"),
                           ("Publish to the Steam Workshop", "project.publish")):
            ttk.Button(workflow.body, text=text, style="Toolbox.Link.TButton",
                       command=lambda p=page: shell.navigate(p)).pack(anchor="w")
        self.project_changed(shell.project)

    # ------------------------------------------------------------------
    def project_changed(self, project) -> None:
        if project is None:
            self.content.pack_forget()
            self.empty.pack(fill="both", expand=True)
            return
        self.empty.pack_forget()
        self.content.pack(fill="both", expand=True)
        self.path_label.configure(text=project.mod_path)
        self._fill_form(project)
        self.saved_label.configure(text="")
        self._refresh_summary(project)

    def _form_values(self) -> dict:
        values = {key: self.vars[key].get().strip() for key, _ in FIELDS}
        values["game"] = self.game_var.get()
        values["description"] = self.description.get("1.0", "end").strip()
        return values

    def _fill_form(self, project) -> None:
        self.game_var.set(project.game_name)
        for key, _ in FIELDS:
            self.vars[key].set(getattr(project, key) or "")
        self.description.delete("1.0", "end")
        self.description.insert("1.0", project.description or "")
        self._loaded = self._form_values()

    def project_reloaded(self, project) -> None:
        """Another module (Publish) saved newer values; show them unless the user is editing here."""
        if self._loaded and self._form_values() != self._loaded:
            return
        self._fill_form(project)

    def on_show(self) -> None:
        if self.shell.project:
            # Pick up edits other modules made to the shared profile.
            self.shell.project = self.shell.projects.reload(self.shell.project)
            self.project_reloaded(self.shell.project)
            self._refresh_summary(self.shell.project)

    def save(self) -> None:
        project = self.shell.project
        if project is None:
            return
        # Only what was edited here: a field left alone keeps whatever another
        # module (Publish, Steam sync) saved since the form was filled.
        values = self._form_values()
        for key, _ in FIELDS:
            if values[key] != self._loaded.get(key):
                setattr(project, key, values[key])
        if values["game"] != self._loaded.get("game"):
            project.game = next((k for k, v in GAMES.items() if v == values["game"]), project.game)
        if values["description"] != self._loaded.get("description"):
            project.description = values["description"]
        self.shell.save_project()
        self.shell.set_project(project)
        self.saved_label.configure(text="Saved.")

    def _refresh_summary(self, project) -> None:
        if self._summary_job is not None and self._summary_job.status in ("queued", "running"):
            self._summary_job.cancel()
        self._summary_job = self.shell.jobs.submit(
            f"Index {project.name}", lambda job: project.summarize(), on_done=self._show_summary)

    def _show_summary(self, summary: ProjectSummary) -> None:
        self.stat_files.set(summary.file_count)
        self.stat_size.set(humanize_bytes(summary.total_bytes))
        self.stat_missions.set(len(summary.missions))
        known = [name for name in summary.planets if name != UNKNOWN_PLANET]
        self.stat_worlds.set(len(known))
        for child in self.kinds.winfo_children():
            child.destroy()
        for kind, count in summary.kinds.items():
            row = ttk.Frame(self.kinds, style="Toolbox.Surface.TFrame")
            row.pack(fill="x")
            ttk.Label(row, text=kind, style="Toolbox.Surface.TLabel", width=14).pack(side="left")
            ttk.Label(row, text=str(count), style="Toolbox.SurfaceMuted.TLabel").pack(side="left")
        if summary.planets:
            per_planet = "  ·  ".join(f"{name} {count}" for name, count in summary.planets.items())
            ttk.Label(self.kinds, text=f"Missions by planet: {per_planet}", style="Toolbox.Surface.TLabel",
                      wraplength=480, justify="left").pack(anchor="w", pady=(8, 0))
        if len(summary.worlds) != len(summary.missions):
            ttk.Label(self.kinds, text=f"{len(summary.worlds)} terrain (.trn) file(s) for "
                                       f"{len(summary.missions)} mission(s).",
                      style="Toolbox.SurfaceMuted.TLabel").pack(anchor="w")
        if summary.missions:
            ttk.Label(self.kinds, text="Missions: " + ", ".join(summary.missions[:12])
                      + (" …" if len(summary.missions) > 12 else ""),
                      style="Toolbox.SurfaceMuted.TLabel", wraplength=480, justify="left").pack(anchor="w", pady=(8, 0))
