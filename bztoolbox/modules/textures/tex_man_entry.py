"""Texture Manager entrypoint with the MakeMAP compatibility layer integrated."""
from __future__ import annotations

import os
import threading
from pathlib import Path

from PIL import Image

from bztoolbox.modules.textures import tex_man as legacy
from bztoolbox.modules.textures.makemap_compat import (
    MapFormat,
    MakeMapOptions,
    _expand_inputs,
    apply_preprocess,
    convert_file,
    encode_map_bytes,
    load_map,
    read_palette,
)


tk = legacy.tk
ttk = legacy.ttk
filedialog = legacy.filedialog
messagebox = legacy.messagebox


def _active_palette(app):
    override = app.custom_pal_path.get() if hasattr(app, "custom_pal_path") else ""
    if override and os.path.exists(override) and override.lower().endswith(".act"):
        return read_palette(override)
    return [tuple(c) for c in app.palette]


def _apply_simple_scale(app, image: Image.Image) -> Image.Image:
    scale_val = app.map_scale_var.get()
    if scale_val != "No Scaling":
        new_size = int(scale_val.split("x")[0])
        image = image.resize((new_size, new_size), Image.Resampling.LANCZOS)
    return image


def process_map_file_compat(app, path, output_folder=None):
    """Drop-in replacement for the legacy MAP tab using the verified codec."""
    base_name = os.path.basename(path)
    file_no_ext = os.path.splitext(base_name)[0]
    dest_dir = output_folder if (output_folder and os.path.isdir(output_folder)) else os.path.dirname(path)
    palette = _active_palette(app)

    if path.lower().endswith(".map"):
        image = _apply_simple_scale(app, load_map(path, palette))
        out = os.path.join(dest_dir, file_no_ext + ".png")
        image.save(out)
        return f"Exported: {file_no_ext}.png"

    image = _apply_simple_scale(app, Image.open(path).convert("RGBA"))
    opts = MakeMapOptions(map_format=MapFormat.ARGB8888, palette=palette)
    out = os.path.join(dest_dir, file_no_ext + ".map")
    Path(out).write_bytes(encode_map_bytes(image, opts))
    return f"Packed: {file_no_ext}.map (A8R8G8B8)"


