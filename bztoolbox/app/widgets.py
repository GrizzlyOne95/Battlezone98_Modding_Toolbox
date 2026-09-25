"""Shared widgets so pages stop re-implementing browse/run/log patterns."""

from __future__ import annotations

import os
import tkinter as tk
from tkinter import filedialog, ttk
from typing import Callable, Iterable, List, Optional, Sequence

from bztoolbox.app import theme
from bztoolbox.app.jobs import CANCELLED, DONE, FAILED, FINISHED, Job, JobManager
from bztoolbox.system import open_in_file_manager  # noqa: F401  (re-exported for pages)


_WHEEL_TARGETS: dict = {}


def register_wheel_target(widget: tk.Misc, scroll: Callable[[int], None]) -> None:
    """Scroll ``widget`` with the mouse wheel while the pointer is over it.

    One ``bind_all`` dispatcher serves every registered panel, so panels on
    different pages (or in different migrated tools) never steal each other's
    wheel events the way per-panel ``bind_all`` calls did.
    """
    key = str(widget)
    _WHEEL_TARGETS[key] = scroll
    widget.bind("<Destroy>", lambda e: _WHEEL_TARGETS.pop(key, None) if str(e.widget) == key else None, add="+")
    root = widget._root()
    if not getattr(root, "_toolbox_wheel_dispatch", False):
        root._toolbox_wheel_dispatch = True
        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            root.bind_all(sequence, _dispatch_wheel, add="+")


def _dispatch_wheel(event) -> None:
    try:
        widget = event.widget.winfo_containing(event.x_root, event.y_root)
    except (AttributeError, KeyError, tk.TclError):
        return
    num = getattr(event, "num", None)
    if num == 4:
        units = -1
    elif num == 5:
        units = 1
    else:
        delta = getattr(event, "delta", 0) or 0
        units = -int(delta / 120) if abs(delta) >= 120 else (-1 if delta > 0 else 1)
    while widget is not None:
        scroll = _WHEEL_TARGETS.get(str(widget))
        if scroll is not None:
            scroll(units)
            return
        widget = widget.master


def install_treeview_resize_cursor(root: tk.Misc) -> None:
    """Show a resize cursor over column dividers of every ``ttk.Treeview``.

    Columns were always draggable, but with flat headings and an unchanged
    cursor nothing hinted at it. A class binding covers the migrated tools too.
    """
    if getattr(root, "_toolbox_tree_cursor", False):
        return
    root._toolbox_tree_cursor = True

    def motion(event):
        tree = event.widget
        try:
            wanted = "sb_h_double_arrow" if tree.identify_region(event.x, event.y) == "separator" else ""
            if str(tree.cget("cursor")) != wanted:
                tree.configure(cursor=wanted)
        except tk.TclError:
            pass

    root.bind_class("Treeview", "<Motion>", motion, add="+")
    root.bind_class("Treeview", "<Leave>", lambda e: _reset_cursor(e.widget), add="+")


def _reset_cursor(widget) -> None:
    try:
        widget.configure(cursor="")
    except tk.TclError:
        pass


class ScrollableFrame(ttk.Frame):
    """Vertically scrolling container; put children in ``.body``."""

    def __init__(self, master, style: str = "Toolbox.TFrame", **kw):
        super().__init__(master, style=style, **kw)
        bg = theme.SURFACE if "Surface" in style else theme.BG
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, borderwidth=0)
        self.scrollbar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview,
                                       style="Toolbox.Vertical.TScrollbar")
        self.body = ttk.Frame(self.canvas, style=style)
        self._window = self.canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.canvas.configure(yscrollcommand=self.scrollbar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")
        self.body.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self._window, width=e.width))
        register_wheel_target(self.canvas, lambda units: self.canvas.yview_scroll(units, "units"))


class Card(ttk.Frame):
    """Titled surface panel; children go in ``.body``."""

    def __init__(self, master, title: str = "", subtitle: str = "", **kw):
        super().__init__(master, style="Toolbox.Card.TFrame", padding=(14, 10), **kw)
        if title:
            ttk.Label(self, text=title.upper(), style="Toolbox.CardTitle.TLabel").pack(anchor="w")
        if subtitle:
            ttk.Label(self, text=subtitle, style="Toolbox.SurfaceMuted.TLabel", wraplength=520,
                      justify="left").pack(anchor="w", pady=(2, 0))
        self.body = ttk.Frame(self, style="Toolbox.Surface.TFrame")
        self.body.pack(fill="both", expand=True, pady=(8, 0))


