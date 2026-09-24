"""Project validation page, backed by :mod:`battlezone.validation`."""

from __future__ import annotations

import json
import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from battlezone.validation import CHECKS, DEFAULT_CHECKS, ValidationCancelled, validate_project
from bztoolbox.app import theme
from bztoolbox.app.widgets import IssueTree, StatBox, open_in_file_manager


class ValidationPage(ttk.Frame):
    def __init__(self, master, shell):
        super().__init__(master, style="Toolbox.TFrame", padding=(18, 4, 18, 12))
        self.shell = shell
        self.report = None
        self.job = None
        self.check_vars = {cid: tk.BooleanVar(value=cid in DEFAULT_CHECKS) for cid in CHECKS}
        self.filter_var = tk.StringVar(value="all")

        top = ttk.Frame(self, style="Toolbox.TFrame")
        top.pack(fill="x")
        self.target_label = ttk.Label(top, text="", style="Toolbox.TLabel")
        self.target_label.pack(side="left")
        self.run_button = ttk.Button(top, text="Run validation", style="Toolbox.Accent.TButton", command=self.run)
        self.run_button.pack(side="right")
        ttk.Button(top, text="Other folder…", style="Toolbox.TButton", command=self.run_other).pack(side="right", padx=6)
        self.export_button = ttk.Button(top, text="Export report…", style="Toolbox.TButton",
                                        command=self.export, state="disabled")
        self.export_button.pack(side="right")

        checks = ttk.Frame(self, style="Toolbox.TFrame")
        checks.pack(fill="x", pady=(8, 4))
        ttk.Label(checks, text="Checks:", style="Toolbox.Muted.TLabel").pack(side="left", padx=(0, 6))
        for check in CHECKS.values():
            ttk.Checkbutton(checks, text=check.title, variable=self.check_vars[check.id],
                            style="Toolbox.TCheckbutton").pack(side="left", padx=(0, 10))

        stats = ttk.Frame(self, style="Toolbox.TFrame")
        stats.pack(fill="x", pady=6)
        self.stat_errors = StatBox(stats, "Errors", "–", theme.ERROR)
        self.stat_warnings = StatBox(stats, "Warnings", "–", theme.WARNING)
        self.stat_info = StatBox(stats, "Info", "–", theme.INFO)
        self.stat_files = StatBox(stats, "Files scanned", "–")
        for box in (self.stat_errors, self.stat_warnings, self.stat_info, self.stat_files):
            box.pack(side="left", padx=(0, 8))
        filters = ttk.Frame(stats, style="Toolbox.TFrame")
        filters.pack(side="right")
        ttk.Label(filters, text="Show", style="Toolbox.Muted.TLabel").pack(side="left", padx=4)
        combo = ttk.Combobox(filters, textvariable=self.filter_var, state="readonly", width=12,
                             values=["all", "error", "warning", "info"] + list(CHECKS), style="Toolbox.TCombobox")
        combo.pack(side="left")
        combo.bind("<<ComboboxSelected>>", lambda e: self._render())

        panes = ttk.PanedWindow(self, orient="vertical")
        panes.pack(fill="both", expand=True)
        self.tree = IssueTree(panes, on_select=self._show_detail)
        panes.add(self.tree, weight=4)
        detail_frame = ttk.Frame(panes, style="Toolbox.TFrame")
        panes.add(detail_frame, weight=1)
        self.detail = tk.Text(detail_frame, height=6, bg="#050505", fg=theme.FG, relief="flat", wrap="word",
                              font=theme.font("mono", 9), state="disabled", highlightthickness=1,
                              highlightbackground=theme.BORDER)
        self.detail.pack(fill="both", expand=True, pady=(6, 0))
        self.detail_actions = ttk.Frame(detail_frame, style="Toolbox.TFrame")
        self.detail_actions.pack(fill="x")
        self.reveal_button = ttk.Button(self.detail_actions, text="Show file in folder", style="Toolbox.TButton",
                                        state="disabled", command=self._reveal)
        self.reveal_button.pack(side="left", pady=4)
        self._selected = None
        self.project_changed(shell.project)

    # ------------------------------------------------------------------
    def project_changed(self, project) -> None:
        if project is None:
            self.target_label.configure(text="Open a project to validate it, or pick a folder.")
            self.run_button.configure(state="disabled")
        else:
            self.target_label.configure(text=f"Target: {project.mod_path}")
            self.run_button.configure(state="normal")

    def run_other(self) -> None:
        folder = filedialog.askdirectory(title="Validate folder", mustexist=True)
        if folder:
            self._start(folder)

    def run(self) -> None:
        if self.shell.project:
            self._start(self.shell.project.mod_path)

    def _start(self, folder: str) -> None:
        if self.job is not None and self.job.status in ("queued", "running"):
            self.job.cancel()
        checks = [cid for cid, var in self.check_vars.items() if var.get()]
        if not checks:
            messagebox.showinfo("Validation", "Select at least one check.")
            return
        self.target_label.configure(text=f"Target: {folder}")
        self.run_button.configure(state="disabled")

        def work(job):
            try:
                return validate_project(folder, checks, progress=job.report, cancel=job.cancel_event)
            except ValidationCancelled:
                job.check_cancelled()
                raise

        self.job = self.shell.jobs.submit(f"Validate {os.path.basename(folder) or folder}", work,
                                          on_done=self._done, on_error=self._failed)

    def _done(self, report) -> None:
        self.report = report
        self.run_button.configure(state="normal" if self.shell.project else "disabled")
        self.export_button.configure(state="normal")
        counts = report.counts
        self.stat_errors.set(counts["error"])
        self.stat_warnings.set(counts["warning"])
        self.stat_info.set(counts["info"])
        self.stat_files.set(report.file_count)
        self.shell.status("Validation passed with no errors." if report.ok
                          else f"Validation found {counts['error']} error(s).")
        self._render()

    def _failed(self, error: str) -> None:
        self.run_button.configure(state="normal" if self.shell.project else "disabled")
        messagebox.showerror("Validation failed", error)

    def _render(self) -> None:
        if self.report is None:
            return
        wanted = self.filter_var.get()
        issues = self.report.issues
        if wanted in ("error", "warning", "info"):
            issues = [i for i in issues if i.severity == wanted]
        elif wanted != "all":
            issues = [i for i in issues if i.check == wanted]
        self.tree.set_issues(issues)

    def _show_detail(self, issue) -> None:
        self._selected = issue
        self.detail.configure(state="normal")
        self.detail.delete("1.0", "end")
        if issue is not None:
            lines = [f"[{issue.severity.upper()}] {issue.message}"]
            if issue.location():
                lines.append(f"Location: {issue.location()}")
            if issue.section or issue.key:
                lines.append(f"Section/key: [{issue.section}] {issue.key}")
            if issue.rule_id:
                lines.append(f"Rule: {issue.rule_id}   Check: {CHECKS[issue.check].title}")
            if issue.suggestion:
                lines.append(f"Suggested fix: {issue.suggestion}")
            if issue.evidence_ids:
                lines.append("Evidence: " + ", ".join(issue.evidence_ids))
            self.detail.insert("1.0", "\n".join(lines))
        self.detail.configure(state="disabled")
        self.reveal_button.configure(state="normal" if issue is not None and issue.path else "disabled")

    def _reveal(self) -> None:
        if self._selected is None or self.report is None:
            return
        path = os.path.join(self.report.root, self._selected.path)
        open_in_file_manager(os.path.dirname(path) if os.path.isfile(path) else self.report.root)

    def export(self) -> None:
        if self.report is None:
            return
        path = filedialog.asksaveasfilename(title="Export validation report", defaultextension=".json",
                                            filetypes=[("JSON", "*.json"), ("Text", "*.txt")])
        if not path:
            return
        if path.lower().endswith(".txt"):
            lines = [f"Validation report for {self.report.root}", ""]
            for issue in self.report.issues:
                lines.append(f"{issue.severity.upper():8} {issue.check:10} {issue.location()}  {issue.message}")
            content = "\n".join(lines) + "\n"
        else:
            content = json.dumps(self.report.to_dict(), indent=2)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(content)
        self.shell.status(f"Report written to {path}")