class MakeMapDialog:
    FORMAT_LABELS = {
        "Indexed / palette (type 0)": MapFormat.INDEXED,
        "A4R4G4B4 (type 1)": MapFormat.ARGB4444,
        "R5G6B5 (type 2)": MapFormat.RGB565,
        "A8R8G8B8 (type 3)": MapFormat.ARGB8888,
        "X8R8G8B8 (type 4)": MapFormat.XRGB8888,
    }

    def __init__(self, app):
        self.app = app
        self.win = tk.Toplevel(app.root)
        try:
            legacy.apply_window_icon(self.win, app.base_dir, app.resource_dir)
        except Exception:
            pass
        self.win.title("Advanced MakeMAP Compatibility")
        self.win.geometry("900x790")
        self.win.minsize(820, 700)

        outer = ttk.Frame(self.win, padding=12)
        outer.pack(fill="both", expand=True)

        source = ttk.LabelFrame(outer, text=" Input / Output ", padding=10)
        source.pack(fill="x", pady=(0, 8))
        self.input_var = tk.StringVar()
        ttk.Label(source, text="Input file, wildcard, or folder:").grid(row=0, column=0, sticky="w")
        ttk.Entry(source, textvariable=self.input_var, width=65).grid(row=0, column=1, padx=6, sticky="ew")
        ttk.Button(source, text="File...", command=self.pick_file).grid(row=0, column=2, padx=2)
        ttk.Button(source, text="Folder...", command=self.pick_folder).grid(row=0, column=3, padx=2)
        source.columnconfigure(1, weight=1)

        self.output_var = tk.StringVar(value="MAP")
        self.format_var = tk.StringVar(value="A8R8G8B8 (type 3)")
        ttk.Label(source, text="Output:").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Combobox(source, textvariable=self.output_var, values=["MAP", "BMP", "TGA"], state="readonly", width=12).grid(row=1, column=1, sticky="w", padx=6, pady=(8, 0))
        ttk.Label(source, text="Target pixel format:").grid(row=2, column=0, sticky="w", pady=(6, 0))
        ttk.Combobox(source, textvariable=self.format_var, values=list(self.FORMAT_LABELS), state="readonly", width=30).grid(row=2, column=1, sticky="w", padx=6, pady=(6, 0))

        self.palette_var = tk.StringVar()
        ttk.Label(source, text="Palette override:").grid(row=3, column=0, sticky="w", pady=(6, 0))
        ttk.Entry(source, textvariable=self.palette_var).grid(row=3, column=1, padx=6, pady=(6, 0), sticky="ew")
        ttk.Button(source, text="ACT...", command=self.pick_palette).grid(row=3, column=2, padx=2, pady=(6, 0))
        ttk.Label(source, text="Blank = current ACT workspace palette").grid(row=3, column=3, sticky="w", pady=(6, 0))

        transforms = ttk.LabelFrame(outer, text=" MakeMAP Transforms ", padding=10)
        transforms.pack(fill="x", pady=8)
        self.recover_var = tk.BooleanVar(value=False)
        self.undopma_var = tk.BooleanVar(value=False)
        self.flipx_var = tk.BooleanVar(value=False)
        self.flipy_var = tk.BooleanVar(value=False)
        self.colorize_var = tk.BooleanVar(value=False)
        self.chromakey_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(transforms, text="Recover alpha", variable=self.recover_var).grid(row=0, column=0, sticky="w", padx=4)
        ttk.Checkbutton(transforms, text="Undo premultiplied alpha", variable=self.undopma_var).grid(row=0, column=1, sticky="w", padx=4)
        ttk.Checkbutton(transforms, text="Flip X", variable=self.flipx_var).grid(row=0, column=2, sticky="w", padx=4)
        ttk.Checkbutton(transforms, text="Flip Y", variable=self.flipy_var).grid(row=0, column=3, sticky="w", padx=4)
        ttk.Checkbutton(transforms, text="Enable colorize curves", variable=self.colorize_var).grid(row=1, column=0, sticky="w", padx=4, pady=(6, 0))

        self.desat_var = tk.StringVar(value="0")
        self.diff_var = tk.StringVar(value="0")
        self.transindex_var = tk.StringVar(value="-1")
        ttk.Label(transforms, text="Desaturate %:").grid(row=1, column=1, sticky="e", pady=(6, 0))
        ttk.Entry(transforms, textvariable=self.desat_var, width=8).grid(row=1, column=2, sticky="w", pady=(6, 0))
        ttk.Label(transforms, text="Diffusion %:").grid(row=2, column=1, sticky="e", pady=(6, 0))
        ttk.Entry(transforms, textvariable=self.diff_var, width=8).grid(row=2, column=2, sticky="w", pady=(6, 0))
        ttk.Label(transforms, text="Transparent index (-1 off):").grid(row=2, column=0, sticky="e", pady=(6, 0))
        ttk.Entry(transforms, textvariable=self.transindex_var, width=8).grid(row=2, column=1, sticky="w", padx=(4, 0), pady=(6, 0))

        ttk.Checkbutton(transforms, text="Chroma key", variable=self.chromakey_var).grid(row=3, column=0, sticky="w", padx=4, pady=(6, 0))
        self.key_r = tk.StringVar(value="255"); self.key_g = tk.StringVar(value="0"); self.key_b = tk.StringVar(value="255")
        key_frame = ttk.Frame(transforms)
        key_frame.grid(row=3, column=1, columnspan=3, sticky="w", pady=(6, 0))
        for label, var in (("R", self.key_r), ("G", self.key_g), ("B", self.key_b)):
            ttk.Label(key_frame, text=label).pack(side="left", padx=(3, 1))
            ttk.Entry(key_frame, textvariable=var, width=5).pack(side="left")

        self.remap_var = tk.StringVar()
        ttk.Label(transforms, text="Remap image:").grid(row=4, column=0, sticky="e", pady=(6, 0))
        ttk.Entry(transforms, textvariable=self.remap_var, width=50).grid(row=4, column=1, columnspan=2, sticky="ew", padx=4, pady=(6, 0))
        ttk.Button(transforms, text="Browse...", command=self.pick_remap).grid(row=4, column=3, sticky="w", pady=(6, 0))

        curves = ttk.LabelFrame(outer, text=" Per-channel colorization (-pow / -mul / -add) ", padding=10)
        curves.pack(fill="x", pady=8)
        ttk.Label(curves, text="Channel").grid(row=0, column=0, padx=5)
        ttk.Label(curves, text="Power").grid(row=0, column=1, padx=5)
        ttk.Label(curves, text="Multiply").grid(row=0, column=2, padx=5)
        ttk.Label(curves, text="Add").grid(row=0, column=3, padx=5)
        self.pow_vars = []; self.mul_vars = []; self.add_vars = []
        for row, channel in enumerate("RGBA", start=1):
            p = tk.StringVar(value="1"); m = tk.StringVar(value="255"); a = tk.StringVar(value="0")
            self.pow_vars.append(p); self.mul_vars.append(m); self.add_vars.append(a)
            ttk.Label(curves, text=channel).grid(row=row, column=0, padx=5, pady=2)
            ttk.Entry(curves, textvariable=p, width=12).grid(row=row, column=1, padx=5, pady=2)
            ttk.Entry(curves, textvariable=m, width=12).grid(row=row, column=2, padx=5, pady=2)
            ttk.Entry(curves, textvariable=a, width=12).grid(row=row, column=3, padx=5, pady=2)

        actions = ttk.Frame(outer)
        actions.pack(fill="x", pady=(8, 4))
        self.convert_btn = ttk.Button(actions, text="CONVERT", style="Success.TButton", command=self.start_convert)
        self.convert_btn.pack(side="left")
        ttk.Label(actions, text="Outputs are written beside each source, matching original MakeMAP behavior.").pack(side="left", padx=12)

        self.log = tk.Text(outer, height=9, bg="#050505", fg=legacy.BZ_FG, font=("Consolas", 9))
        self.log.pack(fill="both", expand=True, pady=(4, 0))

    def pick_file(self):
        path = filedialog.askopenfilename(title="MakeMAP input")
        if path: self.input_var.set(path)

    def pick_folder(self):
        path = filedialog.askdirectory(title="MakeMAP input folder")
        if path: self.input_var.set(path)

    def pick_palette(self):
        path = filedialog.askopenfilename(filetypes=[("ACT / raw RGB palette", "*.act;*.pal"), ("All files", "*.*")])
        if path: self.palette_var.set(path)

    def pick_remap(self):
        path = filedialog.askopenfilename(filetypes=[("Image", "*.png;*.tga;*.bmp;*.jpg;*.jpeg"), ("All files", "*.*")])
        if path: self.remap_var.set(path)

    def _number(self, var, name, integer=False):
        try:
            return int(var.get()) if integer else float(var.get())
        except ValueError:
            raise ValueError(f"Invalid {name}: {var.get()!r}")

    def build_options(self):
        palette_path = self.palette_var.get().strip()
        palette = read_palette(palette_path) if palette_path else _active_palette(self.app)
        remap_path = self.remap_var.get().strip()
        remap = Image.open(remap_path).convert("RGBA") if remap_path else None
        chroma = None
        if self.chromakey_var.get():
            chroma = (
                self._number(self.key_r, "chroma R", True),
                self._number(self.key_g, "chroma G", True),
                self._number(self.key_b, "chroma B", True),
            )
            if any(v < 0 or v > 255 for v in chroma):
                raise ValueError("Chroma-key channels must be 0..255")
        return MakeMapOptions(
            output_mode=self.output_var.get().lower(),
            map_format=self.FORMAT_LABELS[self.format_var.get()],
            palette=palette,
            recover_alpha=self.recover_var.get(),
            chroma_key=chroma,
            transparent_index=self._number(self.transindex_var, "transparent index", True),
            undo_pma=self.undopma_var.get(),
            remap=remap,
            colorize_enabled=self.colorize_var.get(),
            desaturate_percent=self._number(self.desat_var, "desaturation"),
            powers=tuple(self._number(v, "power") for v in self.pow_vars),
            multipliers=tuple(self._number(v, "multiplier") for v in self.mul_vars),
            additions=tuple(self._number(v, "addition") for v in self.add_vars),
            flip_x=self.flipx_var.get(),
            flip_y=self.flipy_var.get(),
            diffusion_percent=self._number(self.diff_var, "diffusion"),
        )

    def write_log(self, text):
        self.log.insert("end", text + "\n")
        self.log.see("end")

    def start_convert(self):
        source = self.input_var.get().strip()
        if not source:
            messagebox.showerror("MakeMAP", "Choose an input file, wildcard, or folder.", parent=self.win)
            return
        try:
            opts = self.build_options()
            inputs = _expand_inputs([source])
            if not inputs:
                raise ValueError("No matching input files")
        except Exception as exc:
            messagebox.showerror("MakeMAP", str(exc), parent=self.win)
            return
        self.convert_btn.configure(state="disabled")
        self.write_log(f"Processing {len(inputs)} input(s)...")

        def worker():
            ok = 0; failed = 0
            for path in inputs:
                try:
                    out = convert_file(path, opts)
                    ok += 1
                    self.win.after(0, lambda p=path, o=out: self.write_log(f"{p} -> {o}"))
                except Exception as exc:
                    failed += 1
                    self.win.after(0, lambda p=path, e=exc: self.write_log(f"ERROR {p}: {e}"))
            self.win.after(0, lambda: self.finish_convert(ok, failed))

        threading.Thread(target=worker, daemon=True).start()

    def finish_convert(self, ok, failed):
        self.convert_btn.configure(state="normal")
        self.write_log(f"Complete: {ok} converted, {failed} failed.")


def install_makemap_integration():
    legacy.BZReduxSuite.process_map_file = process_map_file_compat
    original_setup = legacy.BZReduxSuite.setup_map_tab

    def setup_map_tab_with_advanced(app):
        original_setup(app)
        frame = ttk.LabelFrame(app.tab_map, text=" MakeMAP Compatibility ", padding=8)
        frame.pack(fill="x", padx=20, pady=5, before=app.map_log)
        ttk.Label(
            frame,
            text="Full type 0-4 codec, alpha/chroma tools, remap/color curves, flips and MakeMAP error diffusion.",
        ).pack(side="left", padx=(0, 10))
        ttk.Button(
            frame,
            text="Advanced MakeMAP...",
            style="Success.TButton",
            command=lambda: MakeMapDialog(app),
        ).pack(side="right")

    legacy.BZReduxSuite.setup_map_tab = setup_map_tab_with_advanced


def main():
    install_makemap_integration()
    root = legacy.TkinterDnD.Tk() if legacy.HAS_DND else tk.Tk()
    legacy.BZReduxSuite(root)
    root.mainloop()


if __name__ == "__main__":
    main()