class StatBox(ttk.Frame):
    def __init__(self, master, label: str, value: str = "0", colour: Optional[str] = None):
        super().__init__(master, style="Toolbox.Card.TFrame", padding=(14, 8))
        self.value_label = ttk.Label(self, text=value, style="Toolbox.Stat.TLabel")
        if colour:
            self.value_label.configure(foreground=colour)
        self.value_label.pack(anchor="w")
        ttk.Label(self, text=label.upper(), style="Toolbox.SurfaceMuted.TLabel").pack(anchor="w")

    def set(self, value, colour: Optional[str] = None) -> None:
        self.value_label.configure(text=str(value))
        if colour:
            self.value_label.configure(foreground=colour)


class PathPicker(ttk.Frame):
    """Label + entry + browse button bound to a ``StringVar``."""

    def __init__(self, master, label: str, variable: tk.StringVar, kind: str = "dir",
                 filetypes: Sequence = (("All files", "*.*"),), style_prefix: str = "Toolbox",
                 on_change: Optional[Callable[[str], None]] = None, surface: bool = False):
        frame_style = "Toolbox.Surface.TFrame" if surface else "Toolbox.TFrame"
        label_style = "Toolbox.Surface.TLabel" if surface else "Toolbox.TLabel"
        super().__init__(master, style=frame_style)
        self.variable = variable
        self.kind = kind
        self.filetypes = filetypes
        self.on_change = on_change
        ttk.Label(self, text=label, style=label_style, width=18).pack(side="left")
        self.entry = ttk.Entry(self, textvariable=variable, style="Toolbox.TEntry")
        self.entry.pack(side="left", fill="x", expand=True, padx=(0, 6))
        ttk.Button(self, text="Browse…", style="Toolbox.TButton", command=self.browse).pack(side="left")

    def browse(self) -> None:
        current = self.variable.get()
        initial = current if os.path.isdir(current) else os.path.dirname(current) if current else None
        if self.kind == "dir":
            chosen = filedialog.askdirectory(initialdir=initial or None, mustexist=True)
        elif self.kind == "save":
            chosen = filedialog.asksaveasfilename(initialdir=initial or None, filetypes=self.filetypes)
        else:
            chosen = filedialog.askopenfilename(initialdir=initial or None, filetypes=self.filetypes)
        if chosen:
            self.variable.set(os.path.normpath(chosen))
            if self.on_change:
                self.on_change(self.variable.get())


class IssueTree(ttk.Frame):
    """Severity / check / location / message table for validation results."""

    COLUMNS = (("severity", "Severity", 80), ("check", "Check", 90), ("location", "Location", 260),
               ("message", "Message", 520))

    def __init__(self, master, on_select: Optional[Callable[[object], None]] = None,
                 on_activate: Optional[Callable[[object], None]] = None):
        super().__init__(master, style="Toolbox.TFrame")
        self.tree = ttk.Treeview(self, columns=[c[0] for c in self.COLUMNS], show="headings",
                                 style="Toolbox.Treeview", selectmode="browse")
        for key, heading, width in self.COLUMNS:
            self.tree.heading(key, text=heading)
            self.tree.column(key, width=width, stretch=key == "message", anchor="w")
        for severity, colour in theme.SEVERITY_COLORS.items():
            self.tree.tag_configure(severity, foreground=colour)
        scroll = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview, style="Toolbox.Vertical.TScrollbar")
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self._items: dict = {}
        self._on_select = on_select
        self._on_activate = on_activate
        self.tree.bind("<<TreeviewSelect>>", self._selected)
        self.tree.bind("<Double-1>", self._activated)
        self.tree.bind("<Return>", self._activated)

    def set_issues(self, issues: Iterable) -> None:
        self.tree.delete(*self.tree.get_children())
        self._items.clear()
        for issue in issues:
            iid = self.tree.insert("", "end", values=(issue.severity.upper(), issue.check,
                                                      issue.location(), issue.message),
                                   tags=(issue.severity,))
            self._items[iid] = issue

    def _activated(self, event=None) -> None:
        if self._on_activate is None:
            return
        if event is not None and getattr(event, "y", None) is not None and event.type == tk.EventType.ButtonPress:
            if self.tree.identify_region(event.x, event.y) != "cell":
                return   # headings and column dividers
            row = self.tree.identify_row(event.y)
        else:
            selection = self.tree.selection()
            row = selection[0] if selection else ""
        issue = self._items.get(row)
        if issue is not None:
            self._on_activate(issue)

    def _selected(self, _event=None) -> None:
        if self._on_select:
            selection = self.tree.selection()
            self._on_select(self._items.get(selection[0]) if selection else None)


