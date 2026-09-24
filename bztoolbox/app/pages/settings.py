"""Settings: game install, data folders and external tools."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from bztoolbox import __version__, external, paths
from bztoolbox.app.widgets import Card, PathPicker, ScrollableFrame, open_in_file_manager


class SettingsPage(ScrollableFrame):
    def __init__(self, master, shell):
        super().__init__(master)
        self.shell = shell
        settings = shell.settings
        body = ttk.Frame(self.body, style="Toolbox.TFrame", padding=(18, 4, 18, 18))
        body.pack(fill="both", expand=True)

        game = Card(body, "Battlezone 98 Redux", "Used to find stock assets and the Workshop content folder.")
        game.pack(fill="x", pady=(0, 12))
        self.game_var = tk.StringVar(value=settings.get("game_dir", ""))
        PathPicker(game.body, "Install folder", self.game_var, surface=True,
                   on_change=lambda v: settings.set("game_dir", v)).pack(fill="x")
        self.game_var.trace_add("write", lambda *_: settings.set("game_dir", self.game_var.get().strip()))
        detect = ttk.Frame(game.body, style="Toolbox.Surface.TFrame")
        detect.pack(fill="x", pady=(6, 0))
        ttk.Button(detect, text="Detect", style="Toolbox.TButton", command=self._detect).pack(side="left")
        self.detect_label = ttk.Label(detect, text="", style="Toolbox.SurfaceMuted.TLabel")
        self.detect_label.pack(side="left", padx=8)

        data = Card(body, "Data folders", "Settings, project profiles and module state are kept here, "
                                          "not next to the executable.")
        data.pack(fill="x", pady=(0, 12))
        for label, path in (("Toolbox data", paths.user_data_dir()), ("Project profiles", paths.projects_dir())):
            row = ttk.Frame(data.body, style="Toolbox.Surface.TFrame")
            row.pack(fill="x", pady=1)
            ttk.Label(row, text=label, style="Toolbox.Surface.TLabel", width=18).pack(side="left")
            ttk.Label(row, text=str(path), style="Toolbox.SurfaceMuted.TLabel").pack(side="left")
            ttk.Button(row, text="open", style="Toolbox.Link.TButton",
                       command=lambda p=path: (p.mkdir(parents=True, exist_ok=True), open_in_file_manager(str(p)))
                       ).pack(side="right")

        updates = Card(body, "Updates", f"You have version {__version__}. The toolbox asks GitHub for a newer "
                                          "release at most once a day and shows a banner when there is one.")
        updates.pack(fill="x", pady=(0, 12))
        self.update_var = tk.BooleanVar(value=bool(settings.get("update_check", True)))
        ttk.Checkbutton(updates.body, text="Check for updates when the toolbox starts", variable=self.update_var,
                        style="Toolbox.Surface.TCheckbutton",
                        command=lambda: settings.set("update_check", bool(self.update_var.get()))).pack(anchor="w")
        check_row = ttk.Frame(updates.body, style="Toolbox.Surface.TFrame")
        check_row.pack(fill="x", pady=(6, 0))
        self.check_button = ttk.Button(check_row, text="Check now", style="Toolbox.TButton",
                                       command=self._check_updates)
        self.check_button.pack(side="left")
        self.update_label = ttk.Label(check_row, text="", style="Toolbox.SurfaceMuted.TLabel")
        self.update_label.pack(side="left", padx=8)

        profiles = Card(body, "Import", "Adopt Workshop Uploader upload profiles (JSON) as toolbox projects.")
        profiles.pack(fill="x")
        ttk.Button(profiles.body, text="Import upload profiles…", style="Toolbox.TButton",
                   command=self._import_profiles).pack(anchor="w")

    def _check_updates(self) -> None:
        self.check_button.state(["disabled"])
        self.update_label.configure(text="Checking…")

        def done(update, error):
            self.check_button.state(["!disabled"])
            if error is not None:
                self.update_label.configure(text=f"Could not check: {error}")
            elif update is None:
                self.update_label.configure(text=f"You have the latest version ({__version__}).")
            else:
                self.update_label.configure(text=f"Version {update.version} is available: see the banner above.")

        self.shell.check_for_updates(force=True, on_done=done)

    def _detect(self) -> None:
        found = external.detect_game_installs()
        if found:
            self.game_var.set(str(found[0]))
            self.detect_label.configure(text=f"Found {len(found)} install(s).")
        else:
            self.detect_label.configure(text="No install found; choose the folder manually.")

    def _import_profiles(self) -> None:
        from tkinter import filedialog, messagebox

        files = filedialog.askopenfilenames(title="Workshop Uploader profiles", filetypes=[("JSON", "*.json")])
        imported, failed = 0, []
        for name in files:
            try:
                self.shell.projects.import_profile(name)
                imported += 1
            except Exception as exc:  # noqa: BLE001
                failed.append(f"{name}: {exc}")
        if files:
            message = f"Imported {imported} profile(s)."
            if failed:
                message += "\n\nSkipped:\n" + "\n".join(failed)
            messagebox.showinfo("Import", message)


class ExternalToolsPage(ScrollableFrame):
    def __init__(self, master, shell):
        super().__init__(master)
        self.shell = shell
        self.container = ttk.Frame(self.body, style="Toolbox.TFrame", padding=(18, 4, 18, 18))
        self.container.pack(fill="both", expand=True)
        ttk.Label(self.container, text="Only the features listed under each tool need it; everything else "
                                       "works without them. Leave a path empty to auto-detect.",
                  style="Toolbox.Muted.TLabel").pack(anchor="w", pady=(0, 10))
        self.rows = {}
        for tool in external.TOOLS.values():
            if tool.windows_only and not external.IS_WINDOWS:
                continue
            card = Card(self.container, tool.name, f"{tool.purpose}  Used by: {', '.join(tool.used_by)}.")
            card.pack(fill="x", pady=(0, 10))
            var = tk.StringVar(value=shell.settings.tool_path(tool.id))
            picker = PathPicker(card.body, "Custom path", var, kind="file", surface=True,
                                on_change=lambda v, t=tool.id: self._set(t, v))
            picker.pack(fill="x")
            var.trace_add("write", lambda *_a, t=tool.id, v=var: self._set(t, v.get().strip(), refresh=False))
            status = ttk.Label(card.body, text="", style="Toolbox.SurfaceMuted.TLabel")
            status.pack(anchor="w", pady=(4, 0))
            self.rows[tool.id] = status
        ttk.Button(self.container, text="Re-check all", style="Toolbox.TButton", command=self.refresh).pack(anchor="w")
        self.refresh()

    def on_show(self) -> None:
        self.refresh()

    def _set(self, tool_id: str, value: str, refresh: bool = True) -> None:
        self.shell.settings.set_tool_path(tool_id, value)
        if refresh:
            self.refresh()

    def refresh(self) -> None:
        def work(job):
            return [external.probe_version(external.resolve(tid, self.shell.settings)) for tid in self.rows]

        self.shell.jobs.submit("Detect external tools", work, on_done=self._show)

    def _show(self, statuses) -> None:
        for status in statuses:
            label = self.rows.get(status.tool.id)
            if label is None:
                continue
            if status.found:
                text = f"✔ {status.path}  ({status.source})"
                if status.version:
                    text += f"   {status.version}"
                label.configure(text=text, style="Toolbox.SurfaceSuccess.TLabel")
            else:
                text = "Not found."
                if status.problems:
                    text += "  " + " ".join(status.problems)
                if status.tool.url:
                    text += f"  Download: {status.tool.url}"
                label.configure(text=text, style="Toolbox.SurfaceWarning.TLabel")
