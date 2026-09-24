import os, struct, math, sys, subprocess, ctypes, json
import tkinter as tk
from tkinter import filedialog, messagebox, colorchooser, ttk
from PIL import Image, ImageTk
import imageio.v3 as iio
import numpy as np
import threading
from ctypes import Structure, c_uint32, c_int, c_uint, c_ubyte

try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    HAS_DND = True
except ImportError:
    HAS_DND = False


def _dnd_ready(widget):
    """Drag & drop needs a tkdnd-enabled root (TkinterDnD.Tk), not just the package."""
    if not HAS_DND:
        return False
    try:
        widget.tk.call("package", "present", "tkdnd")
        return True
    except tk.TclError:
        return False

from battlezone.terrain import lgt as lgt_codec
from battlezone.terrain.trn import TRNDocument
from bztoolbox.modules.textures import bcpack
from bztoolbox.modules.textures import uiscan
from bztoolbox.modules.textures import recompress

class DXTBZ2Header(Structure):
    _fields_ = [
        ("m_Sig", c_int), ("m_DXTLevel", c_int),
        ("m_1x1Red", c_ubyte), ("m_1x1Green", c_ubyte),
        ("m_1x1Blue", c_ubyte), ("m_1x1Alpha", c_ubyte),
        ("m_NumMips", c_int), ("m_BaseHeight", c_int), ("m_BaseWidth", c_int)
    ]

# --- BZ98 ENGINE CONSTANTS ---
ZONE_RES = 256  # Redux Standard (256x256 per zone)

# --- BATTLEZONE HUD COLORS ---
BZ_BG = "#0a0a0a"
BZ_FG = "#d4d4d4"
BZ_GREEN = "#00ff00"
BZ_DARK_GREEN = "#004400"
BZ_CYAN = "#00ffff"

from bztoolbox.paths import module_data_dir
from bztoolbox.app.fonts import bz_font

CONFIG_FILE = str(module_data_dir("textures") / "tex_man_config.json")
APP_USER_MODEL_ID = "GrizzlyOne95.Battlezone98Redux.TextureManager"


def _set_app_user_model_id():
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except Exception:
        pass


def _resolve_bundled_icon(base_dir, resource_dir, name):
    candidates = [
        os.path.join(resource_dir, "branding", name),
        os.path.join(resource_dir, name),
        os.path.join(base_dir, "branding", name),
        os.path.join(base_dir, name),
    ]
    here = os.path.dirname(os.path.abspath(__file__))
    candidates.append(os.path.join(os.path.dirname(here), "branding", name))
    candidates.append(os.path.join(os.path.dirname(here), name))
    candidates.append(os.path.join(here, "branding", name))
    for path in candidates:
        if os.path.exists(path):
            return path
    return None


def apply_window_icon(window, base_dir, resource_dir):
    """Apply the canonical app icon to a Tk/Toplevel window."""
    try:
        ico_path = _resolve_bundled_icon(base_dir, resource_dir, "app_icon.ico") or _resolve_bundled_icon(base_dir, resource_dir, "bzrtex.ico")
        if ico_path:
            try:
                window.iconbitmap(ico_path)
            except Exception:
                pass
        png_path = _resolve_bundled_icon(base_dir, resource_dir, "app_icon.png")
        if png_path:
            try:
                image = tk.PhotoImage(file=png_path)
                window.iconphoto(True, image)
                window._battlezone_app_icon = image
            except Exception:
                pass
    except Exception:
        pass


_set_app_user_model_id()

class BZMapFormat:
    INDEXED, ARGB4444, RGB565, ARGB8888, XRGB8888 = 0, 1, 2, 3, 4
    bpp = [1, 2, 2, 4, 4]

# Full 256-color Moon.act data extracted from BZ98R Toolkit
BUILTIN_MOON_PALETTE = [
    (0, 0, 0), (17, 16, 16), (26, 24, 24), (31, 26, 25), (36, 35, 31), (50, 42, 36),
    (52, 49, 48), (60, 56, 56), (68, 64, 64), (77, 72, 72), (85, 80, 80), (84, 79, 76),
    (112, 108, 104), (116, 129, 125), (133, 138, 133), (178, 174, 174), (191, 188, 188),
    (204, 201, 201), (217, 215, 215), (229, 228, 228), (255, 255, 255), (20, 3, 2),
    (40, 6, 3), (59, 10, 5), (79, 13, 6), (99, 16, 8), (107, 0, 8), (148, 8, 0),
    (140, 33, 8), (148, 16, 0), (156, 24, 0), (173, 57, 0), (189, 82, 8), (206, 99, 16),
    (200, 94, 11), (214, 101, 0), (214, 132, 33), (222, 123, 24), (231, 140, 33),
    (231, 156, 41), (239, 173, 57), (222, 156, 49), (222, 165, 57), (222, 165, 74),
    (231, 173, 99), (239, 189, 90), (247, 198, 82), (239, 206, 115), (249, 249, 149),
    (235, 230, 97), (183, 180, 81), (169, 133, 50), (131, 124, 45), (123, 99, 39),
    (149, 101, 17), (87, 59, 2), (80, 67, 28), (78, 48, 3), (53, 40, 12), (36, 24, 5),
    (171, 72, 69), (169, 168, 158), (153, 150, 139), (249, 249, 195), (223, 216, 188),
    (200, 189, 151), (194, 186, 139), (186, 172, 145), (167, 164, 145), (160, 151, 127),
    (175, 168, 134), (160, 145, 106), (157, 145, 109), (136, 130, 107), (132, 125, 80),
    (116, 104, 81), (96, 94, 83), (84, 73, 55), (115, 72, 1), (106, 81, 30),
    (109, 118, 109), (93, 106, 102), (79, 96, 90), (68, 91, 86), (63, 76, 73),
    (62, 63, 57), (48, 70, 67), (46, 61, 56), (37, 59, 54), (34, 50, 45), (31, 42, 41),
    (24, 36, 32), (19, 23, 21), (16, 14, 14), (15, 10, 6), (7, 11, 9), (181, 191, 204),
    (150, 156, 172), (139, 149, 164), (134, 143, 156), (125, 134, 150), (120, 130, 143),
    (115, 124, 139), (112, 129, 150), (111, 120, 135), (107, 116, 131), (106, 124, 145),
    (101, 117, 141), (100, 111, 128), (100, 108, 123), (96, 108, 123), (96, 104, 120),
    (95, 112, 135), (92, 104, 119), (92, 100, 116), (91, 108, 131), (88, 100, 115),
    (88, 96, 112), (85, 104, 127), (84, 96, 111), (84, 92, 108), (83, 100, 123),
    (80, 96, 119), (80, 92, 108), (80, 88, 104), (76, 96, 119), (76, 92, 116),
    (76, 92, 110), (76, 84, 100), (75, 88, 103), (74, 88, 108), (72, 92, 115),
    (72, 88, 112), (72, 84, 104), (72, 84, 99), (72, 80, 95), (68, 88, 112),
    (68, 84, 108), (68, 80, 100), (68, 76, 92), (67, 84, 102), (67, 80, 95),
    (64, 84, 108), (64, 80, 104), (64, 76, 96), (64, 72, 87), (63, 80, 100),
    (63, 76, 91), (60, 80, 104), (60, 76, 104), (60, 76, 100), (60, 72, 92),
    (60, 68, 83), (59, 76, 96), (59, 72, 87), (56, 76, 100), (56, 72, 100),
    (56, 72, 96), (56, 64, 79), (55, 72, 92), (55, 68, 83), (53, 68, 88),
    (52, 72, 96), (52, 68, 96), (52, 68, 92), (52, 64, 88), (52, 60, 75),
    (51, 64, 79), (49, 64, 84), (48, 68, 92), (48, 64, 92), (48, 60, 84),
    (47, 64, 88), (47, 60, 75), (47, 56, 72), (46, 56, 68), (45, 60, 88),
    (45, 60, 80), (44, 56, 79), (44, 52, 68), (44, 51, 64), (43, 60, 84),
    (40, 56, 80), (40, 56, 76), (40, 52, 76), (40, 48, 64), (40, 48, 60),
    (40, 44, 60), (36, 52, 72), (36, 51, 76), (36, 48, 72), (36, 40, 56),
    (35, 44, 60), (33, 41, 56), (31, 38, 53), (28, 36, 49), (26, 33, 45),
    (24, 30, 41), (22, 27, 38), (20, 24, 34), (17, 22, 30), (15, 19, 26),
    (13, 16, 23), (11, 13, 19), (9, 10, 15), (6, 8, 11), (4, 5, 8), (2, 2, 4),
    (0, 0, 0), (0, 0, 0), (0, 0, 0), (0, 0, 0), (0, 0, 0), (0, 0, 0), (0, 0, 0),
    (0, 0, 0), (0, 0, 0), (0, 0, 0), (0, 0, 0), (0, 0, 0), (0, 0, 0), (0, 0, 0),
    (0, 0, 0), (0, 0, 0), (0, 255, 255), (0, 127, 127), (0, 63, 63),
    (78, 194, 242), (14, 153, 240), (7, 109, 222), (12, 149, 203), (6, 102, 171),
    (6, 93, 136), (3, 56, 124), (26, 35, 80), (0, 127, 255), (0, 99, 199),
    (0, 70, 141), (0, 34, 69), (0, 21, 42), (0, 255, 0), (0, 127, 0), (0, 63, 0),
    (0, 31, 0), (0, 15, 0), (255, 0, 0), (127, 0, 0), (63, 0, 0), (31, 0, 0),
    (15, 0, 0), (255, 255, 0), (164, 164, 0), (127, 127, 0), (80, 80, 0),
    (64, 64, 0), (255, 0, 255)
]
class ToolTip:
    def __init__(self, widget, text):
        self.widget = widget
        self.text = text
        self.tip_window = None
        widget.bind("<Enter>", self.show_tip)
        widget.bind("<Leave>", self.hide_tip)

    def show_tip(self, event=None):
        x = self.widget.winfo_rootx() + 25
        y = self.widget.winfo_rooty() + 20
        self.tip_window = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f"+{x}+{y}")
        label = tk.Label(tw, text=self.text, justify='left',
                       background="#1a1a1a", foreground=BZ_CYAN, 
                       relief='solid', borderwidth=1, font=("Consolas", "9"))
        label.pack(ipadx=1)

    def hide_tip(self, event=None):
        if self.tip_window:
            self.tip_window.destroy()
            self.tip_window = None
    
