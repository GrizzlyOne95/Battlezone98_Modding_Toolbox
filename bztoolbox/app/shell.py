"""The Battlezone Modding Toolbox main window.

Layout::

    +----------------------------------------------------------------+
    | BATTLEZONE MODDING TOOLBOX     Project: <name>  [Open] [Close]  |
    +-------------+--------------------------------------------------+
    | Home        |  <page header>                                   |
    | PROJECT     |                                                  |
    |   Overview  |  <page>                                          |
    |   ...       |                                                  |
    +-------------+--------------------------------------------------+
    | status message                               2 tasks running  |
    +----------------------------------------------------------------+

Pages are created the first time they are shown and then kept alive, so a
tool keeps its state while the user moves around the toolbox.
"""

from __future__ import annotations

import os
import sys
import tkinter as tk
import traceback
from tkinter import messagebox, ttk
from typing import Callable, Dict, List, Optional

from battlezone.project import Project, ProjectStore
from bztoolbox import APP_ID, APP_NAME, __version__, external, paths
from bztoolbox.app import theme
from bztoolbox.app.jobs import FINISHED, Job, JobManager
from bztoolbox.modules.registry import PAGES, PAGES_BY_ID, SECTIONS, PageSpec, pages_in
from bztoolbox.settings import Settings, get_settings


