from __future__ import annotations

import os
import threading
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter, ImageTk

from bztoolbox.modules.world import world_builder_core as core
from bztoolbox.modules.world import maketrn_compat
from bztoolbox.modules.world.world_builder_core import *
from bztoolbox.modules.world.hg2_codec import (
    DEFAULT_ZONE_BITS,
    hg2_to_png16_array,
    read_hg2,
    read_hg2_header,
    write_hg2,
)
from bztoolbox.modules.world.maketrn_compat import (
    METERS_PER_ZONE,
    make_stock_geometry,
    make_trn_runtime_seed,
    read_hgt_as_hg2,
    validate_empty_elevation,
)
from bztoolbox.modules.world.mission_visualizer import (
    extract_terrain_name,
    hg2_north_up,
    hg2_world_size,
    resolve_companion_hg2,
    resolve_mission_trn,
    world_to_canvas,
)
from bztoolbox.modules.world.mat_codec import (
    HG2_SAMPLES_PER_ZONE,
    PAINTER_MAX_ELEVATION,
    default_make_trn_rules,
    generate_mat,
    parse_trn_painter,
    validate_paint_rules,
    write_mat,
)
from bztoolbox.modules.world.stock_map_creator import StockBuildConfig, build_stock_map
from bztoolbox.modules.world.terrain_obj import export_hg2_to_obj, read_terrain_obj, resolve_hg2_geometry
from bztoolbox.modules.world.bz2_ter_codec import read_ter
from bztoolbox.modules.world.bz2_terrain_bundle import build_bz2_terrain_bundle
from bztoolbox.modules.world.bz2_terrain_port import convert_ter_height, geometry_for
from bztoolbox.modules.world.bz2_texture_resolver import (build_texture_slot_manifest, find_texture_asset_root,
                                  resolve_trn_texture_slots)
from bztoolbox.modules.world.bz2_pak import PakArchive


# Some CLI import orders load maketrn_compat before world_builder_core exists.
# Re-run its idempotent UI installer now that the base architect is available.
if hasattr(maketrn_compat, "install_world_builder_legacy_hgt_patch"):
    maketrn_compat.install_world_builder_legacy_hgt_patch()
elif hasattr(maketrn_compat, "_install_world_builder_legacy_hgt_ui_patch"):
    maketrn_compat._install_world_builder_legacy_hgt_ui_patch()


_BaseArchitect = core.BZ98TRNArchitect