class BZReduxSuite:
    def __init__(self, root):
        self.root = root
        self.root.title("Battlezone Texture Manager")
        self.root.geometry("1150x900")
        self.root.configure(bg=BZ_BG)
        
        # --- RESOURCES ---
        # Toolbox layout: bundled resources beside this module, per-user
        # state in the toolbox data directory.
        self.resource_dir = os.path.dirname(os.path.abspath(__file__))
        self.base_dir = str(module_data_dir("textures"))
            
        self.custom_font_name = bz_font("Consolas")
            
        apply_window_icon(self.root, self.base_dir, self.resource_dir)

        self.setup_styles()
        
        self.config = self.load_config()
        # Load the Moon Palette as default
        self.palette = [list(c) for c in BUILTIN_MOON_PALETTE]
        self.pal_buttons = []
        self.selected_index = None
        
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(padx=10, pady=10, fill="both", expand=True)
        
        self.tab_act = ttk.Frame(self.notebook)
        self.tab_tex = ttk.Frame(self.notebook)
        self.tab_map = ttk.Frame(self.notebook)
        self.tab_lgt = ttk.Frame(self.notebook)
        self.tab_dxt = ttk.Frame(self.notebook)
        self.tab_pack = ttk.Frame(self.notebook)
        
        self.notebook.add(self.tab_act, text="ACT Palette Editor")
        self.notebook.add(self.tab_tex, text="Texture Manager")
        self.notebook.add(self.tab_map, text="MAP Converter")
        self.notebook.add(self.tab_lgt, text="LGT Converter")
        self.notebook.add(self.tab_dxt, text="DXTBZ2 Converter")
        self.notebook.add(self.tab_pack, text="Channel Packer")
        
        # New Generation Variables
        self.gen_emissive = tk.BooleanVar(value=self.config.get("gen_emissive", False))
        self.emissive_thresh = tk.IntVar(value=self.config.get("emissive_thresh", 200))
        self.gen_specular = tk.BooleanVar(value=self.config.get("gen_specular", False))
        self.spec_contrast = tk.DoubleVar(value=self.config.get("spec_contrast", 1.5))
        self.gen_normal = tk.BooleanVar(value=self.config.get("gen_normal", False))
        self.norm_strength = tk.DoubleVar(value=self.config.get("norm_strength", 2.0))
        self.norm_flip_y = tk.BooleanVar(value=self.config.get("norm_flip_y", False))
        
        # Existing Logic Variables
        self.tex_scale_cutoff = tk.StringVar(value=self.config.get("tex_scale_cutoff", "Disabled"))
        self.tex_auto_alpha = tk.BooleanVar(value=self.config.get("tex_auto_alpha", True))
        self.tex_batch_out = tk.StringVar(value=self.config.get("tex_batch_out", "[Same as Source]"))
        self.tex_from_ext = tk.StringVar(value=self.config.get("tex_from_ext", "all supported"))
        
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        self.setup_act_tab()
        self.setup_texture_tab()
        self.setup_map_tab()
        self.setup_lgt_tab()
        self.setup_dxt_tab()
        self.setup_pack_tab()

    def load_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r') as f: return json.load(f)
            except: pass
        return {}

    def save_config(self):
        cfg = {
            "gen_emissive": self.gen_emissive.get(),
            "emissive_thresh": self.emissive_thresh.get(),
            "gen_specular": self.gen_specular.get(),
            "spec_contrast": self.spec_contrast.get(),
            "gen_normal": self.gen_normal.get(),
            "norm_strength": self.norm_strength.get(),
            "norm_flip_y": self.norm_flip_y.get(),
            "tex_scale_cutoff": self.tex_scale_cutoff.get(),
            "tex_auto_alpha": self.tex_auto_alpha.get(),
            "tex_batch_out": self.tex_batch_out.get(),
            "tex_from_ext": self.tex_from_ext.get()
        }
        try:
            with open(CONFIG_FILE, 'w') as f: json.dump(cfg, f, indent=4)
        except: pass

    def on_close(self):
        self.save_config()
        self.root.destroy()

    def setup_styles(self):
        style = ttk.Style()
        style.theme_use('default')
        main_font = (self.custom_font_name, 10)
        bold_font = (self.custom_font_name, 11, "bold")

        # --- GLOBAL STYLES ---
        style.configure(".", background=BZ_BG, foreground=BZ_FG, font=main_font, bordercolor=BZ_DARK_GREEN)
        style.configure("TFrame", background=BZ_BG)
        style.configure("TNotebook", background=BZ_BG, borderwidth=0)
        style.configure("TNotebook.Tab", background="#1a1a1a", foreground=BZ_FG, padding=[10, 2])
        style.map("TNotebook.Tab", background=[("selected", BZ_DARK_GREEN)], foreground=[("selected", BZ_GREEN)])
        style.configure("TLabelframe", background=BZ_BG, bordercolor=BZ_GREEN)
        style.configure("TLabelframe.Label", background=BZ_BG, foreground=BZ_GREEN, font=bold_font)
        style.configure("TLabel", background=BZ_BG, foreground=BZ_FG)
        style.configure("TEntry", fieldbackground="#1a1a1a", foreground=BZ_CYAN, insertcolor=BZ_GREEN)
        style.configure("TButton", background="#1a1a1a", foreground=BZ_FG)
        style.map("TButton", background=[("active", BZ_DARK_GREEN)], foreground=[("active", BZ_GREEN)])
        style.configure("Success.TButton", foreground=BZ_GREEN, font=bold_font)
        style.configure("Action.TButton", foreground=BZ_CYAN, font=bold_font)
        style.configure("TCheckbutton", background=BZ_BG, foreground=BZ_FG, indicatorcolor=BZ_BG, indicatoron=True)
        style.map("TCheckbutton", indicatorcolor=[("selected", BZ_GREEN)])
        style.configure("TCombobox", fieldbackground="#1a1a1a", foreground=BZ_CYAN, arrowcolor=BZ_GREEN)
        style.map("TCombobox", fieldbackground=[("readonly", "#1a1a1a")], foreground=[("readonly", BZ_CYAN)])

    def log_msg(self, textbox, message):
        textbox.insert("end", f"> {message}\n")
        textbox.see("end")