class Shell:
    def __init__(self, root: tk.Tk, settings: Optional[Settings] = None):
        self.root = root
        self.settings = settings or get_settings()
        self.projects = ProjectStore(paths.projects_dir())
        self.project: Optional[Project] = None
        self._project_listeners: List[Callable[[Optional[Project]], None]] = []
        self._pages: Dict[str, "PageFrame"] = {}
        self._current: Optional[str] = None

        root.title(APP_NAME)
        root.geometry(self._initial_geometry())
        root.minsize(1100, 700)
        root.configure(bg=theme.BG)
        _apply_window_icon(root)
        theme.apply(root)
        _apply_generic_baseline(root)

        self.jobs = JobManager(root)
        self.jobs.add_listener(self._on_job)

        self._build_header()
        body = ttk.Frame(root, style="Toolbox.TFrame")
        body.pack(fill="both", expand=True)
        self._build_sidebar(body)
        self.page_area = ttk.Frame(body, style="Toolbox.TFrame")
        self.page_area.pack(side="left", fill="both", expand=True)
        self._build_statusbar()

        root.protocol("WM_DELETE_WINDOW", self.close)
        self._restore_last_project()
        start = self.settings.get("last_page", "home")
        self.navigate(start if start in PAGES_BY_ID and PAGES_BY_ID[start].available else "home")

    # ------------------------------------------------------------------ layout
    def _initial_geometry(self) -> str:
        try:
            width = max(1100, min(1600, self.root.winfo_screenwidth() - 80))
            height = max(700, min(1000, self.root.winfo_screenheight() - 100))
        except tk.TclError:
            width, height = 1440, 900
        return f"{width}x{height}"

    def _build_header(self) -> None:
        header = ttk.Frame(self.root, style="Toolbox.Surface.TFrame", padding=(8, 8, 14, 8))
        header.pack(fill="x")
        ttk.Button(header, text="☰", width=3, style="Toolbox.TButton",
                   command=self.toggle_sidebar).pack(side="left", padx=(0, 8))
        ttk.Label(header, text="BATTLEZONE", style="Toolbox.Brand.TLabel").pack(side="left")
        ttk.Label(header, text=" MODDING TOOLBOX", style="Toolbox.SurfaceMuted.TLabel").pack(side="left", pady=(3, 0))
        ttk.Button(header, text="Close project", style="Toolbox.TButton",
                   command=lambda: self.set_project(None)).pack(side="right", padx=(6, 0))
        ttk.Button(header, text="Open mod folder…", style="Toolbox.Accent.TButton",
                   command=self.open_project_dialog).pack(side="right")
        self.project_label = ttk.Label(header, text="", style="Toolbox.Surface.TLabel")
        self.project_label.pack(side="right", padx=14)
        ttk.Separator(self.root, orient="horizontal", style="Toolbox.TSeparator").pack(fill="x")

    def _build_sidebar(self, parent) -> None:
        side = ttk.Frame(parent, style="Toolbox.Surface.TFrame", width=230)
        side.pack(side="left", fill="y")
        self.sidebar = side
        side.pack_propagate(False)
        self.nav = ttk.Treeview(side, show="tree", style="Toolbox.Nav.Treeview", selectmode="browse")
        self.nav.pack(fill="both", expand=True, padx=(6, 0), pady=8)
        self.nav.tag_configure("section", foreground=theme.ACCENT_2, font=theme.font("heading", 9, "bold"))
        self.nav.tag_configure("page", foreground=theme.FG)
        for section_id, section_title in SECTIONS:
            pages = pages_in(section_id)
            if not pages:
                continue  # e.g. a build without the optional GPL archive module
            if section_id == "home":
                for page in pages:
                    self.nav.insert("", "end", iid=page.id, text=f"  {page.title}", tags=("page",))
                continue
            self.nav.insert("", "end", iid=f"section:{section_id}", text=section_title.upper(),
                            open=True, tags=("section",))
            for page in pages:
                self.nav.insert(f"section:{section_id}", "end", iid=page.id, text=page.title, tags=("page",))
        self.nav.bind("<<TreeviewSelect>>", self._on_nav)
        ttk.Label(side, text=f"v{__version__}", style="Toolbox.SurfaceMuted.TLabel").pack(anchor="w", padx=12, pady=(0, 8))

    def _build_statusbar(self) -> None:
        ttk.Separator(self.root, orient="horizontal", style="Toolbox.TSeparator").pack(fill="x")
        bar = ttk.Frame(self.root, style="Toolbox.Surface.TFrame", padding=(10, 3))
        bar.pack(fill="x")
        self.status_label = ttk.Label(bar, text="Ready.", style="Toolbox.SurfaceMuted.TLabel")
        self.status_label.pack(side="left")
        self.jobs_button = ttk.Button(bar, text="No background tasks", style="Toolbox.Link.TButton",
                                      command=lambda: self.navigate("tools.tasks"))
        self.jobs_button.pack(side="right")
        self.jobs_progress = ttk.Progressbar(bar, length=140, mode="determinate",
                                             style="Toolbox.Horizontal.TProgressbar")

    # -------------------------------------------------------------- navigation
    def _on_nav(self, _event=None) -> None:
        selection = self.nav.selection()
        if not selection:
            return
        iid = selection[0]
        if iid.startswith("section:"):
            children = self.nav.get_children(iid)
            if children:
                self.nav.selection_set(children[0])
            return
        if iid != self._current:
            self.navigate(iid)

    def navigate(self, page_id: str) -> None:
        spec = PAGES_BY_ID[page_id]
        if self._current and self._current in self._pages:
            self._pages[self._current].pack_forget()
        page = self._pages.get(page_id)
        if page is None:
            page = PageFrame(self.page_area, spec, self)
            self._pages[page_id] = page
        page.pack(fill="both", expand=True)
        self._current = page_id
        if tuple(self.nav.selection()) != (page_id,):
            self.nav.selection_set(page_id)
            self.nav.see(page_id)
        page.shown()
        self.settings.set("last_page", page_id)

    def toggle_sidebar(self) -> None:
        """Collapse the navigation to give wide tools (e.g. Publish) more room."""
        if self.sidebar.winfo_ismapped():
            self.sidebar.pack_forget()
        else:
            self.sidebar.pack(side="left", fill="y", before=self.page_area)

    def status(self, message: str) -> None:
        self.status_label.configure(text=message)

    # ----------------------------------------------------------------- projects
    def add_project_listener(self, callback: Callable[[Optional[Project]], None]) -> None:
        self._project_listeners.append(callback)

    def open_project_dialog(self) -> None:
        from tkinter import filedialog

        initial = self.project.mod_path if self.project else self.settings.get("last_browse_dir", "")
        folder = filedialog.askdirectory(title="Open mod folder", initialdir=initial or None, mustexist=True)
        if folder:
            self.settings.set("last_browse_dir", os.path.dirname(folder))
            self.open_project(folder)

    def open_project(self, folder: str) -> None:
        if not os.path.isdir(folder):
            messagebox.showerror("Open project", f"Folder not found:\n{folder}")
            return
        self.set_project(self.projects.open(os.path.normpath(folder)))
        if self._current == "home":
            self.navigate("project.overview")

    def set_project(self, project: Optional[Project]) -> None:
        self.project = project
        self.settings.set("last_project", project.mod_path if project else "")
        if project:
            self.project_label.configure(text=f"PROJECT:  {project.name}   ·   {project.mod_path}")
            self.status(f"Opened {project.mod_path}")
        else:
            self.project_label.configure(text="No project open")
            self.status("Project closed.")
        for listener in list(self._project_listeners):
            try:
                listener(project)
            except Exception:  # noqa: BLE001 - one page must not break the others
                traceback.print_exc()
        for page in self._pages.values():
            page.project_changed(project)

    def save_project(self) -> None:
        if self.project:
            self.projects.save(self.project)

    def _restore_last_project(self) -> None:
        last = self.settings.get("last_project", "")
        if last and os.path.isdir(last):
            project = self.projects.find(last) or Project(mod_path=last)
            self.set_project(project)
        else:
            self.set_project(None)

    # --------------------------------------------------------------------- jobs
    def _on_job(self, _job: Optional[Job]) -> None:
        active = self.jobs.active
        if not active:
            self.jobs_button.configure(text="No background tasks")
            self.jobs_progress.pack_forget()
            return
        if len(active) == 1:
            job = active[0]
            label = f"{job.title}: {job.message}" if job.message else job.title
        else:
            label = f"{len(active)} tasks running"
        self.jobs_button.configure(text=label[:90])
        known = [j.progress for j in active if j.progress is not None]
        if known:
            if not self.jobs_progress.winfo_ismapped():
                self.jobs_progress.pack(side="right", padx=8)
            self.jobs_progress.configure(value=100 * sum(known) / len(known))
        else:
            self.jobs_progress.pack_forget()

    # -------------------------------------------------------------------- close
    def close(self, confirm: bool = True) -> None:
        active = [job for job in self.jobs.jobs if job.status not in FINISHED]
        if confirm and active and not messagebox.askyesno(
                "Exit", f"{len(active)} background task(s) are still running. Cancel them and exit?"):
            return
        for page in list(self._pages.values()):
            page.request_close()
        self.jobs.shutdown()
        try:
            self.root.destroy()
        except tk.TclError:
            pass


