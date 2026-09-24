import ctypes
import json
import os
from pathlib import Path
import struct
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
import webbrowser
from PIL import Image, ImageDraw, ImageFont, ImageOps, ImageTk

APP_TITLE = "BZ98 Redux Font Generator"
STOCK_REFERENCE_SIZE = 128
ATLAS_SIZE = 1024
ATLAS_SCALE = ATLAS_SIZE // STOCK_REFERENCE_SIZE
STOCK_GLYPH_HEIGHT = 9
ASCII_ROWS = (
    "!\"#$%&'()*+,-./012345678",
    "9:;<=>?@ABCDEFGHIJKLMNOP",
    "QRSTUVWXYZ[\\]^_`abcdef",
    "ghijklmnopqrstuvwxyz{|}~",
)
STOCK_GLYPH_ROWS = (
    (0, " !\"#$%&'()*+,-./012345678", (3, 1, 3, 5, 5, 5, 5, 2, 3, 3, 5, 5, 2, 5, 1, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5)),
    (10, "9:;<=>?@ABCDEFGHIJKLMNOP", (5, 1, 1, 3, 5, 3, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 1, 5, 5, 5, 5, 5, 5, 5)),
    (20, "QRSTUVWXYZ[\\]^_`abcdef", (5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 3, 5, 3, 5, 5, 2, 5, 5, 5, 5, 5, 5)),
    (30, "ghijklmnopqrstuvwxyz{|}", (5, 5, 1, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 5, 3, 1, 3)),
    (40, "~", (5,)),
)
DEFAULT_COLORS = {
    "bg": "#0a0a0a",
    "fg": "#d4d4d4",
    "highlight": "#00ff00",
    "dark_highlight": "#004400",
    "accent": "#00ffff",
}
DEFAULT_OVERLAY_OPACITY = 40


def bundle_dir():
    """Bundled fonts live beside this module, from source and in the toolbox bundle."""
    return Path(__file__).resolve().parent


def app_dir():
    """Per-user state (profiles) lives in the toolbox data directory."""
    from bztoolbox.paths import module_data_dir

    return module_data_dir("fonts")


def resource_path(relative_path):
    return str(bundle_dir() / relative_path)


def stock_overlay_candidates():
    user_profile = Path.home()
    candidates = [
        user_profile / "Documents" / "Battlezone 98 Redux" / "BZ_ASSETS" / "common" / "textures" / "PNGS" / "bzone.png",
        Path(r"C:\GOG Games\Battlezone 98 Redux\BZ_ASSETS\common\textures\PNGS\bzone.png"),
    ]

    program_files_x86 = os.environ.get("ProgramFiles(x86)")
    if program_files_x86:
        candidates.append(
            Path(program_files_x86) / "Steam" / "steamapps" / "common" / "Battlezone 98 Redux" / "BZ_ASSETS" / "common" / "textures" / "PNGS" / "bzone.png"
        )
    return candidates


def find_default_overlay_path():
    for candidate in stock_overlay_candidates():
        if candidate.exists():
            return str(candidate)
    return None


def build_stock_glyph_layout():
    layout = {}
    for row_v, row_text, widths in STOCK_GLYPH_ROWS:
        u = 0
        for char, width in zip(row_text, widths):
            if char != " ":
                layout[char] = (
                    u * ATLAS_SCALE,
                    row_v * ATLAS_SCALE,
                    width * ATLAS_SCALE,
                    STOCK_GLYPH_HEIGHT * ATLAS_SCALE,
                )
            u += width + 1
    return layout


GLYPH_LAYOUT = build_stock_glyph_layout()

class ToolTip:
    def __init__(self, widget, text, bg="#1a1a1a", fg="#00ffff"):
        self.widget = widget
        self.text = text
        self.bg = bg
        self.fg = fg
        self.tip_window = None
        widget.bind("<Enter>", self.show_tip)
        widget.bind("<Leave>", self.hide_tip)

    def show_tip(self, event=None):
        if self.tip_window or not self.text:
            return
        x = self.widget.winfo_rootx() + 25
        y = self.widget.winfo_rooty() + 20
        self.tip_window = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        label = tk.Label(tw, text=self.text, justify='left',
                       background=self.bg, foreground=self.fg, 
                       relief='solid', borderwidth=1, font=("Consolas", "9"))
        label.pack(ipadx=1)

    def hide_tip(self, event=None):
        if self.tip_window:
            self.tip_window.destroy()
            self.tip_window = None