# --- ACT PALETTE EDITOR ---
    def setup_act_tab(self):
        ttk.Label(self.tab_act, text="Battlezone 98 Palette Editor (.ACT)", font=(self.custom_font_name, 16, "bold"), foreground=BZ_GREEN).pack(pady=10)
        
        main_f = ttk.Frame(self.tab_act)
        main_f.pack(pady=10, padx=20, fill="both", expand=True)
        
        # 1. Left: The 16x16 Grid
        grid_f = ttk.Frame(main_f)
        grid_f.pack(side="left", padx=20, pady=20)
        
        self.pal_buttons = []
        for i in range(256):
            r, g, b = self.palette[i]
            # Using standard tk.Button for background color support
            btn = tk.Button(grid_f, text="", width=2, height=1, 
                                bg=f"#{r:02x}{g:02x}{b:02x}",
                                relief="flat",
                                command=lambda x=i: self.select_palette_color(x))
            btn.grid(row=i // 16, column=i % 16, padx=1, pady=1)
            self.pal_buttons.append(btn)
        
        # 2. Middle: Quick Jump Shortcuts (Fixed width/height arguments)
        jump_f = ttk.Frame(main_f, width=140)
        jump_f.pack(side="left", padx=10, fill="y", pady=20)
        ttk.Label(jump_f, text="Quick Jump", font=(self.custom_font_name, 12, "bold")).pack(pady=10)
        
        # Using tk.Button for specific colors
        tk.Button(jump_f, text="Index 209\n(Fog)", bg="#5d6d7e", fg="white", width=12, height=3,
                      command=lambda: self.jump_to_index(209)).pack(pady=5, padx=10)
        
        tk.Button(jump_f, text="Index 223\n(Sky/Scope)", bg="#d4ac0d", fg="black", width=12, height=3,
                      command=lambda: self.jump_to_index(223)).pack(pady=5, padx=10)
        
        ttk.Label(jump_f, text="Ranges:", font=(self.custom_font_name, 10, "italic")).pack(pady=(20, 0))
        
        # Fixed these two buttons specifically:
        ttk.Button(jump_f, text="Terrain (96)", width=15, 
                      command=lambda: self.jump_to_index(96)).pack(pady=2)
        ttk.Button(jump_f, text="Objects (0)", width=15, 
                      command=lambda: self.jump_to_index(0)).pack(pady=2)
        
        # 3. Right: Edit Controls
        ctrl_f = ttk.Frame(main_f)
        ctrl_f.pack(side="right", padx=20, fill="y", expand=True)
        
        self.sel_idx_var = tk.StringVar(value="Select a Color")
        self.sel_label = ttk.Label(ctrl_f, textvariable=self.sel_idx_var, font=(self.custom_font_name, 14, "bold"))
        self.sel_label.pack(pady=10)
        
        self.bz_info_var = tk.StringVar(value="")
        ttk.Label(ctrl_f, textvariable=self.bz_info_var, foreground="#e67e22", wraplength=200).pack()
        
        # RGB Sliders
        self.r_val = self.create_color_slider(ctrl_f, "Red", self.update_color_from_sliders)
        self.g_val = self.create_color_slider(ctrl_f, "Green", self.update_color_from_sliders)
        self.b_val = self.create_color_slider(ctrl_f, "Blue", self.update_color_from_sliders)
        
        # Hex Input
        ttk.Label(ctrl_f, text="Hex Code:").pack(pady=(10,0))
        self.hex_var = tk.StringVar()
        self.hex_entry = ttk.Entry(ctrl_f, textvariable=self.hex_var)
        self.hex_entry.pack(pady=5)
        ttk.Button(ctrl_f, text="Apply Hex", command=self.apply_hex).pack(pady=5)
        
        # File Actions
        ttk.Button(ctrl_f, text="LOAD .ACT", style="Success.TButton", command=self.load_act).pack(fill="x", pady=10)
        ttk.Button(ctrl_f, text="SAVE .ACT", style="Action.TButton", command=self.save_act).pack(fill="x")
        ttk.Button(ctrl_f, text="Import from Image", command=self.import_palette_from_image).pack(fill="x", pady=10)

    def jump_to_index(self, idx):
        """Logic to handle the quick jump buttons without crashing"""
        self.select_palette_color(idx)

    def select_palette_color(self, idx):
        """Updates UI based on selected palette index"""
        self.selected_index = idx
        r, g, b = self.palette[idx]
        
        # Map BZ ranges and specific indices
        if idx == 209:
            info = "INDEX 209: GLOBAL FOG COLOR\n(Horizon transition color)"
            hint = "#95a5a6"
        elif idx == 223:
            info = "INDEX 223: SKY & SNIPERSCOPE\n(Clear-color and lens tint)"
            hint = "#f1c40f"
        elif 0 <= idx <= 95:
            info = f"INDEX {idx}: Objects (Primary)\n(Unit and building textures)"
            hint = "#3498db"
        elif 96 <= idx <= 222:
            info = f"INDEX {idx}: Planet-Specific\n(Terrain and rock smoothing)"
            hint = "#2ecc71"
        elif 224 <= idx <= 255:
            info = f"INDEX {idx}: Objects (Secondary)\n(Extended object range)"
            hint = "#e67e22"
        else:
            info = f"INDEX {idx}: Standard"
            hint = "#ffffff"
        
        self.sel_idx_var.set(f"Index: {idx}")
        self.bz_info_var.set(info)
        self.sel_label.configure(foreground=hint)
        
        # Update sliders and Hex entry
        self.r_val.set(r)
        self.g_val.set(g)
        self.b_val.set(b)
        self.hex_var.set(f"#{r:02x}{g:02x}{b:02x}")
        
        # Visual feedback: Reset all borders, then highlight the selected one
        for i, btn in enumerate(self.pal_buttons):
            if i == idx:
                btn.configure(relief="solid", bd=4)
            else:
                btn.configure(relief="flat", bd=1)

    def update_color_from_sliders(self, _=None):
        if self.selected_index is None: return
        r, g, b = int(self.r_val.get()), int(self.g_val.get()), int(self.b_val.get())
        self.palette[self.selected_index] = [r, g, b]
        hex_code = f"#{r:02x}{g:02x}{b:02x}"
        self.pal_buttons[self.selected_index].configure(bg=hex_code)
        self.hex_var.set(hex_code)
        if hasattr(self, 'update_pal_preview'): self.update_pal_preview()

    def apply_hex(self):
        if self.selected_index is None: return
        hex_val = self.hex_var.get().lstrip('#')
        try:
            r, g, b = tuple(int(hex_val[i:i+2], 16) for i in (0, 2, 4))
            self.r_val.set(r); self.g_val.set(g); self.b_val.set(b)
            self.update_color_from_sliders()
        except: pass

    def load_act(self):
        path = filedialog.askopenfilename(filetypes=[("ACT Palette", "*.act")])
        if not path: return
        try:
            with open(path, 'rb') as f:
                raw = f.read(768)
                self.palette = [list(struct.unpack('<3B', raw[i:i+3])) for i in range(0, 768, 3)]
            for i, btn in enumerate(self.pal_buttons):
                r, g, b = self.palette[i]
                btn.configure(bg=f"#{r:02x}{g:02x}{b:02x}")
            if hasattr(self, 'update_pal_preview'): self.update_pal_preview()
        except Exception as e: print(f"Load Error: {e}")

    def save_act(self):
        path = filedialog.asksaveasfilename(defaultextension=".act", filetypes=[("ACT Palette", "*.act")])
        if not path: return
        try:
            with open(path, 'wb') as f:
                for color in self.palette:
                    f.write(struct.pack('<3B', *color))
        except Exception as e: print(f"Save Error: {e}")

    def import_palette_from_image(self):
        path = filedialog.askopenfilename(filetypes=[("Image", "*.png;*.bmp;*.gif;*.tif")])
        if not path: return
        try:
            img = Image.open(path)
            pal_data = []
            if img.mode == 'P':
                raw_pal = img.getpalette()
                # Chunk into RGB triplets
                pal_data = [raw_pal[i:i+3] for i in range(0, min(len(raw_pal), 768), 3)]
            else:
                q_img = img.quantize(colors=256)
                raw_pal = q_img.getpalette()
                pal_data = [raw_pal[i:i+3] for i in range(0, min(len(raw_pal), 768), 3)]
            
            # Pad if necessary
            while len(pal_data) < 256: pal_data.append([0,0,0])
            
            self.palette = pal_data[:256]
            for i, btn in enumerate(self.pal_buttons):
                r, g, b = self.palette[i]
                btn.configure(bg=f"#{r:02x}{g:02x}{b:02x}")
            if hasattr(self, 'update_pal_preview'): self.update_pal_preview()
            messagebox.showinfo("Success", "Palette imported from image.")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to import palette: {e}")

    def create_color_slider(self, parent, label, cmd):
        ttk.Label(parent, text=label).pack()
        s = tk.Scale(parent, from_=0, to=255, orient="horizontal", command=cmd,
                     bg=BZ_BG, fg=BZ_FG, troughcolor="#1a1a1a", activebackground=BZ_GREEN, highlightthickness=0)
        s.pack(pady=2, fill="x")
        return s

# --- MAP CONVERTER ---
    def setup_map_tab(self):
        ttk.Label(self.tab_map, text=".MAP Texture Serializer", font=(self.custom_font_name, 16, "bold"), foreground=BZ_GREEN).pack(pady=10)
        
        # 1. Palette Preview Section
        preview_frame = ttk.Frame(self.tab_map)
        preview_frame.pack(pady=5, padx=20, fill="x")
        ttk.Label(preview_frame, text="Active Palette Preview (0-255):").pack(pady=2)
        
        self.pal_canvas = tk.Canvas(preview_frame, height=30, bg="black", highlightthickness=0)
        self.pal_canvas.pack(fill="x", padx=10, pady=5)
        self.update_pal_preview() 
        
        # 2. Options Frame (Batch Folder & Scaling)
        opts = ttk.Frame(self.tab_map)
        opts.pack(pady=10, padx=20, fill="x")
        
        # Output Path
        self.batch_out_path = tk.StringVar(value="[Same as Source]")
        ttk.Label(opts, text="Batch Output Folder:").grid(row=0, column=0, padx=10, pady=5, sticky="w")
        ttk.Entry(opts, textvariable=self.batch_out_path, width=50).grid(row=0, column=1, padx=5, pady=5)
        ttk.Button(opts, text="Browse", width=10, command=self.set_batch_out).grid(row=0, column=2, padx=5)
        
        # Scaling Option
        ttk.Label(opts, text="Rescale (Batch/Single):").grid(row=1, column=0, padx=10, pady=5, sticky="w")
        self.map_scale_var = tk.StringVar(value="No Scaling")
        ttk.Combobox(opts, textvariable=self.map_scale_var, values=["No Scaling", "128x128", "256x256", "512x512", "1024x1024"], state="readonly").grid(row=1, column=1, padx=5, sticky="w")
        
        # 3. Palette Override Section (Restored)
        pal_opt = ttk.Frame(self.tab_map)
        pal_opt.pack(pady=5, padx=20, fill="x")
        
        self.custom_pal_path = tk.StringVar(value="[Built-in Workspace Palette]")
        ttk.Label(pal_opt, text="Palette Override:").pack(side="left", padx=10)
        ttk.Entry(pal_opt, textvariable=self.custom_pal_path, width=40).pack(side="left", padx=5)
        ttk.Button(pal_opt, text="Load .ACT", style="Success.TButton", command=self.ui_load_override_pal).pack(side="left", padx=5)
        ttk.Button(pal_opt, text="Reset", command=self.reset_map_palette).pack(side="left", padx=5)
        
        # 4. Actions Frame
        f = ttk.Frame(self.tab_map)
        f.pack(pady=10, padx=20, fill="x")
        
        ttk.Button(f, text="+ Single File (MAP/PNG)", style="Action.TButton", command=self.ui_single_map).pack(side="left", padx=10, expand=True, fill="x")
        ttk.Button(f, text="+ Batch Folder", style="Action.TButton", command=self.ui_batch_map).pack(side="left", padx=10, expand=True, fill="x")
        
        self.map_log = tk.Text(self.tab_map, height=15, bg="#050505", fg=BZ_FG, font=("Consolas", 9))
        self.map_log.pack(padx=20, pady=10, fill="both")

    def update_pal_preview(self, custom_palette=None):
        """Redraws the color strip. Uses workspace palette unless custom_palette is passed."""
        self.pal_canvas.delete("all")
        target_pal = custom_palette if custom_palette else self.palette
        width = 1100 
        color_w = width / 256
        for i in range(256):
            r, g, b = target_pal[i]
            color_hex = f"#{r:02x}{g:02x}{b:02x}"
            self.pal_canvas.create_rectangle(i*color_w, 0, (i+1)*color_w, 30, fill=color_hex, outline="")

    def ui_load_override_pal(self):
        path = filedialog.askopenfilename(filetypes=[("ACT Palette", "*.act")])
        if path:
            self.custom_pal_path.set(path)
            with open(path, 'rb') as f:
                raw = f.read(768)
                temp_pal = [list(struct.unpack('<3B', raw[i:i+3])) for i in range(0, 768, 3)]
                self.update_pal_preview(temp_pal)

    def reset_map_palette(self):
        self.custom_pal_path.set("[Built-in Workspace Palette]")
        self.update_pal_preview() # Reverts to main workspace palette

    def set_batch_out(self):
        folder = filedialog.askdirectory()
        if folder:
            self.batch_out_path.set(folder)

    def process_map_file(self, path, output_folder=None):
        base_name = os.path.basename(path)
        file_no_ext = os.path.splitext(base_name)[0]
        dest_dir = output_folder if (output_folder and os.path.isdir(output_folder)) else os.path.dirname(path)

        # 1. Determine active palette
        active_pal = self.palette
        override_path = self.custom_pal_path.get()
        if os.path.exists(override_path) and override_path.lower().endswith(".act"):
            with open(override_path, 'rb') as f:
                raw = f.read(768)
                active_pal = [list(struct.unpack('<3B', raw[i:i+3])) for i in range(0, 768, 3)]

        if path.lower().endswith(".map"):
            with open(path, 'rb') as f:
                rb, fmt, h, _ = struct.unpack('<4H', f.read(8))
                w = rb // BZMapFormat.bpp[fmt]
                data = f.read()

                if fmt == BZMapFormat.INDEXED:
                    img = Image.frombytes('L', (w, h), data)
                    flat_pal = [v for c in active_pal for v in c]
                    img.putpalette(flat_pal)
                    img = img.convert("RGBA")
                else:
                    img = Image.frombytes('RGBA', (w, h), data, 'raw', 'BGRA')
                
                # Apply Scaling
                scale_val = self.map_scale_var.get()
                if scale_val != "No Scaling":
                    new_size = int(scale_val.split('x')[0])
                    img = img.resize((new_size, new_size), Image.Resampling.LANCZOS)
                
                img.save(os.path.join(dest_dir, file_no_ext + ".png"))
                return f"Exported: {file_no_ext}.png"
        else:
            # PNG -> MAP
            img = Image.open(path).convert("RGBA")
            
            # Apply Scaling
            scale_val = self.map_scale_var.get()
            if scale_val != "No Scaling":
                new_size = int(scale_val.split('x')[0])
                img = img.resize((new_size, new_size), Image.Resampling.LANCZOS)

            b, g, r, a = img.split()
            bgra = Image.merge('RGBA', (b, g, r, a))
            with open(os.path.join(dest_dir, file_no_ext + ".map"), 'wb') as f:
                f.write(struct.pack('<4H', img.width * 4, 3, img.height, 0))
                f.write(bgra.tobytes())
            return f"Packed: {file_no_ext}.map"

    def ui_single_map(self):
        path = filedialog.askopenfilename(filetypes=[("MAP or PNG", "*.map;*.png")])
        if not path: return
        try:
            msg = self.process_map_file(path)
            self.log_msg(self.map_log, msg)
        except Exception as e: self.log_msg(self.map_log, f"ERROR: {e}")

    def ui_batch_map(self):
        src_folder = filedialog.askdirectory(title="Select Source Folder")
        if not src_folder: return
        
        out_dir = self.batch_out_path.get()
        if out_dir == "[Same as Source]": out_dir = None
        
        count = 0
        for file in os.listdir(src_folder):
            if file.lower().endswith((".map", ".png")):
                try:
                    self.process_map_file(os.path.join(src_folder, file), out_dir)
                    count += 1
                except Exception as e:
                    self.log_msg(self.map_log, f"Skip {file}: {e}")
        self.log_msg(self.map_log, f"BATCH COMPLETE: {count} files processed.")

# --- LGT CONVERTER (BZRLGT REFERENCE-COMPATIBLE) ---
    def setup_lgt_tab(self):
        ttk.Label(self.tab_lgt, text="Terrain Lightmap (.LGT) Manager", font=(self.custom_font_name, 16, "bold"), foreground=BZ_GREEN).pack(pady=10)
        
        # Controls Frame
        ctrl = ttk.Frame(self.tab_lgt)
        ctrl.pack(pady=10, padx=20, fill="x")
        
        ttk.Label(ctrl, text="Map Width (Zones):").grid(row=0, column=0, padx=5)
        self.lgt_width_var = tk.StringVar(value="0") # 0 = Auto-Square
        ttk.Entry(ctrl, textvariable=self.lgt_width_var, width=10).grid(row=0, column=1, padx=5)
        ttk.Label(ctrl, text="(Leave 0 for square maps)").grid(row=0, column=2, padx=5)

        btn_f = ttk.Frame(self.tab_lgt)
        btn_f.pack(pady=10)
        ttk.Button(btn_f, text="+ LGT to PNG (Extract)", style="Action.TButton", command=self.lgt_to_png).pack(side="left", padx=10)
        ttk.Button(btn_f, text="+ PNG to LGT (Pack)", style="Action.TButton", command=self.png_to_lgt).pack(side="left", padx=10)

        self.lgt_log = tk.Text(self.tab_lgt, height=20, bg="#050505", fg=BZ_FG, font=("Consolas", 9))
        self.lgt_log.pack(padx=20, pady=10, fill="both")

    def parse_trn_dimensions(self):
        path = filedialog.askopenfilename(filetypes=[("Terrain File", "*.trn")])
        if not path: return
        try:
            width = TRNDocument.read(path).size.width
            if width:
                world_width = int(width)
                # Redux zones are 1280 units wide
                zones_wide = world_width // 1280
                self.lgt_width_var.set(str(zones_wide))
                self.log_msg(self.lgt_log, f"TRN Parsed: World Width {world_width} = {zones_wide} Zones Wide.")
        except Exception as e:
            self.log_msg(self.lgt_log, f"TRN Error: {e}")

    def lgt_to_png(self):
        path = filedialog.askopenfilename(filetypes=[("Lightmap", "*.lgt")])
        if not path: return
        try:
            chunk_size = ZONE_RES * ZONE_RES
            file_size = os.path.getsize(path)
            if file_size % chunk_size != 0:
                raise Exception(f"Invalid LGT size: {file_size} bytes is not a multiple of {chunk_size}.")
            map_chunks = file_size // chunk_size - 1
            if map_chunks <= 0:
                raise Exception("File too small to contain the leading special chunk and map data.")

            gw = int(self.lgt_width_var.get())
            if gw <= 0:
                gw = math.isqrt(map_chunks)
                if gw * gw != map_chunks:
                    raise Exception(f"LGT has {map_chunks} map chunks and is not square; specify Map Width (Zones).")
            if map_chunks % gw != 0:
                raise Exception(f"{map_chunks} map chunks cannot form a grid {gw} zones wide.")
            gh = map_chunks // gw

            # battlezone.terrain.lgt reads the bordered Redux layout (the
            # leading 65,536-byte chunk is the border, not image data).
            lightmap, _, _, _ = lgt_codec.read_lgt(path, gw, gh, zone_size=ZONE_RES)
            out = os.path.splitext(path)[0] + ".png"
            Image.fromarray(lgt_codec.lgt_to_image(lightmap), mode="L").save(out)
            self.log_msg(self.lgt_log, f"Exported {gw}x{gh} zones from BZR LGT.")
        except Exception as e: self.log_msg(self.lgt_log, f"ERROR: {e}")

    def png_to_lgt(self):
        path = filedialog.askopenfilename(filetypes=[("PNG", "*.png")])
        if not path: return
        try:
            img = Image.open(path).convert('L')
            if img.width <= 0 or img.height <= 0:
                raise Exception("Image dimensions must be positive.")
            if img.width % ZONE_RES != 0 or img.height % ZONE_RES != 0:
                raise Exception(f"LGT images must be multiples of {ZONE_RES} pixels; got {img.width}x{img.height}.")

            gw, gh = img.width // ZONE_RES, img.height // ZONE_RES
            out = os.path.splitext(path)[0] + ".lgt"
            # Critical BzrLgt behavior: the leading special chunk is filled from
            # the UNFLIPPED (north-up) image's top-left pixel.
            lgt_codec.write_lgt(out, lgt_codec.image_to_lgt(np.asarray(img)), gw, gh,
                                border=img.getpixel((0, 0)))
            self.log_msg(self.lgt_log, f"Packed {gw*gh} zones into BzrLgt-compatible .LGT.")
        except Exception as e: self.log_msg(self.lgt_log, f"ERROR: {e}")

    def setup_texture_tab(self):
        ttk.Label(self.tab_tex, text="Advanced Texture Processor", font=(self.custom_font_name, 16, "bold"), foreground=BZ_GREEN).pack(pady=10)
        
        # Main container to split controls and log
        main_content = ttk.Frame(self.tab_tex)
        main_content.pack(fill="both", expand=True, padx=10, pady=5)
        
        # Left Column: Format & File Settings
        left_col = ttk.Frame(main_content)
        left_col.pack(side="left", fill="both", expand=True, padx=5, pady=5)
        
        # 0. Source Selection (Single File)
        src_f = ttk.LabelFrame(left_col, text=" Single File Source ", padding=10)
        src_f.pack(fill="x", padx=5, pady=5)
        
        self.tex_single_path = tk.StringVar()
        self.tex_single_entry = ttk.Entry(src_f, textvariable=self.tex_single_path)
        self.tex_single_entry.pack(side="left", fill="x", expand=True, padx=(0, 5))
        ttk.Button(src_f, text="Browse", width=8, command=self.browse_single_tex).pack(side="left")
        
        if _dnd_ready(self.root):
            self.tex_single_entry.drop_target_register(DND_FILES)
            self.tex_single_entry.dnd_bind('<<Drop>>', self.on_tex_drop)
        
        # 1. Format Options
        fmt_f = ttk.LabelFrame(left_col, text=" Format Settings ", padding=10)
        fmt_f.pack(fill="x", padx=5, pady=5)
        
        self.tex_to_ext = tk.StringVar(value=self.config.get("tex_to_ext", ".dds"))
        self.tex_to_ext.trace_add("write", self.update_tex_ui_state)
        ttk.Label(fmt_f, text="Output Format:").grid(row=0, column=0, padx=5, sticky="w")
        ttk.Combobox(fmt_f, textvariable=self.tex_to_ext, values=[".dds", ".png", ".tga"], state="readonly", width=10).grid(row=0, column=1, padx=5, pady=5)
        
        ttk.Label(fmt_f, text="Compression:").grid(row=1, column=0, padx=5, sticky="w")
        self.tex_compress = tk.StringVar(value="Auto")
        self.tex_compress_combo = ttk.Combobox(fmt_f, textvariable=self.tex_compress, values=["Auto", "DXT1", "DXT5", "None"], state="readonly", width=10)
        self.tex_compress_combo.grid(row=1, column=1, padx=5, pady=2)
        
        self.tex_mips = tk.BooleanVar(value=self.config.get("tex_mips", True))
        self.tex_mips_chk = ttk.Checkbutton(fmt_f, text="Gen Mipmaps", variable=self.tex_mips)
        self.tex_mips_chk.grid(row=2, column=0, columnspan=2, padx=5, pady=2, sticky="w")
        
        # Add to setup_texture_tab under Format Settings
        ttk.Label(fmt_f, text="Rescale if > :").grid(row=3, column=0, padx=5, pady=5, sticky="w")
        # self.tex_scale_cutoff loaded in init
        ttk.Combobox(fmt_f, textvariable=self.tex_scale_cutoff, 
                          values=["Disabled", "512", "1024", "2048", "4096"], state="readonly", width=10).grid(row=3, column=1, padx=5, pady=5)
        
        # FIX: Moved Overwrite into the format frame using grid to match its siblings
        self.tex_overwrite = tk.BooleanVar(value=self.config.get("tex_overwrite", False)) 
        ttk.Checkbutton(fmt_f, text="Overwrite Existing", variable=self.tex_overwrite).grid(row=4, column=0, columnspan=2, padx=5, pady=5, sticky="w")
        
        # --- Advanced Map Generation Section ---
        gen_f = ttk.LabelFrame(left_col, text=" Map Generation ", padding=10)
        gen_f.pack(pady=5, padx=5, fill="x")
        
        # Emissive Row
        e_f = ttk.Frame(gen_f)
        e_f.pack(fill="x", padx=10, pady=2)
        ttk.Checkbutton(e_f, text="Create Emissive", variable=self.gen_emissive).pack(side="left")
        ttk.Label(e_f, text="Threshold:").pack(side="right", padx=5)
        tk.Scale(e_f, from_=0, to=255, orient="horizontal", variable=self.emissive_thresh, width=10, length=100,
                 bg=BZ_BG, fg=BZ_FG, troughcolor="#1a1a1a", activebackground=BZ_GREEN, highlightthickness=0).pack(side="right")
        
        # Specular Row
        s_f = ttk.Frame(gen_f)
        s_f.pack(fill="x", padx=10, pady=2)
        ttk.Checkbutton(s_f, text="Create Specular", variable=self.gen_specular).pack(side="left")
        ttk.Label(s_f, text="Contrast:").pack(side="right", padx=5)
        tk.Scale(s_f, from_=0.5, to=3.0, resolution=0.1, orient="horizontal", variable=self.spec_contrast, width=10, length=100,
                 bg=BZ_BG, fg=BZ_FG, troughcolor="#1a1a1a", activebackground=BZ_GREEN, highlightthickness=0).pack(side="right")
        
        # Normal Row
        n_f = ttk.Frame(gen_f)
        n_f.pack(fill="x", padx=10, pady=2)
        ttk.Checkbutton(n_f, text="Smart Normal", variable=self.gen_normal).pack(side="left")
        ttk.Checkbutton(n_f, text="Flip Y (DX)", variable=self.norm_flip_y).pack(side="left", padx=20)
        ttk.Label(n_f, text="Strength:").pack(side="right", padx=5)
        tk.Scale(n_f, from_=0.1, to=10.0, resolution=0.1, orient="horizontal", variable=self.norm_strength, width=10, length=100,
                 bg=BZ_BG, fg=BZ_FG, troughcolor="#1a1a1a", activebackground=BZ_GREEN, highlightthickness=0).pack(side="right")
        
        # 3. Actions & Log (Right Column)
        right_col = ttk.Frame(main_content)
        right_col.pack(side="right", fill="both", expand=True, padx=5, pady=5)
        
        # Preview Canvas
        self.tex_preview_canvas = tk.Canvas(right_col, bg="#050505", height=200, highlightthickness=0)
        self.tex_preview_canvas.pack(fill="x", padx=5, pady=5)
        
        self.tex_log = tk.Text(right_col, height=15, bg="#050505", fg=BZ_FG, font=("Consolas", 9))
        self.tex_log.pack(fill="both", expand=True, padx=5, pady=5)
        
        self.tex_progress = ttk.Progressbar(right_col, style="BZ.Horizontal.TProgressbar", mode="determinate")
        self.tex_progress.pack(fill="x", padx=5, pady=5)
        # Style for progress bar needs to be defined if not already
        style = ttk.Style()
        style.configure("BZ.Horizontal.TProgressbar", thickness=15, background=BZ_GREEN, troughcolor="#050505")
        
        btn_f = ttk.Frame(right_col)
        btn_f.pack(fill="x", pady=5)
        ttk.Button(btn_f, text="Process Single", command=self.ui_single_tex).pack(side="left", fill="x", expand=True, padx=2)
        ttk.Button(btn_f, text="Batch Folder", command=self.start_batch_thread, style="Action.TButton").pack(side="left", fill="x", expand=True, padx=2)
        
        # Batch Settings
        batch_f = ttk.LabelFrame(left_col, text=" Batch Settings ", padding=10)
        batch_f.pack(fill="x", padx=5, pady=5)
        
        self.tex_from_ext = tk.StringVar(value="all supported")
        ttk.Combobox(batch_f, textvariable=self.tex_from_ext, values=["all supported", ".png", ".tga", ".dds", ".jpg"], state="readonly").pack(pady=2, fill="x")
        
        ttk.Entry(batch_f, textvariable=self.tex_batch_out).pack(fill="x", padx=10, pady=2)
        ttk.Button(batch_f, text="Set Output Folder", command=self.set_tex_batch_out).pack(pady=2, fill="x")

        # --- Bulk recompress: the whole-mod pass, not a per-file conversion ---
        # Separate from Batch Folder above because it rewrites in place, keeps
        # the author's mips and resolutions, and is the operation that actually
        # moves a mod's footprint (ISDF Chronicles: 7.8 GB of DDS -> 2.8 GB).
        rc_f = ttk.LabelFrame(left_col, text=" Bulk DDS Recompress (in place) ", padding=10)
        rc_f.pack(fill="x", padx=5, pady=5)

        self.rc_skip_ui = tk.BooleanVar(value=True)
        ttk.Checkbutton(rc_f, text="Skip UI / HUD / font textures",
                        variable=self.rc_skip_ui).pack(anchor="w", pady=1)
        self.rc_dry = tk.BooleanVar(value=False)
        ttk.Checkbutton(rc_f, text="Dry run (report only, write nothing)",
                        variable=self.rc_dry).pack(anchor="w", pady=1)
        ttk.Button(rc_f, text="Recompress Mod Folder...",
                   command=self.start_recompress_thread,
                   style="Action.TButton").pack(pady=(5, 0), fill="x")

    def browse_single_tex(self):
        path = filedialog.askopenfilename(filetypes=[("Image", "*.png;*.tga;*.jpg;*.bmp;*.dds")])
        if path:
            self.tex_single_path.set(path)
            self.load_tex_preview(path)

    def on_tex_drop(self, event):
        path = event.data.strip('{}')
        self.tex_single_path.set(path)
        self.load_tex_preview(path)

    def load_tex_preview(self, path):
        try:
            img, _ = self.internal_load_rgba(path)   # one loader, same as processing uses
            # Resize for preview
            img.thumbnail((300, 200))
            self.tk_tex_preview = ImageTk.PhotoImage(img)
            self.tex_preview_canvas.delete("all")
            cw = self.tex_preview_canvas.winfo_width()
            ch = self.tex_preview_canvas.winfo_height()
            self.tex_preview_canvas.create_image(cw//2, ch//2, image=self.tk_tex_preview)
        except Exception as e:
            self.log_msg(self.tex_log, f"Preview Error: {e}")

    def update_tex_ui_state(self, *args):
        if self.tex_to_ext.get() == ".dds":
            self.tex_compress_combo.configure(state="readonly")
            self.tex_mips_chk.configure(state="normal")
        else:
            self.tex_compress_combo.configure(state="disabled")
            self.tex_mips_chk.configure(state="disabled")

    # --- TEXTURE LOGIC FUNCTIONS ---
    def set_tex_batch_out(self):
        folder = filedialog.askdirectory()
        if folder: 
            self.tex_batch_out.set(folder)

    def start_batch_thread(self):
        src_folder = filedialog.askdirectory(title="Select Source Folder")
        if not src_folder: return
        self.tex_progress['value'] = 0
        thread = threading.Thread(target=self.ui_batch_tex, args=(src_folder,), daemon=True)
        thread.start()

    def start_recompress_thread(self):
        folder = filedialog.askdirectory(title="Mod folder to recompress (rewritten IN PLACE)")
        if not folder:
            return
        backup = None
        if not self.rc_dry.get():
            # Not optional, and not defaulted to a subfolder of the mod: this
            # overwrites the only copy of the art, and a backup inside the tree
            # being rewritten is one stray glob away from being rewritten too.
            backup = filedialog.askdirectory(title="Where to keep the ORIGINALS (required)")
            if not backup:
                self.log_msg(self.tex_log, "Recompress cancelled: no backup folder chosen.")
                return
            if os.path.abspath(backup).startswith(os.path.abspath(folder) + os.sep):
                messagebox.showerror(
                    "Backup folder",
                    "The backup folder is inside the folder being recompressed.\n"
                    "Choose somewhere outside it.")
                return
        self.tex_progress['value'] = 0
        threading.Thread(target=self.ui_recompress, args=(folder, backup),
                         daemon=True).start()

    def ui_recompress(self, folder, backup):
        """Drive recompress.convert over a mod folder, logging to the texture tab."""
        def out(msg):
            self.root.after(0, lambda m=msg: self.log_msg(self.tex_log, m))

        dry = self.rc_dry.get()
        try:
            ui = {} if not self.rc_skip_ui.get() else uiscan.ui_textures(folder)
        except Exception as e:
            ui = {}
            out(f"UI scan failed ({e}); compressing everything.")
        if ui:
            out(f"Leaving {len(ui)} UI texture(s) uncompressed: {', '.join(sorted(ui))}")

        names = sorted((f for f in os.listdir(folder) if f.lower().endswith(".dds")),
                       key=lambda n: -os.path.getsize(os.path.join(folder, n)))
        if not names:
            out("No .dds files in that folder.")
            return
        out(f"{'DRY RUN: ' if dry else ''}{len(names)} DDS file(s) to examine...")

        before = after = 0
        done = skipped = 0
        for i, n in enumerate(names, 1):
            try:
                r = recompress.convert(os.path.join(folder, n), backup, dry, ui)
            except Exception as e:
                out(f"  {n}: FAILED ({e})")
                continue
            if "skipped" in r:
                skipped += 1
            else:
                done += 1
                before += r["before"]
                after += r["after"]
                out("  %-34s %7.1f -> %6.2f MB  %s%s" % (
                    r["file"], r["before"] / 1048576, r["after"] / 1048576, r["fmt"],
                    "" if dry else "  rmse %.2f" % r["rmse"]))
            self.root.after(0, lambda p=i / len(names) * 100:
                            self.tex_progress.configure(value=p))

        if done:
            out("%s%d file(s): %.0f MB -> %.0f MB  (%.1fx, %.0f MB saved). %d skipped."
                % ("DRY RUN " if dry else "", done, before / 1048576, after / 1048576,
                   before / max(1, after), (before - after) / 1048576, skipped))
        else:
            out(f"Nothing to do: {skipped} file(s) skipped (already compressed, UI, or too small).")

    def ui_batch_tex(self, src_folder):
        """Thread-safe batch processing with progress updates"""
        out_dir = self.tex_batch_out.get()
        if out_dir == "[Same as Source]": 
            out_dir = None
        
        from_filter = self.tex_from_ext.get().lower()
        
        # Identify valid files
        supported = [".png", ".tga", ".dds", ".jpg", ".bmp"]
        files = [f for f in os.listdir(src_folder) if os.path.splitext(f)[1].lower() in supported]
        
        if from_filter != "all supported":
            files = [f for f in files if os.path.splitext(f)[1].lower() == from_filter]
        
        total = len(files)
        if total == 0:
            self.root.after(0, lambda: self.log_msg(self.tex_log, "No matching files found."))
            return

        count = 0
        for file in files:
            try:
                msg = self.process_texture(os.path.join(src_folder, file), out_dir)
                count += 1
                # Schedule UI updates on the main thread
                progress = (count / total) * 100
                self.root.after(0, lambda m=msg, p=progress: (self.log_msg(self.tex_log, m), self.tex_progress.configure(value=p)))
            except Exception as e:
                self.root.after(0, lambda f=file, err=e: self.log_msg(self.tex_log, f"Skip {f}: {err}"))
                    
        self.root.after(0, lambda c=count: self.log_msg(self.tex_log, f"BATCH COMPLETE: {c} textures processed."))

    def process_texture(self, path, output_folder=None):
        base_name = os.path.basename(path)
        file_no_ext = os.path.splitext(base_name)[0]
        dest_dir = output_folder if (output_folder and os.path.isdir(output_folder)) else os.path.dirname(path)
        
        target_ext = self.tex_to_ext.get()
        out_path = os.path.join(dest_dir, file_no_ext + target_ext)
        
        # CHECK FOR OVERWRITE
        if os.path.exists(out_path) and not self.tex_overwrite.get():
            return f"Skipped: {file_no_ext}{target_ext} already exists."

        img, src_levels = self.internal_load_rgba(path)
        w, h = img.size

# --- RESTORED: Power of 2 Rescaling Logic ---
        cutoff_val = self.tex_scale_cutoff.get()
        if cutoff_val != "Disabled":
            try:
                limit = int(cutoff_val)
                # If either dimension exceeds the budget, downscale by half
                if w > limit or h > limit:
                    new_w, new_h = w // 2, h // 2
                    img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
                    w, h = img.size # Update dimensions for logging
                    src_levels = None   # resampled: the source chain no longer matches
            except ValueError:
                pass

        # Alpha detection
        has_alpha = False
        if self.tex_auto_alpha.get():
            alpha_extrema = img.getchannel('A').getextrema()
            if alpha_extrema and alpha_extrema[0] < 255:
                has_alpha = True
        
        # Smart naming: if input ends in _d, strip it so we get _e/_s/_n instead of _d_e
        gen_name = file_no_ext
        if gen_name.lower().endswith("_d"):
            gen_name = gen_name[:-2]

        if self.gen_emissive.get(): self.internal_gen_emissive(img, dest_dir, gen_name, target_ext)
        if self.gen_specular.get(): self.internal_gen_specular(img, dest_dir, gen_name, target_ext)
        if self.gen_normal.get(): self.internal_gen_normal(img, dest_dir, gen_name, target_ext)
        
        self.internal_save_img(img, out_path, has_alpha, src_levels)
        return f"Done: {file_no_ext} ({w}x{h}) -> {target_ext}"

    # --- INTERNAL UTILITIES ---
    def internal_load_rgba(self, path):
        """-> (RGBA PIL image, source mip levels or None).

        bcpack is tried first for uncompressed DDS, not because Pillow gets the
        pixels wrong -- at 12.3.0 it agrees on every layout in this art to within
        1/255 -- but because Pillow exposes **mip 0 only**: a DDS has no
        `n_frames` and `seek(1)` raises EOFError. Reading the levels here is what
        lets the save path transcode the author's own chain instead of resampling
        a new one.

        Anything bcpack declines (already block-compressed, cubemap, exotic) falls
        through to Pillow, which handles those plus PNG/TGA/JPG/BMP.
        """
        if path.lower().endswith(".dds"):
            try:
                levels, _ = bcpack.read_dds(path)
                return Image.fromarray(levels[0], "RGBA"), levels
            except bcpack.Unsupported:
                pass          # compressed or exotic: Pillow's DDS reader handles it
        return Image.open(path).convert("RGBA"), None

    def internal_save_img(self, img, out_path, has_alpha, src_levels=None):
        """Write the image, block-compressing in-process when the target is DDS.

        This used to shell out to texconv.exe through a temporary TGA. It now
        encodes with bcpack, which removes the external binary from the build
        entirely (it was step 3 of the README's setup) and drops the temp file
        and subprocess per image.

        `src_levels` is the source file's own mip chain, when the caller read
        one and did not transform the image. Those levels are transcoded as they
        are, so an author's hand-tuned chain survives instead of being resampled
        by whatever filter we would have picked for them.
        """
        if not out_path.lower().endswith(".dds"):
            img.save(out_path)
            return

        base = np.asarray(img.convert("RGBA"), dtype=np.uint8)
        levels = src_levels if src_levels else [base]

        comp_mode = self.tex_compress.get()
        if comp_mode == "Auto":
            # has_alpha comes from the caller's own extrema check; fall back to
            # the shared 250 floor, which ignores the authoring noise that makes
            # a literal `min < 255` double a fully opaque file's size.
            fmt = "DXT5" if (has_alpha or bcpack.has_real_alpha(levels)) else "DXT1"
        elif comp_mode in ("DXT1", "DXT5"):
            fmt = comp_mode
        else:
            fmt = None                                   # "None": stay uncompressed

        if self.tex_mips.get():
            levels, _ = bcpack.build_chain(levels, base.shape[1], base.shape[0])
        else:
            levels = levels[:1]

        if fmt is None:
            bcpack.write_dds_uncompressed(out_path, levels)
        else:
            bcpack.write_dds(out_path, base.shape[1], base.shape[0],
                             [bcpack.encode_level(lv, fmt) for lv in levels], fmt)

    def internal_gen_emissive(self, img, dest, name, ext):
        thresh = self.emissive_thresh.get()
        mask = img.convert("L").point(lambda p: 255 if p > thresh else 0)
        emissive = Image.new("RGBA", img.size, (0, 0, 0, 255))
        emissive.paste(img, (0, 0), mask)
        self.internal_save_img(emissive, os.path.join(dest, f"{name}_e{ext}"), False)

    def internal_gen_specular(self, img, dest, name, ext):
        spec = img.convert("L")
        contrast = self.spec_contrast.get()
        spec = spec.point(lambda p: min(255, int(p * contrast)))
        self.internal_save_img(spec.convert("RGBA"), os.path.join(dest, f"{name}_s{ext}"), False)

    def internal_gen_normal(self, img, dest, name, ext):
        gray = np.array(img.convert("L"), dtype=float)
        grad_x = np.gradient(gray, axis=1)
        grad_y = np.gradient(gray, axis=0)
        strength = self.norm_strength.get()
        nx = -grad_x * strength
        ny = grad_y * strength if self.norm_flip_y.get() else -grad_y * strength
        nz = np.ones_like(gray) * 255.0
        norm = np.sqrt(nx**2 + ny**2 + nz**2)
        nx, ny, nz = nx/norm, ny/norm, nz/norm
        r, g, b = ((nx + 1.0) * 127.5).astype(np.uint8), ((ny + 1.0) * 127.5).astype(np.uint8), (nz * 255.0).astype(np.uint8)
        normal_map = Image.fromarray(np.stack([r, g, b, np.full_like(r, 255)], axis=2))
        self.internal_save_img(normal_map, os.path.join(dest, f"{name}_n{ext}"), False)

    def ui_single_tex(self):
        path = self.tex_single_path.get()
        if not path or not os.path.exists(path):
            path = filedialog.askopenfilename()
            if not path: return
            self.tex_single_path.set(path)
        try:
            msg = self.process_texture(path)
            self.log_msg(self.tex_log, msg)
        except Exception as e: 
            self.log_msg(self.tex_log, f"ERROR: {e}")
            
    def setup_dxt_tab(self):
        ttk.Label(self.tab_dxt, text="DXTBZ2 Texture Converter", font=(self.custom_font_name, 16, "bold"), foreground=BZ_GREEN).pack(pady=10)
        
        # --- Settings Frame ---
        ctrl = ttk.Frame(self.tab_dxt)
        ctrl.pack(pady=10, padx=20, fill="x")

        # Format Selection
        ttk.Label(ctrl, text="Output Format:").grid(row=0, column=0, padx=10, pady=10)
        self.dxt_out_ext = tk.StringVar(value=".dds")
        self.dxt_out_ext.trace_add("write", self.update_dxt_ui_state)
        ttk.Combobox(ctrl, textvariable=self.dxt_out_ext, values=[".dds", ".png"], state="readonly", width=10).grid(row=0, column=1, padx=10)

        # Compression Option
        ttk.Label(ctrl, text="Compression:").grid(row=1, column=0, padx=10, pady=5)
        self.dxt_compress = tk.StringVar(value="Auto")
        self.dxt_compress_combo = ttk.Combobox(ctrl, textvariable=self.dxt_compress, values=["Auto", "DXT1", "DXT5", "None"], state="readonly", width=10)
        self.dxt_compress_combo.grid(row=1, column=1, padx=10)

        # Standard Options (Linked to your existing logic)
        self.dxt_mips = tk.BooleanVar(value=True)
        self.dxt_mips_chk = ttk.Checkbutton(ctrl, text="Gen Mipmaps (DDS only)", variable=self.dxt_mips)
        self.dxt_mips_chk.grid(row=2, column=0, padx=20, pady=5)
        
        self.dxt_overwrite = tk.BooleanVar(value=False)
        ttk.Checkbutton(ctrl, text="Overwrite Existing", variable=self.dxt_overwrite).grid(row=2, column=1, padx=20, pady=5)

        # --- Action Buttons ---
        btn_f = ttk.Frame(self.tab_dxt)
        btn_f.pack(pady=10)
        ttk.Button(btn_f, text="+ Convert Single .dxtbz2", style="Action.TButton", command=self.ui_single_dxt).pack(side="left", padx=10)
        ttk.Button(btn_f, text="+ Batch Folder", style="Action.TButton", command=self.ui_batch_dxt).pack(side="left", padx=10)

        self.dxt_log = tk.Text(self.tab_dxt, height=20, bg="#050505", fg=BZ_FG, font=("Consolas", 9))
        self.dxt_log.pack(padx=20, pady=10, fill="both")

    def update_dxt_ui_state(self, *args):
        if self.dxt_out_ext.get() == ".dds":
            self.dxt_compress_combo.configure(state="readonly")
            self.dxt_mips_chk.configure(state="normal")
        else:
            self.dxt_compress_combo.configure(state="disabled")
            self.dxt_mips_chk.configure(state="disabled")

    def process_dxtbz2(self, path):
        """Converts dxtbz2 to a temp DDS, then uses internal_save_img for final compression/format"""
        base_name = os.path.basename(path)
        file_no_ext = os.path.splitext(base_name)[0]
        out_ext = self.dxt_out_ext.get()
        final_out = os.path.join(os.path.dirname(path), file_no_ext + out_ext)

        if os.path.exists(final_out) and not self.dxt_overwrite.get():
            return f"Skipped: {file_no_ext}{out_ext} exists."

        with open(path, "rb") as f:
            header = DXTBZ2Header()
            f.readinto(header)
            
            # Read chunk size for the first mip
            size_raw = f.read(4)
            if not size_raw: return "Error: Empty file"
            chunk_size = struct.unpack("I", size_raw)[0]
            
            # Check for alpha based on data density
            has_alpha = chunk_size // header.m_BaseHeight == header.m_BaseWidth
            
            # Extract raw DXT data
            raw_data = f.read(chunk_size)
            
        # Wrap the raw DXT payload in a minimal DDS so PIL can open it, then
        # hand it to the shared save path for format/mips.
        temp_dds = path + ".tmp.dds"
        self.internal_wrap_dxt_to_dds(temp_dds, header, raw_data, has_alpha)

        try:
            # Open the wrapped DDS as a PIL image
            with Image.open(temp_dds) as img:
                # Reuse the shared texture save path for compression/mips/format
                # Temporarily override UI variables to match this tab's settings
                old_mips = self.tex_mips.get()
                old_compress = self.tex_compress.get()
                self.tex_mips.set(self.dxt_mips.get())
                self.tex_compress.set(self.dxt_compress.get())
                
                self.internal_save_img(img, final_out, has_alpha)
                
                self.tex_mips.set(old_mips) # Restore global state
                self.tex_compress.set(old_compress)
        finally:
            if os.path.exists(temp_dds): os.remove(temp_dds)

        return f"Converted: {file_no_ext} -> {out_ext}"

    def internal_wrap_dxt_to_dds(self, out_path, header, data, has_alpha):
        """Minimal DDS wrapper to make raw DXT data readable by PIL"""
        with open(out_path, "wb") as f:
            f.write(b"DDS ")
            # Basic Header
            f.write(struct.pack("<IIIIIII 11I", 124, 0x1|0x2|0x4|0x1000, header.m_BaseHeight, header.m_BaseWidth, 0, 0, 1, *[0]*11))
            # Pixel Format (DXT1 or DXT5)
            fourcc = b"DXT5" if has_alpha else b"DXT1"
            f.write(struct.pack("<II4sIIIII", 32, 0x4, fourcc, 0, 0, 0, 0, 0))
            # Caps
            f.write(struct.pack("<IIII I", 0x1000, 0, 0, 0, 0))
            f.write(data)

    def ui_single_dxt(self):
        path = filedialog.askopenfilename(filetypes=[("Legacy Texture", "*.dxtbz2")])
        if not path: return
        try:
            msg = self.process_dxtbz2(path)
            self.log_msg(self.dxt_log, msg)
        except Exception as e:
            self.log_msg(self.dxt_log, f"ERROR: {e}")

    def ui_batch_dxt(self):
        folder = filedialog.askdirectory()
        if not folder: return
        
        def run_batch():
            files = [f for f in os.listdir(folder) if f.lower().endswith(".dxtbz2")]
            for f in files:
                try:
                    msg = self.process_dxtbz2(os.path.join(folder, f))
                    self.root.after(0, lambda m=msg: self.log_msg(self.dxt_log, m))
                except: pass
            self.root.after(0, lambda: self.log_msg(self.dxt_log, "Batch Finished."))
            
        threading.Thread(target=run_batch, daemon=True).start()
        
    def setup_pack_tab(self):
        ttk.Label(self.tab_pack, text="Channel Packer (Alpha Injector)", font=(self.custom_font_name, 16, "bold"), foreground=BZ_GREEN).pack(pady=10)
        
        f = ttk.Frame(self.tab_pack, padding=20)
        f.pack(fill="both", expand=True)
        
        # RGB Input
        ttk.Label(f, text="RGB Source (Color):").pack(anchor="w")
        self.pack_rgb_path = tk.StringVar()
        e1 = ttk.Entry(f, textvariable=self.pack_rgb_path)
        e1.pack(fill="x", pady=(0, 5))
        ttk.Button(f, text="Browse RGB", command=lambda: self.pack_rgb_path.set(filedialog.askopenfilename())).pack(anchor="e", pady=(0, 15))
        
        # Alpha Input
        ttk.Label(f, text="Alpha Source (Grayscale/Gloss/Opacity):").pack(anchor="w")
        self.pack_alpha_path = tk.StringVar()
        e2 = ttk.Entry(f, textvariable=self.pack_alpha_path)
        e2.pack(fill="x", pady=(0, 5))
        ttk.Button(f, text="Browse Alpha", command=lambda: self.pack_alpha_path.set(filedialog.askopenfilename())).pack(anchor="e", pady=(0, 15))
        
        if _dnd_ready(self.root):
            for e in [e1, e2]:
                e.drop_target_register(DND_FILES)
                e.dnd_bind('<<Drop>>', lambda event, var=e.cget("textvariable"): self.root.setvar(var, event.data.strip('{}')))

        # Output
        ttk.Label(f, text="Output Filename:").pack(anchor="w")
        self.pack_out_path = tk.StringVar()
        ttk.Entry(f, textvariable=self.pack_out_path).pack(fill="x", pady=(0, 5))
        ttk.Button(f, text="Save As...", command=lambda: self.pack_out_path.set(filedialog.asksaveasfilename(defaultextension=".png"))).pack(anchor="e", pady=(0, 20))
        
        ttk.Button(f, text="MERGE & SAVE", style="Success.TButton", command=self.process_pack).pack(fill="x", pady=10)
        
        self.pack_log = tk.Text(f, height=10, bg="#050505", fg=BZ_FG, font=("Consolas", 9))
        self.pack_log.pack(fill="both", expand=True)

    def process_pack(self):
        rgb_p = self.pack_rgb_path.get()
        a_p = self.pack_alpha_path.get()
        out_p = self.pack_out_path.get()
        
        if not rgb_p or not a_p or not out_p:
            self.log_msg(self.pack_log, "Error: Missing file paths.")
            return
            
        try:
            rgb_img = Image.open(rgb_p).convert("RGB")
            alpha_img = Image.open(a_p).convert("L")
            
            if rgb_img.size != alpha_img.size:
                self.log_msg(self.pack_log, f"Resizing Alpha {alpha_img.size} to match RGB {rgb_img.size}...")
                alpha_img = alpha_img.resize(rgb_img.size, Image.Resampling.LANCZOS)
                
            rgb_img.putalpha(alpha_img)
            rgb_img.save(out_p)
            self.log_msg(self.pack_log, f"Success: Saved RGBA to {out_p}")
        except Exception as e:
            self.log_msg(self.pack_log, f"Error: {e}")

if __name__ == "__main__":
    root = TkinterDnD.Tk() if HAS_DND else tk.Tk()
    app = BZReduxSuite(root)
    root.mainloop()