class PageFrame(ttk.Frame):
    """A page slot: header plus a lazily created native or legacy page."""

    def __init__(self, master, spec: PageSpec, shell: Shell):
        super().__init__(master, style="Toolbox.TFrame")
        self.spec = spec
        self.shell = shell
        self.widget = None        # native page widget, or legacy root widget
        self.app = None           # legacy application object
        self._project_hook = None
        self._built = False
        self._build_header()
        self.content = ttk.Frame(self, style="Toolbox.TFrame")
        self.content.pack(fill="both", expand=True)

    def _build_header(self) -> None:
        if self.spec.id == "home":
            return
        header = ttk.Frame(self, style="Toolbox.TFrame", padding=(18, 12, 18, 6))
        header.pack(fill="x")
        ttk.Label(header, text=self.spec.title.upper(), style="Toolbox.Title.TLabel").pack(anchor="w")
        detail = self.spec.summary
        if self.spec.origin:
            detail += f"   (formerly {self.spec.origin})"
        ttk.Label(header, text=detail, style="Toolbox.Muted.TLabel").pack(anchor="w")
        self.requirements = ttk.Label(header, text="", style="Toolbox.Warning.TLabel")
        self.requirements.pack(anchor="w")

    def _refresh_requirements(self) -> None:
        if not self.spec.requires or not hasattr(self, "requirements"):
            return
        missing = []
        for tool_id in self.spec.requires:
            status = external.resolve(tool_id, self.shell.settings)
            if not status.found:
                missing.append(status.tool.name)
        text = ""
        if missing:
            text = (f"Optional external tool(s) not found: {', '.join(missing)}. "
                    "Some features need them; see Settings › External Tools.")
        self.requirements.configure(text=text)

    def shown(self) -> None:
        self._refresh_requirements()
        if not self._built:
            self._built = True
            self.shell.status(f"Loading {self.spec.title}…")
            self.update_idletasks()
            self._build_page()
            self.shell.status("Ready.")
        elif self.widget is not None and hasattr(self.widget, "on_show"):
            self.widget.on_show()

    def _build_page(self) -> None:
        try:
            factory = self.spec.load_factory()
            if self.spec.kind == "legacy":
                host = ttk.Frame(self.content, style="Toolbox.TFrame")
                host.pack(fill="both", expand=True)
                self.widget, self.app = factory(host)
                self.widget.pack(fill="both", expand=True)
                self._project_hook = self.spec.load_project_hook()
            else:
                self.widget = factory(self.content, self.shell)
                self.widget.pack(fill="both", expand=True)
            self.project_changed(self.shell.project)
        except Exception as exc:  # noqa: BLE001 - show the failure in the page
            self._show_error(exc)

    def _show_error(self, exc: Exception) -> None:
        for child in self.content.winfo_children():
            child.destroy()
        box = ttk.Frame(self.content, style="Toolbox.TFrame", padding=18)
        box.pack(fill="both", expand=True)
        ttk.Label(box, text=f"{self.spec.title} could not be loaded.", style="Toolbox.Error.TLabel").pack(anchor="w")
        ttk.Label(box, text=f"{exc.__class__.__name__}: {exc}", style="Toolbox.TLabel",
                  wraplength=900, justify="left").pack(anchor="w", pady=(4, 8))
        text = tk.Text(box, height=18, bg="#050505", fg=theme.MUTED, relief="flat", font=theme.font("mono", 9))
        text.insert("1.0", traceback.format_exc())
        text.configure(state="disabled")
        text.pack(fill="both", expand=True)

    def project_changed(self, project: Optional[Project]) -> None:
        if not self._built:
            return
        try:
            if self.spec.kind == "legacy":
                if project is not None and self._project_hook is not None and self.app is not None:
                    self._project_hook(self.app, project)
            elif self.widget is not None and hasattr(self.widget, "project_changed"):
                self.widget.project_changed(project)
        except Exception:  # noqa: BLE001
            traceback.print_exc()

    def request_close(self) -> None:
        try:
            if self.spec.kind == "legacy" and self.widget is not None:
                self.widget.toolbox_request_close()
            elif self.widget is not None and hasattr(self.widget, "on_close"):
                self.widget.on_close()
        except Exception:  # noqa: BLE001 - never block exit
            traceback.print_exc()