def draw_custom_caret(draw, x, y, w, h, color=(255, 255, 255, 255)):
    padding_x = w * 0.25
    top_y = y + (h * 0.3)
    bottom_y = y + (h * 0.6)
    left_x = x + padding_x
    right_x = x + w - padding_x
    mid_x = x + (w / 2)
    draw.line([(left_x, bottom_y), (mid_x, top_y)], fill=color, width=4)
    draw.line([(mid_x, top_y), (right_x, bottom_y)], fill=color, width=4)


def get_render_font(font_cache, font_path, font_size):
    cache_key = (font_path, font_size)
    font = font_cache.get(cache_key)
    if font is None:
        try:
            font = ImageFont.truetype(font_path, font_size)
        except (OSError, ValueError):
            font = ImageFont.load_default()
        font_cache[cache_key] = font
    return font


def generate_sheet_image(let_f, sym_f, u_v, l_v, n_v, s_v, h_nudge, f_size, center_lower, show_grid, font_cache=None):
    width, height = ATLAS_SIZE, ATLAS_SIZE
    work_layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(work_layer)

    if font_cache is None:
        font_cache = {}

    for r_idx, row_text in enumerate(ASCII_ROWS):
        for char in row_text:
            if char not in GLYPH_LAYOUT:
                continue

            x_base, y_base, target_w, target_h = GLYPH_LAYOUT[char]

            v_val = u_v if char.isupper() else l_v if char.islower() else n_v if char.isdigit() else s_v

            if show_grid:
                draw.rectangle([x_base, y_base, x_base + target_w, y_base + target_h], outline=(0, 255, 255, 120))

            if char == "^":
                draw_custom_caret(draw, x_base + h_nudge, y_base - v_val, target_w, target_h)
                continue

            font_path = let_f if char.isalpha() else sym_f
            font = get_render_font(font_cache, font_path, f_size)

            bbox = draw.textbbox((0, 0), char, font=font)
            text_w, text_h = bbox[2] - bbox[0], bbox[3] - bbox[1]
            draw_x = (x_base + (target_w - text_w) // 2 - bbox[0]) + h_nudge

            if char.islower() and not center_lower:
                draw_y = (y_base + target_h - text_h - bbox[1]) - v_val
            else:
                draw_y = (y_base + (target_h - text_h) // 2 - bbox[1]) - v_val

            draw.text((draw_x, draw_y), char, fill=(255, 255, 255, 255), font=font)

    preview_bg = Image.new("RGBA", (width, height), (0, 0, 0, 255))
    preview_bg.paste(work_layer, (0, 0), work_layer)
    return preview_bg, work_layer

def save_as_dds_native(image, filename):
    width, height = image.size
    with open(filename, 'wb') as f:
        f.write(b'DDS ')
        f.write(struct.pack('<IIIIIII', 124, 0x1 + 0x2 + 0x4 + 0x8 + 0x1000, height, width, width * 4, 0, 0))
        f.write(b'\x00' * 44) 
        f.write(struct.pack('<IIIIIIII', 32, 0x41, 0, 32, 0x000000FF, 0x0000FF00, 0x00FF0000, 0xFF000000))
        f.write(struct.pack('<IIIII', 0x1000, 0, 0, 0, 0))
        f.write(image.tobytes())

class BzoneApp:
    def __init__(self, root):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("1100x950")
        self.root.minsize(900, 700)

        self.base_dir = app_dir()
        self.profiles_dir = self.base_dir / "profiles"
        self.profiles_dir.mkdir(exist_ok=True)
        self.colors = DEFAULT_COLORS.copy()
        self.font_cache = {}
        self.overlay_image_cache = {}
        self.canvas_image_id = None
        self.last_profile_path = None
        self._queued_logs = []
        self._warning_cache = set()

        self.load_custom_fonts()

        self.let_f = resource_path("Orbitron-Bold.ttf")
        self.sym_f = resource_path("Orbitron-Bold.ttf")
        self.u_v, self.l_v, self.n_v, self.s_v = tk.IntVar(value=0), tk.IntVar(value=5), tk.IntVar(value=0), tk.IntVar(value=0)
        self.h_n = tk.IntVar(value=0)
        self.f_size = tk.IntVar(value=55)
        self.center_lower = tk.BooleanVar(value=False)
        self.show_grid = tk.BooleanVar(value=False)
        self.overlay_enabled = tk.BooleanVar(value=False)
        self.overlay_opacity = tk.IntVar(value=DEFAULT_OVERLAY_OPACITY)
        self.letter_font_var = tk.StringVar()
        self.symbol_font_var = tk.StringVar()
        self.profile_var = tk.StringVar(value="Profile: none")
        self.overlay_var = tk.StringVar(value="Overlay: none")
        self.overlay_path = find_default_overlay_path()

        self.setup_styles()
        self.setup_ui()
        self.root.configure(bg=self.colors["bg"])
        self.refresh_status_labels()
        self.flush_queued_logs()
        if self.overlay_path:
            self.log(f"Detected stock overlay atlas: {Path(self.overlay_path).name}")
        self.log("Application Initialized.")

    def load_custom_fonts(self):
        self.current_font = "Segoe UI"
        font_path = resource_path("BZONE.ttf")
        if os.path.exists(font_path) and sys.platform == "win32":
            try:
                if ctypes.windll.gdi32.AddFontResourceExW(font_path, 0x10, 0) > 0:
                    self.current_font = "BZONE"
                    self.log("Loaded bundled BZONE.ttf for UI.")
            except OSError as exc:
                self.log(f"UI font load skipped: {exc}")

    def setup_styles(self):
        style = ttk.Style()
        style.theme_use('default')
        c = self.colors
        main_font = (self.current_font, 10)
        bold_font = (self.current_font, 11, "bold")
        
        style.configure(".", background=c["bg"], foreground=c["fg"], font=main_font)
        style.configure("TFrame", background=c["bg"])
        style.configure("TLabelframe", background=c["bg"], bordercolor=c["highlight"])
        style.configure("TLabelframe.Label", background=c["bg"], foreground=c["highlight"], font=bold_font)
        style.configure("TLabel", background=c["bg"], foreground=c["fg"])
        style.configure("TButton", background="#1a1a1a", foreground=c["fg"])
        style.map("TButton", background=[("active", c["dark_highlight"])], foreground=[("active", c["highlight"])])
        style.configure("Success.TButton", foreground=c["highlight"], font=bold_font)
        style.configure("TCheckbutton", background=c["bg"], foreground=c["fg"])
        style.map("TCheckbutton", background=[("active", c["bg"])])

    def setup_ui(self):
        main = ttk.Frame(self.root, padding=10)
        main.pack(fill="both", expand=True)

        header = ttk.Frame(main)
        header.pack(fill="x", pady=(0, 20))
        h_label = tk.Label(header, text="FONT GENERATOR", font=(self.current_font, 24, "bold"), 
                         background=self.colors["bg"], foreground=self.colors["highlight"])
        h_label.pack(side="left")

        content = ttk.Frame(main)
        content.pack(fill="both", expand=True)

        left = ttk.Frame(content, width=350)
        left.pack(side="left", fill="y", padx=(0, 10))

        prof_frame = ttk.LabelFrame(left, text=" PROFILE ", padding=10)
        prof_frame.pack(fill="x", pady=(0, 10))
        ttk.Button(prof_frame, text="LOAD PROFILE", command=self.load_profile).pack(side="left", fill="x", expand=True, padx=2)
        ttk.Button(prof_frame, text="SAVE PROFILE", command=self.save_profile).pack(side="left", fill="x", expand=True, padx=2)
        tk.Label(prof_frame, textvariable=self.profile_var, anchor="w", background=self.colors["bg"], foreground=self.colors["accent"]).pack(fill="x", pady=(8, 0))

        sel_frame = ttk.LabelFrame(left, text=" FONT SELECTION ", padding=10)
        sel_frame.pack(fill="x", pady=(0, 10))
        b1 = ttk.Button(sel_frame, text="CHOOSE LETTER FONT", command=self.set_let)
        b1.pack(fill="x")
        ToolTip(b1, "Select the TTF/OTF font for Alpha characters.")
        tk.Label(sel_frame, textvariable=self.letter_font_var, wraplength=300, justify="left", anchor="w",
                 background=self.colors["bg"], foreground=self.colors["accent"]).pack(fill="x", pady=(4, 0))

        b2 = ttk.Button(sel_frame, text="CHOOSE SYMBOL FONT", command=self.set_sym)
        b2.pack(fill="x", pady=5)
        ToolTip(b2, "Select the TTF/OTF font for Symbols and Numbers.")
        tk.Label(sel_frame, textvariable=self.symbol_font_var, wraplength=300, justify="left", anchor="w",
                 background=self.colors["bg"], foreground=self.colors["accent"]).pack(fill="x")

        set_frame = ttk.LabelFrame(left, text=" FONT SETTINGS ", padding=10)
        set_frame.pack(fill="x")
        ttk.Label(set_frame, text="Global Font Size").pack()
        s_size = tk.Scale(set_frame, from_=30, to=70, orient="horizontal", variable=self.f_size, 
                         bg=self.colors["bg"], fg=self.colors["fg"], highlightthickness=0,
                         command=lambda x: self.update_preview())
        s_size.pack(fill="x")

        nudge_frame = ttk.LabelFrame(left, text=" VERTICAL NUDGES ", padding=10)
        nudge_frame.pack(fill="x", pady=10)
        for lbl, var in [("Uppercase", self.u_v), ("Lowercase", self.l_v), ("Numbers", self.n_v), ("Symbols", self.s_v)]:
            ttk.Label(nudge_frame, text=lbl).pack()
            tk.Scale(nudge_frame, from_=-30, to=30, orient="horizontal", variable=var, 
                    bg=self.colors["bg"], fg=self.colors["fg"], highlightthickness=0,
                    command=lambda x: self.update_preview()).pack(fill="x")

        preset_frame = ttk.Frame(nudge_frame)
        preset_frame.pack(fill="x", pady=5)
        ttk.Label(preset_frame, text="Presets:").pack(side="left")
        p1 = ttk.Button(preset_frame, text="Reset", width=6, command=lambda: self.apply_preset(0, 0, 0, 0))
        p1.pack(side="left", padx=2)
        p2 = ttk.Button(preset_frame, text="Abt-Up", width=6, command=lambda: self.apply_preset(-5, -5, -5, -5))
        p2.pack(side="left", padx=2)
        p3 = ttk.Button(preset_frame, text="Abt-Dn", width=6, command=lambda: self.apply_preset(5, 5, 5, 5))
        p3.pack(side="left", padx=2)

        align_frame = ttk.LabelFrame(left, text=" ALIGNMENT & VIEW ", padding=10)
        align_frame.pack(fill="x")
        ttk.Label(align_frame, text="Horizontal Shift").pack()
        tk.Scale(align_frame, from_=-20, to=20, orient="horizontal", variable=self.h_n, 
                bg=self.colors["bg"], fg=self.colors["fg"], highlightthickness=0,
                command=lambda x: self.update_preview()).pack(fill="x")
        ttk.Checkbutton(align_frame, text="Force Center Lowercase", variable=self.center_lower, command=self.update_preview).pack(anchor="w")
        ttk.Checkbutton(align_frame, text="Show Layout Grid", variable=self.show_grid, command=self.update_preview).pack(anchor="w")

        overlay_frame = ttk.LabelFrame(left, text=" STOCK OVERLAY ", padding=10)
        overlay_frame.pack(fill="x", pady=(10, 0))
        ttk.Checkbutton(overlay_frame, text="Show Stock Compare Overlay", variable=self.overlay_enabled, command=self.update_preview).pack(anchor="w")
        ttk.Label(overlay_frame, text="Overlay Opacity").pack()
        tk.Scale(overlay_frame, from_=0, to=100, orient="horizontal", variable=self.overlay_opacity,
                bg=self.colors["bg"], fg=self.colors["fg"], highlightthickness=0,
                command=lambda x: self.update_preview()).pack(fill="x")
        ttk.Button(overlay_frame, text="AUTO-DETECT OVERLAY", command=self.auto_detect_overlay).pack(fill="x", pady=(4, 0))
        ttk.Button(overlay_frame, text="CHOOSE OVERLAY IMAGE", command=self.set_overlay_path).pack(fill="x", pady=(4, 0))
        tk.Label(overlay_frame, textvariable=self.overlay_var, wraplength=300, justify="left", anchor="w",
                 background=self.colors["bg"], foreground=self.colors["accent"]).pack(fill="x", pady=(6, 0))

        exp_btn = ttk.Button(left, text="EXPORT DDS", style="Success.TButton", command=self.export_dds)
        exp_btn.pack(fill="x", pady=20, ipady=10)

        ttk.Button(left, text="About", command=self.show_about).pack(side="bottom", fill="x")

        right = ttk.Frame(content)
        right.pack(side="right", fill="both", expand=True)

        canvas_container = tk.Frame(right, bg="#000")
        canvas_container.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(canvas_container, bg="black", width=512, height=512, highlightthickness=1, highlightbackground=self.colors["dark_highlight"])
        self.canvas.place(relx=0.5, rely=0.5, anchor="center")

        self.log_box = tk.Text(right, height=10, state="disabled", bg="#050505", fg=self.colors["fg"], font=("Consolas", 9))
        self.log_box.pack(fill="x", side="bottom", pady=(10, 0))

        self.update_preview()

    def log(self, msg):
        if not hasattr(self, "log_box"):
            self._queued_logs.append(msg)
            return
        self.log_box.config(state="normal")
        self.log_box.insert("end", f"> {msg}\n")
        self.log_box.see("end")
        self.log_box.config(state="disabled")

    def flush_queued_logs(self):
        queued = self._queued_logs
        self._queued_logs = []
        for msg in queued:
            self.log(msg)

    def warn_once(self, msg):
        if msg in self._warning_cache:
            return
        self._warning_cache.add(msg)
        self.log(msg)

    def refresh_status_labels(self):
        self.letter_font_var.set(f"Letters: {Path(self.let_f).name}")
        self.symbol_font_var.set(f"Symbols: {Path(self.sym_f).name}")
        profile_name = Path(self.last_profile_path).name if self.last_profile_path else "none"
        self.profile_var.set(f"Profile: {profile_name}")
        overlay_name = Path(self.overlay_path).name if self.overlay_path else "none"
        self.overlay_var.set(f"Overlay: {overlay_name}")

    def get_effective_font_path(self, font_path, role_name):
        if font_path and os.path.exists(font_path):
            return font_path

        fallback = resource_path("Orbitron-Bold.ttf")
        missing_name = font_path if font_path else "<unset>"
        self.warn_once(f"{role_name} font not found: {missing_name}. Using Orbitron-Bold.ttf.")
        return fallback

    def get_overlay_image(self):
        if not self.overlay_path:
            self.warn_once("Stock overlay is enabled but no overlay image is selected.")
            return None
        if not os.path.exists(self.overlay_path):
            self.warn_once(f"Overlay image not found: {self.overlay_path}")
            return None

        image = self.overlay_image_cache.get(self.overlay_path)
        if image is None:
            try:
                with Image.open(self.overlay_path) as raw_image:
                    image = raw_image.convert("RGBA")
                self.overlay_image_cache[self.overlay_path] = image
            except OSError as exc:
                self.warn_once(f"Failed to load overlay image: {exc}")
                return None
        return image

    def build_overlay_preview(self, generated_layer):
        overlay_image = self.get_overlay_image()
        if overlay_image is None:
            return None

        if overlay_image.size != (ATLAS_SIZE, ATLAS_SIZE):
            overlay_image = overlay_image.resize((ATLAS_SIZE, ATLAS_SIZE), Image.Resampling.NEAREST)

        compare_image = Image.new("RGBA", (ATLAS_SIZE, ATLAS_SIZE), (0, 0, 0, 255))
        generated_alpha = generated_layer.getchannel("A")
        compare_image.paste((0, 255, 255, 255), (0, 0), generated_alpha)

        stock_alpha = overlay_image.getchannel("A")
        alpha_min, alpha_max = stock_alpha.getextrema()
        if alpha_max > 0 and alpha_min < alpha_max:
            stock_mask = stock_alpha
        else:
            stock_mask = ImageOps.grayscale(overlay_image)
        opacity_scale = max(0, min(self.overlay_opacity.get(), 100)) / 100.0
        stock_mask = stock_mask.point(lambda px: int(px * opacity_scale))
        compare_image.paste((255, 80, 80, 255), (0, 0), stock_mask)
        return compare_image

    def apply_preset(self, u, l, n, s):
        self.u_v.set(u)
        self.l_v.set(l)
        self.n_v.set(n)
        self.s_v.set(s)
        self.update_preview()
        self.log(f"Applied preset: {u}, {l}, {n}, {s}")

    def save_profile(self):
        f = filedialog.asksaveasfilename(initialdir=str(self.profiles_dir), defaultextension=".json", filetypes=[("Profile", "*.json")])
        if not f:
            return
        data = {
            "u_v": self.u_v.get(), "l_v": self.l_v.get(), "n_v": self.n_v.get(), "s_v": self.s_v.get(),
            "h_n": self.h_n.get(), "f_size": self.f_size.get(),
            "center_lower": self.center_lower.get(),
            "let_f": self.let_f, "sym_f": self.sym_f
        }
        try:
            with open(f, 'w', encoding="utf-8") as outfile:
                json.dump(data, outfile, indent=4)
            self.last_profile_path = f
            self.refresh_status_labels()
            self.log(f"Profile saved: {os.path.basename(f)}")
        except OSError as e:
            messagebox.showerror("Error", f"Failed to save profile: {e}")

    def load_profile(self):
        f = filedialog.askopenfilename(initialdir=str(self.profiles_dir), filetypes=[("Profile", "*.json")])
        if not f:
            return
        try:
            with open(f, 'r', encoding="utf-8") as infile:
                data = json.load(infile)
                self.u_v.set(data.get("u_v", 0))
                self.l_v.set(data.get("l_v", 5))
                self.n_v.set(data.get("n_v", 0))
                self.s_v.set(data.get("s_v", 0))
                self.h_n.set(data.get("h_n", 0))
                self.f_size.set(data.get("f_size", 55))
                self.center_lower.set(data.get("center_lower", False))
                self.let_f = data.get("let_f", self.let_f)
                self.sym_f = data.get("sym_f", self.sym_f)
            self.last_profile_path = f
            self.refresh_status_labels()
            self.update_preview()
            self.log(f"Profile loaded: {os.path.basename(f)}")
        except (OSError, json.JSONDecodeError) as e:
            messagebox.showerror("Error", f"Failed to load profile: {e}")

    def show_about(self):
        about = tk.Toplevel(self.root)
        about.title("About BZFont Generator")
        about.geometry("450x450")
        about.configure(bg=self.colors["bg"])
        container = tk.Frame(about, padx=20, pady=20, bg=self.colors["bg"])
        container.pack()
        tk.Label(container, text="Battlezone 98 Redux Font Generator", font=(self.current_font, 12, "bold"), bg=self.colors["bg"], fg=self.colors["highlight"]).pack()
        tk.Label(container, text="Credits: GrizzlyOne95", font=(self.current_font, 10, "italic"), bg=self.colors["bg"], fg=self.colors["fg"]).pack(pady=(0, 10))
        tk.Label(container, text="Exports native 32-bit uncompressed DDS files.", wraplength=400, justify="left", bg=self.colors["bg"], fg=self.colors["fg"]).pack()
        link = tk.Label(container, text="\nGitHub Repository", fg=self.colors["accent"], cursor="hand2", font=(self.current_font, 10, "underline"), bg=self.colors["bg"])
        link.pack()
        link.bind("<Button-1>", lambda e: webbrowser.open("https://github.com/GrizzlyOne95/Battlezone98ReduxFontGenerator"))
        ttk.Button(container, text="Close", command=about.destroy).pack(pady=20)

    def auto_detect_overlay(self):
        detected = find_default_overlay_path()
        if detected:
            self.overlay_path = detected
            self.refresh_status_labels()
            self.update_preview()
            self.log(f"Detected stock overlay atlas: {os.path.basename(detected)}")
        else:
            self.log("No stock overlay atlas detected in common Battlezone install paths.")

    def set_overlay_path(self):
        selected = filedialog.askopenfilename(
            title="Choose stock overlay atlas",
            filetypes=[("Images", "*.png *.dds *.tga"), ("All files", "*.*")],
        )
        if selected:
            self.overlay_path = selected
            self.refresh_status_labels()
            self.update_preview()
            self.log(f"Overlay image updated: {os.path.basename(selected)}")

    def update_preview(self):
        let_font = self.get_effective_font_path(self.let_f, "Letter")
        sym_font = self.get_effective_font_path(self.sym_f, "Symbol")
        final_img, generated_layer = generate_sheet_image(let_font, sym_font, self.u_v.get(), self.l_v.get(),
                                                          self.n_v.get(), self.s_v.get(), self.h_n.get(),
                                                          self.f_size.get(),
                                                          self.center_lower.get(), self.show_grid.get(), self.font_cache)
        if self.overlay_enabled.get():
            overlay_preview = self.build_overlay_preview(generated_layer)
            if overlay_preview is not None:
                final_img = overlay_preview
        prev = final_img.resize((512, 512), Image.Resampling.LANCZOS)
        self.tk_img = ImageTk.PhotoImage(prev)
        if self.canvas_image_id is None:
            self.canvas_image_id = self.canvas.create_image(0, 0, anchor="nw", image=self.tk_img)
        else:
            self.canvas.itemconfigure(self.canvas_image_id, image=self.tk_img)

    def export_dds(self):
        let_font = self.get_effective_font_path(self.let_f, "Letter")
        sym_font = self.get_effective_font_path(self.sym_f, "Symbol")
        _, export_img = generate_sheet_image(let_font, sym_font, self.u_v.get(), self.l_v.get(),
                                             self.n_v.get(), self.s_v.get(), self.h_n.get(),
                                             self.f_size.get(),
                                             self.center_lower.get(), False, self.font_cache)
        f_path = filedialog.asksaveasfilename(defaultextension=".dds", initialfile="bzfont.dds", filetypes=[("DDS", "*.dds")])
        if f_path:
            try:
                save_as_dds_native(export_img, f_path)
                self.log(f"Exported DDS: {os.path.basename(f_path)}")
                messagebox.showinfo("Success", "DDS exported successfully!")
            except Exception as e:
                self.log(f"Export Error: {e}")
                messagebox.showerror("Export Error", f"Failed: {e}")

    def set_let(self):
        f = filedialog.askopenfilename(filetypes=[("Fonts", "*.ttf *.otf")])
        if f:
            self.let_f = f
            self.refresh_status_labels()
            self.update_preview()
            self.log(f"Letter Font updated: {os.path.basename(f)}")

    def set_sym(self):
        f = filedialog.askopenfilename(filetypes=[("Fonts", "*.ttf *.otf")])
        if f:
            self.sym_f = f
            self.refresh_status_labels()
            self.update_preview()
            self.log(f"Symbol Font updated: {os.path.basename(f)}")

if __name__ == "__main__":
    root = tk.Tk()
    app = BzoneApp(root)
    root.mainloop()