class BZ98TRNArchitect(_BaseArchitect):
    """World Builder with canonical Redux HG2 I/O and MakeTRN-compatible MAT painting."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._install_bz2_port_tab()

        # The legacy binary's real built-in defaults are 0..15 degrees => Mat0
        # and 15..90 degrees => Mat3. The old CLI help incorrectly says 10.
        self.paint_rules = default_make_trn_rules()
        self.paint_trn_config = None

        # MakeTRN /c compatibility controls. Blank width/depth means "use the
        # selected WorldBuilder size preset". Runtime-random MAT variants match
        # MakeTRN's srand(clock()); deterministic mode is a WorldBuilder extension.
        self.stock_width_override = core.tk.StringVar(value="")
        self.stock_depth_override = core.tk.StringVar(value="")
        self.stock_empty_elevation = core.tk.IntVar(value=0)
        self.stock_param_path = core.tk.StringVar(value="")
        self.make_trn_deterministic_mat = core.tk.BooleanVar(value=False)
        self._install_stock_make_trn_controls()

        # TerraZone-inspired, Blender-independent OBJ terrain round-trip state.
        self.terrain_obj_path = core.tk.StringVar(value="")
        self.terrain_obj_status = core.tk.StringVar(value="No OBJ loaded")
        self.terrain_obj_mesh = None
        self._install_terrain_obj_controls()

        try:
            self.refresh_rules_list()
        except Exception:
            pass

    def _install_bz2_port_tab(self):
        """Keep the BZ2/BZCC importer separate from the BZ1 Legacy Atlas page."""
        self.bz2_ter_path = core.tk.StringVar(value="")
        self.bz2_trn_path = core.tk.StringVar(value="")
        self.bz2_asset_root = core.tk.StringVar(value="")
        self.bz2_output_dir = core.tk.StringVar(value="")
        self.bz2_name = core.tk.StringVar(value="")
        self.bz2_target_min_x = core.tk.StringVar(value="0")
        self.bz2_target_min_z = core.tk.StringVar(value="0")
        self.bz2_status = core.tk.StringVar(value="Choose a BZ2/BZCC .TER to inspect.")
        self.tab_bz2_port = core.ttk.Frame(self.notebook)
        self.notebook.insert(self.tab_hg2, self.tab_bz2_port, text=" BZ2 → BZ1 Map Port ")
        pane = core.ttk.Frame(self.tab_bz2_port, padding=20)
        pane.pack(fill="both", expand=True)
        core.ttk.Label(pane, text="BZ2 / BZCC TERRAIN PORT", foreground=core.BZ_GREEN,
                       font=(self.custom_font_name, 14, "bold")).pack(anchor="w", pady=(0, 12))
        core.ttk.Label(pane, text="Terrain pipeline: TER → world-scale HG2 → reduced Redux MAT → exact atlas transitions.\n"
                       "Add the companion TRN + texture asset root to build a full terrain-validation bundle.",
                       foreground=core.BZ_CYAN, justify="left").pack(anchor="w", pady=(0, 16))

        def path_row(label, variable, callback):
            frame = core.ttk.LabelFrame(pane, text=label, padding=10)
            frame.pack(fill="x", pady=5)
            core.ttk.Entry(frame, textvariable=variable).pack(side="left", fill="x", expand=True, padx=(0, 8))
            core.ttk.Button(frame, text="Browse", command=callback).pack(side="right")

        path_row("Source BZ2/BZCC .TER", self.bz2_ter_path, self._browse_bz2_ter)
        path_row("Companion BZ2/BZCC .TRN", self.bz2_trn_path, self._browse_bz2_trn)
        path_row("Texture asset root", self.bz2_asset_root,
                 lambda: self.bz2_asset_root.set(core.filedialog.askdirectory() or self.bz2_asset_root.get()))
        path_row("Fresh output folder", self.bz2_output_dir,
                 lambda: self.bz2_output_dir.set(core.filedialog.askdirectory() or self.bz2_output_dir.get()))
        name_row = core.ttk.Frame(pane)
        name_row.pack(fill="x", pady=10)
        core.ttk.Label(name_row, text="Redux terrain name (1–8 characters):").pack(side="left")
        core.ttk.Entry(name_row, textvariable=self.bz2_name, width=12).pack(side="left", padx=10)
        core.ttk.Label(name_row, text="Target MinX / MinZ (m):").pack(side="left", padx=(20, 0))
        core.ttk.Entry(name_row, textvariable=self.bz2_target_min_x, width=8).pack(side="left", padx=5)
        core.ttk.Entry(name_row, textvariable=self.bz2_target_min_z, width=8).pack(side="left", padx=5)
        core.ttk.Button(pane, text="INSPECT TER", command=self._inspect_bz2_ter).pack(fill="x", pady=5)
        self.bz2_convert_button = core.ttk.Button(
            pane, text="CONVERT TER + HG2 + MAT DIAGNOSTICS",
            command=self._convert_bz2_ter, style="Success.TButton"
        )
        self.bz2_convert_button.pack(fill="x", pady=5)
        self.bz2_bundle_button = core.ttk.Button(
            pane, text="BUILD RESOLVED TERRAIN BUNDLE",
            command=self._build_bz2_bundle, style="Success.TButton"
        )
        self.bz2_bundle_button.pack(fill="x", pady=5)
        core.ttk.Button(pane, text="EXTRACT REQUIRED PAK TEXTURES…",
                        command=self._extract_bz2_pak_textures).pack(fill="x", pady=5)
        core.ttk.Label(pane, textvariable=self.bz2_status, justify="left", wraplength=1050,
                       foreground=core.BZ_FG).pack(anchor="w", pady=12)

    def _browse_bz2_ter(self):
        path = core.filedialog.askopenfilename(filetypes=[("BZ2/BZCC terrain", "*.ter"), ("All files", "*.*")])
        if path:
            self.bz2_ter_path.set(path)
            source_path = Path(path)
            self.bz2_name.set(source_path.stem[:8])
            companion = source_path.with_suffix(".trn")
            if companion.is_file():
                self.bz2_trn_path.set(str(companion))
            self.bz2_asset_root.set("")
            self._inspect_bz2_ter()
            if companion.is_file():
                self._suggest_bz2_asset_root(source_path, companion)
            if not self.bz2_asset_root.get():
                self.bz2_status.set(
                    self.bz2_status.get() + "\nSelect the BZCC game folder with .pak archives "
                    "or a folder with loose textures named by the TRN."
                )

    def _browse_bz2_trn(self):
        path = core.filedialog.askopenfilename(
            filetypes=[("BZ2/BZCC terrain config", "*.trn"), ("All files", "*.*")]
        )
        if path:
            self.bz2_trn_path.set(path)
            if not self.bz2_asset_root.get() and self.bz2_ter_path.get():
                self._suggest_bz2_asset_root(Path(self.bz2_ter_path.get()), Path(path))

    def _suggest_bz2_asset_root(self, ter_path, trn_path):
        try:
            source = read_ter(ter_path)
            ancestors = list(Path(ter_path).parents[:4])
            candidates = [path for parent in ancestors for path in (parent, parent / "worlds")]
            found = find_texture_asset_root(build_texture_slot_manifest(source),
                                            trn_path, candidates)
            if found:
                self.bz2_asset_root.set(str(found))
        except (OSError, ValueError) as exc:
            self.bz2_status.set(f"Cannot locate source textures automatically: {exc}")

    def _extract_bz2_pak_textures(self):
        """Export only the companion TRN's needed packed textures on demand."""
        try:
            source = read_ter(self.bz2_ter_path.get())
            manifest = resolve_trn_texture_slots(
                build_texture_slot_manifest(source), self.bz2_trn_path.get(),
                self.bz2_asset_root.get())
            if not manifest["ready_for_atlas"]:
                raise ValueError(f"Missing texture slots: {manifest['unresolved_used_slots']}")
            entries = [entry for entry in manifest["slots"]
                       if entry["used"] and entry.get("source_archive")]
            if not entries:
                self.bz2_status.set("All required textures are already loose files.")
                return
            output = core.filedialog.askdirectory(title="Extract required PAK textures into folder")
            if not output:
                return
            extracted = []
            for entry in entries:
                extracted.append(PakArchive(entry["source_archive"]).extract(
                    entry["source_member"], output))
            self.bz2_status.set(f"Extracted {len(extracted)} required texture(s) into {output}.")
        except Exception as exc:
            self.bz2_status.set(f"PAK extraction failed: {exc}")

    def _inspect_bz2_ter(self):
        try:
            source = read_ter(self.bz2_ter_path.get())
            min_x, min_z = self._bz2_target_origin()
            geo = geometry_for(source, target_min_x=min_x, target_min_z=min_z)
            self.bz2_status.set(
                f"TER v{source.version} · {source.heights_m.shape[1]}×{source.heights_m.shape[0]} "
                f"samples at {source.spacing_m} m · authored {geo.source_width_m}×{geo.source_depth_m} m\n"
                f"Redux padding: {geo.zones_x}×{geo.zones_z} zones; origin ({geo.min_x}, {geo.min_z}) m; "
                f"vertical offset {geo.vertical_offset_m:g} m. Source channels retained for atlas/MAT work."
            )
        except Exception as exc:
            self.bz2_status.set(f"Cannot inspect TER: {exc}")

    def _bz2_target_origin(self):
        """Blank preserves the source's padded origin; 0,0 rehomes to Redux."""
        values = (self.bz2_target_min_x.get().strip(), self.bz2_target_min_z.get().strip())
        try:
            return tuple(int(value) if value else None for value in values)
        except ValueError as exc:
            raise ValueError("Target MinX and MinZ must be whole meters") from exc

    def _convert_bz2_ter(self):
        ter, out, name = self.bz2_ter_path.get(), self.bz2_output_dir.get(), self.bz2_name.get()
        if not ter or not out:
            self.bz2_status.set("Select a TER and an output folder first.")
            return
        try:
            min_x, min_z = self._bz2_target_origin()
        except ValueError as exc:
            self.bz2_status.set(str(exc))
            return
        self.bz2_convert_button.configure(state="disabled")
        self.bz2_bundle_button.configure(state="disabled")
        self.bz2_status.set("Converting TER height and encoding Redux MAT diagnostics…")

        def worker():
            try:
                result = convert_ter_height(
                    ter, out, name, target_min_x=min_x, target_min_z=min_z
                )
                message = (f"Wrote {name}.hg2, source channels and {name}_reduced.MAT to {out}. "
                           f"Redux zones: {result['redux_zones']}; vertical offset: "
                           f"{result['vertical_offset_m']:g} m. Texture resolution/atlas/TRN still pending.")
            except Exception as exc:
                message = f"Conversion failed: {exc}"
            self.root.after(0, lambda: (
                self.bz2_status.set(message),
                self.bz2_convert_button.configure(state="normal"),
                self.bz2_bundle_button.configure(state="normal"),
            ))

        threading.Thread(target=worker, daemon=True).start()

    def _build_bz2_bundle(self):
        ter = self.bz2_ter_path.get()
        trn = self.bz2_trn_path.get()
        assets = self.bz2_asset_root.get()
        out = self.bz2_output_dir.get()
        name = self.bz2_name.get()
        if not ter or not trn or not assets or not out:
            self.bz2_status.set(
                "Select TER, companion TRN, texture asset root, and a fresh output folder first."
            )
            return
        try:
            min_x, min_z = self._bz2_target_origin()
        except ValueError as exc:
            self.bz2_status.set(str(exc))
            return
        self.bz2_convert_button.configure(state="disabled")
        self.bz2_bundle_button.configure(state="disabled")
        self.bz2_status.set("Resolving source textures and building HG2/MAT/atlas/TRN bundle…")

        def worker():
            try:
                result = build_bz2_terrain_bundle(
                    ter, trn, assets, out, name,
                    target_min_x=min_x, target_min_z=min_z,
                )
                mat = result["mat_reduction"]
                message = (
                    f"Built terrain validation bundle: {name}.hg2, {name}.mat and "
                    f"{name}.trn. Exact transitions: {len(mat['cap_pairs'])} cap pair(s), "
                    f"{len(mat['diagonal_pairs'])} diagonal pair(s); "
                    f"{mat['ambiguous_cells']} ambiguous cell(s) collapsed to dominant material. "
                    "Next: validate orientation and terrain appearance in BZR."
                )
            except Exception as exc:
                message = f"Bundle build failed: {exc}"
            self.root.after(0, lambda: (
                self.bz2_status.set(message),
                self.bz2_convert_button.configure(state="normal"),
                self.bz2_bundle_button.configure(state="normal"),
            ))

        threading.Thread(target=worker, daemon=True).start()

    def _install_stock_make_trn_controls(self):
        """Append the useful MakeTRN /w /h /e /p controls to Stock Map Creator."""
        try:
            containers = self.tab_stock.winfo_children()
            if not containers:
                return
            columns = containers[0].winfo_children()
            if not columns:
                return
            left_col = columns[0]

            frame = core.ttk.LabelFrame(left_col, text=" MakeTRN Compatibility ", padding=8)
            frame.pack(fill="x", pady=(10, 0))
            core.ttk.Label(
                frame,
                text="Optional /w and /h overrides (meters):",
                foreground=core.BZ_CYAN,
            ).pack(anchor="w")

            dims = core.ttk.Frame(frame)
            dims.pack(fill="x", pady=3)
            core.ttk.Label(dims, text="Width:").grid(row=0, column=0, sticky="w")
            core.ttk.Entry(dims, textvariable=self.stock_width_override, width=9).grid(
                row=0, column=1, padx=(4, 10)
            )
            core.ttk.Label(dims, text="Depth:").grid(row=0, column=2, sticky="w")
            core.ttk.Entry(dims, textvariable=self.stock_depth_override, width=9).grid(
                row=0, column=3, padx=4
            )

            elev = core.ttk.Frame(frame)
            elev.pack(fill="x", pady=3)
            core.ttk.Label(elev, text="Empty elevation (/e):").pack(side="left")
            core.tk.Spinbox(
                elev,
                from_=0,
                to=4094,
                textvariable=self.stock_empty_elevation,
                width=8,
                bg="#1a1a1a",
                fg=core.BZ_CYAN,
                insertbackground=core.BZ_GREEN,
            ).pack(side="left", padx=5)

            param = core.ttk.Frame(frame)
            param.pack(fill="x", pady=3)
            core.ttk.Label(param, text="Layer file (/p):").pack(side="left")
            core.ttk.Entry(param, textvariable=self.stock_param_path).pack(
                side="left", fill="x", expand=True, padx=5
            )
            core.ttk.Button(param, text="...", width=3, command=self._browse_stock_parameter_file).pack(
                side="left"
            )

            core.ttk.Checkbutton(
                frame,
                text="Deterministic MAT variants (seed 1; WorldBuilder extension)",
                variable=self.make_trn_deterministic_mat,
            ).pack(anchor="w", pady=(4, 0))
            core.ttk.Label(
                frame,
                text="Blank = preset size. MakeTRN normalizes dimensions to 1280 m terrain zones.",
                font=(self.custom_font_name, 7, "italic"),
                foreground="#777777",
                wraplength=390,
            ).pack(anchor="w", pady=(3, 0))
        except Exception as exc:
            self.log(f"MakeTRN compatibility controls unavailable: {exc}", "warning")

    def _browse_stock_parameter_file(self):
        path = core.filedialog.askopenfilename(
            title="Select MakeTRN layer parameter file",
            filetypes=[("MakeTRN Layer Config", "*.ini *.txt *.trn"), ("All Files", "*.*")],
        )
        if path:
            self.stock_param_path.set(path)

    def validate_map_name(self, value):
        """Make the existing Stock UI match its documented alphanumeric rule."""
        return len(value) <= 8 and (value == "" or value.isalnum())

    def _install_terrain_obj_controls(self):
        """Add OBJ terrain round-trip controls to the Heightmap Converter tab."""
        try:
            containers = self.tab_hg2.winfo_children()
            if not containers:
                return
            columns = containers[0].winfo_children()
            if not columns:
                return
            left_panel = columns[0]

            frame = core.ttk.LabelFrame(left_panel, text=" Terrain OBJ Round-Trip ", padding=8)
            frame.pack(fill="x", pady=(10, 0))

            core.ttk.Label(
                frame,
                text="Edit HG2 terrain as a regular Wavefront OBJ mesh.",
                foreground=core.BZ_CYAN,
            ).pack(anchor="w")
            core.ttk.Label(
                frame,
                text="WorldBuilder requires no Blender install. In a 3D editor, sculpt Y/height and keep the X/Z grid intact.",
                font=(self.custom_font_name, 7, "italic"),
                foreground="#777777",
                wraplength=390,
            ).pack(anchor="w", pady=(2, 5))

            buttons = core.ttk.Frame(frame)
            buttons.pack(fill="x")
            core.ttk.Button(
                buttons, text="IMPORT OBJ", command=self.browse_terrain_obj
            ).pack(side="left", expand=True, fill="x", padx=(0, 3))
            core.ttk.Button(
                buttons, text="OBJ -> HG2", command=self.export_obj_to_hg2
            ).pack(side="left", expand=True, fill="x", padx=3)
            core.ttk.Button(
                buttons, text="HG2 -> OBJ", command=self.export_hg2_to_obj
            ).pack(side="left", expand=True, fill="x", padx=(3, 0))

            core.ttk.Label(
                frame,
                textvariable=self.terrain_obj_status,
                foreground=core.BZ_GREEN,
                wraplength=390,
            ).pack(anchor="w", pady=(5, 0))
        except Exception as exc:
            self.log(f"Terrain OBJ controls unavailable: {exc}", "warning")

    def _preview_height_array(self, heights):
        arr = np.asarray(heights, dtype=np.float32)
        if arr.size == 0:
            return
        f_min, f_max = float(arr.min()), float(arr.max())
        if f_max > f_min:
            norm = (arr - f_min) / (f_max - f_min)
        else:
            norm = np.zeros_like(arr, dtype=np.float32)
        preview = Image.fromarray((np.clip(norm, 0.0, 1.0) * 255).astype(np.uint8))
        cw, ch = self.hg2_preview_canvas.winfo_width(), self.hg2_preview_canvas.winfo_height()
        if cw < 10:
            cw, ch = 600, 600
        preview.thumbnail((cw, ch), self.resample_method)
        self.hg2_tk_photo = ImageTk.PhotoImage(preview)
        self.hg2_preview_canvas.delete("all")
        self.hg2_preview_canvas.create_image(cw // 2, ch // 2, image=self.hg2_tk_photo)

    def browse_terrain_obj(self):
        path = core.filedialog.askopenfilename(
            title="Import Terrain OBJ",
            filetypes=[("Wavefront OBJ", "*.obj"), ("All Files", "*.*")],
        )
        if not path:
            return
        try:
            mesh = read_terrain_obj(path)
            self.terrain_obj_mesh = mesh
            self.terrain_obj_path.set(path)
            if mesh.zones_x and mesh.zones_z:
                self.hg2_target_zw.set(mesh.zones_x)
                self.hg2_target_zl.set(mesh.zones_z)
            meta = (
                f"{mesh.zones_x}x{mesh.zones_z} zones"
                if mesh.zones_x and mesh.zones_z
                else "geometry inferred from X/Z grid"
            )
            self.terrain_obj_status.set(
                f"{os.path.basename(path)}: {mesh.samples_x}x{mesh.samples_z} vertices, {meta}"
            )
            self._preview_height_array(mesh.heights)
            self.log(
                f"Loaded terrain OBJ: {os.path.basename(path)} "
                f"({mesh.samples_x}x{mesh.samples_z} height samples).",
                "success",
            )
        except Exception as exc:
            self.terrain_obj_mesh = None
            self.terrain_obj_status.set("OBJ load failed")
            core.messagebox.showerror("Terrain OBJ", f"Failed to import OBJ:\n{exc}")

    def export_hg2_to_obj(self):
        source_path = self.hg2_path.get()
        if not source_path or not os.path.isfile(source_path) or not source_path.lower().endswith(".hg2"):
            core.messagebox.showerror("Terrain OBJ", "Select an HG2 in Heightmap Converter first.")
            return
        save_path = core.filedialog.asksaveasfilename(
            title="Export HG2 Terrain as OBJ",
            defaultextension=".obj",
            initialfile=os.path.splitext(os.path.basename(source_path))[0] + ".obj",
            filetypes=[("Wavefront OBJ", "*.obj")],
        )
        if not save_path:
            return
        try:
            export_hg2_to_obj(source_path, save_path)
            header = read_hg2_header(source_path)
            spacing = METERS_PER_ZONE / float(1 << header.zone_bits)
            self.log(
                f"Exported terrain OBJ: {os.path.basename(save_path)} "
                f"({header.zones_x}x{header.zones_z} zones, {spacing:g} m/sample).",
                "success",
            )
            core.messagebox.showinfo(
                "Terrain OBJ",
                f"Exported:\n{save_path}\n\n"
                "The OBJ contains WorldBuilder HG2 metadata and a regular X/Z grid. "
                "Edit vertex Y values in Blender, 3ds Max, Maya, or another OBJ editor, "
                "then import it here and export back to HG2.",
            )
        except Exception as exc:
            core.messagebox.showerror("Terrain OBJ", f"Failed to export OBJ:\n{exc}")

    def export_obj_to_hg2(self):
        mesh = self.terrain_obj_mesh
        if mesh is None:
            path = self.terrain_obj_path.get()
            if not path or not os.path.isfile(path):
                core.messagebox.showerror("Terrain OBJ", "Import a terrain OBJ first.")
                return
            try:
                mesh = read_terrain_obj(path)
                self.terrain_obj_mesh = mesh
            except Exception as exc:
                core.messagebox.showerror("Terrain OBJ", f"Failed to import OBJ:\n{exc}")
                return

        try:
            zones_x, zones_z, zone_bits = resolve_hg2_geometry(
                mesh,
                preferred_zones_x=int(self.hg2_target_zw.get()),
                preferred_zones_z=int(self.hg2_target_zl.get()),
            )
        except Exception as exc:
            core.messagebox.showerror("Terrain OBJ", str(exc))
            return

        save_path = core.filedialog.asksaveasfilename(
            title="Export Terrain OBJ as HG2",
            defaultextension=".hg2",
            initialfile=os.path.splitext(os.path.basename(mesh.path))[0] + ".hg2",
            filetypes=[("Redux Heightmap", "*.hg2")],
        )
        if not save_path:
            return

        try:
            write_hg2(
                save_path,
                mesh.heights,
                zones_x=zones_x,
                zones_z=zones_z,
                zone_bits=zone_bits,
            )
            self.hg2_target_zw.set(zones_x)
            self.hg2_target_zl.set(zones_z)
            self.log(
                f"Exported HG2 from OBJ: {os.path.basename(save_path)} "
                f"({zones_x}x{zones_z} zones, zone_bits={zone_bits}).",
                "success",
            )
            core.messagebox.showinfo(
                "Terrain OBJ",
                f"Saved Redux HG2:\n{save_path}\n\n"
                f"Grid: {mesh.samples_x} x {mesh.samples_z} samples\n"
                f"Zones: {zones_x} x {zones_z}\n"
                f"Height range: {int(mesh.heights.min()) / 10.0:g} - "
                f"{int(mesh.heights.max()) / 10.0:g} m",
            )
        except Exception as exc:
            core.messagebox.showerror("Terrain OBJ", f"Failed to write HG2:\n{exc}")

    def browse_hg2(self):
        path = core.filedialog.askopenfilename(
            filetypes=[("Heightmaps", "*.hg2 *.hgt *.png *.bmp")]
        )
        if not path:
            return
        self.hg2_path.set(path)
        if path.lower().endswith(".hg2"):
            try:
                header = read_hg2_header(path)
                self.hg2_target_zw.set(header.zones_x)
                self.hg2_target_zl.set(header.zones_z)
            except Exception as exc:
                core.messagebox.showerror("HG2 Error", str(exc))
                return
        elif path.lower().endswith(".hgt"):
            try:
                trn = core.TRNParser.parse(os.path.splitext(path)[0] + ".trn")
                if trn.get("Width") and trn.get("Depth"):
                    self.hg2_target_zw.set(int(round(trn["Width"] / 1280.0)))
                    self.hg2_target_zl.set(int(round(trn["Depth"] / 1280.0)))
            except Exception:
                pass
        self.update_hg2_preview()

    def update_hg2_preview(self, *args):
        path = self.hg2_path.get()
        if not path or not os.path.exists(path):
            return
        if not path.lower().endswith(".hg2"):
            return super().update_hg2_preview(*args)
        try:
            _, heights = read_hg2(path)
            arr = hg2_to_png16_array(heights).astype(np.float32)
            arr *= self.hg2_brightness.get()
            arr = (arr - 32768.0) * self.hg2_contrast.get() + 32768.0
            temp_img = Image.fromarray(arr, mode="F")
            if self.hg2_smooth_val.get() > 0:
                temp_img = temp_img.filter(ImageFilter.GaussianBlur(self.hg2_smooth_val.get()))
            final_arr = np.array(temp_img)
            f_min, f_max = final_arr.min(), final_arr.max()
            norm = ((final_arr - f_min) / (f_max - f_min)) if f_max > f_min else final_arr / 65535.0
            preview = Image.fromarray((np.clip(norm, 0.0, 1.0) * 255).astype(np.uint8))
            cw, ch = self.hg2_preview_canvas.winfo_width(), self.hg2_preview_canvas.winfo_height()
            if cw < 10:
                cw, ch = 600, 600
            preview.thumbnail((cw, ch), self.resample_method)
            self.hg2_tk_photo = ImageTk.PhotoImage(preview)
            self.hg2_preview_canvas.delete("all")
            self.hg2_preview_canvas.create_image(cw // 2, ch // 2, image=self.hg2_tk_photo)
        except Exception as exc:
            print(f"Preview Update Error: {exc}")

    def convert_hg2_to_png(self):
        path = self.hg2_path.get()
        if not path or not os.path.exists(path):
            return
        if not path.lower().endswith(".hg2"):
            return super().convert_hg2_to_png()
        self.btn_hg2_png.config(text="CONVERTING...", state="disabled")
        try:
            _, heights = read_hg2(path)
            out_path = os.path.splitext(path)[0] + "_edit.png"
            if self.hg2img_compat.get():
                h = np.flipud((heights & 0x0FFF).astype(np.uint16))
                g = (h >> 4).astype(np.uint8)
                r = (h & 0x0F).astype(np.uint8) if self.hg2img_precision.get() else np.zeros_like(g)
                b = np.zeros_like(g)
                a = np.full_like(g, 255)
                out_img = Image.fromarray(np.dstack([r, g, b, a]), mode="RGBA")
                out_img.save(out_path)
                self.log(f"Success: Converted (HG2IMG legacy) ({out_img.width}x{out_img.height})", "success")
            else:
                out_img = Image.fromarray(hg2_to_png16_array(heights), mode="I;16")
                out_img.save(out_path)
                self.log(f"Success: Converted ({out_img.width}x{out_img.height})", "success")
        except Exception as exc:
            self.log(f"Error: Conversion failed: {exc}", "error")
        finally:
            self.root.after(0, lambda: self.btn_hg2_png.config(text="HG2 -> PNG", state="normal"))

    def _load_mission_background(self, path, *, redraw=True):
        """Load a mission background and retain its authoritative world geometry."""
        if path.lower().endswith(".hg2"):
            header, heights = read_hg2(path)
            display_heights = hg2_north_up(heights)
            peak = max(int(display_heights.max()), 1)
            arr_norm = np.clip(
                display_heights.astype(np.float32) / float(peak) * 255.0,
                0,
                255,
            ).astype(np.uint8)
            img = Image.fromarray(arr_norm)
            world_width, world_depth = hg2_world_size(header)
            self.mission_bg_world_width = world_width
            self.mission_bg_world_depth = world_depth
            self.mission_bg_hg2_header = header
        else:
            img = Image.open(path).convert("L")
            self.mission_bg_world_width = None
            self.mission_bg_world_depth = None
            self.mission_bg_hg2_header = None

        self.mission_bg_img = img
        self.mission_bg_source = os.path.abspath(path)
        if redraw:
            self.redraw_mission_canvas()

    def browse_mission_bg(self):
        path = core.filedialog.askopenfilename(
            filetypes=[("Map Image", "*.hg2 *.png *.bmp *.jpg")]
        )
        if not path:
            return
        try:
            self._load_mission_background(path)
        except Exception as exc:
            core.messagebox.showerror("Error", f"Failed to load map: {exc}")

    def _fallback_mission_world_size(self):
        try:
            size = float(self.selected_preset.get().split("(")[1].split("m")[0])
        except Exception:
            size = 5120.0
        return size, size

    def load_mission_overlay(self):
        bzn_path = core.filedialog.askopenfilename(
            title="Select Mission File (ASCII)",
            filetypes=[("Battlezone Mission", "*.bzn")],
        )
        if not bzn_path:
            return

        try:
            terrain_name = extract_terrain_name(bzn_path)
            trn_path = resolve_mission_trn(bzn_path, terrain_name)
            trn_data = core.TRNParser.parse(str(trn_path)) if trn_path else {}
            self.min_x = float(trn_data.get("MinX", 0.0) or 0.0)
            self.min_z = float(trn_data.get("MinZ", 0.0) or 0.0)
            self.mission_objects, self.ai_paths = core.BZNParser.parse(bzn_path)

            companion_hg2 = resolve_companion_hg2(trn_path)
            if self.mission_bg_img is None and companion_hg2 is not None:
                self._load_mission_background(str(companion_hg2), redraw=False)

            trn_width = float(trn_data["Width"]) if trn_data.get("Width") else None
            trn_depth = float(trn_data["Depth"]) if trn_data.get("Depth") else None
            bg_width = getattr(self, "mission_bg_world_width", None)
            bg_depth = getattr(self, "mission_bg_world_depth", None)
            fallback_width, fallback_depth = self._fallback_mission_world_size()
            self.mission_world_width = trn_width or bg_width or fallback_width
            self.mission_world_depth = trn_depth or bg_depth or fallback_depth

            warnings = []
            if trn_path is None:
                warnings.append("TRN not found; using HG2/preset dimensions.")
            if trn_width and trn_depth and bg_width and bg_depth and (
                abs(trn_width - bg_width) > 0.01 or abs(trn_depth - bg_depth) > 0.01
            ):
                warnings.append(
                    "TRN/HG2 size mismatch: "
                    f"TRN {trn_width:g}x{trn_depth:g}, HG2 {bg_width:g}x{bg_depth:g}."
                )

            bg_source = getattr(self, "mission_bg_source", None)
            if companion_hg2 is not None and bg_source:
                if os.path.normcase(os.path.abspath(str(companion_hg2))) != os.path.normcase(os.path.abspath(bg_source)):
                    warnings.append("Loaded background differs from the BZN terrain HG2.")

            info_lines = [
                f"TerrainName: {terrain_name or 'N/A'}",
                f"TRN: {os.path.basename(str(trn_path)) if trn_path else 'N/A'}",
                f"MinX: {self.min_x:g}, MinZ: {self.min_z:g}",
                f"World: {self.mission_world_width:g} x {self.mission_world_depth:g}",
                f"Objects: {len(self.mission_objects)}",
                f"Paths: {len(self.ai_paths)}",
            ]
            if getattr(self, "mission_bg_source", None):
                info_lines.append(f"Background: {os.path.basename(self.mission_bg_source)}")
            if warnings:
                info_lines.append("")
                info_lines.extend(f"WARNING: {warning}" for warning in warnings)

            self.mission_info.config(state="normal")
            self.mission_info.delete("1.0", "end")
            self.mission_info.insert("1.0", "\n".join(info_lines))
            self.mission_info.config(state="disabled")
            self.redraw_mission_canvas()
        except ValueError as exc:
            core.messagebox.showerror("Error", str(exc))
        except Exception as exc:
            core.messagebox.showerror("Error", f"Failed to load mission: {exc}")

    def draw_mission_objects_on_canvas(self, canvas):
        if not hasattr(self, "map_draw_rect"):
            cw = canvas.winfo_width()
            ch = canvas.winfo_height()
            self.map_draw_rect = (cw // 2 - 250, ch // 2 - 250, 500, 500)

        world_width = getattr(self, "mission_world_width", None)
        world_depth = getattr(self, "mission_world_depth", None)
        if not world_width or not world_depth:
            world_width = getattr(self, "mission_bg_world_width", None)
            world_depth = getattr(self, "mission_bg_world_depth", None)
        if not world_width or not world_depth:
            world_width, world_depth = self._fallback_mission_world_size()

        min_x = float(getattr(self, "min_x", 0.0))
        min_z = float(getattr(self, "min_z", 0.0))
        for path in getattr(self, "ai_paths", []) or []:
            points = path.get("points", [])
            if len(points) < 2:
                continue
            polyline = []
            for point in points:
                try:
                    cx, cy = world_to_canvas(
                        point[0], point[1], min_x=min_x, min_z=min_z,
                        world_width=world_width, world_depth=world_depth,
                        draw_rect=self.map_draw_rect,
                    )
                    polyline.extend((cx, cy))
                except (TypeError, ValueError, IndexError):
                    continue
            if len(polyline) >= 4:
                canvas.create_line(*polyline, fill=core.BZ_CYAN, width=1)

        for obj in getattr(self, "mission_objects", []) or []:
            try:
                cx, cy = world_to_canvas(
                    obj["pos"][0], obj["pos"][2], min_x=min_x, min_z=min_z,
                    world_width=world_width, world_depth=world_depth,
                    draw_rect=self.map_draw_rect,
                )
            except (KeyError, TypeError, ValueError, IndexError):
                continue
            color = core.BZ_GREEN
            cls = obj.get("odf", "").lower()
            if "recycle" in cls or "cons" in cls:
                color = "#ffee00"
            elif "fact" in cls:
                color = "#ff8800"
            elif "turr" in cls or "tow" in cls:
                color = "#ff4444"
            elif "scav" in cls:
                color = "#0088ff"
            canvas.create_rectangle(cx - 2, cy - 2, cx + 2, cy + 2, fill=color, outline="")

    def _read_image_for_painter(self, path):
        """WorldBuilder extension: normalize an image to Redux's 256-sample/zone grid."""
        zones_x, zones_z = int(self.hg2_target_zw.get()), int(self.hg2_target_zl.get())
        if zones_x <= 0 or zones_z <= 0:
            raise ValueError("Set valid zone dimensions before painting an image.")
        target = (zones_x * HG2_SAMPLES_PER_ZONE, zones_z * HG2_SAMPLES_PER_ZONE)
        img = Image.open(path)
        mode = img.mode
        legacy = self.hg2img_compat.get() and mode not in ("I;16", "I;16B", "I;16L", "I")
        if legacy:
            rgba = np.asarray(img.convert("RGBA"), dtype=np.uint8)
            red, green = rgba[..., 0].astype(np.uint16), rgba[..., 1].astype(np.uint16)
            heights = (green << 4) | ((red & 0x0F) if self.hg2img_precision.get() and red.max() <= 15 else 0)
            heights = np.flipud(heights)
            source = Image.fromarray(heights.astype(np.uint16), mode="I;16")
        else:
            if mode in ("I;16", "I;16B", "I;16L", "I"):
                raw = np.asarray(img.convert("I;16"), dtype=np.uint16).astype(np.float32)
                heights = np.rint(raw / 65535.0 * PAINTER_MAX_ELEVATION).astype(np.uint16)
            else:
                raw = np.asarray(img.convert("L"), dtype=np.uint8).astype(np.float32)
                heights = np.rint(raw / 255.0 * PAINTER_MAX_ELEVATION).astype(np.uint16)
            source = Image.fromarray(heights, mode="I;16")
        if source.size != target:
            source = source.resize(target, Image.Resampling.NEAREST)
        return np.asarray(source, dtype=np.uint16), zones_x, zones_z

    def _painter_trn_config(self, source_path):
        explicit = getattr(self, "paint_trn_config", None)
        if explicit is not None:
            return explicit
        adjacent = os.path.splitext(source_path)[0] + ".trn"
        if os.path.exists(adjacent):
            try:
                return parse_trn_painter(adjacent)
            except Exception:
                pass
        return None

    def _hgt_geometry_from_trn(self, trn):
        if trn is None or not trn.width or not trn.depth:
            raise ValueError("MakeTRN-compatible HGT import requires a companion TRN with Width and Depth.")
        zones_x_f = float(trn.width) / METERS_PER_ZONE
        zones_z_f = float(trn.depth) / METERS_PER_ZONE
        zones_x, zones_z = int(round(zones_x_f)), int(round(zones_z_f))
        if zones_x <= 0 or zones_z <= 0 or abs(zones_x_f - zones_x) > 1e-6 or abs(zones_z_f - zones_z) > 1e-6:
            raise ValueError("HGT companion TRN dimensions must be exact 1280 m zone multiples.")
        return zones_x, zones_z

    def run_auto_painter(self):
        source_path = self.hg2_path.get()
        if not source_path:
            core.messagebox.showerror("Error", "Please select an input HG2/image first.")
            return
        warnings = validate_paint_rules(self.paint_rules)
        fatal = [w for w in warnings if "slope range" not in w]
        if fatal:
            core.messagebox.showerror("Paint Rules", "\n".join(fatal[:12]))
            return
        try:
            lower = source_path.lower()
            extension_note = ""
            trn = self._painter_trn_config(source_path)
            if lower.endswith(".hg2"):
                header, arr = read_hg2(source_path)
                zones_x, zones_z = header.zones_x, header.zones_z
            elif lower.endswith(".hgt"):
                zones_x, zones_z = self._hgt_geometry_from_trn(trn)
                arr = read_hgt_as_hg2(source_path, zones_x, zones_z)
                hg2_path = os.path.splitext(source_path)[0] + ".hg2"
                write_hg2(
                    hg2_path,
                    arr,
                    zones_x=zones_x,
                    zones_z=zones_z,
                    zone_bits=DEFAULT_ZONE_BITS,
                )
                extension_note = (
                    f"\nSource: legacy HGT converted with MakeTRN's recovered triangle interpolator."
                    f"\nWrote companion HG2: {os.path.basename(hg2_path)}"
                )
            else:
                arr, zones_x, zones_z = self._read_image_for_painter(source_path)
                extension_note = "\nSource: WorldBuilder image-input extension (resampled to 256 HG2 samples/zone)."

            min_x = trn.min_x if trn else 0.0
            min_z = trn.min_z if trn else 0.0
            world_width = trn.width if trn and trn.width else zones_x * 1280.0
            world_depth = trn.depth if trn and trn.depth else zones_z * 1280.0
            seed = 1 if self.make_trn_deterministic_mat.get() else make_trn_runtime_seed()
            mat_data, stats = generate_mat(
                arr,
                self.paint_rules,
                zones_x,
                zones_z,
                cap_transitions=trn.cap_transitions if trn else None,
                diagonal_transitions=trn.diagonal_transitions if trn else None,
                bzn_paths=self.bzn_paths,
                min_x=min_x,
                min_z=min_z,
                world_width=world_width,
                world_depth=world_depth,
                legacy_seed=seed,
                strict=True,
            )
            save_path = core.filedialog.asksaveasfilename(
                defaultextension=".mat",
                filetypes=[("Material Map", "*.mat")],
            )
            if not save_path:
                return
            write_mat(save_path, mat_data, zones_x, zones_z)
            notes = []
            if stats.ambiguous_tiles:
                notes.append(f"{stats.ambiguous_tiles} corner patterns collapsed exactly as MakeTRN does")
            if stats.unsupported_transition_tiles:
                notes.append(
                    f"{stats.unsupported_transition_tiles} generated transitions have no matching TRN texture definition (MAT preserved)"
                )
            suffix = ("\n\nDiagnostics:\n- " + "\n- ".join(notes)) if notes else ""
            rng_note = (
                "deterministic WorldBuilder seed = 1"
                if self.make_trn_deterministic_mat.get()
                else f"legacy runtime seed = {seed} (MakeTRN srand(clock) behavior)"
            )
            core.messagebox.showinfo(
                "Success",
                f"Saved {save_path}\nMAT: {zones_x}x{zones_z} zones, {mat_data.shape[1]}x{mat_data.shape[0]} entries\n"
                f"Solids {stats.solid_tiles} | Caps {stats.cap_tiles} | Diagonals {stats.diagonal_tiles}"
                f"{extension_note}{suffix}\n\nMakeTRN-compatible core; {rng_note}.",
            )
        except Exception as exc:
            core.messagebox.showerror("Error", f"Failed: {exc}")

    def load_auto_painter_config(self):
        path = core.filedialog.askopenfilename(
            filetypes=[("MakeTRN / Terrain Config", "*.ini *.trn *.txt"), ("All Files", "*.*")]
        )
        if not path:
            return
        try:
            config = parse_trn_painter(path)
            self.paint_trn_config = config
            if config.layers:
                if core.messagebox.askyesno(
                    "Load MakeTRN Rules",
                    f"Found {len(config.layers)} [LayerN] rules. Replace existing rules?",
                ):
                    self.paint_rules = [dict(layer) for layer in config.layers]
                    self.refresh_rules_list()
            else:
                core.messagebox.showwarning(
                    "Terrain Metadata Loaded",
                    "No [LayerN] MakeTRN painter rules were found. Existing rules were kept.\n\n"
                    f"Loaded {len(config.texture_types)} TextureTypes and {len(config.transitions)} transition definitions for diagnostics.",
                )
                return
            core.messagebox.showinfo(
                "Painter Config Loaded",
                f"Rules: {len(config.layers)}\nTextureTypes: {len(config.texture_types)}\n"
                f"Directional transition definitions: {len(config.transitions)}\n\n"
                "Rule order is significant: first matching layer wins, with inclusive bounds.",
            )
        except Exception as exc:
            core.messagebox.showerror("Error", f"Failed to parse painter config: {exc}")

    def validate_rules(self):
        warnings = validate_paint_rules(self.paint_rules)
        config = getattr(self, "paint_trn_config", None)
        if config and config.texture_types:
            available = set(config.texture_types)
            for i, rule in enumerate(self.paint_rules):
                material = int(rule.get("mat_id", -1))
                if material not in available:
                    warnings.append(f"Rule {i} (Mat{material}): material is not defined by loaded TRN metadata")
        details = (
            "MakeTRN semantics: first-match-wins; all bounds inclusive; elevation compares against "
            "the minimum raw HG2 value in the local 8x8 neighborhood divided by 5; slope uses "
            "MakeTRN's maximum local edge delta and legacy angle formula."
        )
        if warnings:
            core.messagebox.showwarning("Validation Issues", details + "\n\n" + "\n".join(warnings[:12]))
        else:
            extra = f"\nTRN transition definitions available: {len(config.transitions)}" if config else ""
            core.messagebox.showinfo("Validation", details + extra)

    def auto_balance_rules(self):
        """WorldBuilder convenience feature; not part of legacy MakeTRN."""
        if not self.paint_rules:
            return
        count = len(self.paint_rules)
        chunk = PAINTER_MAX_ELEVATION / count
        for i, rule in enumerate(self.paint_rules):
            rule["min_h"] = int(i * chunk)
            rule["max_h"] = int((i + 1) * chunk)
            rule["min_s"] = 0
            rule["max_s"] = 90
        self.refresh_rules_list()
        core.messagebox.showinfo(
            "Auto-Balance (WorldBuilder Extension)",
            f"Balanced {count} rules across legacy parameter range 0-{int(PAINTER_MAX_ELEVATION)}.\n\n"
            "This is a convenience tool, not a MakeTRN operation. Elevation rules are compared to min(raw HG2)/5.",
        )

    def _stock_preset_meters(self):
        presets = {
            "Tiny (1280m)": 1280,
            "Small (2560m)": 2560,
            "Medium (5120m)": 5120,
            "Large (10240m)": 10240,
            "Huge (20480m)": 20480,
        }
        return presets.get(self.stock_size_preset.get(), 5120)

    def generate_stock_map(self):
        name = self.stock_map_name.get().strip()
        if not name:
            core.messagebox.showerror("Error", "Map Name is required.")
            return
        if not self.validate_map_name(name):
            core.messagebox.showerror("Error", "Map Name must be 1-8 alphanumeric characters.")
            return

        out_dir = core.filedialog.askdirectory(title="Select Output Folder")
        if not out_dir:
            return

        try:
            preset = self._stock_preset_meters()
            width_text = self.stock_width_override.get().strip()
            depth_text = self.stock_depth_override.get().strip()
            requested_width = int(width_text) if width_text else preset
            requested_depth = int(depth_text) if depth_text else preset
            geometry = make_stock_geometry(requested_width, requested_depth)
            empty = validate_empty_elevation(self.stock_empty_elevation.get())

            param_path = self.stock_param_path.get().strip()
            if param_path:
                parsed = parse_trn_painter(param_path)
                if not parsed.layers:
                    raise ValueError("The selected /p file contains no valid [Layer0]..[Layer7] rules.")
                rules = [dict(layer) for layer in parsed.layers]
                warnings = validate_paint_rules(rules)
                fatal = [warning for warning in warnings if "slope range" not in warning]
                if fatal:
                    raise ValueError("; ".join(fatal))
            else:
                rules = default_make_trn_rules()

            world_key = self.stock_world_type.get()
            template = self.get_stock_template_data(world_key)
            seed = 1 if self.make_trn_deterministic_mat.get() else make_trn_runtime_seed()
            cfg = StockBuildConfig(
                name=name,
                out_dir=out_dir,
                geometry=geometry,
                empty_elevation=empty,
                time_of_day=int(self.stock_time.get()),
                music_track=int(self.audio_track.get()),
                music_loop_first=int(self.audio_loop_first.get()),
                music_loop_last=int(self.audio_loop_last.get()),
                music_loop_skip=int(self.audio_loop_skip.get()),
                ambient=tuple(float(value.get()) for value in self.light_ambient),
                diffuse=tuple(float(value.get()) for value in self.light_diffuse),
                specular=tuple(float(value.get()) for value in self.light_specular),
                normal_view=template["NormalView"],
                static_trn=template["Static"],
                paint_rules=rules,
                legacy_seed=seed,
            )

            if geometry.width_meters != requested_width or geometry.depth_meters != requested_depth:
                self.log(
                    f"MakeTRN normalized requested {requested_width}x{requested_depth} m to "
                    f"{geometry.width_meters}x{geometry.depth_meters} m.",
                    "info",
                )
        except Exception as exc:
            core.messagebox.showerror("Stock Map", str(exc))
            return

        self.btn_stock_gen.config(text="GENERATING...", state="disabled")
        core.threading.Thread(target=self._generate_stock_map_worker, args=(cfg,), daemon=True).start()

    def _generate_stock_map_worker(self, cfg):
        try:
            result = build_stock_map(cfg)
            stats = result.mat_stats
            rng_mode = "seed 1" if self.make_trn_deterministic_mat.get() else f"runtime seed {cfg.legacy_seed}"
            self.log(
                f"Success: Generated {os.path.basename(result.trn_path)}, "
                f"{os.path.basename(result.hg2_path)}, and {os.path.basename(result.mat_path)}.",
                "success",
            )
            self.log(
                f"Geometry: {cfg.geometry.zones_x}x{cfg.geometry.zones_z} zones "
                f"({cfg.geometry.width_meters}x{cfg.geometry.depth_meters} m); "
                f"MAT {result.mat_width}x{result.mat_height}; "
                f"solids {stats.solid_tiles}, caps {stats.cap_tiles}, diagonals {stats.diagonal_tiles}; {rng_mode}.",
                "info",
            )
            if stats.unsupported_transition_tiles:
                self.log(
                    f"Warning: {stats.unsupported_transition_tiles} MAT transitions have no matching TRN transition texture.",
                    "warning",
                )
        except Exception as exc:
            self.log(f"Stock Gen Error: {exc}", "error")
        finally:
            self.root.after(0, lambda: self.btn_stock_gen.config(text="GENERATE MAP FILES", state="normal"))


if __name__ == "__main__":
    root = core.tk.Tk()
    app = BZ98TRNArchitect(root)
    root.mainloop()