def _apply_window_icon(root: tk.Tk) -> None:
    try:
        if sys.platform == "win32":
            root.iconbitmap(str(paths.resource("branding", "app_icon.ico")))
        image = tk.PhotoImage(file=str(paths.resource("branding", "app_icon.png")))
        root.iconphoto(True, image)
        root._toolbox_icon = image  # keep a reference
    except (tk.TclError, OSError):
        pass


def _apply_generic_baseline(root: tk.Tk) -> None:
    """Dark defaults for generic ttk styles before any module configures its own.

    Migrated modules still style ``TFrame``/``TLabel``/... themselves (with the
    same palette); this baseline keeps modules that never did, such as the
    terrain generator, consistent with the rest of the toolbox.
    """
    style = ttk.Style(root)
    body = theme.font("body", 10)
    style.configure(".", background=theme.BG, foreground=theme.FG, fieldbackground="#050505",
                    bordercolor=theme.BORDER, troughcolor=theme.SURFACE, font=body)
    style.configure("TButton", background=theme.SURFACE_ALT, foreground=theme.FG)
    style.map("TButton", background=[("active", "#223022")], foreground=[("active", theme.ACCENT)])
    style.configure("TEntry", fieldbackground="#050505", foreground=theme.FG, insertcolor=theme.ACCENT)
    style.configure("TCombobox", fieldbackground="#050505", foreground=theme.FG, arrowcolor=theme.ACCENT)
    style.map("TCombobox", fieldbackground=[("readonly", "#050505")], foreground=[("readonly", theme.FG)])
    style.configure("TLabelframe", background=theme.BG)
    style.configure("TLabelframe.Label", background=theme.BG, foreground=theme.ACCENT)
    style.configure("TNotebook.Tab", background=theme.SURFACE, foreground=theme.FG)
    style.map("TNotebook.Tab", background=[("selected", theme.ACCENT_DIM)], foreground=[("selected", theme.ACCENT)])
    style.configure("Treeview", background="#070907", fieldbackground="#070907", foreground=theme.FG)


def _set_app_user_model_id() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except Exception:  # noqa: BLE001
        pass


def _make_root() -> tk.Tk:
    try:
        from tkinterdnd2 import TkinterDnD  # drag & drop for the texture tools

        return TkinterDnD.Tk()
    except Exception:  # noqa: BLE001
        return tk.Tk()


def run(project: Optional[str] = None, page: Optional[str] = None) -> int:
    _set_app_user_model_id()
    root = _make_root()
    shell = Shell(root)
    if project:
        shell.open_project(project)
    if page:
        if page not in PAGES_BY_ID:
            matches = [p.id for p in PAGES if p.id.endswith(page) or p.title.lower() == page.lower()]
            page = matches[0] if matches else None
        if page:
            shell.navigate(page)
    root.mainloop()
    return 0