class LogView(ttk.Frame):
    """Read-only structured log with severity colouring."""

    def __init__(self, master, height: int = 8):
        super().__init__(master, style="Toolbox.TFrame")
        self.text = tk.Text(self, height=height, bg="#050505", fg=theme.FG, insertbackground=theme.ACCENT,
                            relief="flat", wrap="word", font=theme.font("mono", 9), state="disabled",
                            highlightthickness=1, highlightbackground=theme.BORDER)
        for tag, colour in (("error", theme.ERROR), ("warning", theme.WARNING), ("info", theme.INFO),
                            ("success", theme.SUCCESS), ("muted", theme.MUTED)):
            self.text.tag_configure(tag, foreground=colour)
        scroll = ttk.Scrollbar(self, orient="vertical", command=self.text.yview, style="Toolbox.Vertical.TScrollbar")
        self.text.configure(yscrollcommand=scroll.set)
        self.text.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")

    def write(self, message: str, tag: str = "") -> None:
        self.text.configure(state="normal")
        self.text.insert("end", message.rstrip("\n") + "\n", (tag,) if tag else ())
        self.text.see("end")
        self.text.configure(state="disabled")

    def clear(self) -> None:
        self.text.configure(state="normal")
        self.text.delete("1.0", "end")
        self.text.configure(state="disabled")


class JobsPanel(ttk.Frame):
    """Live list of background jobs with progress and cancel."""

    def __init__(self, master, manager: JobManager):
        super().__init__(master, style="Toolbox.TFrame")
        self.manager = manager
        header = ttk.Frame(self, style="Toolbox.TFrame")
        header.pack(fill="x", pady=(0, 6))
        ttk.Label(header, text="Tasks run in the background; pages stay usable while they work.",
                  style="Toolbox.Muted.TLabel").pack(side="left")
        ttk.Button(header, text="Clear finished", style="Toolbox.TButton",
                   command=manager.clear_finished).pack(side="right")
        self.tree = ttk.Treeview(self, columns=("status", "progress", "message", "time"), show="tree headings",
                                 style="Toolbox.Treeview", selectmode="browse", height=10)
        self.tree.heading("#0", text="Task")
        self.tree.column("#0", width=260)
        for key, text, width in (("status", "Status", 90), ("progress", "Progress", 90),
                                 ("message", "Detail", 380), ("time", "Time", 70)):
            self.tree.heading(key, text=text)
            self.tree.column(key, width=width, anchor="w", stretch=key == "message")
        self.tree.tag_configure(FAILED, foreground=theme.ERROR)
        self.tree.tag_configure(DONE, foreground=theme.SUCCESS)
        self.tree.tag_configure(CANCELLED, foreground=theme.MUTED)
        self.tree.pack(fill="both", expand=True)
        buttons = ttk.Frame(self, style="Toolbox.TFrame")
        buttons.pack(fill="x", pady=(6, 0))
        ttk.Button(buttons, text="Cancel selected", style="Toolbox.TButton", command=self._cancel).pack(side="left")
        ttk.Button(buttons, text="Show error details", style="Toolbox.TButton", command=self._details).pack(side="left", padx=6)
        manager.add_listener(self._on_job)
        self.bind("<Destroy>", lambda e: manager.remove_listener(self._on_job) if e.widget is self else None)
        self.refresh()

    def refresh(self) -> None:
        self.tree.delete(*self.tree.get_children())
        for job in reversed(self.manager.jobs):
            self._upsert(job)

    def _row(self, job: Job):
        progress = "…" if job.progress is None else f"{job.progress * 100:.0f}%"
        if job.status in FINISHED and job.status != DONE:
            progress = ""
        return (job.status.upper(), progress, job.message, f"{job.elapsed:.1f}s")

    def _upsert(self, job: Job) -> None:
        iid = f"job{job.id}"
        if self.tree.exists(iid):
            self.tree.item(iid, values=self._row(job), tags=(job.status,))
        else:
            self.tree.insert("", 0, iid=iid, text=job.title, values=self._row(job), tags=(job.status,))

    def _on_job(self, job: Optional[Job]) -> None:
        if job is None:
            self.refresh()
        else:
            self._upsert(job)

    def _selected_job(self) -> Optional[Job]:
        selection = self.tree.selection()
        if not selection:
            return None
        job_id = int(selection[0][3:])
        return next((job for job in self.manager.jobs if job.id == job_id), None)

    def _cancel(self) -> None:
        job = self._selected_job()
        if job and job.status not in FINISHED:
            job.cancel()

    def _details(self) -> None:
        job = self._selected_job()
        if not job or not (job.details or job.error):
            return
        window = tk.Toplevel(self)
        window.title(f"{job.title} — error")
        window.configure(bg=theme.BG)
        log = LogView(window, height=20)
        log.pack(fill="both", expand=True, padx=10, pady=10)
        log.write(job.details or job.error, "error")


def ask_directory(title: str, initial: str = "") -> str:
    return filedialog.askdirectory(title=title, initialdir=initial or None, mustexist=True) or ""


def humanize_bytes(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.0f} {unit}" if unit == "B" else f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"


def bullet_list(master, items: List[str], style: str = "Toolbox.Surface.TLabel") -> None:
    for item in items:
        ttk.Label(master, text=f"•  {item}", style=style, wraplength=560, justify="left").pack(anchor="w")
