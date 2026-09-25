"""Home: recent projects, quick actions and Battlezone install detection."""

from __future__ import annotations

import os
from tkinter import messagebox, ttk

from bztoolbox import APP_NAME, __version__, external
from bztoolbox.app import theme
from bztoolbox.app.widgets import Card, ScrollableFrame

QUICK_ACTIONS = (
    ("Validate project", "project.validation"),
    ("Port a BZCC mission", "missions.port"),
    ("Build or port a world", "world.builder"),
    ("Generate terrain", "world.generate"),
    ("Convert textures", "assets.textures"),
    ("Publish to Workshop", "project.publish"),
)


class HomePage(ScrollableFrame):
    def __init__(self, master, shell):
        super().__init__(master)
        self.shell = shell
        body = self.body
        body.columnconfigure(0, weight=3, uniform="home")
        body.columnconfigure(1, weight=2, uniform="home")

        hero = ttk.Frame(body, style="Toolbox.TFrame", padding=(20, 18, 20, 6))
        hero.grid(row=0, column=0, columnspan=2, sticky="ew")
        ttk.Label(hero, text=APP_NAME.upper(), style="Toolbox.Title.TLabel").pack(anchor="w")
        ttk.Label(hero, text=("Open a mod folder, then build terrain, inspect missions, edit assets, "
                              "validate, localize, package and publish without leaving the toolbox."),
                  style="Toolbox.Muted.TLabel").pack(anchor="w", pady=(2, 0))

        # --- projects --------------------------------------------------
        self.projects_card = Card(body, "Projects", "Recently opened mod folders.")
        self.projects_card.grid(row=1, column=0, sticky="nsew", padx=(20, 8), pady=8)
        actions = ttk.Frame(self.projects_card.body, style="Toolbox.Surface.TFrame")
        actions.pack(fill="x", pady=(0, 8))
        ttk.Button(actions, text="Open mod folder…", style="Toolbox.Accent.TButton",
                   command=shell.open_project_dialog).pack(side="left")
        ttk.Button(actions, text="New mod…", style="Toolbox.TButton",
                   command=self.new_mod).pack(side="left", padx=6)
        self.recent_list = ttk.Frame(self.projects_card.body, style="Toolbox.Surface.TFrame")
        self.recent_list.pack(fill="both", expand=True)

        # --- quick actions ---------------------------------------------
        quick = Card(body, "Quick actions")
        quick.grid(row=1, column=1, sticky="nsew", padx=(8, 20), pady=8)
        for label, page_id in QUICK_ACTIONS:
            ttk.Button(quick.body, text=label, style="Toolbox.TButton",
                       command=lambda p=page_id: shell.navigate(p)).pack(fill="x", pady=2)

        # --- install detection -------------------------------------------
        self.install_card = Card(body, "Battlezone install")
        self.install_card.grid(row=2, column=0, sticky="nsew", padx=(20, 8), pady=8)
        self.install_body = ttk.Frame(self.install_card.body, style="Toolbox.Surface.TFrame")
        self.install_body.pack(fill="x")

        # --- external tools -------------------------------------------
        self.tools_card = Card(body, "External tools", "Only needed by specific features.")
        self.tools_card.grid(row=2, column=1, sticky="nsew", padx=(8, 20), pady=8)
        self.tools_body = ttk.Frame(self.tools_card.body, style="Toolbox.Surface.TFrame")
        self.tools_body.pack(fill="x")
        ttk.Button(self.tools_card.body, text="Configure…", style="Toolbox.Link.TButton",
                   command=lambda: shell.navigate("settings.external")).pack(anchor="w", pady=(6, 0))

        ttk.Label(body, text=f"Version {__version__}", style="Toolbox.Muted.TLabel").grid(
            row=3, column=0, sticky="w", padx=20, pady=(4, 16))
        self.on_show()

    def on_show(self) -> None:
        self._render_recent()
        self._render_install()
        self._render_tools()

    def project_changed(self, _project) -> None:
        self._render_recent()

    # ------------------------------------------------------------------
    def _render_recent(self) -> None:
        for child in self.recent_list.winfo_children():
            child.destroy()
        projects = self.shell.projects.list()[: self.shell.settings.get("recent_limit", 12)]
        if not projects:
            ttk.Label(self.recent_list, text="No projects yet. Open a mod folder to start.",
                      style="Toolbox.SurfaceMuted.TLabel").pack(anchor="w")
            return
        for project in projects:
            row = ttk.Frame(self.recent_list, style="Toolbox.Surface.TFrame")
            row.pack(fill="x", pady=1)
            exists = os.path.isdir(project.mod_path)
            current = self.shell.project and os.path.normcase(self.shell.project.mod_path) == os.path.normcase(project.mod_path)
            name = project.name + ("   (open)" if current else "") + ("" if exists else "   (missing)")
            ttk.Button(row, text=name, style="Toolbox.Link.TButton",
                       state="normal" if exists else "disabled",
                       command=lambda p=project.mod_path: self.shell.open_project(p)).pack(side="left")
            ttk.Label(row, text=project.mod_path, style="Toolbox.SurfaceMuted.TLabel").pack(side="left", padx=8)
            ttk.Button(row, text="forget", style="Toolbox.Link.TButton",
                       command=lambda p=project: self._forget(p)).pack(side="right")

    def _forget(self, project) -> None:
        if messagebox.askyesno("Forget project", f"Remove '{project.name}' from the recent list?\n"
                                                 "The mod folder itself is not touched."):
            self.shell.projects.forget(project)
            self._render_recent()

    def _render_install(self) -> None:
        for child in self.install_body.winfo_children():
            child.destroy()
        configured = self.shell.settings.get("game_dir", "")
        detected = external.detect_game_installs()
        if configured:
            ok = os.path.isdir(configured)
            ttk.Label(self.install_body, text=("✔ " if ok else "✖ ") + configured,
                      style="Toolbox.SurfaceSuccess.TLabel" if ok else "Toolbox.SurfaceError.TLabel").pack(anchor="w")
        elif detected:
            ttk.Label(self.install_body, text=f"Detected: {detected[0]}", style="Toolbox.SurfaceSuccess.TLabel").pack(anchor="w")
            ttk.Button(self.install_body, text="Use this install", style="Toolbox.Link.TButton",
                       command=lambda: self._use_install(str(detected[0]))).pack(anchor="w")
        else:
            ttk.Label(self.install_body, text="Battlezone 98 Redux was not detected.",
                      style="Toolbox.SurfaceWarning.TLabel").pack(anchor="w")
        ttk.Button(self.install_body, text="Change in Settings…", style="Toolbox.Link.TButton",
                   command=lambda: self.shell.navigate("settings.general")).pack(anchor="w")

    def _use_install(self, path: str) -> None:
        self.shell.settings.set("game_dir", path)
        self._render_install()

    def _render_tools(self) -> None:
        for child in self.tools_body.winfo_children():
            child.destroy()
        for status in external.resolve_all(self.shell.settings):
            if status.tool.windows_only and not external.IS_WINDOWS:
                continue
            row = ttk.Frame(self.tools_body, style="Toolbox.Surface.TFrame")
            row.pack(fill="x")
            style = "Toolbox.SurfaceSuccess.TLabel" if status.found else "Toolbox.SurfaceMuted.TLabel"
            mark = "✔" if status.found else "–"
            ttk.Label(row, text=f"{mark} {status.tool.name}", style=style, width=22).pack(side="left")
            ttk.Label(row, text=status.source or "not found", style="Toolbox.SurfaceMuted.TLabel").pack(side="left")

    def new_mod(self) -> None:
        try:
            from bztoolbox.modules.publishing.uploader import TemplateWizard
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("New mod", f"The content wizard is unavailable: {exc}")
            return
        colors = {"bg": theme.BG, "fg": theme.FG, "highlight": theme.ACCENT,
                  "dark_highlight": theme.ACCENT_DIM, "accent": theme.ACCENT_2}
        TemplateWizard(self.winfo_toplevel(), colors, self.shell.open_project)
