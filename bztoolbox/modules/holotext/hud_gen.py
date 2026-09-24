import os
import sys
import subprocess
import tkinter as tk
from tkinter import ttk, colorchooser, filedialog, messagebox
from PIL import Image, ImageDraw, ImageFont, ImageTk
import math
import ctypes

# Platform check
IS_WINDOWS = sys.platform == "win32"

BUNDLED_FONT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "BZONE.ttf")


class BZFontGenerator:
    def __init__(self, root):
        self.root = root
        self.root.title("Battlezone Holo Text Generator")
        self.root.geometry("800x950")
        
        # --- THEME & COLORS ---
        self.colors = {
            "bg": "#0a0a0a", "fg": "#d4d4d4",
            "highlight": "#00ff00", "dark_highlight": "#004400", "accent": "#00ffff"
        }
        
        self.output_dir = tk.StringVar(value=os.path.join(os.getcwd(), "output"))
        self.font_path = tk.StringVar(value=BUNDLED_FONT) 
        self.variant_count = tk.IntVar(value=10)
        self.text_color = "#00FF00"
        self.spacing = tk.DoubleVar(value=1.5)
        self.export_mode = tk.StringVar(value="Sheet") 

        self.load_custom_fonts()
        self.setup_styles()
        self.create_widgets()

        # Bindings for Live Preview
        self.font_path.trace_add("write", lambda *args: self.update_preview())
        self.variant_count.trace_add("write", lambda *args: self.update_preview())

    def load_custom_fonts(self):
        self.current_font = "Consolas"
        if IS_WINDOWS:
            font_path = BUNDLED_FONT
            if os.path.exists(font_path):
                try:
                    if ctypes.windll.gdi32.AddFontResourceExW(font_path, 0x10, 0) > 0:
                        self.current_font = "BZONE"
                except: pass

    def setup_styles(self):
        style = ttk.Style()
        style.theme_use('default')
        c = self.colors
        
        main_font = (self.current_font, 10)
        bold_font = (self.current_font, 11, "bold")
        
        style.configure(".", background=c["bg"], foreground=c["fg"], font=main_font)
        style.configure("TFrame", background=c["bg"])
        style.configure("TNotebook", background=c["bg"], borderwidth=0)
        style.configure("TNotebook.Tab", background="#1a1a1a", foreground=c["fg"], padding=[10, 2])
        style.map("TNotebook.Tab", background=[("selected", c["dark_highlight"])], foreground=[("selected", c["highlight"])])
        style.configure("TLabelframe", background=c["bg"], bordercolor=c["highlight"])
        style.configure("TLabelframe.Label", background=c["bg"], foreground=c["highlight"], font=bold_font)
        style.configure("TLabel", background=c["bg"], foreground=c["fg"])
        style.configure("TEntry", fieldbackground="#1a1a1a", foreground=c["accent"], insertcolor=c["highlight"])
        style.configure("TButton", background="#1a1a1a", foreground=c["fg"])
        style.map("TButton", background=[("active", c["dark_highlight"])], foreground=[("active", c["highlight"])])
        
        style.configure("Accent.TButton", foreground=c["highlight"], font=bold_font)
        style.configure("TSpinbox", fieldbackground="#1a1a1a", foreground=c["accent"], arrowcolor=c["highlight"])
        style.configure("TRadiobutton", background=c["bg"], foreground=c["fg"])
        style.map("TRadiobutton", background=[("active", c["bg"])])

    def create_widgets(self):
        self.root.configure(bg=self.colors["bg"])
        
        # --- HEADER ---
        header_frame = ttk.Frame(self.root, padding=(20, 10))
        header_frame.pack(fill="x")
        ttk.Label(header_frame, text="BATTLEZONE HOLO TEXT", font=(self.current_font, 24, "bold"), foreground=self.colors["highlight"]).pack(side="left")
        ttk.Label(header_frame, text="GENERATOR", font=(self.current_font, 10), foreground=self.colors["accent"]).pack(side="left", padx=10, pady=(10, 0))

        tab_control = ttk.Notebook(self.root)
        self.gen_tab = ttk.Frame(tab_control)
        self.lua_tab = ttk.Frame(tab_control)
        tab_control.add(self.gen_tab, text=' 1. ASSET GENERATOR ')
        tab_control.add(self.lua_tab, text=' 2. LUA CODE GENERATOR ')
        tab_control.pack(expand=1, fill="both", padx=10, pady=10)

        # --- ASSET GENERATOR TAB ---
        gen_scroll_frame = ttk.Frame(self.gen_tab)
        gen_scroll_frame.pack(fill="both", expand=True)

        gen_frame = ttk.Frame(gen_scroll_frame, padding="20")
        gen_frame.pack(fill="both", expand=True)

        # Mode Selection
        mode_frame = ttk.LabelFrame(gen_frame, text=" EXPORT STRATEGY ", padding=10)
        mode_frame.pack(fill="x", pady=(0, 15))
        ttk.Radiobutton(mode_frame, text="Individual DDS (Master Material)", variable=self.export_mode, value="Individual").pack(side="left", padx=10)
        ttk.Radiobutton(mode_frame, text="Sprite Sheet (spritea.sta)", variable=self.export_mode, value="Sheet").pack(side="left", padx=10)

        # Output Dir
        ttk.Label(gen_frame, text="OUTPUT DIRECTORY:").pack(anchor="w")
        path_frame = ttk.Frame(gen_frame)
        path_frame.pack(fill="x", pady=(0, 10))
        tk.Entry(path_frame, textvariable=self.output_dir, bg="#1a1a1a", fg=self.colors["accent"], insertbackground=self.colors["highlight"], borderwidth=1).pack(side="left", fill="x", expand=True)
        ttk.Button(path_frame, text="BROWSE", command=self.browse_output).pack(side="right", padx=(5, 0))

        # Font File
        ttk.Label(gen_frame, text="FONT FILE (.TTF):").pack(anchor="w")
        font_frame = ttk.Frame(gen_frame)
        font_frame.pack(fill="x", pady=(0, 10))
        tk.Entry(font_frame, textvariable=self.font_path, bg="#1a1a1a", fg=self.colors["accent"], insertbackground=self.colors["highlight"], borderwidth=1).pack(side="left", fill="x", expand=True)
        ttk.Button(font_frame, text="LOAD FONT", command=self.browse_font).pack(side="right", padx=(5, 0))

        # Configuration Row
        cfg_row = ttk.Frame(gen_frame)
        cfg_row.pack(fill="x", pady=5)
        
        # Variants
        v_frame = ttk.Frame(cfg_row)
        v_frame.pack(side="left", fill="x", expand=True)
        ttk.Label(v_frame, text="VARIANTS PER CHAR:").pack(anchor="w")
        ttk.Spinbox(v_frame, from_=1, to=20, textvariable=self.variant_count).pack(fill="x", pady=5)

        # Color
        c_frame = ttk.Frame(cfg_row)
        c_frame.pack(side="left", fill="x", expand=True, padx=(20, 0))
        ttk.Label(c_frame, text="TEXT COLOR:").pack(anchor="w")
        ttk.Button(c_frame, text="SELECT COLOR", command=self.choose_color).pack(fill="x", pady=5)
        self.color_preview = tk.Frame(c_frame, height=20, bg=self.text_color, relief="flat", borderwidth=1)
        self.color_preview.pack(fill="x", pady=(0, 5))

        # --- PREVIEW PANE ---
        preview_frame = ttk.LabelFrame(gen_frame, text=" LIVE PREVIEW ", padding=10)
        preview_frame.pack(fill="x", pady=20)
        
        self.preview_canvas = tk.Canvas(preview_frame, height=100, bg="#050505", highlightthickness=1, highlightbackground=self.colors["dark_highlight"])
        self.preview_canvas.pack(fill="x")
        
        # Spacing Slider (New)
        ttk.Label(preview_frame, text="PREVIEW SPACING:").pack(anchor="w", pady=(10, 0))
        self.spacing_scale = ttk.Scale(preview_frame, from_=0.5, to=3.0, variable=self.spacing, orient="horizontal", command=lambda e: self.update_preview())
        self.spacing_scale.pack(fill="x", pady=5)

        ttk.Button(gen_frame, text="BUILD ASSETS", command=self.generate, style="Accent.TButton", cursor="hand2").pack(fill="x", ipady=15, pady=10)

        # --- LUA TAB ---
        lua_frame = ttk.Frame(self.lua_tab, padding="20")
        lua_frame.pack(fill="both", expand=True)
        
        ttk.Label(lua_frame, text="HANDLE NAME:").pack(anchor="w")
        self.handle_name = tk.Entry(lua_frame, bg="#1a1a1a", fg=self.colors["accent"], insertbackground=self.colors["highlight"], borderwidth=1)
        self.handle_name.insert(0, "h")
        self.handle_name.pack(fill="x", pady=(0, 10))
        
        ttk.Label(lua_frame, text="TEXT STRING:").pack(anchor="w")
        self.lua_input = tk.Entry(lua_frame, bg="#1a1a1a", fg=self.colors["accent"], insertbackground=self.colors["highlight"], borderwidth=1)
        self.lua_input.insert(0, "GRIZZLY ONE")
        self.lua_input.pack(fill="x", pady=(0, 10))
        self.lua_input.bind("<KeyRelease>", lambda e: self.update_preview()) # Also update preview from here
        
        self.lua_output = tk.Text(lua_frame, height=20, font=("Consolas", 10), bg="#050505", fg="#d4d4d4", padx=10, pady=10, borderwidth=1, highlightthickness=1, highlightbackground=self.colors["dark_highlight"])
        self.lua_output.pack(fill="both", expand=True, pady=10)
        
        btn_lua = ttk.Button(lua_frame, text="GENERATE LUA BLOCK", command=self.generate_lua_block)
        btn_lua.pack(fill="x")

        # Initial Preview
        self.root.after(100, self.update_preview)

    def update_preview(self):
        try:
            text = self.lua_input.get() if hasattr(self, 'lua_input') else "GRIZZLY ONE"
            if not text: text = "PREVIEW"
            
            width = self.preview_canvas.winfo_width()
            if width < 1: width = 740
            height = 100
            
            img = Image.new("RGBA", (width, height), (5, 5, 5, 255))
            draw = ImageDraw.Draw(img)
            
            fpath = self.font_path.get()
            if not os.path.exists(fpath):
                # Fallback to systemic font if local not found
                fpath = "Arial"
                
            try:
                fnt = ImageFont.truetype(fpath, 40)
            except:
                fnt = ImageFont.load_default()
                
            s = self.spacing.get()
            
            # Draw text centered
            total_w = 0
            char_imgs = []
            for c in text:
                if c == " ": 
                    total_w += 20 * s
                    continue
                bbox = draw.textbbox((0, 0), c, font=fnt)
                cw = bbox[2] - bbox[0]
                char_imgs.append((c, cw))
                total_w += cw + (10 * s)
                
            curr_x = (width - total_w) / 2
            for c, cw in char_imgs:
                draw.text((curr_x, (height - 40) / 2), c, font=fnt, fill=self.text_color)
                curr_x += cw + (10 * s)
                
            self.preview_photo = ImageTk.PhotoImage(img)
            self.preview_canvas.create_image(0, 0, anchor="nw", image=self.preview_photo)
        except Exception as e:
            print(f"Preview error: {e}")

    def get_ascii_map(self):
        return {32:"sp", 33:"ex", 34:"qu", 35:"ha", 36:"dl", 37:"pc", 38:"am", 39:"ap", 40:"lp", 41:"rp", 42:"as", 43:"pl", 44:"cm", 45:"da", 46:"dt", 47:"sl", 58:"cl", 59:"sc", 60:"lt", 61:"eq", 62:"gt", 63:"qm", 64:"at", 91:"lb", 92:"bs", 93:"rb", 94:"cr", 95:"un", 96:"gr", 123:"lc", 124:"pi", 125:"rc", 126:"ti"}

    def browse_output(self):
        p = filedialog.askdirectory(); self.output_dir.set(p) if p else None
    def browse_font(self):
        p = filedialog.askopenfilename(filetypes=[("Fonts", "*.ttf *.otf")]); self.font_path.set(p) if p else None
    def choose_color(self):
        c = colorchooser.askcolor()[1]
        if c: 
            self.text_color = c
            self.color_preview.config(bg=c)
            self.update_preview()

    def get_auto_font(self, target_px):
        try:
            fpath = self.font_path.get() if os.path.exists(self.font_path.get()) else "arial.ttf"
            test_size = 10
            font = ImageFont.truetype(fpath, test_size)
            bbox = font.getbbox("W")
            scale = target_px / max(bbox[2]-bbox[0], bbox[3]-bbox[1])
            return ImageFont.truetype(fpath, int(test_size * scale))
        except: return ImageFont.load_default()

    def generate(self):
        out = self.output_dir.get()
        if not os.path.exists(out): os.makedirs(out)
        
        # Defining characters list at the start of the method
        chars = []
        for i in range(65, 91): chars.append((f"ui{chr(i)}", chr(i)))
        for i in range(97, 123): chars.append((f"uiL{chr(i).upper()}", chr(i)))
        for i in range(48, 58): chars.append((f"ui{chr(i)}", chr(i)))
        for code, name in self.get_ascii_map().items(): chars.append((f"ui_{name}", chr(code)))

        mode = self.export_mode.get()
        
        with open(os.path.join(out, "master_font.material"), "w") as mf:
            mf.write('import * from "sprites.material"\n\n')
            if mode == "Sheet":
                self.build_sheet(chars, out, mf)
            else:
                self.build_individual(chars, out, mf)

        tconv = os.path.join(os.getcwd(), "texconv.exe")
        if os.path.exists(tconv):
            subprocess.run([tconv, "-f", "BC3_UNORM", "-y", "-o", out, os.path.join(out, "*.png")], creationflags=subprocess.CREATE_NO_WINDOW)
            for f in os.listdir(out):
                if f.endswith(".png"): os.remove(os.path.join(out, f))
        
        messagebox.showinfo("Success", f"Build finished in {mode} mode.")

    def build_sheet(self, chars, out, mf, cell=96):
        sheet_dim = 1024
        cols = 10 
        sheet = Image.new("RGBA", (sheet_dim, sheet_dim), (0, 0, 0, 0))
        draw = ImageDraw.Draw(sheet)
        fnt = self.get_auto_font(cell - 6)
        sta_lines = ["# BZ Optimized Sprite Sheet", "# HARDCODED TO spritea.sta"]

        # Material points to the DDS we are about to make
        mf.write('material font_sheet : BZSprite/Additive\n{\n\tset_texture_alias DiffuseMap font_sheet.dds\n}\n')

        for idx, (base, char) in enumerate(chars):
            x, y = (idx % cols) * cell, (idx // cols) * cell
            bbox = draw.textbbox((0, 0), char, font=fnt)
            draw.text((x + (cell-(bbox[2]-bbox[0]))/2, y + (cell-(bbox[3]-bbox[1]))/2 - bbox[1]), char, font=fnt, fill=self.text_color)
            
            for i in range(1, self.variant_count.get() + 1):
                vn = f"{base}{i}"
                # Registry entries in spritea.sta
                sta_lines.append(f'"{vn}" font_sheet {x} {y} {cell} {cell} {sheet_dim} {sheet_dim} 0x00000000')
                self.write_odf(out, vn, vn) 

        sheet.save(os.path.join(out, "font_sheet.png"))
        with open(os.path.join(out, "spritea.sta"), "w") as f: f.write("\n".join(sta_lines))

    def build_individual(self, chars, out, mf):
        fnt = self.get_auto_font(60)
        for base, char in chars:
            img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)
            bbox = draw.textbbox((0, 0), char, font=fnt)
            draw.text(((64-(bbox[2]-bbox[0]))/2, (64-(bbox[3]-bbox[1]))/2 - bbox[1]), char, font=fnt, fill=self.text_color)
            img.save(os.path.join(out, f"{base}.png"))

            for i in range(1, self.variant_count.get() + 1):
                vn = f"{base}{i}"
                self.write_odf(out, vn, f"{vn}.tga")
                mf.write(f'material {vn}.tga : BZSprite/Additive\n{{\n\tset_texture_alias DiffuseMap {base}.dds\n}}\n\n')

    def write_odf(self, out, name, tex):
        with open(os.path.join(out, f"{name}.odf"), "w") as f:
            f.write(f'[ExplosionClass]\nclassLabel="explosion"\nparticleTypes=1\nparticleClass1="{name}.l"\nparticleCount1=1\n\n[l]\nrenderBase="draw_sprite"\nsimulateBase="sim_null"\ntextureName="{tex}"\nstartColor="255 255 255 255"\nfinishColor="255 255 255 255"\nstartRadius=1.2\nfinishRadius=1.2\nanimateTime=1e30\nlifeTime=0.5\n')

    def generate_lua_block(self):
        text = self.lua_input.get(); h = self.handle_name.get(); s = self.spacing.get(); usage = {}; map = self.get_ascii_map()
        lua = [f"-- Generated for: {text}", f"local p = GetPosition({h})", f"local r = GetRight({h})", f"local u = GetUp({h})"]
        start_offset = -((len(text)-1)*s / 2)
        for i, char in enumerate(text):
            if char == " ": continue
            if 'A' <= char <= 'Z': b = f"ui{char}"
            elif 'a' <= char <= 'z': b = f"uiL{char.upper()}"
            elif '0' <= char <= '9': b = f"ui{char}"
            else: b = f"ui_{map.get(ord(char), 'un')}"
            usage[b] = usage.get(b, 0) + 1
            off = start_offset + (i * s)
            lua.append(f'MakeExplosion("{b}{usage[b]}", p + (r * {off:.2f}) + (u * 2.5))')
        self.lua_output.delete(1.0, tk.END); self.lua_output.insert(tk.END, "\n".join(lua))

if __name__ == "__main__":
    root = tk.Tk(); app = BZFontGenerator(root); root.mainloop()
