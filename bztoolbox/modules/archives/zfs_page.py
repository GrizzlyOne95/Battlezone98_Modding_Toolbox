"""ZFS Archives page: browse, extract, verify and pack ZFS archives.

Replaces the ZFS Specialist UI. All archive work is done by the pure-Python
:mod:`battlezone.archives.zfs` on the shared job system, so it runs on every
platform and never blocks the window.
"""

from __future__ import annotations

import os
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from battlezone.archives.zfs import ZFSArchive, ZFSError, files_in_folder, write_zfs
from bztoolbox.app.widgets import Card, PathPicker, StatBox, humanize_bytes, open_in_file_manager


class ZFSPage(ttk.Frame):
    COLUMNS = (("name", "File name", 220), ("ext", "Ext", 60), ("size", "Size", 100),
               ("packed", "Packed", 100), ("ratio", "Ratio", 70), ("method", "Method", 80))

    def __init__(self, master, shell):
        super().__init__(master, style="Toolbox.TFrame", padding=(18, 4, 18, 12))
        self.shell = shell
        self.archive: ZFSArchive | None = None
        self.sort_key, self.sort_reverse = "index", False
        self.filter_var = tk.StringVar()
        self.filter_var.trace_add("write", lambda *_: self._render())

        tabs = ttk.Notebook(self, style="Toolbox.TNotebook")
        tabs.pack(fill="both", expand=True)
        browse = ttk.Frame(tabs, style="Toolbox.TFrame", padding=(0, 8))
        pack = ttk.Frame(tabs, style="Toolbox.TFrame", padding=(0, 8))
        tabs.add(browse, text="Explorer")
        tabs.add(pack, text="Pack")
        self._build_browser(browse)
        self._build_packer(pack)

    # ------------------------------------------------------------------ browse
    def _build_browser(self, parent) -> None:
        actions = ttk.Frame(parent, style="Toolbox.TFrame")
        actions.pack(fill="x")
        ttk.Button(actions, text="Open archive…", style="Toolbox.Accent.TButton",
                   command=self.open_dialog).pack(side="left")
        self.extract_button = ttk.Button(actions, text="Extract selected…", style="Toolbox.TButton",
                                         command=lambda: self.extract(selected_only=True), state="disabled")
        self.extract_button.pack(side="left", padx=6)
        self.extract_all_button = ttk.Button(actions, text="Extract all…", style="Toolbox.TButton",
                                             command=lambda: self.extract(selected_only=False), state="disabled")
        self.extract_all_button.pack(side="left")
        self.verify_button = ttk.Button(actions, text="Verify", style="Toolbox.TButton",
                                        command=self.verify, state="disabled")
        self.verify_button.pack(side="left", padx=6)

        keys = ttk.Frame(parent, style="Toolbox.TFrame")
        keys.pack(fill="x", pady=(8, 0))
        ttk.Label(keys, text="Key override", style="Toolbox.Muted.TLabel").pack(side="left")
        self.key_var = tk.StringVar()
        ttk.Entry(keys, textvariable=self.key_var, width=18, style="Toolbox.TEntry").pack(side="left", padx=6)
        ttk.Label(keys, text="number, 0x hex or password (empty: key from the archive)",
                  style="Toolbox.Muted.TLabel").pack(side="left")
        self.dir_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(keys, text="Directory is encrypted", variable=self.dir_var,
                        style="Toolbox.TCheckbutton").pack(side="right")

        stats = ttk.Frame(parent, style="Toolbox.TFrame")
        stats.pack(fill="x", pady=8)
        self.stat_files = StatBox(stats, "Files", "–")
        self.stat_size = StatBox(stats, "Unpacked", "–")
        self.stat_packed = StatBox(stats, "Packed", "–")
        self.stat_format = StatBox(stats, "Format", "–")
        for box in (self.stat_files, self.stat_size, self.stat_packed, self.stat_format):
            box.pack(side="left", padx=(0, 8))
        search = ttk.Frame(stats, style="Toolbox.TFrame")
        search.pack(side="right", anchor="s")
        ttk.Label(search, text="Filter", style="Toolbox.Muted.TLabel").pack(side="left", padx=4)
        ttk.Entry(search, textvariable=self.filter_var, width=24, style="Toolbox.TEntry").pack(side="left")

        table = ttk.Frame(parent, style="Toolbox.TFrame")
        table.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(table, columns=[c[0] for c in self.COLUMNS], show="headings",
                                 style="Toolbox.Treeview", selectmode="extended")
        for key, heading, width in self.COLUMNS:
            self.tree.heading(key, text=heading, command=lambda k=key: self._sort(k))
            self.tree.column(key, width=width, anchor="w" if key in ("name", "method") else "e",
                             stretch=key == "name")
        scroll = ttk.Scrollbar(table, orient="vertical", command=self.tree.yview,
                               style="Toolbox.Vertical.TScrollbar")
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.tree.bind("<Double-1>", lambda e: self.extract(selected_only=True))

    def open_dialog(self) -> None:
        path = filedialog.askopenfilename(title="Open ZFS archive",
                                          filetypes=[("ZFS archives", "*.zfs"), ("All files", "*.*")])
        if path:
            self.open(path)

    def open(self, path: str) -> None:
        key = self.key_var.get().strip() or None
        try:
            archive = ZFSArchive(path, key=key, decrypt_directory=self.dir_var.get())
        except (OSError, ZFSError) as exc:
            messagebox.showerror("Cannot open archive", str(exc))
            return
        self.archive = archive
        for button in (self.extract_button, self.extract_all_button, self.verify_button):
            button.configure(state="normal")
        entries = archive.entries
        self.stat_files.set(len(entries))
        self.stat_size.set(humanize_bytes(sum(e.size for e in entries)))
        self.stat_packed.set(humanize_bytes(sum(e.packed_size for e in entries)))
        encrypted = " (encrypted)" if archive.encrypted else ""
        self.stat_format.set(archive.header.format + encrypted)
        self._render()
        message = f"Opened {os.path.basename(path)}: {len(entries)} files"
        if archive.warnings:
            message += f" ({len(archive.warnings)} warning(s): {archive.warnings[0]})"
        self.shell.status(message)

    def _sort(self, key: str) -> None:
        self.sort_reverse = not self.sort_reverse if self.sort_key == key else False
        self.sort_key = key
        self._render()

    def _render(self) -> None:
        self.tree.delete(*self.tree.get_children())
        if self.archive is None:
            return
        query = self.filter_var.get().strip().lower()
        rows = [e for e in self.archive.entries if query in e.name.lower()]
        sort_values = {
            "name": lambda e: e.name.lower(), "ext": lambda e: e.extension, "size": lambda e: e.size,
            "packed": lambda e: e.packed_size, "method": lambda e: e.method, "index": lambda e: e.index,
            "ratio": lambda e: e.packed_size / e.size if e.size else 1.0,
        }
        rows.sort(key=sort_values[self.sort_key], reverse=self.sort_reverse)
        for entry in rows:
            ratio = f"{100 * entry.packed_size / entry.size:.0f}%" if entry.size else "–"
            self.tree.insert("", "end", values=(entry.name, entry.extension, humanize_bytes(entry.size),
                                     humanize_bytes(entry.packed_size), ratio, entry.method))
        self._visible = rows

    def _selected_entries(self):
        items = self.tree.selection()
        rows = getattr(self, "_visible", [])
        return [rows[self.tree.index(item)] for item in items]

    def extract(self, selected_only: bool) -> None:
        if self.archive is None:
            return
        entries = self._selected_entries() if selected_only else list(self.archive.entries)
        if not entries:
            messagebox.showinfo("Extract", "Select one or more files first.")
            return
        out_dir = filedialog.askdirectory(title="Extract to folder")
        if not out_dir:
            return
        archive = self.archive
        key = self.key_var.get().strip() or None

        def work(job):
            def progress(i, total, name):
                job.check_cancelled()
                job.report(i / total, name)
            return archive.extract(entries, out_dir, progress=progress, key=key)

        def done(paths):
            self.shell.status(f"Extracted {len(paths)} file(s) to {out_dir}")
            open_in_file_manager(out_dir)

        self.shell.jobs.submit(f"Extract {len(entries)} file(s) from {archive.path.name}", work,
                               on_done=done, on_error=lambda e: messagebox.showerror("Extract failed", e))

    def verify(self) -> None:
        if self.archive is None:
            return
        archive = self.archive

        def work(job):
            def progress(i, total, name):
                job.check_cancelled()
                job.report(i / total, name)
            return archive.verify(progress)

        def done(problems):
            if problems:
                messagebox.showwarning("Verify", f"{len(problems)} problem(s):\n\n" + "\n".join(problems[:20]))
            else:
                self.shell.status(f"{archive.path.name}: all {len(archive)} files decode correctly.")

        self.shell.jobs.submit(f"Verify {archive.path.name}", work, on_done=done,
                               on_error=lambda e: messagebox.showerror("Verify failed", e))

    # -------------------------------------------------------------------- pack
    def _build_packer(self, parent) -> None:
        card = Card(parent, "Pack a folder into a ZFS archive",
                    "Every file in the folder becomes an archive member. Names are flat and limited "
                    "to 15 characters. Members are LZO1X-compressed when that makes them smaller.")
        card.pack(fill="x")
        self.pack_source = tk.StringVar()
        self.pack_output = tk.StringVar()
        PathPicker(card.body, "Source folder", self.pack_source, surface=True,
                   on_change=self._suggest_output).pack(fill="x", pady=2)
        PathPicker(card.body, "Output archive", self.pack_output, kind="save", surface=True,
                   filetypes=(("ZFS archives", "*.zfs"),)).pack(fill="x", pady=2)
        options = ttk.Frame(card.body, style="Toolbox.Surface.TFrame")
        options.pack(fill="x", pady=(6, 0))
        ttk.Label(options, text="Encryption key", style="Toolbox.Surface.TLabel", width=18).pack(side="left")
        self.pack_key = tk.StringVar(value="0")
        ttk.Entry(options, textvariable=self.pack_key, width=18, style="Toolbox.TEntry").pack(side="left")
        self.pack_compress = tk.BooleanVar(value=True)
        self.pack_recursive = tk.BooleanVar(value=False)
        ttk.Checkbutton(options, text="Compress (LZO1X)", variable=self.pack_compress,
                        style="Toolbox.Surface.TCheckbutton").pack(side="left", padx=12)
        ttk.Checkbutton(options, text="Include subfolders", variable=self.pack_recursive,
                        style="Toolbox.Surface.TCheckbutton").pack(side="left")
        self.pack_button = ttk.Button(card.body, text="Build archive", style="Toolbox.Accent.TButton",
                                      command=self.build_archive)
        self.pack_button.pack(anchor="e", pady=(10, 0))

    def _suggest_output(self, folder: str) -> None:
        if folder and not self.pack_output.get():
            self.pack_output.set(os.path.normpath(folder.rstrip("\\/") + ".zfs"))

    def build_archive(self) -> None:
        source, output = self.pack_source.get().strip(), self.pack_output.get().strip()
        if not os.path.isdir(source) or not output:
            messagebox.showinfo("Pack", "Choose a source folder and an output archive.")
            return
        files = files_in_folder(source, recursive=self.pack_recursive.get())
        if not files:
            messagebox.showinfo("Pack", "The folder has no files.")
            return
        key, compress = self.pack_key.get(), self.pack_compress.get()
        self.pack_button.configure(state="disabled")

        def work(job):
            def progress(i, total, name):
                job.report(i / total, name)
            return write_zfs(output, files, key=key, compress=compress, progress=progress,
                             cancel=lambda: job.cancelled)

        def finished(entries):
            self.pack_button.configure(state="normal")
            self.shell.status(f"Wrote {output} ({len(entries)} files)")
            self.open(output)

        def failed(error):
            self.pack_button.configure(state="normal")
            messagebox.showerror("Pack failed", error)

        self.shell.jobs.submit(f"Pack {os.path.basename(output)}", work, on_done=finished, on_error=failed)
