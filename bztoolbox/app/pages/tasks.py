"""Background task list."""

from __future__ import annotations

from tkinter import ttk

from bztoolbox.app.widgets import JobsPanel


class TasksPage(ttk.Frame):
    def __init__(self, master, shell):
        super().__init__(master, style="Toolbox.TFrame", padding=(18, 4, 18, 12))
        JobsPanel(self, shell.jobs).pack(fill="both", expand=True)
