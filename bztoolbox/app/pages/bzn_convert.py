"""Missions > 1.5 <-> Redux: re-save a Battlezone 1 BZN at the other game's version."""

from __future__ import annotations

import os
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from bztoolbox.app.widgets import Card, LogView, PathPicker, ScrollableFrame

BZN_TYPES = (("BZN missions", "*.bzn"), ("All files", "*.*"))
TARGET_CHOICES = (
    ("auto", "The other game (Redux → 1.5 1045, 1.5 → Redux 2016)"),
    ("1.5", "Battlezone 1.5 (version 1045)"),
    ("redux", "Battlezone 98 Redux (version 2016)"),
    ("custom", "Version:"),
)


def target_from_form(choice: str, custom: str):
    """The ``target`` argument for :func:`convert_bzn` (None = the other game)."""
    if choice == "auto":
        return None
    if choice == "custom":
        text = custom.strip()
        if not text.isdigit():
            raise ValueError("Enter a BZN version number, e.g. 1045 or 2016.")
        return int(text)
    return choice


class BZNConvertPage(ScrollableFrame):
    def __init__(self, master, shell):
        super().__init__(master)
        self.shell = shell
        self.job = None
        self.source = tk.StringVar()
        self.output = tk.StringVar()
        self.odf_dir = tk.StringVar()
        self.target = tk.StringVar(value="auto")
        self.custom_version = tk.StringVar(value="1045")
        self.binary = tk.BooleanVar(value=False)
        self.allow_loss = tk.BooleanVar(value=False)
        self.normalize = tk.BooleanVar(value=False)

        body = ttk.Frame(self.body, style="Toolbox.TFrame", padding=(18, 4, 18, 18))
        body.pack(fill="both", expand=True)

        card = Card(body, "Convert a mission", "Battlezone 1.5 saves BZN version 1045 (1037–1044 from older "
                                               "patches); Redux saves 2016. The converter re-saves the map at "
                                               "the other version, adds or drops the fields that exist in only "
                                               "one of them, and lists every change. It refuses a conversion "
                                               "that would lose a value unless you allow it.")
        card.pack(fill="x", pady=(0, 12))
        form = card.body
        PathPicker(form, "Source BZN", self.source, kind="file", filetypes=BZN_TYPES, surface=True,
                   on_change=lambda _v: self._suggest_output()).pack(fill="x", pady=2)
        PathPicker(form, "Output BZN", self.output, kind="save", filetypes=BZN_TYPES,
                   surface=True).pack(fill="x", pady=2)
        PathPicker(form, "Mod ODF folder", self.odf_dir, kind="dir", surface=True).pack(fill="x", pady=2)
        ttk.Label(form, text="ODF folder: optional. BZNs do not store object classes; stock ODFs are known, and "
                             "the classLabel of custom ODFs in this folder settles the rest.",
                  style="Toolbox.SurfaceMuted.TLabel", wraplength=900, justify="left").pack(anchor="w", pady=(2, 6))

        targets = ttk.Frame(form, style="Toolbox.Surface.TFrame")
        targets.pack(fill="x", pady=(2, 4))
        ttk.Label(targets, text="Convert to", style="Toolbox.Surface.TLabel", width=18).grid(row=0, column=0, sticky="nw")
        for row, (value, label) in enumerate(TARGET_CHOICES):
            ttk.Radiobutton(targets, text=label, value=value, variable=self.target, style="Toolbox.Surface.TRadiobutton",
                            command=self._suggest_output).grid(row=row, column=1, sticky="w")
        ttk.Entry(targets, textvariable=self.custom_version, style="Toolbox.TEntry", width=8).grid(
            row=len(TARGET_CHOICES) - 1, column=2, sticky="w", padx=(4, 0))

        for var, label in ((self.binary, "Write a binary BZN (default ASCII)"),
                           (self.normalize, "Normalise number formatting (default: keep the source's spelling)"),
                           (self.allow_loss, "Write even if some values have no equivalent (they are listed)")):
            ttk.Checkbutton(form, text=label, variable=var, style="Toolbox.Surface.TCheckbutton").pack(anchor="w")

        actions = ttk.Frame(form, style="Toolbox.Surface.TFrame")
        actions.pack(fill="x", pady=(10, 0))
        self.convert_button = ttk.Button(actions, text="Convert", style="Toolbox.Accent.TButton", command=self.convert)
        self.convert_button.pack(side="left")

        ttk.Label(body, text="RESULT", style="Toolbox.Heading.TLabel").pack(anchor="w")
        self.log = LogView(body, height=16)
        self.log.pack(fill="both", expand=True, pady=(4, 0))
        self.log.write("Pick a BZN and press Convert. Nothing is written until the conversion checks out.", "muted")

    def _suggest_output(self) -> None:
        source = self.source.get().strip()
        if not source:
            return
        choice = self.target.get()
        version = {"1.5": "1045", "redux": "2016", "custom": self.custom_version.get().strip()}.get(choice, "")
        suffix = f"_v{version}" if version else "_converted"
        current = self.output.get().strip()
        if not current or Path(current).stem.startswith(Path(source).stem + "_"):
            self.output.set(str(Path(source).with_name(Path(source).stem + suffix + ".bzn")))

    def convert(self) -> None:
        if self.job is not None and self.job.status in ("queued", "running"):
            return
        source, output = self.source.get().strip(), self.output.get().strip()
        if not source or not os.path.isfile(source):
            messagebox.showerror("BZN convert", "Select a source BZN.")
            return
        if not output:
            messagebox.showerror("BZN convert", "Select an output file.")
            return
        if os.path.abspath(output) == os.path.abspath(source):
            messagebox.showerror("BZN convert", "Write the conversion to a new file, not over the source.")
            return
        try:
            target = target_from_form(self.target.get(), self.custom_version.get())
        except ValueError as exc:
            messagebox.showerror("BZN convert", str(exc))
            return
        if os.path.exists(output) and not messagebox.askyesno("Replace output?", f"Replace the existing file?\n\n{output}"):
            return
        odf_dirs = [self.odf_dir.get().strip()] if self.odf_dir.get().strip() else []
        options = dict(binary=self.binary.get(), odf_dirs=odf_dirs, allow_loss=self.allow_loss.get(),
                       preserve_spelling=not self.normalize.get())
        self.convert_button.state(["disabled"])
        self.log.clear()
        self.log.write(f"Converting {Path(source).name}…", "info")

        def work(_job):
            from battlezone.bzn.version_convert import ConversionError, convert_bzn

            try:
                result = convert_bzn(source, target, **options)
            except ConversionError as exc:
                return False, str(exc), exc.result
            Path(output).write_bytes(result.data)
            return True, output, result

        self.job = self.shell.jobs.submit(f"Convert {Path(source).name}", work,
                                          on_done=self._done, on_error=self._failed)

    def _done(self, outcome) -> None:
        ok, message, result = outcome
        self.convert_button.state(["!disabled"])
        if result is not None:
            for line in result.summary_lines(detail=10):
                tag = "error" if line.startswith(("LOSS", "    ", "VERIFY")) else \
                      "warning" if line.startswith(("WARNING", "note")) else ""
                self.log.write(line, tag)
        if ok:
            self.log.write(f"Done: {message}", "success")
            self.shell.status(f"Converted mission written to {message}")
        else:
            self.log.write(f"Not written: {message}", "error")
            self.shell.status("BZN conversion refused; see the result.")

    def _failed(self, error: str) -> None:
        self.convert_button.state(["!disabled"])
        self.log.write(error, "error")
