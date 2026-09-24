from __future__ import annotations

import os
import sys
import threading

from bztoolbox.modules.world.legacy_batch import discover_legacy_batch_folders, run_legacy_batch


def install_world_builder_legacy_batch_patch() -> None:
    """Add immediate-subfolder batch porting to the Legacy Atlas GUI."""
    core = sys.modules.get("bztoolbox.modules.world.world_builder_core")
    if core is None:
        return
    base = getattr(core, "BZ98TRNArchitect", None)
    if base is None or getattr(base, "_legacy_batch_installed", False):
        return

    original_setup = base.setup_legacy_tab

    def setup_legacy_tab_with_batch(self):
        original_setup(self)

        self.legacy_batch_source_root = core.tk.StringVar(value="")
        self.legacy_batch_out_root = core.tk.StringVar(value="")
        self.legacy_batch_info = core.tk.StringVar(
            value="Select a parent folder whose immediate subfolders each contain a legacy mission."
        )
        self.legacy_batch_use_manual_palette = core.tk.BooleanVar(value=False)

        children = self.tab_legacy.winfo_children()
        parent = children[0] if children else self.tab_legacy
        batch_f = core.ttk.LabelFrame(parent, text=" Batch Port Mission Folders ", padding=10)
        batch_f.pack(fill="x", pady=(10, 5))

        src_row = core.ttk.Frame(batch_f)
        src_row.pack(fill="x", pady=2)
        core.ttk.Label(src_row, text="Source parent:", width=15).pack(side="left")
        core.ttk.Entry(src_row, textvariable=self.legacy_batch_source_root).pack(
            side="left", fill="x", expand=True, padx=5
        )

        def browse_source():
            path = core.filedialog.askdirectory(title="Select parent folder containing legacy mission folders")
            if path:
                self.legacy_batch_source_root.set(path)
                self.scan_legacy_batch_root(path)

        core.ttk.Button(src_row, text="Browse", command=browse_source).pack(side="left")

        out_row = core.ttk.Frame(batch_f)
        out_row.pack(fill="x", pady=2)
        core.ttk.Label(out_row, text="Redux output:", width=15).pack(side="left")
        core.ttk.Entry(out_row, textvariable=self.legacy_batch_out_root).pack(
            side="left", fill="x", expand=True, padx=5
        )
        core.ttk.Button(
            out_row,
            text="Browse",
            command=lambda: self.legacy_batch_out_root.set(
                core.filedialog.askdirectory(title="Select parent folder for Redux outputs")
            ),
        ).pack(side="left")

        option_row = core.ttk.Frame(batch_f)
        option_row.pack(fill="x", pady=(5, 2))
        core.ttk.Checkbutton(
            option_row,
            text="Apply current manual ACT palette to every mission",
            variable=self.legacy_batch_use_manual_palette,
        ).pack(side="left")
        core.ttk.Label(
            option_row,
            text="Unchecked = resolve each mission's palette independently",
            foreground="#888888",
        ).pack(side="left", padx=10)

        core.ttk.Label(
            batch_f,
            textvariable=self.legacy_batch_info,
            foreground=core.BZ_CYAN,
            font=("Consolas", 9),
        ).pack(anchor="w", pady=(3, 3))

        self.btn_legacy_batch = core.ttk.Button(
            batch_f,
            text="BATCH PORT SUBFOLDERS",
            command=self.generate_legacy_batch,
            style="Success.TButton",
        )
        self.btn_legacy_batch.pack(fill="x", pady=(5, 0))

    def scan_legacy_batch_root(self, path=None):
        root = path or self.legacy_batch_source_root.get().strip()
        if not root:
            self.legacy_batch_info.set("No batch source parent selected.")
            return
        try:
            missions, skipped = discover_legacy_batch_folders(root)
            self.legacy_batch_info.set(
                f"{len(missions)} mission folder(s) found; {len(skipped)} non-mission folder(s) skipped. "
                "Only immediate subfolders are processed."
            )
        except Exception as exc:
            self.legacy_batch_info.set(f"Batch scan failed: {exc}")

    def generate_legacy_batch(self):
        source_root = self.legacy_batch_source_root.get().strip()
        output_root = self.legacy_batch_out_root.get().strip()
        if not source_root or not output_root:
            core.messagebox.showerror("Batch Port", "Select both batch source and output parent folders.")
            return
        try:
            missions, _skipped = discover_legacy_batch_folders(source_root)
        except Exception as exc:
            core.messagebox.showerror("Batch Port", str(exc))
            return
        if not missions:
            core.messagebox.showerror(
                "Batch Port",
                "No immediate subfolders containing BZN missions were found.",
            )
            return

        image_format = self.legacy_format.get()
        explicit_palette = None
        if self.legacy_batch_use_manual_palette.get():
            explicit_palette = self.legacy_pal_path.get().strip() or None
            if not explicit_palette:
                core.messagebox.showerror(
                    "Batch Port",
                    "Manual palette override is enabled, but no ACT palette is selected.",
                )
                return

        self.btn_legacy_batch.config(text="BATCH PORTING...", state="disabled")
        self.legacy_batch_info.set(f"Processing {len(missions)} mission folder(s)...")
        threading.Thread(
            target=self._generate_legacy_batch_worker,
            args=(source_root, output_root, image_format, explicit_palette),
            daemon=True,
        ).start()

    def generate_legacy_batch_worker(self, source_root, output_root, image_format, explicit_palette):
        saved = {
            "source": self.legacy_source_dir.get(),
            "output": self.legacy_out_dir.get(),
            "prefix": self.legacy_prefix.get(),
            "palette": self.legacy_pal_path.get(),
            "format": self.legacy_format.get(),
        }
        try:
            def port_one(source_dir: str, output_dir: str, prefix: str) -> None:
                # Reuse the exact same single-map worker and all installed HGT,
                # package, stock-palette, material, and preflight patches.
                self.legacy_source_dir.set(source_dir)
                self.legacy_out_dir.set(output_dir)
                self.legacy_prefix.set(prefix)
                self.legacy_format.set(image_format)
                self.legacy_pal_path.set(explicit_palette or "")
                if hasattr(self, "legacy_auto_hgt"):
                    self.legacy_auto_hgt.set(True)
                if hasattr(self, "legacy_auto_package"):
                    self.legacy_auto_package.set(True)
                self._generate_legacy_worker(source_dir, output_dir)

            result = run_legacy_batch(
                source_root,
                output_root,
                port_one,
                explicit_palette=explicit_palette,
                log=self.log,
            )
            summary = (
                f"BATCH COMPLETE: {result.ready_count}/{len(result.items)} READY TO LAUNCH; "
                f"{result.failed_count} failed/not ready; report: {os.path.basename(result.report_path)}"
            )
            self.log(summary, "success" if result.all_ready else "warning")
            self.root.after(0, lambda: self.legacy_batch_info.set(summary))
        except Exception as exc:
            self.log(f"Batch port failed: {exc}", "error")
            self.root.after(0, lambda: self.legacy_batch_info.set(f"BATCH FAILED: {exc}"))
        finally:
            try:
                self.legacy_source_dir.set(saved["source"])
                self.legacy_out_dir.set(saved["output"])
                self.legacy_prefix.set(saved["prefix"])
                self.legacy_pal_path.set(saved["palette"])
                self.legacy_format.set(saved["format"])
            except Exception:
                pass
            self.root.after(
                0,
                lambda: self.btn_legacy_batch.config(text="BATCH PORT SUBFOLDERS", state="normal"),
            )

    base.setup_legacy_tab = setup_legacy_tab_with_batch
    base.scan_legacy_batch_root = scan_legacy_batch_root
    base.generate_legacy_batch = generate_legacy_batch
    base._generate_legacy_batch_worker = generate_legacy_batch_worker
    base._legacy_batch_installed = True
