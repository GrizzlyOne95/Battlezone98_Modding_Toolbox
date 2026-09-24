import io
import os
import sys
import ctypes
import math
import json
import threading
import random
import re
import numpy as np
import struct
import imageio
import tkinter as tk
from datetime import datetime
from tkinter import filedialog, messagebox, ttk
from PIL import Image, ImageDraw, ImageFilter, ImageTk, ImageOps, ImageEnhance
from battlezone.terrain.hg2 import read_hg2, write_hg2
from battlezone.terrain.trn import TRNDocument
from bztoolbox.modules.world.custom_atlas_builder import (
    build_custom_atlas,
    generate_normal_map as atlas_generate_normal_map,
    generate_specular_map as atlas_generate_specular_map,
    generate_transition_mask as atlas_generate_transition_mask,
)
from scipy.ndimage import map_coordinates

# --- BATTLEZONE HUD COLORS ---
BZ_BG = "#0a0a0a"
BZ_FG = "#d4d4d4"
BZ_GREEN = "#00ff00"
BZ_DARK_GREEN = "#004400"
BZ_CYAN = "#00ffff"

from bztoolbox.app.widgets import register_wheel_target
from bztoolbox.paths import module_data_dir
from bztoolbox.app.fonts import bz_font

CONFIG_FILE = str(module_data_dir("world") / "world_builder_config.json")
APP_USER_MODEL_ID = "GrizzlyOne95.Battlezone98Redux.WorldBuilder"


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
    candidates.append(os.path.join(here, "branding", name))
    candidates.append(os.path.join(here, name))
    for path in candidates:
        if os.path.exists(path):
            return path
    return None


def apply_window_icon(window, base_dir, resource_dir):
    """Apply the canonical app icon to a Tk/Toplevel window."""
    try:
        ico_path = _resolve_bundled_icon(base_dir, resource_dir, "app_icon.ico") or _resolve_bundled_icon(base_dir, resource_dir, "wb.ico")
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

# Full 256-color Moon.act data
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


class BinaryFieldType:
    DATA_VOID = 0
    DATA_BOOL = 1
    DATA_CHAR = 2
    DATA_SHORT = 3
    DATA_LONG = 4
    DATA_FLOAT = 5
    DATA_DOUBLE = 6
    DATA_ID = 7
    DATA_PTR = 8
    DATA_VEC3D = 9
    DATA_VEC2D = 10
    DATA_MAT3DOLD = 11
    DATA_MAT3D = 12
    DATA_STRING = 13
    DATA_QUAT = 14

class BinaryBZNParser:
    def __init__(self, data):
        self.data = data
        self.pos = 0
        self.version = 0
        self.is_binary = False
        self.entities = []
        self.paths = []

    def read_token(self):
        if self.pos + 4 > len(self.data):
            return None, None
        
        # Tag/Type (2 bytes)
        tag_type = self.data[self.pos]
        self.pos += 2
        
        # Length (2 bytes)
        length = struct.unpack("<H", self.data[self.pos:self.pos+2])[0]
        self.pos += 2
        
        # Value
        if self.pos + length > len(self.data):
            return tag_type, None
            
        value = self.data[self.pos:self.pos+length]
        self.pos += length
        
        return tag_type, value

    def parse_float(self, data):
        if not data or len(data) < 4: return 0.0
        return struct.unpack("<f", data[:4])[0]

    def parse_int(self, data):
        if not data or len(data) < 4: return 0
        return struct.unpack("<i", data[:4])[0]

    def parse_uint(self, data):
        if not data or len(data) < 4: return 0
        return struct.unpack("<I", data[:4])[0]

    def parse_vec2d(self, data, index=0):
        # Bi-vector (X, Z)
        offset = index * 8
        if not data or len(data) < offset + 8: return (0.0, 0.0)
        x = struct.unpack("<f", data[offset:offset+4])[0]
        z = struct.unpack("<f", data[offset+4:offset+8])[0]
        return (x, z)

    def parse_string(self, data):
        if not data: return ""
        try:
            return data.decode('ascii').strip('\x00')
        except:
            return ""

    def load(self):
        """Main entry point to parse paths from BZN data."""
        self.pos = 0
        self.paths = []
        
        # 1. Version
        tag, val = self.read_token()
        if tag is None: return []
        self.version = self.parse_int(val)
        
        # 2. binarySave flag
        if self.version > 1022:
            tag, val = self.read_token()
            self.is_binary = (val[0] != 0) if val else False
            
            # 3. msn_filename
            tag, val = self.read_token()
            
        # 4. seq_count
        tag, val = self.read_token()
        
        # 5. missionSave
        if self.version >= 1016:
            tag, val = self.read_token()
            
        # 6. TerrainName (except 1001)
        if self.version != 1001:
            tag, val = self.read_token()
            
        # 7. start_time (1011, 1012)
        if self.version in [1011, 1012]:
            tag, val = self.read_token()
            
        # Hydrate Section
        # GameObject Count
        tag, val = self.read_token()
        if tag is None: return []
        go_count = self.parse_int(val)
        
        # We need to skip GameObjects. Each GameObject starts with a PrjID (DATA_ID = 7)
        # and has a sequence of tokens. This is hard without a full state machine,
        # but we can look for the "name" token (CHAR) after the entities list.
        # Actually, let's just keep reading until we see something matching AOIs or AIPaths.
        
        # Skip GameObjects
        for _ in range(go_count):
            self._skip_game_object()
            
        # Mission Name (CHAR)
        tag, val = self.read_token()
        
        # sObject (PTR)
        tag, val = self.read_token()
        
        # BZ1 1044 extra bool
        if self.version == 1044:
            # We don't have Consume logic here, so let's check next tag
            old_pos = self.pos
            tag, val = self.read_token()
            if tag != 4: # If not long (size for AOIs), backtrack
                self.pos = old_pos
        
        # AOIs Count (LONG=4)
        tag, val = self.read_token()
        aoi_count = self.parse_int(val)
        for _ in range(aoi_count):
            for _ in range(6): # undefptr, team, inter, inside, value, force
                self.read_token()
                
        # AIPaths Count (LONG=4)
        tag, val = self.read_token()
        path_count = self.parse_int(val)
        
        for _ in range(path_count):
            path = {"label": "", "points": [], "type": 0}
            
            # old_ptr
            self.read_token()
            
            # label size
            tag, val = self.read_token()
            label_size = self.parse_int(val)
            
            if label_size > 0:
                tag, val = self.read_token()
                path["label"] = self.parse_string(val)
                
            # pointCount
            tag, val = self.read_token()
            pt_count = self.parse_int(val)
            
            # points (VEC2D = 10)
            tag, val = self.read_token()
            for i in range(pt_count):
                path["points"].append(self.parse_vec2d(val, i))
                
            # pathType
            tag, val = self.read_token()
            path["type"] = self.parse_int(val)
            
            self.paths.append(path)
            
        return self.paths

    def scan_for_paths(self):
        """Heuristic scan for AI Path structures in binary BZN."""
        self.paths = []
        # Search for DATA_VEC2D (10) blocks which are usually path points
        # and look for the count prefix.
        
        # A better heuristic: Search for the string "AiPaths" or look for 
        # the section after the entities.
        
        # Redux BZN usually puts paths towards the end.
        # Let's search for sequences of (Tag=4, Val=Count) then (Tag=8 or 13, Val=Ptr).
        
        # Reset and scan
        self.pos = 0
        while self.pos < len(self.data) - 4:
            old_pos = self.pos
            tag, val = self.read_token()
            if tag is None: break
            
            # Heuristic: Find a DATA_LONG (4) followed by some tokens, 
            # then another DATA_LONG that could be a path count.
            # actually, let's look for the pointCount (tag 4) and points (tag 10) sequence.
            
            if tag == 10: # DATA_VEC2D
                # This might be a path. Let's look backwards for the label.
                # This is risky. 
                pass
                
        # For now, let's rely on the structured load() and improve _skip_game_object.
        return self.paths

    def _skip_game_object(self):
        """Skip a GameObject by consuming its base tokens and then searching for next PrjID."""
        start = self.pos
        # Consume base fields
        for _ in range(7): self.read_token()
        if self.version > 1001: self.read_token()
        
        # Now we are in class-specific data.
        # We search for the next tag that looks like a PrjID (DATA_ID=7) 
        # or the end of the entities section (Mission Name DATA_CHAR=2).
        
        while self.pos < len(self.data) - 4:
            next_tag = self.data[self.pos]
            if next_tag == 7: # PrjID
                # Check if length is reasonable (e.g. < 64)
                length = struct.unpack("<H", self.data[self.pos+2:self.pos+4])[0]
                if length < 64:
                    return # Found next object
            elif next_tag == 2: # Mission Name
                # Check if this could be the end of list
                return 
                
            # Skip one token
            self.read_token()

class AutoPainter:
    """
    Handles generation of .mat files from heightmap data using configurable rules.
    Implements Marching Squares for tile transitions (Solid, Cap, Diagonal).
    """
    
    @staticmethod
    def calculate_slope_map(heightmap, scale_factor=1.0):
        """
        Calculates slope in degrees for each point.
        heightmap: 2D numpy array (0-4095 range usually)
        scale_factor: Multiplier to convert height units to horizontal units if needed.
                      BZ grid is 10m? Height is 0-409.5m? 
                      Each unit in HG2 is 0.1m (0-4095 => 0-409.5m).
                      Grid spacing is 1280m / 64 = 20m? No, depends on resolution.
                      Let's assume standard BZ ratio for now.
        """
        # Simple gradient magnitude
        gy, gx = np.gradient(heightmap)
        slope = np.sqrt(gx**2 + gy**2)
        # Normalize/Convert to degrees? 
        # For now, let's keep it abstract or use a heuristic. 
        # User rules use 0-90 degrees.
        # atan(slope) * 180/pi
        # We need the ratio of dz/dx. 
        # If height is 0.1m units, and grid is X meters.
        # Let's approximate grid as 10.0 units? 
        # Actually simplest is to normalize to 0-90 range based on observable max.
        return np.degrees(np.arctan(slope))

    @staticmethod
    def rasterize_path_mask(h, w, bzn_paths, path_label):
        """Creates a binary mask from a BZN path."""
        mask = np.zeros((h, w), dtype=bool)
        target_path = next((p for p in bzn_paths if p['label'] == path_label), None)
        if not target_path:
            return mask
            
        pts = target_path['points']
        if not pts:
            return mask
            
        # Rasterize using PIL
        # BZ points are in world coords (X, Z). 
        # We need to map them to (W, H).
        # Heuristic: Find bounds of heightmap or assume standard 1280x1280 world.
        # Actually, we should probably know the world size from the app.
        # For now, let's assume the points are local to the 0-1280 range 
        # which is common for BZ maps.
        
        # Scaling: BZ Maps are typically 1280m x 1280m or 640m x 640m.
        # HG2s are 128x128 or 64x64 or 256x256.
        # Let's assume the heightmap represents the full world.
        
        # Determine world bounds if possible, or use fixed 1280.0
        world_size = 1280.0 # Standard BZ world size
        
        img = Image.new('L', (w, h), 0)
        draw = ImageDraw.Draw(img)
        
        # Map world (X, Z) to (row, col)
        # X -> col (0 to w)
        # Z -> row (0 to h) - note: Z increases "down" in some BZ contexts? 
        # In BZ, Z is North. In Screen, Y is Down.
        
        poly = []
        for (x, z) in pts:
            px = (x / world_size) * w
            pz = (1.0 - (z / world_size)) * h # Invert Z for screen space? 
            # Actually, let's just use (x, z) relative mapping.
            poly.append((px, pz))
            
        if target_path['type'] == 3: # Loop
            draw.polygon(poly, fill=255)
        else:
            draw.line(poly, fill=255, width=4) # Thickness heuristic
            
        return np.array(img) > 127

    @staticmethod
    def generate_mat(height_data, rules, progress_callback=None, bzn_paths=None):
        """
        height_data: 2D numpy array (H, W)
        rules: List of dicts [{'mat_id': int, 'min_h': float, 'max_h': float, 'min_s': float, 'max_s': float}]
               Ordered by Priority (Lowest to Highest).
        """
        h, w = height_data.shape
        # MAT resolution is half of heightmap
        mat_h, mat_w = h // 2, w // 2
        
        # 1. Calculate Vertex Materials (Ideal)
        # Result: (H, W) array of Material IDs
        slope_map = AutoPainter.calculate_slope_map(height_data)
        vertex_mats = np.zeros_like(height_data, dtype=np.uint8)
        
        # Apply rules from bottom to top priority
        # Default to 0
        for rule in rules:
            mat_id = rule['mat_id']
            min_h, max_h = rule['min_h'], rule['max_h']
            min_s, max_s = rule['min_s'], rule['max_s']
            
            # Evaluate Mask
            mask = (height_data >= min_h) & (height_data <= max_h) & \
                   (slope_map >= min_s) & (slope_map <= max_s)
            
            # Apply Image/Path Mask
            if rule.get('mask_path'):
                m_path = rule['mask_path']
                if m_path.startswith("PATH:") and bzn_paths:
                    # Path-based mask
                    path_label = m_path[5:]
                    mask &= AutoPainter.rasterize_path_mask(h, w, bzn_paths, path_label)
                elif os.path.exists(m_path):
                    # Image-based mask
                    try:
                        mask_img = Image.open(m_path).convert("L")
                        if mask_img.size != (w, h):
                            mask_img = mask_img.resize((w, h), Image.Resampling.BILINEAR)
                        mask_arr = np.array(mask_img)
                        mask &= (mask_arr > 127) # Threshold
                    except Exception as e:
                        print(f"Mask Load Error: {e}")

            vertex_mats[mask] = mat_id
            
        # 2. Generate Tiles (Marching Squares)
        mat_data = np.zeros((mat_h, mat_w), dtype=np.uint16)
        
        for y in range(mat_h):
            if progress_callback and y % 10 == 0:
                progress_callback(y / mat_h * 100)
                
            for x in range(mat_w):
                # Get the 4 corners of this tile
                # Grid:
                # TL(x,y)     TR(x+1,y)
                # BL(x,y+1)   BR(x+1,y+1)
                
                # In numpy/image coords (row, col):
                # TL(y,x)     TR(y, x+1)
                # BL(y+1,x)   BR(y+1, x+1)
                
                # Careful with indices vs size
                colors = [
                    vertex_mats[y*2, x*2],     # TL
                    vertex_mats[y*2, x*2+1],   # TR
                    vertex_mats[y*2+1, x*2+1], # BR
                    vertex_mats[y*2+1, x*2]    # BL
                ]
                
                # Determine dominant materials
                unique_mats = sorted(list(set(colors)))
                
                base_mat = unique_mats[0]
                next_mat = unique_mats[-1] if len(unique_mats) > 1 else base_mat
                
                # If only 1 material -> Solid
                if base_mat == next_mat:
                    # Solid
                    entry = AutoPainter.encode_entry(base_mat, base_mat, cap=0, flip=0, rot=0, variant=0)
                else:
                    # Transition
                    # We only support 2-way transitions well in this format (Base -> Next).
                    # Higher ID usually means "Overlaying" Lower ID.
                    # So Base = Lower, Next = Higher.
                    # But if we have [0, 2, 5], we might struggle. 
                    # Let's simplify: Base = Min(colors), Next = Max(colors)
                    
                    # Generate 4-bit mask for High Priority (Next) corners
                    # TL, TR, BR, BL order
                    mask = 0
                    if colors[0] == next_mat: mask |= 8 # 1000
                    if colors[1] == next_mat: mask |= 4 # 0100
                    if colors[2] == next_mat: mask |= 2 # 0010
                    if colors[3] == next_mat: mask |= 1 # 0001
                    
                    # Look up shape
                    cap = 0
                    flip = 0
                    rot = 0
                    
                    # Shapes (1 = Next Mat / High Priority)
                    if mask == 0: # All Base
                        pass # handled above
                    elif mask == 15: # All Next
                        base_mat = next_mat # promote
                    
                    # Corners (1 high corner) -> Cap
                    elif mask == 8: # 1000 TL
                        cap=0; flip=0; rot=0 # Check rotation later
                    elif mask == 4: # 0100 TR
                        cap=0; flip=0; rot=3 # -90 deg
                    elif mask == 2: # 0010 BR
                        cap=0; flip=0; rot=2 # 180 deg
                    elif mask == 1: # 0001 BL
                        cap=0; flip=0; rot=1 # 90 deg
                        
                    # Sides (2 adjacent) -> Cap (Side?) -> Actually traditionally "Cap" is 1 corner?
                    # Some sets use Caps for sides too. 
                    # If 2 corners are high, it's a Half/Half.
                    # BZ usually handles this with Caps or Diagonals?
                    # Let's approximate 2-side as Cap for now? Or Diagonal?
                    # Diagonal is 1010 (Opposite).
                    
                    # Half/Half (Side)
                    elif mask == 12: # 1100 Top (TL+TR)
                        cap=0; flip=1; rot=0 
                    elif mask == 6:  # 0110 Right (TR+BR)
                        cap=0; flip=1; rot=3
                    elif mask == 3:  # 0011 Bottom (BR+BL)
                        cap=0; flip=1; rot=2
                    elif mask == 9:  # 1001 Left (TL+BL)
                        cap=0; flip=1; rot=1
                        
                    # Diagonals (Opposite)
                    elif mask == 10: # 1010 TL+BR
                        cap=1; flip=0; rot=0
                    elif mask == 5:  # 0101 TR+BL
                        cap=1; flip=1; rot=0 # or rot 1
                        
                    # Inverse Corners (3 High, 1 Low) -> Swap Base/Next and treat as 1 High Corner of Low
                    # Mask 0111 (7) -> TL is Low.
                    elif mask in [7, 11, 13, 14]:
                        # Swap
                        temp = base_mat
                        base_mat = next_mat
                        next_mat = temp
                        # Invert mask (bitwise not & 15)
                        inv_mask = (~mask) & 15
                        # Re-process as Corner
                        if inv_mask == 8: # TL
                            cap=0; flip=0; rot=0
                        elif inv_mask == 4: # TR
                            cap=0; flip=0; rot=3
                        elif inv_mask == 2: # BR
                            cap=0; flip=0; rot=2
                        elif inv_mask == 1: # BL
                            cap=0; flip=0; rot=1
                            
                    entry = AutoPainter.encode_entry(base_mat, next_mat, cap, flip, rot, variant=0)
                
                mat_data[y, x] = entry
                
        return mat_data

    @staticmethod
    def encode_entry(base, next_mat, cap, flip, rot, variant=0):
        """
        Constructs the 16-bit MAT entry.
        0-1: Variant
        2-3: Unused
        4-5: Rotation
        6: Flip
        7: Cap
        8-11: Next
        12-15: Base
        """
        entry = 0
        entry |= (variant & 0x3)
        entry |= ((rot & 0x3) << 4)
        entry |= ((flip & 0x1) << 6)
        entry |= ((cap & 0x1) << 7)
        entry |= ((next_mat & 0xF) << 8)
        entry |= ((base & 0xF) << 12)
        return entry

class TRNParser:
    @staticmethod
    def parse(path):
        data = {
            "MinX": 0.0, "MinZ": 0.0, "MaterialName": None,
            "Width": None, "Depth": None,
            "TextureTypes": [] # List of found IDs
        }
        if not os.path.exists(path):
            return data
        try:
            doc = TRNDocument.read(path)
        except Exception as e:
            print(f"TRN Parser Error: {e}")
            return data
        size = doc.size
        data.update(MinX=size.min_x, MinZ=size.min_z, Width=size.width, Depth=size.depth,
                    MaterialName=doc.material_name, TextureTypes=sorted(doc.texture_types()))
        return data

class BZNParser:
    @staticmethod
    def parse(path):
        objects = []
        paths = []
        
        if not os.path.exists(path):
            return objects, paths
            
        try:
            with open(path, 'r') as f:
                # Check for binary chars in first chunk to fail fast
                try:
                    chunk = f.read(1024)
                    if '\0' in chunk:
                        raise UnicodeDecodeError("Binary check", b"", 0, 0, "Null byte found")
                    f.seek(0)
                    lines = f.readlines()
                except UnicodeDecodeError:
                    raise ValueError("Binary BZN file detected. Please save as ASCII using '/asciisave' game argument.")
            
            current_obj = None
            in_game_object = False
            
            i = 0
            while i < len(lines):
                line = lines[i].strip()
                
                if line == "[GameObject]":
                    if current_obj:
                        objects.append(current_obj)
                    in_game_object = True
                    current_obj = {
                        "name": "Unknown", 
                        "odf": "Unknown", 
                        "pos": (0,0,0), 
                        "rot": 0,
                        "label": None
                    }
                    
                    # Look ahead for immediate name/odf
                    if i + 2 < len(lines):
                        current_obj["name"] = lines[i+1].strip()
                        current_obj["odf"] = lines[i+2].strip()
                        i += 2
                
                elif line == "[AiPath]":
                    if current_obj:
                        objects.append(current_obj)
                        current_obj = None
                    in_game_object = False
                    # Path parsing can be added here
                    
                elif in_game_object and current_obj:
                    if line.startswith("label ="):
                        current_obj["label"] = line.split("=", 1)[1].strip()
                        
                    elif "seqno [" in line:
                        # Parse Position (Based on BZMapIO logic)
                        # seqno [1] is at lines[i]
                        # BZMapIO: X at i+8, Z at i+4 (inverted?), Y at i+6
                        # Wait, BZMapIO said:
                        # loc[0] (X) = line[x+8] - MinZ  <-- Swapped axis?
                        # loc[1] (Y) = line[x+4]*-1 - MinX
                        # loc[2] (Z) = line[x+6] - MinHeight
                        
                        # Let's try to parse the block safely
                        try:
                            # Typically seqno block is 
                            # seqno [1]
                            # 4 (count?)
                            # val1
                            # val2 ...
                            
                            # Let's just store raw values if possible, or try to interpret
                            # Using BZMapIO logic for now assuming standard format
                            if i + 8 < len(lines):
                                # BZ coords are X, Z, Y (Up). 
                                # WorldBuilder uses X, Y (Top-Down).
                                # BZMapIO seems to swap X/Z for Blender coords.
                                
                                # Let's assume lines[i+4] is X-ish and lines[i+8] is Z-ish
                                # We will clarify coordinates when visualizing
                                raw_x = float(lines[i+4].strip())
                                raw_h = float(lines[i+6].strip())
                                raw_z = float(lines[i+8].strip())
                                current_obj["pos"] = (raw_x, raw_h, raw_z)
                        except:
                            pass
                            
                i += 1
            
            if current_obj:
                objects.append(current_obj)
                
        except Exception as e:
            print(f"BZN Parser Error: {e}")
            raise e
            
        return objects, paths

class BZ98TRNArchitect:
    def __init__(self, root):
        self.root = root # Keep reference to main root
        self.root.title("BZ98 Redux: World Builder Suite")
        self.root.geometry("1400x950")
        self.root.configure(bg=BZ_BG)
        
        # Font/Icon logic - Moved up for config loading
        # Toolbox layout: bundled resources beside this module, per-user
        # state in the toolbox data directory.
        self.resource_dir = os.path.dirname(os.path.abspath(__file__))
        self.base_dir = str(module_data_dir("world"))

        self.config = self.load_config()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        # Initialize variables first to prevent AttributeErrors
        self.sky_prefix_var = tk.StringVar(value="pmars")
        self.hg2_path = tk.StringVar() 
        
# Use self. to make it an instance attribute
        self.map_presets = [
            "Tiny (1280m)", "Small (2560m)", "Medium (5120m)", 
            "Large (10240m)", "Huge (20480m)", "Custom",
            "World Machine (1024m)", "World Machine (2048m)"
        ]
        
        self.selected_preset = tk.StringVar(value=self.map_presets[2]) # Defaults to Medium
        
        self.hg2_width_meters = tk.IntVar(value=5120)
        self.hg2_depth_meters = tk.IntVar(value=5120)

        # --- Variables ---
        self.planet_var = tk.StringVar(value=self.config.get("planet_prefix", "AC"))
        self.tile_res_var = tk.IntVar(value=self.config.get("tile_res", 512))
        # self.synthetic_mode = tk.BooleanVar(value=True)
        self.style_var = tk.StringVar(value=self.config.get("style", "Square/Blocky"))
        self.depth_var = tk.DoubleVar(value=self.config.get("depth", 0.10))
        self.teeth_count = tk.IntVar(value=self.config.get("teeth", 12))
        self.jitter_var = tk.DoubleVar(value=self.config.get("jitter", 0.0))
        self.blend_softness = tk.IntVar(value=self.config.get("softness", 0))
        self.seed_var = tk.IntVar(value=random.randint(0, 99999))
        self.sky_input_path = tk.StringVar()
        self.sky_rotation = tk.DoubleVar(value=0.0)
        self.sky_out_res = tk.IntVar(value=2048)
        self.zoom_level = 0.25
        self.trans_mode_var = tk.StringVar(value=self.config.get("trans_mode", "Linear"))
        self.trans_mode_var.trace_add("write", self.update_preview)
        self.trans_mode_var.trace_add("write", lambda *args: self.update_preview())
        self.style_var.trace_add("write", lambda *args: self.update_preview())
        
        self.export_dds = tk.BooleanVar(value=self.config.get("exp_dds", True))
        self.export_mat = tk.BooleanVar(value=self.config.get("exp_mat", True))
        self.export_trn = tk.BooleanVar(value=self.config.get("exp_trn", True))
        
        # HG2 Conversion Control Variables
        self.hg2_target_zw = tk.IntVar(value=8) # Default 8 zones wide
        self.hg2_target_zl = tk.IntVar(value=8) # Default 8 zones long
        self.hg2_brightness = tk.DoubleVar(value=1.0)
        self.hg2_contrast = tk.DoubleVar(value=1.0)
        self.hg2_smooth_val = tk.IntVar(value=0)
        self.hg2img_compat = tk.BooleanVar(value=self.config.get("hg2img_compat", True))
        self.hg2img_precision = tk.BooleanVar(value=self.config.get("hg2img_precision", True))
        self.hgt_output = tk.BooleanVar(value=self.config.get("hgt_output", False))
        
        # Legacy Atlas Variables
        self.legacy_source_dir = tk.StringVar()
        self.legacy_out_dir = tk.StringVar()
        self.legacy_pal_path = tk.StringVar()
        self.legacy_prefix = tk.StringVar(value="legacy")

        # Export Toggles
        self.exp_png = tk.BooleanVar(value=self.config.get("exp_png", False))
        self.exp_dds = tk.BooleanVar(value=self.config.get("exp_dds", True))
        self.exp_csv = tk.BooleanVar(value=self.config.get("exp_csv", True))
        self.exp_trn = tk.BooleanVar(value=self.config.get("exp_trn", True))
        self.exp_mat = tk.BooleanVar(value=self.config.get("exp_mat", True))
        self.exp_normal = tk.BooleanVar(value=self.config.get("exp_normal", False))
        self.exp_specular = tk.BooleanVar(value=self.config.get("exp_specular", False))
        self.exp_emissive = tk.BooleanVar(value=self.config.get("exp_emissive", False))
        
        self.source_dir = ""
        self.groups = {} 
        self.full_atlas_preview = None
        self.preview_tk = None
        
        self.style_presets = {
            "Custom": {},
            "Tech Base (Blocky)": {"style": "Square/Blocky", "depth": 0.1, "teeth": 12, "jitter": 0.0, "soft": 0},
            "Rocky Terrain": {"style": "Sawtooth", "depth": 0.15, "teeth": 25, "jitter": 5.0, "soft": 1},
            "Alien Organic": {"style": "Plasma/Circuit", "depth": 0.2, "teeth": 8, "jitter": 15.0, "soft": 0},
            "Soft Snow/Sand": {"style": "Fractal Noise", "depth": 0.12, "teeth": 10, "jitter": 2.0, "soft": 8},
            "Digital/Matrix": {"style": "Binary Dither", "depth": 0.05, "teeth": 40, "jitter": 0.0, "soft": 0}
        }
        self.selected_style_preset = tk.StringVar(value="Custom")

        # Stock Map Variables
        self.stock_map_name = tk.StringVar()
        self.stock_world_type = tk.StringVar(value="Moon")
        self.stock_size_preset = tk.StringVar(value="Medium (5120m)")
        self.stock_time = tk.IntVar(value=1100)
        
        # Lighting (RGB)
        self.light_diffuse = (tk.DoubleVar(value=1.0), tk.DoubleVar(value=1.0), tk.DoubleVar(value=1.0))
        self.light_ambient = (tk.DoubleVar(value=1.0), tk.DoubleVar(value=1.0), tk.DoubleVar(value=1.0))
        self.light_specular = (tk.DoubleVar(value=1.0), tk.DoubleVar(value=1.0), tk.DoubleVar(value=1.0))
        
        # Audio
        self.audio_track = tk.IntVar(value=27)
        self.audio_loop_first = tk.IntVar(value=27)
        self.audio_loop_last = tk.IntVar(value=27)
        self.audio_loop_skip = tk.IntVar(value=-1)

        self.custom_font_name = bz_font("Consolas")

        apply_window_icon(self.root, self.base_dir, self.resource_dir)

        try:
            self.resample_method = Image.Resampling.LANCZOS
        except AttributeError:
            self.resample_method = Image.LANCZOS

        self.setup_styles()
        self.setup_ui()
        self.bind_events()

    def load_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r') as f:
                    data = json.load(f)
                    # Convert relative path back to absolute
                    if "out_dir" in data and data["out_dir"] and not os.path.isabs(data["out_dir"]):
                        data["out_dir"] = os.path.normpath(os.path.join(self.base_dir, data["out_dir"]))
                    return data
            except: pass
        return {}

    def on_close(self):
        def make_rel(path):
            if not path: return ""
            try:
                if os.path.splitdrive(path)[0].lower() == os.path.splitdrive(self.base_dir)[0].lower():
                    return os.path.relpath(path, self.base_dir)
            except: pass
            return path

        cfg = {
            "planet_prefix": self.planet_var.get(),
            "tile_res": self.tile_res_var.get(),
            "trans_mode": self.trans_mode_var.get(),
            "style": self.style_var.get(),
            "depth": self.depth_var.get(),
            "teeth": self.teeth_count.get(),
            "jitter": self.jitter_var.get(),
            "softness": self.blend_softness.get(),
            "out_dir": make_rel(self.out_dir_var.get()),
            "exp_dds": self.exp_dds.get(),
            "exp_mat": self.exp_mat.get(),
            "exp_trn": self.exp_trn.get(),
            "exp_normal": self.exp_normal.get(),
            "hg2img_compat": self.hg2img_compat.get(),
            "hg2img_precision": self.hg2img_precision.get(),
            "hgt_output": self.hgt_output.get()
        }
        with open(CONFIG_FILE, 'w') as f:
            json.dump(cfg, f, indent=4)
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
        style.configure("Vertical.TScrollbar", background="#1a1a1a", troughcolor=BZ_BG, arrowcolor=BZ_GREEN)
        style.configure("TCheckbutton", background=BZ_BG, foreground=BZ_FG, indicatorcolor=BZ_BG, indicatoron=True)
        style.map("TEntry", fieldbackground=[("readonly", "#1a1a1a")], foreground=[("readonly", BZ_CYAN)])
        style.configure("TCombobox", fieldbackground="#1a1a1a", foreground=BZ_CYAN, arrowcolor=BZ_GREEN)
        style.map("TCombobox", fieldbackground=[("readonly", "#1a1a1a")], foreground=[("readonly", BZ_CYAN)])
        style.configure("TMenubutton", background="#1a1a1a", foreground=BZ_CYAN)
        style.map("TMenubutton", background=[("active", BZ_DARK_GREEN)], foreground=[("active", BZ_GREEN)])
    
    def setup_help_tab(self):
        container = ttk.Frame(self.tab_help, padding=30)
        container.pack(fill="both", expand=True)

        ttk.Label(container, text="World Builder Suite Guide", font=(self.custom_font_name, 16, "bold")).pack(anchor="w", pady=(0, 20))

        # Main horizontal split
        columns_frame = ttk.Frame(container)
        columns_frame.pack(fill="both", expand=True)

        # --- COLUMN 1: ATLAS CREATOR (LEFT) ---
        left_col = ttk.Frame(columns_frame)
        left_col.pack(side="left", fill="both", expand=True, padx=(0, 20))

        ttk.Label(left_col, text="ATLAS CREATOR", font=(self.custom_font_name, 11, "bold"), foreground=BZ_GREEN).pack(anchor="w")
        help_box_left = tk.Text(left_col, font=("Consolas", 10), bg="#050505", fg=BZ_FG, relief="flat", wrap="word", insertbackground=BZ_GREEN)
        help_box_left.pack(fill="both", expand=True, pady=10)

        atlas_guide = (
            "HOW TO USE THE ATLAS CREATOR\n\n"
            "1. NAVIGATION TIPS\n"
            "   - PREVIEW PAN: Click and drag with the Left Mouse Button to move the atlas preview.\n"
            "   - PREVIEW ZOOM: Use the Mouse Wheel to zoom in and out of the texture tiles.\n"
            "   - CONTROL PANEL: If the options on the left are cut off, use the Scroll Wheel or the \n"
            "     scrollbar on the far left edge to reveal the 'Build' button.\n\n"
            "2. PREPARE SOURCE TEXTURES\n"
            "   - Place your solid textures in a single folder.\n"
            "   - Name them S0.dds (or PNG), S1.dds, S2.dds, etc. (up to S9).\n"
            "   - Variations (e.g., S0_B.dds) are automatically used for randomization.\n\n"
            "3. TRANSITION LOGIC (Quantity of Tiles)\n"
            "   - LINEAR: Creates a sequence. S0 links to S1, S1 links to S2, etc. Best for biomes.\n"
            "   - MATRIX: Creates every possible combination. Every S# links to every other S#.\n\n"
            "4. PATTERN ENGINE (The 'Look')\n"
            "   - STYLE: Sets the visual transition shape (e.g., 'Square/Blocky' for tech, 'Soft Clouds').\n"
            "   - EDGE DEPTH: How far the transition effect reaches into the solid tiles.\n"
            "   - FREQUENCY: The density of the transition pattern (Teeth per size).\n"
            "   - JITTER: Adds random offset to edges for a less uniform, 'hand-painted' feel.\n"
            "   - FEATHERING: Applies a blur filter to the transition mask for smoother blends.\n"
            "   - NEW SEED: Randomizes the jitter and pattern noise for the current settings.\n\n"
            "5. MAP GENERATION\n"
            "   - NORMAL MAP: Creates a 'Smart' depth map using a Sobel operator on color data.\n"
            "   - SPECULAR MAP: Creates high-contrast gloss mapping based on pixel luminosity.\n"
            "   - EMISSIVE MAP: Isolates bright colors (threshold > 220) to create glow assets.\n\n"
            "6. EXPORT FILES\n"
            "   - CSV MAPPING: A manifest identifying which tile is which for internal tools.\n"
            "   - TRN CONFIG: The terrain configuration file defining TextureTypes for the engine.\n"
            "     Note: This provides the texture tile entries ready for copy/paste into a TRN.\n"
            "   - MATERIAL FILE: The Ogre script linking textures to shaders and aliases."
        )
        help_box_left.insert("1.0", atlas_guide)
        help_box_left.config(state="disabled")

        # --- COLUMN 2: WORLD TOOLS (RIGHT) ---
        right_col = ttk.Frame(columns_frame)
        right_col.pack(side="right", fill="both", expand=True, padx=(20, 0))

        ttk.Label(right_col, text="WORLD BUILDER TOOLS", font=(self.custom_font_name, 11, "bold"), foreground=BZ_CYAN).pack(anchor="w")
        help_box_right = tk.Text(right_col, font=("Consolas", 10), bg="#050505", fg=BZ_FG, relief="flat", wrap="word", insertbackground=BZ_GREEN)
        help_box_right.pack(fill="both", expand=True, pady=10)

        tools_guide = (
            "1. CUBEMAP GENERATOR\n"
            "   • INPUT: Requires 1 high resolution equirectangular HDRI projection image.\n"
            "   • Prefix: The naming convention your textures and materials will use.\n"
            "   • RESIZE: Forces all faces to matching powers of 2 (e.g., 1024px).\n"
            "   • DDS CONVERSION: Automatically exports faces into DDS format.(Recommended)\n\n"
            "2. HG2 CONVERTER\n"
            "   • RAW DATA: Reads Battlezone heightfield data (.hg2) and converts it to a visual heightmap.\n"
            "   • PRESETS: Match your map scale (e.g., Medium 5120m) to ensure correct aspect ratios.\n     This only applies when going PNG to HG2.\n"
            "   • BRIGHTNESS/CONTRAST: Adjust to expand the dynamic range of the terrain peaks/valleys.\n       Try defaults first.\n"
            "   • SMOOTHING: Runs a Gaussian pass to remove 'stair-stepping' on low-res terrain.\n\n"
        )
        help_box_right.insert("1.0", tools_guide)
        help_box_right.config(state="disabled")

        # Footer
        ttk.Label(container, text="BZ98R World Builder | Developed by GrizzlyOne95", 
                 font=(self.custom_font_name, 8, "italic"), foreground="#666666").pack(side="bottom", anchor="w")
    
    def setup_auto_painter_ui(self):
        self.tab_paint = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_paint, text="Auto-Painter")
        
        # Layout: Left Panel (Rules), Right Panel (Rules List)
        # Actually need: Source HG2 (already loaded?), Rules List, Preview Button, Generate Button.
        
        # Top Bar: Controls
        top_frame = ttk.LabelFrame(self.tab_paint, text="Configuration")
        top_frame.pack(fill="x", padx=5, pady=5)
        
        # Rule Inputs
        r_frame = ttk.Frame(top_frame)
        r_frame.pack(fill="x", padx=5, pady=5)
        
        ttk.Label(r_frame, text="Mat ID:").pack(side="left")
        self.ap_mat_id = ttk.Entry(r_frame, width=3)
        self.ap_mat_id.pack(side="left", padx=2)
        self.ap_mat_id.insert(0, "0")
        
        ttk.Label(r_frame, text="Elev(min-max):").pack(side="left", padx=5)
        self.ap_min_h = ttk.Entry(r_frame, width=5)
        self.ap_min_h.pack(side="left")
        self.ap_min_h.insert(0, "0")
        self.ap_max_h = ttk.Entry(r_frame, width=5)
        self.ap_max_h.pack(side="left")
        self.ap_max_h.insert(0, "4095")
        
        ttk.Label(r_frame, text="Slope(min-max):").pack(side="left", padx=5)
        self.ap_min_s = ttk.Entry(r_frame, width=4)
        self.ap_min_s.pack(side="left")
        self.ap_min_s.insert(0, "0")
        self.ap_max_s = ttk.Entry(r_frame, width=4)
        self.ap_max_s.pack(side="left")
        self.ap_max_s.insert(0, "90")
        
        ttk.Label(r_frame, text="Mask:").pack(side="left", padx=5)
        self.ap_mask_path = ttk.Entry(r_frame, width=15)
        self.ap_mask_path.pack(side="left")
        ttk.Button(r_frame, text="...", command=self.browse_ap_mask, width=3).pack(side="left", padx=2)
        
        ttk.Button(r_frame, text="Add/Update Rule", command=self.add_paint_rule).pack(side="left", padx=10)
        
        # Rules List
        list_frame = ttk.Frame(self.tab_paint)
        list_frame.pack(fill="both", expand=True, padx=5, pady=5)
        
        cols = ("ID", "Height", "Slope", "Mask")
        self.rules_tree = ttk.Treeview(list_frame, columns=cols, show="headings", height=8)
        
        # Sort logic: click header to sort
        self.rules_tree.heading("ID", text="Mat ID", command=lambda: self.sort_paint_rules("mat_id"))
        self.rules_tree.heading("Height", text="Elevation Range", command=lambda: self.sort_paint_rules("min_h"))
        self.rules_tree.heading("Slope", text="Slope Range", command=lambda: self.sort_paint_rules("min_s"))
        self.rules_tree.heading("Mask", text="Image Mask", command=lambda: self.sort_paint_rules("mask_path"))
        
        self.rules_tree.column("Mask", width=150)
        
        self.rules_tree.pack(side="left", fill="both", expand=True)
        
        # Buttons
        btn_frame = ttk.Frame(self.tab_paint)
        btn_frame.pack(fill="x", padx=5, pady=5)
        
        ttk.Button(btn_frame, text="Load TRN/Rules...", command=self.load_auto_painter_config).pack(side="left", padx=2)
        ttk.Button(btn_frame, text="Save Rules...", command=self.save_auto_painter_config).pack(side="left", padx=2)
        ttk.Button(btn_frame, text="Auto-Balance", command=self.auto_balance_rules).pack(side="left", padx=2)
        ttk.Button(btn_frame, text="Validate", command=self.validate_rules).pack(side="left", padx=2)
        
        ttk.Button(btn_frame, text="Load BZN Paths...", command=self.load_bzn_paths).pack(side="left", padx=2)
        ttk.Button(btn_frame, text="Generate .MAT...", command=self.run_auto_painter).pack(side="right", padx=2)
        
        # Store rules
        self.paint_rules = []
        self.bzn_paths = []
        self.sort_descending = False

    def sort_paint_rules(self, key):
        self.sort_descending = not self.sort_descending
        self.paint_rules.sort(key=lambda x: x[key], reverse=self.sort_descending)
        self.refresh_rules_list()
        
    def add_paint_rule(self):
        try:
            mid = int(self.ap_mat_id.get())
            minh = float(self.ap_min_h.get())
            maxh = float(self.ap_max_h.get())
            mins = float(self.ap_min_s.get())
            maxs = float(self.ap_max_s.get())
            mpath = self.ap_mask_path.get()
            
            rule = {
                'mat_id': mid,
                'min_h': minh, 'max_h': maxh,
                'min_s': mins, 'max_s': maxs,
                'mask_path': mpath
            }
            self.paint_rules.append(rule)
            self.refresh_rules_list()
            # Clear fields
            self.ap_mask_path.delete(0, 'end')
        except ValueError:
            messagebox.showerror("Error", "Invalid numeric values")
            
    def load_bzn_paths(self):
        path = filedialog.askopenfilename(filetypes=[("Battlezone Mission", "*.bzn"), ("All Files", "*.*")])
        if not path:
            return
            
        try:
            with open(path, "rb") as f:
                data = f.read()
            
            parser = BinaryBZNParser(data)
            paths = parser.load()
            
            if not paths:
                # Attempt heuristic scan if structured load failed
                paths = parser.scan_for_paths()
                
            if paths:
                self.bzn_paths = paths
                messagebox.showinfo("BZN Loaded", f"Loaded {len(paths)} paths from {os.path.basename(path)}.\n\nYou can now use 'PATH:Label' in the Mask field.")
            else:
                messagebox.showwarning("BZN Warning", "No paths found in BZN file. It might be an ASCII BZN or a different version.")
                
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load BZN: {e}")

    def browse_ap_mask(self):
        path = filedialog.askopenfilename(filetypes=[("Mask Image", "*.png *.bmp *.jpg *.tga"), ("All Files", "*.*")])
        if path:
            self.ap_mask_path.delete(0, 'end')
            self.ap_mask_path.insert(0, path)
            
    def clear_paint_rules(self):
        self.paint_rules = []
        self.refresh_rules_list()
        
    def refresh_rules_list(self):
        for i in self.rules_tree.get_children():
            self.rules_tree.delete(i)
        for r in self.paint_rules:
            m_name = os.path.basename(r.get('mask_path', ''))
            self.rules_tree.insert("", "end", values=(
                r['mat_id'], 
                f"{r['min_h']} - {r['max_h']}",
                f"{r['min_s']} - {r['max_s']}",
                m_name if m_name else "None"
            ))
            
    def run_auto_painter(self):
        # 1. Get Height Data
        if not self.hg2_path.get():
             messagebox.showerror("Error", "Please select an input image/HG2 first.")
             return
             
        # Load Data similar to convert worker
        try:
            img = Image.open(self.hg2_path.get()).convert("I;16")
            arr = np.array(img).astype(np.float32)
            # Replicate scaling logic used in HG2
            is_hg2 = self.hg2_path.get().lower().endswith(".hg2")
            
            if not is_hg2:
                arr = (arr / 65535.0) * 4095.0
            
            # Run Painter
            mat_data = AutoPainter.generate_mat(arr, self.paint_rules, bzn_paths=self.bzn_paths)
            
            # Save
            save_path = filedialog.asksaveasfilename(defaultextension=".mat", filetypes=[("Material Map", "*.mat")])
            if save_path:
                with open(save_path, "wb") as f:
                    f.write(mat_data.tobytes()) # Numpy tobytes writes simple binary array
                messagebox.showinfo("Success", f"Saved {save_path}")
                
        except Exception as e:
            messagebox.showerror("Error", f"Failed: {e}")

    def load_auto_painter_config(self):
        path = filedialog.askopenfilename(filetypes=[("Paint Config", "*.trn *.ini *.txt"), ("All Files", "*.*")])
        if not path:
            return

        ext = os.path.splitext(path)[1].lower()
        
        if ext == ".trn":
            # Load TRN -> Auto-populate materials
            data = TRNParser.parse(path)
            if not data.get("TextureTypes"):
                messagebox.showwarning("Warning", "No [TextureTypeX] sections found in TRN.")
                return
                
            if messagebox.askyesno("Confirm", "This will clear existing rules and populate from TRN. Continue?"):
                self.clear_paint_rules()
                
                # Default max height
                max_h = 1000.0
                
                for tid in data["TextureTypes"]:
                    self.add_paint_rule_internal(tid, 0, max_h, 0, 90)
                
                messagebox.showinfo("Loaded", f"Loaded {len(data['TextureTypes'])} materials from TRN.")
                
        else:
            # Load INI/TXT [LayerX] format
            try:
                import configparser
                config = configparser.ConfigParser()
                config.read(path)
                
                new_rules = []
                for section in config.sections():
                    if section.lower().startswith("layer"):
                        try:
                            mat_str = config.get(section, "Material")
                            mat_id = int(mat_str.split('(')[0].strip())
                            
                            min_h = float(config.get(section, "ElevationStart"))
                            max_h = float(config.get(section, "ElevationEnd"))
                            min_s = float(config.get(section, "SlopeStart"))
                            max_s = float(config.get(section, "SlopeEnd"))
                            mask_path = config.get(section, "MaskPath") if config.has_option(section, "MaskPath") else ""
                            
                            new_rules.append({
                                'mat_id': mat_id,
                                'min_h': min_h, 'max_h': max_h,
                                'min_s': min_s, 'max_s': max_s,
                                'mask_path': mask_path
                            })
                        except Exception as e:
                            print(f"Skipping section {section}: {e}")
                            
                if new_rules:
                    if messagebox.askyesno("Confirm", f"Found {len(new_rules)} rules. Replace existing?"):
                        self.paint_rules = new_rules
                        self.refresh_rules_list()
            except Exception as e:
                messagebox.showerror("Error", f"Failed to parse INI: {e}")

    def save_auto_painter_config(self):
        path = filedialog.asksaveasfilename(defaultextension=".ini", filetypes=[("INI Config", "*.ini")])
        if not path:
            return
            
        try:
            with open(path, 'w') as f:
                for i, rule in enumerate(self.paint_rules):
                    f.write(f"[Layer{i}]\n")
                    f.write(f"ElevationStart = {rule['min_h']}\n")
                    f.write(f"ElevationEnd   = {rule['max_h']}\n")
                    f.write(f"SlopeStart     = {rule['min_s']}\n")
                    f.write(f"SlopeEnd       = {rule['max_s']}\n")
                    f.write(f"Material       = {rule['mat_id']}\n")
                    if rule.get('mask_path'):
                        f.write(f"MaskPath       = {rule['mask_path']}\n")
                    f.write("\n")
            messagebox.showinfo("Success", "Rules saved.")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save: {e}")

    def validate_rules(self):
        warnings = []
        
        for i, rule in enumerate(self.paint_rules):
            # Check basic validity
            if rule['min_h'] >= rule['max_h']:
                warnings.append(f"Rule {i}(Mat{rule['mat_id']}): Min Height >= Max Height")
            if rule['min_s'] >= rule['max_s']:
                warnings.append(f"Rule {i}(Mat{rule['mat_id']}): Min Slope >= Max Slope")
            
            # Check Bounds
            if rule['min_s'] < 0 or rule['max_s'] > 90:
                warnings.append(f"Rule {i}(Mat{rule['mat_id']}): Slope out of range (0-90)")
                
            if rule['min_h'] < 0 or rule['max_h'] > 4095:
                warnings.append(f"Rule {i}(Mat{rule['mat_id']}): Height out of valid range (0-4095)")
                
            # Check for exact duplicates (redundant)
            for j in range(i+1, len(self.paint_rules)):
                r2 = self.paint_rules[j]
                if (rule['mat_id'] == r2['mat_id'] and
                    rule['min_h'] == r2['min_h'] and rule['max_h'] == r2['max_h'] and
                    rule['min_s'] == r2['min_s'] and rule['max_s'] == r2['max_s']):
                    warnings.append(f"Rule {i} and {j} are identical duplicates.")

        # Note: Overlaps are allowed due to painter's algorithm (later rules overwrite earlier ones)
        
        if warnings:
            messagebox.showwarning("Validation Issues", "\n".join(warnings[:10]))
        else:
            messagebox.showinfo("Validation", "Rules look valid! (Overlaps are allowed)")

    def auto_balance_rules(self):
        if not self.paint_rules:
            return
        
        count = len(self.paint_rules)
        max_h = 819.1 # Max BZMapIO elevation (8191 / 10)
        chunk = max_h / count
        
        for i, rule in enumerate(self.paint_rules):
            rule['min_h'] = float(i * chunk)
            rule['max_h'] = float((i + 1) * chunk)
            rule['min_s'] = 0
            rule['max_s'] = 90
            
        self.refresh_rules_list()
        messagebox.showinfo("Auto-Balance", f"Balanced {count} rules across 0-{max_h}m.")

    def add_paint_rule_internal(self, mat_id, min_h, max_h, min_s, max_s, mask_path=""): 
        self.paint_rules.append({
            "mat_id": mat_id,
            "min_h": float(min_h),
            "max_h": float(max_h),
            "min_s": float(min_s),
            "max_s": float(max_s), "mask_path": mask_path
        })
        self.refresh_rules_list()

    def browse_hg2(self):
        path = filedialog.askopenfilename(filetypes=[("Heightmaps", "*.hg2 *.hgt *.png *.bmp")])
        if path:
            self.hg2_path.set(path)
            # Auto-detect dimensions if it's an HG2
            if path.lower().endswith(".hg2"):
                try:
                    with open(path, "rb") as f:
                        header = f.read(12)
                        _, _, z_w, z_l, _, _ = struct.unpack("<HHHHHH", header)
                        self.hg2_target_zw.set(z_w)
                        self.hg2_target_zl.set(z_l)
                except:
                    pass
            elif path.lower().endswith(".hgt"):
                try:
                    trn_path = os.path.splitext(path)[0] + ".trn"
                    trn = TRNParser.parse(trn_path)
                    if trn.get("Width") and trn.get("Depth"):
                        zw = int(round(trn["Width"] / 1280.0))
                        zl = int(round(trn["Depth"] / 1280.0))
                        if zw > 0 and zl > 0:
                            self.hg2_target_zw.set(zw)
                            self.hg2_target_zl.set(zl)
                except:
                    pass
            # Trigger preview update after selection
            self.update_hg2_preview()
            
    def load_mission_overlay(self):
        # 1. Ask for BZN file (ASCII)
        bzn_path = filedialog.askopenfilename(title="Select Mission File (ASCII)", filetypes=[("Battlezone Mission", "*.bzn")])
        if not bzn_path:
            return
            
        # 2. Try to find matching TRN
        base_path = os.path.splitext(bzn_path)[0]
        trn_path = base_path + ".trn"
        
        # 3. Parse TRN
        trn_data = TRNParser.parse(trn_path)
        self.min_x = trn_data.get("MinX", 0.0)
        self.min_z = trn_data.get("MinZ", 0.0)
        
        # 4. Parse BZN
        # 4. Parse BZN
        try:
            self.mission_objects, self.ai_paths = BZNParser.parse(bzn_path)
            
            info = f"MinX: {self.min_x}, MinZ: {self.min_z}\n"
            info += f"Objects: {len(self.mission_objects)}\n"
            info += f"Paths: {len(self.ai_paths)}"
            
            self.mission_info.config(state="normal")
            self.mission_info.delete("1.0", "end")
            self.mission_info.insert("1.0", info)
            self.mission_info.config(state="disabled")
            
            self.redraw_mission_canvas()
            
        except ValueError as e:
            messagebox.showerror("Error", str(e))
        except Exception as e:
            messagebox.showerror("Error", f"Failed to parse BZN: {e}")

    def rapid_import_wm(self):
        dir_path = filedialog.askdirectory(title="Select World Machine Project Output Folder")
        if not dir_path:
            return
            
        # Common filenames
        files = {
            "height": ["Heightmap.png", "Height.png", "output.png"],
            "flow": ["Flow.png", "erosion_flow.png"],
            "slope": ["Slopes.png", "Slope.png", "erosion_slope.png"]
        }
        
        found = {}
        for key, aliases in files.items():
            for alias in aliases:
                p = os.path.join(dir_path, alias)
                if os.path.exists(p):
                    found[key] = p
                    break
                    
        if not found.get("height"):
            messagebox.showerror("By the Beard!", "Could not find a heightmap (Heightmap.png) in this folder.")
            return
            
        # 1. Set HG2 Path
        self.hg2_path.set(found["height"])
        self.update_hg2_preview()
        
        # 2. Setup Auto-Painter Rules
        msg = f"Found:\n- Height: {os.path.basename(found['height'])}\n"
        if found.get('flow'): msg += f"- Flow: {os.path.basename(found['flow'])}\n"
        if found.get('slope'): msg += f"- Slope: {os.path.basename(found['slope'])}\n"
        msg += "\nAuto-populate paint rules based on these masks?"
        
        if messagebox.askyesno("Rapid Import", msg):
            self.clear_paint_rules()
            
            # Rule 1: Dirt/Base (Low slope)
            self.add_paint_rule_internal(0, 0, 4095, 0, 35)
            
            # Rule 2: Rock (High slope)
            if found.get("slope"):
                self.add_paint_rule_internal(1, 0, 4095, 30, 90, mask_path=found["slope"])
            else:
                 self.add_paint_rule_internal(1, 0, 4095, 30, 90)
                 
            # Rule 3: Flow/Grass (Using Flow mask)
            if found.get("flow"):
                self.add_paint_rule_internal(2, 0, 4095, 0, 90, mask_path=found["flow"])
                
            self.notebook.select(self.tab_paint)
            messagebox.showinfo("Success", "World Machine project imported. Rules populated in Auto-Painter.")





    def convert_hg2_to_png(self):
        path = self.hg2_path.get()
        if not path or not os.path.exists(path):
            return
        
        self.btn_hg2_png.config(text="CONVERTING...", state="disabled")
        try:
            if path.lower().endswith(".hg2"):
                _header, img_array = read_hg2(path)
            elif path.lower().endswith(".hgt"):
                zone_size = 128
                z_w = self.hg2_target_zw.get()
                z_l = self.hg2_target_zl.get()
                
                trn_path = os.path.splitext(path)[0] + ".trn"
                trn = TRNParser.parse(trn_path)
                if trn.get("Width") and trn.get("Depth"):
                    zw = int(round(trn["Width"] / 1280.0))
                    zl = int(round(trn["Depth"] / 1280.0))
                    if zw > 0 and zl > 0:
                        z_w, z_l = zw, zl
                
                with open(path, "rb") as f:
                    raw_data = np.frombuffer(f.read(), dtype=np.uint16)
                
                expected = z_w * z_l * zone_size * zone_size
                if raw_data.size != expected:
                    raise ValueError(f"Invalid HGT size. Expected {expected} entries, got {raw_data.size}.")
                
                full_w, full_h = z_w * zone_size, z_l * zone_size
                img_array = np.zeros((full_h, full_w), dtype=np.uint16)
                
                idx = 0
                for zy in range(z_l):
                    for zx in range(z_w):
                        start_x, start_y = zx * zone_size, zy * zone_size
                        zone_data = raw_data[idx : idx + (zone_size * zone_size)]
                        if zone_data.size == (zone_size * zone_size):
                            img_array[start_y:start_y+zone_size, start_x:start_x+zone_size] = \
                                zone_data.reshape((zone_size, zone_size))
                        idx += (zone_size * zone_size)
            else:
                raise ValueError("Unsupported input format for HG2/HGT conversion.")

            out_path = os.path.splitext(path)[0] + "_edit.png"
            
            if self.hg2img_compat.get():
                # HG2IMG legacy mode: 12-bit heights in RG, vertical flip
                h = (img_array & 0x0FFF).astype(np.uint16)
                h = np.flipud(h)
                g = (h >> 4).astype(np.uint8)
                if self.hg2img_precision.get():
                    r = (h & 0x0F).astype(np.uint8)
                else:
                    r = np.zeros_like(g, dtype=np.uint8)
                b = np.zeros_like(g, dtype=np.uint8)
                a = np.full_like(g, 255, dtype=np.uint8)
                out_img = Image.fromarray(np.dstack([r, g, b, a]), mode="RGBA")
                out_img.save(out_path)
                self.log(f"Success: Converted (HG2IMG legacy) ({out_img.width}x{out_img.height})", "success")
            else:
                # Lossless 16-bit PNG
                if path.lower().endswith(".hg2"):
                    img_array = (img_array & 0x1FFF).astype(np.uint16)
                    img_array = (np.clip(img_array, 0, 8191).astype(np.uint32) * 8).astype(np.uint16)
                else:
                    img_array = (img_array & 0x0FFF).astype(np.uint16)
                    img_array = (np.clip(img_array, 0, 4095).astype(np.uint32) * 16).astype(np.uint16)
                out_img = Image.fromarray(img_array).convert("I;16")
                out_img.save(out_path)
                self.log(f"Success: Converted ({out_img.width}x{out_img.height})", "success")
        except Exception as e:
            self.log(f"Error: Conversion failed: {e}", "error")
        finally:
            self.root.after(0, lambda: self.btn_hg2_png.config(text="HG2 -> PNG", state="normal"))

    def convert_png_to_hg2(self):
        path = self.hg2_path.get()
        if not path or not os.path.exists(path): return
        
        cfg = {
            "path": path,
            "zw": getattr(self, 'hg2_target_zw', tk.IntVar(value=8)).get(),
            "zl": getattr(self, 'hg2_target_zl', tk.IntVar(value=8)).get(),
            "brightness": self.hg2_brightness.get() if hasattr(self, 'hg2_brightness') else 1.0,
            "contrast": self.hg2_contrast.get() if hasattr(self, 'hg2_contrast') else 1.0,
            "smooth": self.hg2_smooth_val.get() if hasattr(self, 'hg2_smooth_val') else 0
        }
        self.btn_png_hg2.config(text="CONVERTING...", state="disabled")
        threading.Thread(target=self._convert_png_to_hg2_worker, args=(cfg,), daemon=True).start()

    def _convert_png_to_hg2_worker(self, cfg):
        try:
            # 1. Load the PNG
            img = Image.open(cfg["path"])
            img_mode = img.mode
            
            # 2. Dynamic Dimensions Calculation
            z_w = cfg["zw"]
            z_l = cfg["zl"]
            
            # Calculate zone_size based on image width and number of zones
            # This prevents the 512 -> 2048 scaling issue
            if z_w <= 0 or z_l <= 0:
                raise ValueError("Invalid zone dimensions.")
            if img.width % z_w != 0 or img.height % z_l != 0:
                raise ValueError("Image size is not divisible by zone dimensions.")
            zone_size = img.width // z_w
            if zone_size != (img.height // z_l):
                raise ValueError("Non-square zones detected. Check image size and zone dimensions.")
            
            # Determine depth for the HG2 header (2^depth = zone_size)
            # e.g., 64px = depth 6, 128px = depth 7, 256px = depth 8
            depth = int(math.log2(zone_size))
            if 2**depth != zone_size:
                raise ValueError("Zone size must be a power of two.")
            
            legacy_png = self.hg2img_compat.get() and img_mode not in ("I;16", "I;16B", "I;16L", "I")

            if legacy_png:
                # HG2IMG legacy PNG: 8-bit RG, vertically flipped
                img = img.convert("RGBA")
                arr = np.array(img).astype(np.uint8)
                r = arr[..., 0].astype(np.uint16)
                g = arr[..., 1].astype(np.uint16)
                use_precision = self.hg2img_precision.get()
                if use_precision and r.max() > 15:
                    self.log("HG2IMG precision disabled: R channel exceeds 0-15 (treating as green-only).", "warn")
                    use_precision = False
                if use_precision:
                    h = (g << 4) | (r & 0x0F)
                else:
                    h = (g << 4)
                h = np.flipud(h)
                
                # Apply adjusters in 16-bit space for consistency
                arr16 = (h.astype(np.float32) * 16.0)  # 0-65520
                arr16 *= cfg["brightness"]
                mean = 32768.0
                arr16 = (arr16 - mean) * cfg["contrast"] + mean
                
                if cfg["smooth"] > 0:
                    img_proc = Image.fromarray((arr16 / 256).astype(np.uint8)).convert("RGB")
                    img_proc = img_proc.filter(ImageFilter.GaussianBlur(cfg["smooth"]))
                    arr16 = np.array(img_proc.convert("L")).astype(np.float32) * 256
                
                img_final_arr = np.clip((arr16 / 16.0), 0, 4095).astype(np.uint16)
                img_final_arr = img_final_arr & 0x0FFF
            else:
                # Lossless 16-bit PNG
                img = img.convert("I;16")
                arr = np.array(img).astype(np.float32)
                arr *= cfg["brightness"]
                mean = 32768.0
                arr = (arr - mean) * cfg["contrast"] + mean
                
                # Smoothing fix for Pillow mode compatibility
                if cfg["smooth"] > 0:
                    img_proc = Image.fromarray((arr / 256).astype(np.uint8)).convert("RGB")
                    img_proc = img_proc.filter(ImageFilter.GaussianBlur(cfg["smooth"]))
                    img_final_arr = np.array(img_proc.convert("L")).astype(np.float32) * 256
                else:
                    img_final_arr = arr

                # Scale to 13-bit (HG2) or 12-bit (HGT) and mask
                if self.hgt_output.get():
                    img_final_arr = (img_final_arr.astype(np.uint32) // 16)
                    img_final_arr = np.clip(img_final_arr, 0, 4095).astype(np.uint16)
                    img_final_arr = img_final_arr & 0x0FFF
                else:
                    img_final_arr = (img_final_arr.astype(np.uint32) // 8)
                    img_final_arr = np.clip(img_final_arr, 0, 8191).astype(np.uint16)
                    img_final_arr = img_final_arr & 0x1FFF

            h, w = img_final_arr.shape 
            
            if self.hgt_output.get():
                # HGT output: 128x128 zones, no header. Flags are zeroed.
                if zone_size != 128:
                    raise ValueError("HGT requires 128x128 zones. Adjust map size/preset.")
                hgt_data = (img_final_arr & 0x0FFF).astype(np.uint16)
                output_data = bytearray()
                for zy in range(z_l):
                    for zx in range(z_w):
                        zone = hgt_data[zy*zone_size : (zy+1)*zone_size, zx*zone_size : (zx+1)*zone_size]
                        output_data.extend(zone.tobytes())
                out_path = cfg["path"].rsplit('.', 1)[0] + "_export.hgt"
                with open(out_path, "wb") as f:
                    f.write(output_data)
                self.log(f"Success: Exported {z_w}x{z_l} HGT", "success")
            else:
                out_path = cfg["path"].rsplit('.', 1)[0] + "_export.hg2"
                write_hg2(out_path, img_final_arr, z_w, z_l, zone_bits=depth)

                self.log(f"Success: Exported {z_w}x{z_l} HG2 (Zone Size: {zone_size})", "success")
            
        except Exception as e:
            self.log(f"Error: Failed to save HG2: {e}", "error")
        finally:
            self.root.after(0, lambda: self.btn_png_hg2.config(text="PNG -> HG2", state="normal"))
        
    # --- THE MISSING METHOD ---
    def create_fine_tune_slider(self, parent, label, var, from_, to, res=1.0, tip=None, command=None):
        frame = ttk.Frame(parent)
        frame.pack(fill="x", pady=2)
        lbl = ttk.Label(frame, text=label, font=(self.custom_font_name, 9)); lbl.pack(side="top", anchor="w")
        inner = ttk.Frame(frame)
        inner.pack(fill="x")
        
        if command is None:
            command = self.update_preview
            
        def adjust(delta):
            val = var.get() + delta
            var.set(round(max(from_, min(to, val)), 3))
            command()

        ttk.Button(inner, text="<", command=lambda: adjust(-res), width=2).pack(side="left")
        scale = tk.Scale(inner, from_=from_, to=to, resolution=res, orient="horizontal", 
                         variable=var, command=lambda v: command(), showvalue=True,
                         bg=BZ_BG, fg=BZ_FG, troughcolor="#1a1a1a", activebackground=BZ_GREEN, highlightthickness=0)
        scale.pack(side="left", fill="x", expand=True)
        ttk.Button(inner, text=">", command=lambda: adjust(res), width=2).pack(side="left")
        
        if tip: ToolTip(lbl, tip)

    def setup_ui(self):
        # 1. Create Notebook
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(expand=True, fill="both")

        # TAB 1: Stock Map Creator
        self.tab_stock = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_stock, text=" Stock Map Creator ")
        self.setup_stock_tab()

        # TAB 2: Custom Atlas Creator
        self.tab_trn = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_trn, text=" Custom Atlas Creator ")

        # TAB 2.5: Legacy Atlas Creator
        self.tab_legacy = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_legacy, text=" Legacy Atlas Creator ")
        self.setup_legacy_tab()

        # TAB 3: HG2 Management
        self.tab_hg2 = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_hg2, text=" HG2 Management ")
        self.setup_hg2_tab()

        # TAB 4: Cubemap Creator
        self.tab_sky = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_sky, text=" Cubemap Creator ")
        self.setup_sky_tab()

        # TAB 5: Mission Visualizer
        self.tab_mission = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_mission, text=" Mission Visualizer ")
        self.setup_mission_tab()

        # TAB 6: Auto-Painter
        self.setup_auto_painter_ui()

        # TAB 7: Help & About (LAST)
        self.tab_help = ttk.Frame(self.notebook)
        self.notebook.add(self.tab_help, text=" Help & About ")
        self.setup_help_tab()



    # --- TAB 1 CONTROLS ---
        left_container = ttk.Frame(self.tab_trn, width=360)
        left_container.pack(side="left", fill="y")
        left_container.pack_propagate(False) 

        canvas = tk.Canvas(left_container, highlightthickness=0, bg=BZ_BG)
        scrollbar = ttk.Scrollbar(left_container, orient="vertical", command=canvas.yview, style="Vertical.TScrollbar")
        ctrls = ttk.Frame(canvas, padding=15)

        ctrls.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=ctrls, anchor="nw", width=335)
        canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        
        # Help Btn
        help_btn_frame = ttk.Frame(ctrls)
        help_btn_frame.pack(fill="x", pady=(0, 10))
        ttk.Button(help_btn_frame, text="❓ About / Help", 
                  command=lambda: self.notebook.select(self.tab_help)).pack(side="right")


        # Shared wheel dispatcher: scrolls this panel only while the pointer is
        # over it (a bare bind_all would scroll it from every toolbox page).
        register_wheel_target(canvas, lambda units: canvas.yview_scroll(units, "units"))

        # --- WIDGETS ---
        # 1. SOURCE SELECT (Moved to Top)
        ttk.Button(ctrls, text="1. SELECT SOURCE FOLDER", command=self.browse).pack(fill="x", pady=(0,5))
        
        # 2. OUTPUT SELECT (Moved to Top)
        ttk.Label(ctrls, text="OUTPUT DESTINATION:", font=(self.custom_font_name, 8, "bold")).pack(anchor="w")
        out_f = ttk.Frame(ctrls)
        out_f.pack(fill="x", pady=2)
        self.out_dir_var = tk.StringVar(value=self.config.get("out_dir", "Export"))
        ttk.Entry(out_f, textvariable=self.out_dir_var, font=(self.custom_font_name, 8)).pack(side="left", fill="x", expand=True)
        ttk.Button(out_f, text="...", command=self.browse_output, width=3).pack(side="left", padx=2)

        ttk.Separator(ctrls, orient="horizontal").pack(fill="x", pady=10)

        ttk.Label(ctrls, text="PLANET CONFIG", font=(self.custom_font_name, 11, "bold"), foreground=BZ_GREEN).pack(anchor="w")
        ttk.Entry(ctrls, textvariable=self.planet_var, width=10).pack(anchor="w", pady=2)
        
        ttk.Label(ctrls, text="DESIRED TILE SIZE:").pack(anchor="w", pady=(10,0))
        res_opts = [256, 512, 1024, 2048, 4096]
        self.res_dropdown = ttk.Combobox(ctrls, textvariable=self.tile_res_var, values=res_opts, state="readonly")
        self.res_dropdown.pack(fill="x", pady=5)

        ttk.Separator(ctrls, orient="horizontal").pack(fill="x", pady=10)

        ttk.Label(ctrls, text="PATTERN ENGINE", font=(self.custom_font_name, 11, "bold"), foreground=BZ_GREEN).pack(anchor="w")
        
        ttk.Label(ctrls, text="TRANSITION LOGIC:").pack(anchor="w", pady=(10,0))
        ttk.Combobox(ctrls, textvariable=self.trans_mode_var, values=["Linear", "Matrix"], state="readonly").pack(fill="x", pady=5)
        
        self.style_dropdown = ttk.Combobox(ctrls, textvariable=self.style_var, state="readonly")
        self.style_dropdown.pack(fill="x", pady=5)

        ttk.Label(ctrls, text="STYLE PRESETS:").pack(anchor="w", pady=(10,0))
        sp_menu = ttk.Combobox(ctrls, textvariable=self.selected_style_preset, values=list(self.style_presets.keys()), state="readonly")
        sp_menu.pack(fill="x", pady=5)
        sp_menu.bind("<<ComboboxSelected>>", self.apply_style_preset)

        self.create_fine_tune_slider(ctrls, "Edge Depth:", self.depth_var, 0.0, 0.5, 0.01, "How far the transition pattern cuts into the tile.")
        self.create_fine_tune_slider(ctrls, "Frequency (Teeth/Size):", self.teeth_count, 2, 80, 1, "Density of the pattern (e.g., number of sawteeth).")
        self.create_fine_tune_slider(ctrls, "Random Jitter:", self.jitter_var, 0.0, 50.0, 0.5, "Randomizes the edges for a more organic look.")
        self.create_fine_tune_slider(ctrls, "Feathering (Blur):", self.blend_softness, 0, 50, 1, "Softens the transition edges (good for snow/sand).")

        ttk.Button(ctrls, text="🎲 NEW SEED", command=self.cycle_seed).pack(fill="x", pady=5)
        self.info_label = ttk.Label(ctrls, text="Atlas Size: 0x0", foreground="#666666")
        self.info_label.pack(fill="x", pady=5)

        ttk.Separator(ctrls, orient="horizontal").pack(fill="x", pady=15)

        # Output Settings
        ttk.Label(ctrls, text="OUTPUT OPTIONS", font=(self.custom_font_name, 10, "bold"), foreground=BZ_GREEN).pack(anchor="w")
        for text, var in [
            ("Export PNG (Preview)", self.exp_png),
            ("Export DDS (Production)", self.exp_dds),
            ("Export Normal Map", self.exp_normal),
            ("Export Specular Map", self.exp_specular),
            ("Export Emissive Map", self.exp_emissive),
            ("Export CSV Mapping", self.exp_csv),
            ("Export .TRN Config", self.exp_trn),
            ("Export .material File", self.exp_mat)
        ]:
            ttk.Checkbutton(ctrls, text=text, variable=var).pack(anchor="w")

        ttk.Separator(ctrls, orient="horizontal").pack(fill="x", pady=15)

        self.btn_generate = ttk.Button(ctrls, text="2. BUILD ATLAS", command=self.generate, style="Success.TButton")
        self.btn_generate.pack(fill="x", pady=(15, 20))

        # --- TAB 1 PREVIEW ---
        pre_frame = ttk.Frame(self.tab_trn)
        pre_frame.pack(side="right", expand=True, fill="both")
        self.canvas = tk.Canvas(pre_frame, bg="#050505", highlightthickness=0)
        self.canvas.pack(side="left", expand=True, fill="both")
        self.on_mode_change()
        
        # --- LOG CONSOLE ---
        self.log_frame = ttk.Frame(self.root, padding=5)
        self.log_frame.pack(side="bottom", fill="x")
        self.log_box = tk.Text(self.log_frame, height=6, state="disabled", bg="#050505", fg=BZ_FG, font=("Consolas", 9))
        self.log_box.pack(fill="both", expand=True)
        self.log_box.tag_config("info", foreground=BZ_CYAN)
        self.log_box.tag_config("success", foreground=BZ_GREEN)
        self.log_box.tag_config("error", foreground="#ff5555")
        self.log_box.tag_config("warning", foreground="#ffff55")
        self.log_box.tag_config("timestamp", foreground="#666666")
        
        self.print_welcome_log()

    def print_welcome_log(self):
        self.log("--------------------------------------------------", "timestamp")
        self.log("   BZ98 REDUX WORLD BUILDER SUITE - INITIALIZED   ", "success")
        self.log("--------------------------------------------------", "timestamp")
        self.log("• Stock Map Creator: Generate standard multiplayer maps", "info")
        self.log("• Atlas Creator: Build custom terrain texture atlases", "info")
        self.log("• HG2 Management: Convert and edit heightmaps", "info")
        self.log("• Cubemap Creator: Generate skyboxes from panoramas", "info")
        self.log("Select a tab to begin operations.", "timestamp")

    def setup_stock_tab(self):
        container = ttk.Frame(self.tab_stock, padding=20)
        container.pack(fill="both", expand=True)

        # --- LEFT COLUMN: CONFIG ---
        left_col = ttk.LabelFrame(container, text=" Map Configuration ", padding=15)
        left_col.pack(side="left", fill="both", expand=True, padx=(0, 10))

        # Map Name (Validated)
        ttk.Label(left_col, text="Map Name (Max 8 chars, Alpha only):").pack(anchor="w")
        ttk.Label(left_col, text="Map Name (Max 8 chars, Alphanumeric):").pack(anchor="w")
        vcmd = (self.root.register(self.validate_map_name), '%P')
        entry_name = ttk.Entry(left_col, textvariable=self.stock_map_name, validate="key", validatecommand=vcmd)
        entry_name.pack(fill="x", pady=(0, 10))
        ToolTip(entry_name, "Internal name for the map (e.g., 'MULTI01'). Must be 8 letters or less.")
        ToolTip(entry_name, "Internal name for the map (e.g., 'MULTI01'). Must be 8 characters or less (Letters/Numbers).")

        # World Type
        ttk.Label(left_col, text="World / Biome:").pack(anchor="w")
        worlds = ["Moon", "Achilles", "Europa", "Venus", "Mars", "Io", "Ganymede", "Elysium"]
        ttk.Combobox(left_col, textvariable=self.stock_world_type, values=worlds, state="readonly").pack(fill="x", pady=(0, 10))

        # Size
        ttk.Label(left_col, text="Map Size:").pack(anchor="w")
        ttk.Combobox(left_col, textvariable=self.stock_size_preset, values=self.map_presets, state="readonly").pack(fill="x", pady=(0, 10))

        # Time
        ttk.Label(left_col, text="Time of Day (0-2400):").pack(anchor="w")
        tk.Scale(left_col, variable=self.stock_time, from_=0, to=2400, orient="horizontal", 
                 bg=BZ_BG, fg=BZ_FG, troughcolor="#1a1a1a", activebackground=BZ_GREEN, highlightthickness=0).pack(fill="x", pady=(0, 10))

        # Audio Settings (Undocumented Params)
        ttk.Label(left_col, text="Audio / CD Track Settings:", foreground=BZ_CYAN).pack(anchor="w", pady=(10, 5))
        
        aud_grid = ttk.Frame(left_col)
        aud_grid.pack(fill="x")
        
        for i, (label, var, tip) in enumerate([
            ("Track:", self.audio_track, "The specific CD track index to play when the mission starts."),
            ("Loop First:", self.audio_loop_first, "The starting track index of the ambient playlist loop."),
            ("Loop Last:", self.audio_loop_last, "The ending track index of the ambient playlist loop."),
            ("Loop Skip:", self.audio_loop_skip, "A track index within the range to SKIP (e.g. victory themes). Set -1 to skip nothing.")
        ]):
            ttk.Label(aud_grid, text=label, font=("Consolas", 8)).grid(row=i//2, column=(i%2)*2, sticky="w", padx=5)
            ent = ttk.Entry(aud_grid, textvariable=var, width=5)
            ent.grid(row=i//2, column=(i%2)*2+1, sticky="w")
            ToolTip(ent, tip)

        # --- RIGHT COLUMN: LIGHTING & BUILD ---
        right_col = ttk.LabelFrame(container, text=" Lighting & Build ", padding=15)
        right_col.pack(side="right", fill="both", expand=True, padx=(10, 0))

        def create_rgb_slider(parent, label, vars):
            f = ttk.Frame(parent)
            f.pack(fill="x", pady=5)
            ttk.Label(f, text=label, font="bold").pack(anchor="w")
            
            sub = ttk.Frame(f)
            sub.pack(fill="x")
            
            colors = {"R": "#ff5555", "G": "#55ff55", "B": "#5555ff"}
            
            for i, (col, var) in enumerate(zip(["R", "G", "B"], vars)):
                c_hex = colors[col]
                l = ttk.Label(sub, text=col, foreground=c_hex)
                l.pack(side="left", padx=(5, 0))
                s = tk.Scale(sub, variable=var, from_=0.0, to=3.0, resolution=0.05, orient="horizontal", showvalue=1,
                             bg=BZ_BG, fg=BZ_FG, troughcolor="#1a1a1a", activebackground=c_hex, highlightthickness=0)
                s.pack(side="left", fill="x", expand=True)

        create_rgb_slider(right_col, "Sun / Diffuse Color", self.light_diffuse)
        create_rgb_slider(right_col, "Ambient Color", self.light_ambient)
        create_rgb_slider(right_col, "Specular Color", self.light_specular)
        ttk.Button(right_col, text="RESET LIGHTING", command=self.reset_lighting_defaults).pack(fill="x", pady=5)

        ttk.Separator(right_col, orient="horizontal").pack(fill="x", pady=20)

        self.btn_stock_gen = ttk.Button(right_col, text="GENERATE MAP FILES", command=self.generate_stock_map, style="Success.TButton")
        self.btn_stock_gen.pack(fill="x", pady=10)

    def setup_legacy_tab(self):
        container = ttk.Frame(self.tab_legacy, padding=20)
        container.pack(fill="both", expand=True)
        
        ttk.Label(container, text="LEGACY ATLAS CONVERTER (BZ 1.5 -> REDUX)", font=(self.custom_font_name, 14, "bold"), foreground=BZ_GREEN).pack(anchor="w", pady=(0, 10))
        
        # Source
        src_f = ttk.LabelFrame(container, text=" Source Directory ", padding=10)
        src_f.pack(fill="x", pady=5)
        
        src_inner = ttk.Frame(src_f)
        src_inner.pack(fill="x")
        
        src_ent = ttk.Entry(src_inner, textvariable=self.legacy_source_dir)
        src_ent.pack(side="left", fill="x", expand=True, padx=5)
        ToolTip(src_ent, "Folder of .MAP terrain texture tiles")
        ttk.Button(src_inner, text="Browse", command=self.browse_legacy_source).pack(side="left")
        
        self.legacy_trn_info = tk.StringVar()
        ttk.Label(src_f, textvariable=self.legacy_trn_info, foreground=BZ_CYAN, font=("Consolas", 9)).pack(anchor="w", padx=5, pady=(5,0))
        
        # Output
        out_f = ttk.LabelFrame(container, text=" Output Directory ", padding=10)
        out_f.pack(fill="x", pady=5)
        out_ent = ttk.Entry(out_f, textvariable=self.legacy_out_dir)
        out_ent.pack(side="left", fill="x", expand=True, padx=5)
        ToolTip(out_ent, "Where redux files will be placed")
        ttk.Button(out_f, text="Browse", command=lambda: self.legacy_out_dir.set(filedialog.askdirectory())).pack(side="left")
        
        # Settings
        set_f = ttk.LabelFrame(container, text=" Conversion Settings ", padding=10)
        set_f.pack(fill="x", pady=5)
        
        ttk.Label(set_f, text="Output Prefix:").pack(side="left", padx=5)
        ttk.Entry(set_f, textvariable=self.legacy_prefix, width=15).pack(side="left", padx=5)
        
        # Format Selection
        ttk.Label(set_f, text="Format:").pack(side="left", padx=(10, 5))
        self.legacy_format = tk.StringVar(value=".dds")
        ttk.Combobox(set_f, textvariable=self.legacy_format, values=[".dds", ".png"], state="readonly", width=8).pack(side="left")

        ttk.Label(set_f, text="Palette (Optional):").pack(side="left", padx=(20, 5))
        pal_ent = ttk.Entry(set_f, textvariable=self.legacy_pal_path)
        pal_ent.pack(side="left", fill="x", expand=True, padx=5)
        ToolTip(pal_ent, "If the ported world has a custom .ACT palette file, select it here.")
        ttk.Button(set_f, text="Load .ACT", command=lambda: self.legacy_pal_path.set(filedialog.askopenfilename(filetypes=[("ACT Palette", "*.act")]))).pack(side="left")

        self.btn_legacy_gen = ttk.Button(container, text="CONVERT & BUILD ATLAS", command=self.generate_legacy_atlas, style="Success.TButton")
        self.btn_legacy_gen.pack(fill="x", pady=20)
        
        ttk.Label(container, text="* Scans for files ending in '0.map' or '0.bmp' (e.g. ca00sa0.bmp)\n* Automatically arranges tiles into an efficient grid.\n* Generates .material, .csv, and atlas image.", foreground="#888888").pack(anchor="w")

    def browse_legacy_source(self):
        path = filedialog.askdirectory()
        if path:
            self.legacy_source_dir.set(path)
            self.scan_legacy_folder(path)

    def scan_legacy_folder(self, path):
        self.legacy_trn_info.set("")
        try:
            trn_files = [f for f in os.listdir(path) if f.lower().endswith('.trn')]
            if trn_files:
                trn_file = trn_files[0]
                full_trn = os.path.join(path, trn_file)
                with open(full_trn, 'r', errors='ignore') as f:
                    content = f.read()
                
                match = re.search(r'Palette\s*=\s*([^\s\n\r]+)', content, re.IGNORECASE)
                if match:
                    pal_name = match.group(1)
                    self.legacy_trn_info.set(f"Detected TRN: {trn_file} | Palette: {pal_name}")
                    
                    local_pal = os.path.join(path, pal_name)
                    if os.path.exists(local_pal):
                        self.legacy_pal_path.set(local_pal)
                        self.log(f"Auto-selected palette: {local_pal}", "success")
                else:
                    self.legacy_trn_info.set(f"Detected TRN: {trn_file} (No Palette defined)")
        except Exception as e:
            self.log(f"Error scanning source: {e}", "error")

    def generate_legacy_atlas(self):
        src = self.legacy_source_dir.get()
        out = self.legacy_out_dir.get()
        if not src or not out:
            messagebox.showerror("Error", "Please select source and output directories.")
            return
            
        self.btn_legacy_gen.config(text="PROCESSING...", state="disabled")
        threading.Thread(target=self._generate_legacy_worker, args=(src, out), daemon=True).start()

    # ------------------------------------------------------------------
    #  Legacy (BZ 1.5 -> Redux) conversion helpers
    # ------------------------------------------------------------------

    # A sky dome / backdrop: opaque, unlit, no depth write.
    SKY_MAT_TEMPLATE = """material %(mat)s
{
\ttechnique
\t{
\t\tpass
\t\t{
\t\t\tvertex_program_ref Effect_vertex
\t\t\t{
\t\t\t}
\t\t\tfragment_program_ref Effect_fragment
\t\t\t{
\t\t\t}

\t\t\tlighting off
\t\t\tdepth_write off
\t\t\ttexture_unit
\t\t\t{
\t\t\t\ttexture %(tex)s
\t\t\t}
\t\t}
\t}
}
"""

    # A cloud layer: same programs as the dome but alpha blended, two sided.
    CLOUD_MAT_TEMPLATE = """material %(mat)s
{
\ttechnique
\t{
\t\tpass
\t\t{
\t\t\tvertex_program_ref Effect_vertex
\t\t\t{
\t\t\t}
\t\t\tfragment_program_ref Effect_fragment
\t\t\t{
\t\t\t}

\t\t\tcull_hardware none
\t\t\tlighting off
\t\t\tscene_blend alpha_blend
\t\t\tdepth_write off
\t\t\tdiffuse 1 1 1
\t\t\ttexture_unit
\t\t\t{
\t\t\t\ttexture %(tex)s
\t\t\t}
\t\t}
\t}
}
"""

    # A [Stars] / [StarList] billboard: planet, moon, milky way.
    STAR_MAT_TEMPLATE = """material %(mat)s
{
\ttechnique
\t{
\t\tpass
\t\t{
\t\t\tvertex_program_ref Sky_vertex
\t\t\t{
\t\t\t}
\t\t\tfragment_program_ref Sky_fragment
\t\t\t{
\t\t\t}

\t\t\tcull_hardware none
\t\t\tcull_software none
\t\t\tlighting off
\t\t\tfog_override true none
\t\t\tscene_blend %(blend)s
\t\t\tdepth_write off
\t\t\tdiffuse vertexcolour
\t\t\ttexture_unit
\t\t\t{
\t\t\t\ttex_address_mode clamp
\t\t\t\ttexture %(tex)s
\t\t\t}
\t\t}
\t}
}
"""

    @staticmethod
    def _next_pot(n):
        """Smallest power of two >= n."""
        n = max(1, int(n))
        return 1 << (n - 1).bit_length()

    @staticmethod
    def _find_file_ci(directory, name):
        """Case-insensitive lookup inside a directory."""
        low = name.lower()
        for f in os.listdir(directory):
            if f.lower() == low:
                return os.path.join(directory, f)
        return None

    @staticmethod
    def _neighbour_count(mask):
        c = np.zeros(mask.shape, dtype=np.uint8)
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1),
                       (1, 1), (1, -1), (-1, 1), (-1, -1)):
            c += np.roll(np.roll(mask, dy, 0), dx, 1)
        return c

    def _key_background(self, idx):
        """Build an alpha mask for a legacy sprite.

        Palette index 0 is the transparent key, but only where it is actually
        the background: index-0 pixels fully enclosed by the sprite are real
        black and must stay opaque, or the sprite ends up riddled with holes.
        So flood fill index 0 inward from the border, then drop the 1px dither
        fringe those old textures carry around their silhouette.
        """
        zero = (idx == 0)
        bg = np.zeros_like(zero)
        bg[0, :] |= zero[0, :]
        bg[-1, :] |= zero[-1, :]
        bg[:, 0] |= zero[:, 0]
        bg[:, -1] |= zero[:, -1]
        while True:
            grown = bg.copy()
            for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                grown |= np.roll(np.roll(bg, dy, 0), dx, 1)
            grown &= zero
            if (grown == bg).all():
                break
            bg = grown

        opaque = ~bg
        # Morphological opening: erode, then dilate, keeping only what survived.
        eroded = opaque & (self._neighbour_count(opaque) >= 6)
        opaque = opaque & (eroded | (self._neighbour_count(eroded) >= 5))
        return opaque

    def _bleed_rgb(self, rgb, opaque, rounds=6):
        """Push opaque colour out into the keyed region so that bilinear
        filtering and mip generation cannot drag the key colour back in as a
        dark fringe around the sprite."""
        work = rgb.astype(np.uint16).copy()
        mask = opaque.copy()
        for _ in range(rounds):
            acc = np.zeros_like(work)
            cnt = np.zeros(mask.shape, dtype=np.uint16)
            for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1),
                           (1, 1), (1, -1), (-1, 1), (-1, -1)):
                acc += (np.roll(np.roll(work, dy, 0), dx, 1)
                        * np.roll(np.roll(mask, dy, 0), dx, 1)[..., None])
                cnt += np.roll(np.roll(mask, dy, 0), dx, 1)
            grow = (~mask) & (cnt > 0)
            if not grow.any():
                break
            work[grow] = acc[grow] // np.maximum(cnt[grow], 1)[..., None]
            mask |= grow
        return work.astype(np.uint8)

    def _write_atlas_dds(self, path, cells, grid, tile_px):
        """Write a DXT1 atlas with a mip chain, matching how the stock Redux
        terrain atlases are built.

        Each mip level is packed from tiles downsampled *individually*, so a
        tile never bleeds into its neighbour at low mips. The chain stops once
        a tile is 4px, which is exactly the 7 levels stock ships for its 4x4
        256px atlases.
        """
        levels = max(1, tile_px.bit_length() - 2)
        payload = b""
        for lvl in range(levels):
            t = tile_px >> lvl
            dim = grid * t
            img = Image.new("RGBA", (dim, dim), (0, 0, 0, 255))
            for gx, gy, tile in cells:
                sub = tile if t == tile_px else tile.resize((t, t), Image.LANCZOS)
                img.paste(sub, (gx * t, gy * t))
            img.putalpha(255)
            buf = io.BytesIO()
            img.save(buf, format="DDS", pixel_format="DXT1")
            payload += buf.getvalue()[128:]

        dim0 = grid * tile_px
        hdr = bytearray(128)
        hdr[0:4] = b"DDS "
        struct.pack_into('<I', hdr, 4, 124)                 # dwSize
        struct.pack_into('<I', hdr, 8, 0x000A1007)          # CAPS|H|W|PIXELFORMAT|MIPMAPCOUNT|LINEARSIZE
        struct.pack_into('<I', hdr, 12, dim0)               # dwHeight
        struct.pack_into('<I', hdr, 16, dim0)               # dwWidth
        struct.pack_into('<I', hdr, 20, dim0 * dim0 // 2)   # linear size of mip 0
        struct.pack_into('<I', hdr, 28, levels)             # dwMipMapCount
        struct.pack_into('<I', hdr, 76, 32)                 # pixelformat dwSize
        struct.pack_into('<I', hdr, 80, 0x5)                # FOURCC | ALPHAPIXELS
        hdr[84:88] = b"DXT1"
        struct.pack_into('<I', hdr, 108, 0x00401008)        # TEXTURE|COMPLEX|MIPMAP
        with open(path, 'wb') as f:
            f.write(bytes(hdr))
            f.write(payload)
        return levels

    def _parse_trn_textures(self, trn_path):
        """Pull every .map texture reference out of a legacy .trn, tagged with
        the kind of material Redux needs for it."""
        wanted = []
        pending = []
        for section, key, val in TRNDocument.read(trn_path).map_references():
            section = section.lower()
            if section == 'sky':
                if re.match(r'^(Sky|Backdrop|Sun)Texture$', key, re.IGNORECASE):
                    wanted.append((val, 'sky', None))
            elif section == 'clouds':
                if re.match(r'^Texture\d+$', key, re.IGNORECASE):
                    wanted.append((val, 'cloud', None))
            elif section == 'stars':
                m = re.match(r'^Texture(\d+)$', key, re.IGNORECASE)
                if m:
                    pending.append((val, m.group(1)))
            elif section == 'starlist':
                if key.lower() == 'texture':
                    wanted.append((val, 'star', 'alpha_blend'))

        for val, _num in pending:
            # Every stock [Stars] planet material (earth, milkyway, saturn,
            # smjovian) is additive. That is what makes a body read as a pale
            # disc hanging in a lit daytime sky rather than a sticker pasted
            # over it, so ignore the TRN's Alpha flag and follow stock.
            # [StarList] is the little star field and alpha blends, as stock
            # stars.material does.
            wanted.append((val, 'star', 'src_alpha one'))

        seen = set()
        out = []
        for val, kind, blend in wanted:
            if val.lower() in seen:
                continue
            seen.add(val.lower())
            out.append((val, kind, blend))
        return out

    def _convert_sky_textures(self, src, out, pal, atlas_names):
        """Convert the sky / cloud / star .MAPs a .trn references into PNGs
        plus the Ogre materials Redux looks them up by.

        Redux resolves these by material NAME, which is the .map filename from
        the .trn -- so the emitted material is literally `material EARTH2.MAP`.
        Only textures that actually ship in the source folder are converted;
        anything else (acloud.map, stars.map, sun.0 ...) is stock and already
        has a material, which we must not shadow.
        """
        trns = [f for f in os.listdir(src) if f.lower().endswith('.trn')]
        if not trns:
            self.log("No .trn in source folder - skipping sky/star materials.", "warning")
            return 0

        made = 0
        for name, kind, blend in self._parse_trn_textures(os.path.join(src, trns[0])):
            path = self._find_file_ci(src, name)
            if not path:
                self.log(f"  {name} ({kind}) not in source folder - assuming stock.", "info")
                continue
            img = self.read_bz_map(path, pal)
            if img is None:
                self.log(f"  {name} could not be decoded.", "error")
                continue

            stem = os.path.splitext(os.path.basename(path))[0].lower()
            # A tile that is also packed into the terrain atlas needs a
            # distinct texture filename so the two uses stay separate.
            png_stem = stem + "_sky" if stem in atlas_names else stem
            png_name = png_stem + ".png"

            rgb = np.asarray(img.convert("RGB"))
            if kind == 'sky':
                Image.fromarray(rgb, "RGB").save(os.path.join(out, png_name))
            else:
                with open(path, 'rb') as f:
                    rb, fmt, h, _ = struct.unpack('<4H', f.read(8))
                    data = f.read()
                w = rb // BZMapFormat.bpp[fmt]
                if fmt == BZMapFormat.INDEXED:
                    idx = np.frombuffer(data[:w * h], dtype=np.uint8).reshape(h, w)[::-1]
                else:
                    # A 16- or 32-bit plate has no palette index to key on, and
                    # reading its payload as bytes gives half an image of noise.
                    # The convention these tiles encode is 'index 0 is the hole',
                    # and index 0 is black in every BZ palette, so key on black
                    # and hand _key_background the same 0/1 shape it expects.
                    flat = np.asarray(img.convert('RGB')).reshape(-1, 3)
                    idx = np.where(flat.sum(axis=1) == 0, 0, 1).astype(np.uint8)
                    idx = idx.reshape(np.asarray(img).shape[:2])
                opaque = self._key_background(idx)
                bled = self._bleed_rgb(rgb, opaque)
                alpha = np.where(opaque, 255, 0).astype(np.uint8)
                Image.fromarray(np.dstack([bled, alpha]), "RGBA").save(
                    os.path.join(out, png_name))

            mat_name = os.path.basename(path).upper()
            if not mat_name.upper().endswith('.MAP'):
                mat_name += '.MAP'
            if kind == 'sky':
                body = self.SKY_MAT_TEMPLATE % {"mat": mat_name, "tex": png_name}
            elif kind == 'cloud':
                body = self.CLOUD_MAT_TEMPLATE % {"mat": mat_name, "tex": png_name}
            else:
                body = self.STAR_MAT_TEMPLATE % {"mat": mat_name, "tex": png_name,
                                                 "blend": blend}
            header = (f"// Generated by World Builder from {os.path.basename(path)}\n"
                      f"// Redux looks this up by material name, which must stay "
                      f"equal to the .map the .trn references.\n")
            with open(os.path.join(out, png_stem + ".material"), 'w', newline='\n') as f:
                f.write(header + body)

            self.log(f"  {os.path.basename(path)} -> {png_name} "
                     f"(material {mat_name}, {kind})", "success")
            made += 1
        return made

    def _generate_legacy_worker(self, src, out):
        try:
            # 1. Find Files
            files = sorted(f for f in os.listdir(src)
                           if f.lower().endswith(('0.map', '0.bmp', '0.png')))
            if not files:
                self.log("No matching legacy files found (must end in 0.map, 0.bmp, or 0.png).", "warning")
                return

            # Palette: explicit choice wins, else take the one the .trn names.
            pal = BUILTIN_MOON_PALETTE
            pal_path = self.legacy_pal_path.get()
            if not (pal_path and os.path.exists(pal_path)):
                trns = [f for f in os.listdir(src) if f.lower().endswith('.trn')]
                if trns:
                    with open(os.path.join(src, trns[0]), 'r', errors='ignore') as f:
                        m = re.search(r'Palette\s*=\s*([^\s\n\r]+)', f.read(), re.IGNORECASE)
                    if m:
                        cand = self._find_file_ci(src, m.group(1).strip())
                        if cand:
                            pal_path = cand
                            self.log(f"Palette taken from {trns[0]}: {os.path.basename(cand)}", "info")
            if pal_path and os.path.exists(pal_path):
                with open(pal_path, 'rb') as f:
                    raw = f.read(768)
                    pal = [list(struct.unpack('<3B', raw[i:i + 3])) for i in range(0, 768, 3)]
            else:
                self.log("No .ACT palette found - falling back to the built-in Moon palette.", "warning")

            images, names = [], []
            name_pattern = re.compile(r'^([a-zA-Z]{2})(\d)(\d)([scd])([a-zA-Z])0$', re.IGNORECASE)
            trn_data = {}

            for f in files:
                path = os.path.join(src, f)
                try:
                    if f.lower().endswith(".map"):
                        img = self.read_bz_map(path, pal)
                    else:
                        img = Image.open(path).convert("RGBA")
                    if not img:
                        continue
                    images.append(img)
                    root_name = os.path.splitext(f)[0]
                    names.append(root_name)

                    match = name_pattern.match(root_name)
                    if not match:
                        self.log(f"{f} does not look like a terrain tile - packed, "
                                 f"but no TRN entry written.", "warning")
                        continue
                    _, t_from, t_to, kind, var = match.groups()
                    t_from = int(t_from)
                    trn_data.setdefault(t_from, [])
                    k_lower, v_upper = kind.lower(), var.upper()
                    if k_lower == 's':
                        key = f"Solid{v_upper}0"
                    elif k_lower == 'c':
                        key = f"CapTo{t_to}_{v_upper}0"
                    else:
                        key = f"DiagonalTo{t_to}_{v_upper}0"
                    trn_data[t_from].append(f"{key:<15} = {root_name.upper()}.MAP")
                except Exception as e:
                    self.log(f"Failed to load {f}: {e}", "error")

            if not images:
                return

            # 2. Atlas packing. Round the grid up to a power of two so the
            #    atlas is POT and the mip chain divides cleanly -- a 4x4 grid
            #    of 256px tiles is exactly what stock Redux ships.
            count = len(images)
            gs = self._next_pot(math.ceil(math.sqrt(count)))
            w, h = images[0].size
            atlas_size = gs * w

            uv_step = 1.0 / gs
            csv_lines = [f",0,0,{uv_step:.6g},{uv_step:.6g}"]
            cells = []
            for idx, (img, name) in enumerate(zip(images, names)):
                gx, gy = idx % gs, idx // gs
                if img.size != (w, h):
                    img = img.resize((w, h))
                cells.append((gx, gy, img.convert("RGBA")))
                u, v = gx * uv_step, gy * uv_step
                csv_lines.append(f"{name.upper()}.MAP,{u:.6g},{v:.6g},{uv_step:.6g},{uv_step:.6g}")

            if not os.path.exists(out):
                os.makedirs(out)

            prefix = self.legacy_prefix.get()
            mat_stem = f"{prefix}_detail_atlas"
            ext = self.legacy_format.get()
            atlas_file = f"{prefix}_atlas{ext}"

            if ext.lower() == ".dds":
                levels = self._write_atlas_dds(os.path.join(out, atlas_file), cells, gs, w)
                self.log(f"Atlas: {atlas_size}x{atlas_size} DXT1, {levels} mip levels.", "info")
            else:
                flat = Image.new("RGBA", (atlas_size, atlas_size), (0, 0, 0, 0))
                for gx, gy, tile in cells:
                    flat.paste(tile, (gx * w, gy * h))
                flat.save(os.path.join(out, atlas_file))
                self.log(f"Atlas: {atlas_size}x{atlas_size} PNG (no mips).", "info")

            # 3. CSV -- Redux looks for <MaterialName>.csv, so the stem has to
            #    match the material, not be a separate "_mapping" name.
            with open(os.path.join(out, f"{mat_stem}.csv"), "w", newline='\n') as f:
                f.write("\n".join(csv_lines) + "\n")

            # 4. TRN entries, led by the [Atlases] block that binds the map to
            #    the generated material. Without it the terrain never draws.
            with open(os.path.join(out, "TRN_Entries.txt"), "w", newline='\n') as f:
                f.write("; Paste into your .trn. The [Atlases] block is required:\n")
                f.write("; it is what points the terrain at the generated material.\n\n")
                f.write("[Atlases]\n")
                f.write(f"MaterialName\t= {mat_stem}\n\n")
                for t_idx in sorted(trn_data.keys()):
                    f.write(f"[TextureType{t_idx}]\n")
                    for line in sorted(trn_data[t_idx]):
                        f.write(f"{line}\n")
                    f.write("\n")

            # 5. A neutral detail/specular map.
            #
            #    BZTerrainBase defaults DetailMap and SpecularMap to white.png,
            #    and the terrain shader computes `detailMap.Sample(...) * 2`.
            #    Leaving them unset therefore means a detail factor of 2.0 and
            #    full specular: the terrain renders at double brightness up
            #    close, fading with distance via saturate(depth * 0.025), so it
            #    reads as a blown-out near band. Every stock atlas ships detail
            #    and specular maps averaging 0.5, i.e. exactly neutral through
            #    that *2. A legacy tile set has no such data, so emit a flat 50%
            #    grey and bind it to both.
            neutral_name = f"{prefix}_neutral.png"
            Image.new("RGB", (8, 8), (128, 128, 128)).save(os.path.join(out, neutral_name))

            # 6. Terrain material.
            with open(os.path.join(out, f"{mat_stem}.material"), "w", newline='\n') as f:
                f.write('import * from "BZTerrainBase.material"\n\n')
                f.write(f'material {mat_stem.upper()} : BZTerrainBase\n{{\n')
                f.write(f'\tset_texture_alias DiffuseMap {atlas_file}\n')
                f.write(f'\tset_texture_alias DetailMap {neutral_name}\n')
                f.write(f'\tset_texture_alias NormalMap flat_n.dds\n')
                f.write(f'\tset_texture_alias SpecularMap {neutral_name}\n')
                f.write(f'\tset_texture_alias EmissiveMap black.dds\n\n')
                f.write(f'\tset $diffuse "1 1 1"\n')
                f.write(f'\tset $ambient "1 1 1"\n')
                f.write(f'\tset $specular ".25 .25 .25"\n')
                f.write(f'\tset $shininess "63"\n')
                f.write(f'\tset $bias "0"\n')
                f.write('}\n')

            self.log(f"Legacy Conversion Complete: {count} tiles packed into "
                     f"{atlas_size}x{atlas_size} atlas ({gs}x{gs} grid).", "success")

            # 7. Sky, cloud and star textures referenced by the .trn.
            atlas_names = {n.lower() for n in names}
            made = self._convert_sky_textures(src, out, pal, atlas_names)
            if made:
                self.log(f"Converted {made} sky/cloud/star texture(s) with materials.", "success")

        except Exception as e:
            self.log(f"Legacy Error: {e}", "error")
        finally:
            self.root.after(0, lambda: self.btn_legacy_gen.config(text="CONVERT & BUILD ATLAS", state="normal"))

    def reset_lighting_defaults(self):
        for group in [self.light_diffuse, self.light_ambient, self.light_specular]:
            for var in group:
                var.set(1.0)

    def validate_map_name(self, P):
        if len(P) > 8: return False
        if not P.isalpha() and P != "": return False
        if not P.isalnum() and P != "": return False
        return True

    def generate_stock_map(self):
        name = self.stock_map_name.get()
        if not name:
            messagebox.showerror("Error", "Map Name is required.")
            return
        
        out_dir = filedialog.askdirectory(title="Select Output Folder")
        if not out_dir: return

        # Map Preset to Zones logic
        # Assuming 1 zone = 1280m (standard BZ1 chunk)
        # Tiny (1280m) -> 1x1
        # Small (2560m) -> 2x2
        # Medium (5120m) -> 4x4
        preset_map = {
            "Tiny (1280m)": 1,
            "Small (2560m)": 2,
            "Medium (5120m)": 4,
            "Large (10240m)": 8,
            "Huge (20480m)": 16
        }
        zones = preset_map.get(self.stock_size_preset.get(), 4)

        cfg = {
            "name": name,
            "world": self.stock_world_type.get(),
            "zones": zones,
            "out_dir": out_dir
        }
        
        self.btn_stock_gen.config(text="GENERATING...", state="disabled")
        threading.Thread(target=self._generate_stock_map_worker, args=(cfg,), daemon=True).start()

    def _generate_stock_map_worker(self, cfg):
        try:
            name = cfg["name"]
            zones = cfg["zones"]
            world = cfg["world"].lower()
            world_key = cfg["world"] # Case sensitive for dictionary lookup
            out_dir = cfg["out_dir"]
            
            # 1. Generate Flat HG2
            # Depth 7 = 128px per zone (Standard BZ1)
            depth = 7
            zone_res = 128
            
            # Create flat data (mid-grey or 0?) BZ1 usually 0 is bottom.
            # Let's use 0 for flat ground.
            total_res = zones * zone_res
            flat_data = np.zeros((total_res, total_res), dtype=np.uint16)

            hg2_path = os.path.join(out_dir, f"{name}.hg2")
            write_hg2(hg2_path, flat_data, zones, zones, zone_bits=depth)

            # 2. Generate TRN File
            trn_path = os.path.join(out_dir, f"{name}.trn")
            
            # Get Template Data
            tpl = self.get_stock_template_data(world_key)
            
            # Prepare NormalView block with user Time override
            nv_block = tpl["NormalView"]
            nv_block = re.sub(r"Time\s*=\s*\d+", f"Time={self.stock_time.get()}", nv_block)
            
            # Map Size in Meters
            size_m = zones * 1280
            
            with open(trn_path, "w") as f:
                f.write(f"[Size]\nMinX=0\nMinZ=0\nWidth={size_m}\nDepth={size_m}\nHeight=100\n\n")
                
                f.write(f"{nv_block}\n\n")
                
                # Write Static Content (Atlases, Sky, Clouds, Stars, TextureTypes, Color)
                f.write(f"{tpl['Static']}\n\n")
                
                f.write("[World]\n")
                f.write(f"MusicTrack={self.audio_track.get()}\n")
                f.write(f"MusicLoopFirst={self.audio_loop_first.get()}\n")
                f.write(f"MusicLoopLast={self.audio_loop_last.get()}\n")
                f.write(f"MusicLoopSkip={self.audio_loop_skip.get()}\n\n")
                f.write("[Sun_Ambient]\n")
                f.write(f"Red = {self.light_ambient[0].get():.4f}f\n")
                f.write(f"Green = {self.light_ambient[1].get():.4f}f\n")
                f.write(f"Blue = {self.light_ambient[2].get():.4f}f\n\n")

                f.write("[Sun_Diffuse]\n")
                f.write(f"Red = {self.light_diffuse[0].get():.4f}f\n")
                f.write(f"Green = {self.light_diffuse[1].get():.4f}f\n")
                f.write(f"Blue = {self.light_diffuse[2].get():.4f}f\n\n")

                f.write("[Sun_Specular]\n")
                f.write(f"Red = {self.light_specular[0].get():.4f}f\n")
                f.write(f"Green = {self.light_specular[1].get():.4f}f\n")
                f.write(f"Blue = {self.light_specular[2].get():.4f}f\n\n")

            self.log(f"Success: Generated {name}.hg2 and {name}.trn in {out_dir}", "success")
            
        except Exception as e:
            self.log(f"Stock Gen Error: {e}", "error")
        finally:
            self.root.after(0, lambda: self.btn_stock_gen.config(text="GENERATE MAP FILES", state="normal"))

    def get_stock_template_data(self, world):
        """Returns the TRN template blocks for the specified world."""
        
        # Defaults
        nv_default = "[NormalView]\nTime=1200\nFogStart=100\nFogEnd=250\nFogBreak=60\nVisibilityRange=250\nIntensity=40\nAmbient=0\nFlatRange=250\nShadowLuma=0"
        
        templates = {
            "Moon": {
                "NormalView": "[NormalView]\nTime=900\nFogStart=175\nFogEnd=250\nFogBreak=60\nVisibilityRange=250\nIntensity=90\nAmbient=0\nFlatRange=250\nShadowLuma=0\nFogDirection=0\nTerrainShadowLuma=40\nCarAmbient=30",
                "Static": """[Atlases]\nMaterialName = mn_detail_atlas\n\n[Sky]\nSunTexture=sun.0\nSkyHeight = 110\nSkyTexture=\nBackdropDistance= 400\nBackdropWidth = 800\nBackdropHeight = 100\n\n[Stars]\nRadius = 1000\nTexture00 = earth.map\nAlpha00 = 0\nSize00 = 200\nAzimuth00 = 150\nElevation00 = 10\nRoll00 = 300\nTexture01 = milkyway.map\nColor01 = "255 255 255 64"\nAlpha01 = 0\nWidth01 = 4000\nHeight01 = 1000\nAzimuth01 = -50\nElevation01 = 40\nRoll01 = 40\n\n[StarList]\nSolid = 0\nLayerHeight = 15\nTexture = stars.map\nRadius = 1000\nStart0 = 0\nEnd0 = 360\nSize0 = 350\nCount0 = 13\nStart1 = 0\nEnd1 = 360\nSize1 = 350\nCount1 = 10\nStart2 = 0\nEnd2 = 360\nSize2 = 350\nCount2 = 11\n\n[Color]\nPalette=MOON.ACT\nLuma=MOON.LUM\nTranslucency=MOON.TBL\nAlpha=MOON.ALB\n\n[TextureType0]\nFlatColor= 104\nSolidA0 = mn00sA0.map\nSolidA1 = mn00sA1.map\nSolidA2 = mn00sA2.map\nSolidA3 = mn00sA3.map\nSolidb0 = mn00sA0.map\nSolidb1 = mn00sA1.map\nSolidb2 = mn00sA2.map\nSolidb3 = mn00sA3.map\nSolidc0 = mn00sA0.map\nSolidc1 = mn00sA1.map\nSolidc2 = mn00sA2.map\nSolidc3 = mn00sA3.map\nSolidd0 = mn00sC0.map\nSolidd1 = mn00sC1.map\nSolidd2 = mn00sC2.map\nSolidd3 = mn00sC3.map\nCapTo3_A0 = mn03cA0.map\nCapTo3_A1 = mn03cA1.map\nCapTo3_A2 = mn03cA2.map\nCapTo3_A3 = mn03cA3.map\nDiagonalTo3_A0 = mn03dA0.map\nDiagonalTo3_A1 = mn03dA1.map\nDiagonalTo3_A2 = mn03dA2.map\nDiagonalTo3_A3 = mn03dA3.map\nCapTo4_A0 = mn04cA0.map\nCapTo4_A1 = mn04cA1.map\nCapTo4_A2 = mn04cA2.map\nCapTo4_A3 = mn04cA3.map\nDiagonalTo4_A0 = mn04dA0.map\nDiagonalTo4_A1 = mn04dA1.map\nDiagonalTo4_A2 = mn04dA2.map\nDiagonalTo4_A3 = mn04dA3.map\n\n[TextureType3]\nFlatColor= 196\nSolidA0 = mn33sA0.map\nSolidA1 = mn33sA1.map\nSolidA2 = mn33sA2.map\nSolidA3 = mn33sA3.map\n\n[TextureType4]\nFlatColor= 7\nSolidA0 = mn44sA0.map\nSolidA1 = mn44sA1.map\nSolidA2 = mn44sA2.map\nSolidA3 = mn44sA3.map\nSolidB0 = mn44sB0.map\nSolidB1 = mn44sB1.map\nSolidB2 = mn44sB2.map\nSolidB3 = mn44sB3.map\n\n[TextureType5]\nFlatColor= 7\nSolidA0 = mn55sA0.map\nSolidA1 = mn55sA1.map\nSolidA2 = mn55sA2.map\nSolidA3 = mn55sA3.map\n\n[TextureType6]\nFlatColor= 7\nSolidA0 = mn66sA0.map\nSolidA1 = mn66sA1.map\nSolidA2 = mn66sA2.map\nSolidA3 = mn66sA3.map"""
            },
            "Mars": {
                "NormalView": "[NormalView]\nTime=900\nFogStart=120\nFogEnd=250\nFogBreak=60\nVisibilityRange=250\nIntensity=40\nAmbient=0\nFlatRange=250\nShadowLuma=0\nFogDirection=1\nTerrainShadowLuma=20\nCarAmbient=20",
                "Static": """[Atlases]\nMaterialName = ma_detail_atlas\n\n[Sky]\nSunTexture=sun.0\nSkyHeight = 110\nSkyTexture= mars.map\nBackdropTexture =\nBackdropDistance= 400\nBackdropWidth = 800\nBackdropHeight = 100\n\n[Clouds]\nCount = 8\nType = 1\nTileSize = 1000\nTexture0 = acloud2.map\nSize0 = 500\nHeight0 = 100\nTexture1 = acloud2.map\nSize1 = 500\nHeight1 = 90\nTexture2 = acloud2.map\nSize2 = 500\nHeight2 = 80\n\n[Color]\nPalette=MARS.ACT\nLuma=MARS.LUM\nTranslucency=MARS.TBL\nAlpha=MARS.ALB\n\n[TextureType0]\nFlatColor= 108\nSolidA0 = ma00sA0.map\nSolidA1 = ma00sA1.map\nSolidA2 = ma00sA2.map\nSolidA3 = ma00sA3.map\nSolidB0 = ma00sB0.map\nSolidB1 = ma00sB1.map\nSolidB2 = ma00sB2.map\nSolidB3 = ma00sB3.map\nSolidC0 = ma00sC0.map\nSolidC1 = ma00sC1.map\nSolidC2 = ma00sC2.map\nSolidC3 = ma00sC3.map\nCapTo1_A0 = ma01cA0.map\nCapTo1_A1 = ma01cA1.map\nCapTo1_A2 = ma01cA2.map\nCapTo1_A3 = ma01cA3.map\nDiagonalTo1_A0 = ma01dA0.map\nDiagonalTo1_A1 = ma01dA1.map\nDiagonalTo1_A2 = ma01dA2.map\nDiagonalTo1_A3 = ma01dA3.map\nCapTo4_A0 = ma04cA0.map\nCapTo4_A1 = ma04cA1.map\nCapTo4_A2 = ma04cA2.map\nCapTo4_A3 = ma04cA3.map\nCapTo4_B0 = ma04cB0.map\nCapTo4_B1 = ma04cB1.map\nCapTo4_B2 = ma04cB2.map\nCapTo4_B3 = ma04cB3.map\nDiagonalTo4_A0 = ma04dA0.map\nDiagonalTo4_A1 = ma04dA1.map\nDiagonalTo4_A2 = ma04dA2.map\nDiagonalTo4_A3 = ma04dA3.map\n\n[TextureType1]\nFlatColor= 160\nSolidA0 = ma11sA0.map\nSolidA1 = ma11sA1.map\nSolidA2 = ma11sA2.map\nSolidA3 = ma11sA3.map\nSolidB0 = ma11sA0.map\nSolidB1 = ma11sA1.map\nSolidB2 = ma11sA2.map\nSolidB3 = ma11sA3.map\nSolidC0 = ma11sB0.map\nSolidC1 = ma11sB1.map\nSolidC2 = ma11sB2.map\nSolidC3 = ma11sB3.map\nSolidD0 = ma11sC0.map\nSolidD1 = ma11sC1.map\nSolidD2 = ma11sC2.map\nSolidD3 = ma11sC3.map\nCapTo3_A0 = ma13cA0.map\nCapTo3_A1 = ma13cA1.map\nCapTo3_A2 = ma13cA2.map\nCapTo3_A3 = ma13cA3.map\nDiagonalTo3_A0 = ma13dA0.map\nDiagonalTo3_A1 = ma13dA1.map\nDiagonalTo3_A2 = ma13dA2.map\nDiagonalTo3_A3 = ma13dA3.map\n\n[TextureType2]\nFlatColor= 192\nSolidA0 = ma22sA0.map\nSolidA1 = ma22sA1.map\nSolidA2 = ma22sA2.map\nSolidA3 = ma22sA3.map\n\n[TextureType3]\nFlatColor= 195\nSolidA0 = ma33sA0.map\nSolidA1 = ma33sA1.map\nSolidA2 = ma33sA2.map\nSolidA3 = ma33sA3.map\n\n[TextureType4]\nFlatColor= 4\nSolidA0 = ma44sA0.map\nSolidA1 = ma44sA1.map\nSolidA2 = ma44sA2.map\nSolidA3 = ma44sA3.map\nSolidB0 = ma44sB0.map\nSolidB1 = ma44sB1.map\nSolidB2 = ma44sB2.map\nSolidB3 = ma44sB3.map\nSolidC0 = ma44sC0.map\nSolidC1 = ma44sC1.map\nSolidC2 = ma44sC2.map\nSolidC3 = ma44sC3.map"""
            },
            "Venus": {
                "NormalView": "[NormalView]\nTime=1200\nFogStart=30\nFogEnd=100\nFogBreak=30\nVisibilityRange=100\nIntensity=40\nAmbient=0\nFlatRange=250\nShadowLuma=0\nFogDirection=1\nTerrainShadowLuma=30\nCarAmbient=20",
                "Static": """[Atlases]\nMaterialName = ve_detail_atlas\n\n[Sky]\nSunTexture=sun.0\nSkyType=0\nSkyHeight = 110\nSkyTexture= venus.map\nBackdropDistance= 400\nBackdropWidth = 800\nBackdropHeight = 100\n\n[LightningBolt]\nminDelay=5000\nmaxDelay=30000\nBolts=3\nDuration=100\nColor=20\nDistance=75\nSound=lstart.wav\n\n[Color]\nPalette=venus.ACT\nLuma=venus.LUM\nTranslucency=venus.TBL\nAlpha=venus.ALB\n\n[TextureType0]\nFlatColor= 124\nSolidA0 = ve00sA0.map\nSolidA1 = ve00sA1.map\nSolidA2 = ve00sA2.map\nSolidA3 = ve00sA3.map\nCapTo1_A0 = ve01cA0.map\nCapTo1_A1 = ve01cA1.map\nCapTo1_A2 = ve01cA2.map\nCapTo1_A3 = ve01cA3.map\nDiagonalTo1_A0 = ve01dA0.map\nDiagonalTo1_A1 = ve01dA1.map\nDiagonalTo1_A2 = ve01dA2.map\nDiagonalTo1_A3 = ve01dA3.map\nCapTo2_A0 = ve02cA0.map\nCapTo2_A1 = ve02cA1.map\nCapTo2_A2 = ve02cA2.map\nCapTo2_A3 = ve02cA3.map\nCapTo2_B0 = ve02cB0.map\nCapTo2_B1 = ve02cB1.map\nCapTo2_B2 = ve02cB2.map\nCapTo2_B3 = ve02cB3.map\nDiagonalTo2_A0 = ve02dA0.map\nDiagonalTo2_A1 = ve02dA1.map\nDiagonalTo2_A2 = ve02dA2.map\nDiagonalTo2_A3 = ve02dA3.map\nCapTo3_A0 = ve03cA0.map\nCapTo3_A1 = ve03cA1.map\nCapTo3_A2 = ve03cA2.map\nCapTo3_A3 = ve03cA3.map\nDiagonalTo3_A0 = ve03dA0.map\nDiagonalTo3_A1 = ve03dA1.map\nDiagonalTo3_A2 = ve03dA2.map\nDiagonalTo3_A3 = ve03dA3.map\n\n[TextureType1]\nFlatColor= 96\nSolidA0 = ve11sA0.map\nSolidA1 = ve11sA1.map\nSolidA2 = ve11sA2.map\nSolidA3 = ve11sA3.map\n\n[TextureType2]\nFlatColor= 167\nSolidA0 = ve22sA0.map\nSolidA1 = ve22sA1.map\nSolidA2 = ve22sA2.map\nSolidA3 = ve22sA3.map\nSolidB0 = ve22sB0.map\nSolidB1 = ve22sB1.map\nSolidB2 = ve22sB2.map\nSolidB3 = ve22sB3.map\n\n[TextureType3]\nFlatColor= 203\nSolidA0 = ve33sA0.map\nSolidA1 = ve33sA1.map\nSolidA2 = ve33sA2.map\nSolidA3 = ve33sA3.map\n\n[TextureType4]\nFlatColor= 207\nSolidA0 = ve44sA0.map\nSolidA1 = ve44sA1.map\nSolidA2 = ve44sA2.map\nSolidA3 = ve44sA3.map"""
            },
            "Io": {
                "NormalView": "[NormalView]\nTime=1200\nLava=1\nFogStart=175\nFogEnd=250\nFogBreak=50\nVisibilityRange=250\nIntensity=90\nAmbient=10\nFlatRange=250\nShadowLuma=0\nFogDirection=0\nTerrainShadowLuma=20\nCarAmbient=30\nwave=1",
                "Static": """[Atlases]\nMaterialName = io_detail_atlas\n\n[Sky]\nSunTexture=\nSkyType= 1\nSkyHeight = 200\nSkyTexture= jupiter.map\nBackdropDistance= 400\nBackdropWidth = 800\nBackdropHeight = 100\n\n[Stars]\nRadius = 500\nTexture00 = stars.map\nSize00 = 100\nAzimuth00 = 0\nElevation00 = 5\nTexture01 = stars.map\nSize01 = 100\nAzimuth01 = 15\nElevation01 = 5\nRoll01 = 176\nTexture02 = stars.map\nSize02 = 100\nAzimuth02 = 30\nElevation02 = 5\nRoll16 = 90\nTexture03 = stars.map\nSize03 = 100\nAzimuth03 = 45\nElevation03 = 5\nTexture04 = stars.map\nSize04 = 100\nAzimuth04 = 60\nElevation04 = 5\nRoll04 = 78\nTexture05 = stars.map\nSize05 = 100\nAzimuth05 = 75\nElevation05 = 5\nRoll05 = 300\nTexture06 = stars.map\nSize06 = 100\nAzimuth06 = 90\nElevation06 = 5\nRoll16 = 180\nTexture07 = stars.map\nSize07 = 100\nAzimuth07 = 105\nElevation07 = 5\nTexture08 = stars.map\nSize08 = 100\nAzimuth08 = 120\nElevation08 = 5\nTexture09 = stars.map\nSize09 = 100\nAzimuth09 = 135\nElevation09 = 5\nRoll16 = 90\nTexture10 = stars.map\nSize10 = 100\nAzimuth10 = 150\nElevation10 = 5\nTexture11 = stars.map\nSize11 = 100\nAzimuth11 = 165\nElevation11 = 5\nRoll16 = 180\nTexture12 = stars.map\nSize12 = 100\nAzimuth12 = 180\nElevation12 = 5\nTexture13 = stars.map\nSize13 = 100\nAzimuth13 = 195\nElevation13 = 5\nRoll13 = 176\nTexture14 = stars.map\nSize14 = 100\nAzimuth14 = 210\nElevation14 = 5\nTexture15 = stars.map\nSize15 = 100\nAzimuth15 = 225\nElevation15 = 5\nTexture16 = stars.map\nSize16 = 100\nAzimuth16 = 240\nElevation16 = 5\nRoll16 = 78\nTexture17 = stars.map\nSize17 = 100\nAzimuth17 = 255\nElevation17 = 5\nRoll17 = 300\nTexture18 = stars.map\nSize18 = 100\nAzimuth18 = 270\nElevation18 = 5\nTexture19 = stars.map\nSize19 = 100\nAzimuth19 = 285\nElevation19 = 5\nTexture20 = stars.map\nSize20 = 100\nAzimuth20 = 300\nElevation20 = 5\nRoll16 = 180\nTexture21 = stars.map\nSize21 = 100\nAzimuth21 = 315\nElevation21 = 5\nTexture22 = stars.map\nSize22 = 100\nAzimuth22 = 345\nElevation22 = 5\nTexture23 = stars.map\nSize23 = 100\nAzimuth23 = 360\nElevation23 = 5\nRoll16 = 180\n\n[Color]\nPalette=io.ACT\nLuma=io.LUM\nTranslucency=io.TBL\nAlpha=io.ALB\n\n[TextureType0]\nFlatColor= 134\nSolidA0 = io00sA0.map\nSolidA1 = io00sA1.map\nSolidA2 = io00sA2.map\nSolidA3 = io00sA3.map\nSolidB0 = io00sA0.map\nSolidB1 = io00sA1.map\nSolidB2 = io00sA2.map\nSolidB3 = io00sA3.map\nSolidC0 = io00sB0.map\nSolidC1 = io00sB1.map\nSolidC2 = io00sB2.map\nSolidC3 = io00sB3.map\nSolidD0 = io00sC0.map\nSolidD1 = io00sC1.map\nSolidD2 = io00sC2.map\nSolidD3 = io00sC3.map\nCapTo1_A0 = io01cA0.map\nCapTo1_A1 = io01cA1.map\nCapTo1_A2 = io01cA2.map\nCapTo1_A3 = io01cA3.map\nDiagonalTo1_A0 = io01dA0.map\nDiagonalTo1_A1 = io01dA1.map\nDiagonalTo1_A2 = io01dA2.map\nDiagonalTo1_A3 = io01dA3.map\nCapTo3_A0 = io03cA0.map\nCapTo3_A1 = io03cA1.map\nCapTo3_A2 = io03cA2.map\nCapTo3_A3 = io03cA3.map\nDiagonalTo3_A0 = io03dA0.map\nDiagonalTo3_A1 = io03dA1.map\nDiagonalTo3_A2 = io03dA2.map\nDiagonalTo3_A3 = io03dA3.map\n\n[TextureType1]\nFlatColor= 96\nSolidA0 = io11sA0.map\nSolidA1 = io11sA1.map\nSolidA2 = io11sA2.map\nSolidA3 = io11sA3.map\n\n[TextureType3]\nFlatColor= 112\nSolidA0 = io33sA0.map\nSolidA1 = io33sA1.map\nSolidA2 = io33sA2.map\nSolidA3 = io33sA3.map\nSolidB0 = io33sB0.map\nSolidB1 = io33sB1.map\nSolidB2 = io33sB2.map\nSolidB3 = io33sB3.map\nSolidC0 = io33sA0.map\nSolidC1 = io33sA1.map\nSolidC2 = io33sA2.map\nSolidC3 = io33sA3.map\nSolidD0 = io33sA0.map\nSolidD1 = io33sA1.map\nSolidD2 = io33sA2.map\nSolidD3 = io33sA3.map\nCapTo4_A0 = io34ca0.map\nCapTo4_A1 = io34ca1.map\nCapTo4_A2 = io34ca2.map\nCapTo4_A3 = io34ca3.map\nDiagonalTo4_A0 = io34dA0.map\nDiagonalTo4_A1 = io34dA1.map\nDiagonalTo4_A2 = io34dA2.map\nDiagonalTo4_A3 = io34dA3.map\n\n[TextureType4]\nFlatColor= 208\nSolidA0 = io44sA0.map\nSolidA1 = io44sA1.map\nSolidA2 = io44sA2.map\nSolidA3 = io44sA3.map\nCapTo5_A0 = io45ca0.map\nCapTo5_A1 = io45ca1.map\nCapTo5_A2 = io45ca2.map\nCapTo5_A3 = io45ca3.map\nCapTo5_B0 = io45cb0.map\nCapTo5_B1 = io45cb1.map\nCapTo5_B2 = io45cb2.map\nCapTo5_B3 = io45cb3.map\nDiagonalTo5_A0 = io45dA0.map\nDiagonalTo5_A1 = io45dA1.map\nDiagonalTo5_A2 = io45dA2.map\nDiagonalTo5_A3 = io45dA3.map\n\n[TextureType5]\nFlatColor= 4\nSolidA0 = io55sA0.map\nSolidA1 = io55sA1.map\nSolidA2 = io55sA2.map\nSolidA3 = io55sA3.map\nSolidB0 = io55sB0.map\nSolidB1 = io55sB1.map\nSolidB2 = io55sB2.map\nSolidB3 = io55sB3.map\nSolidC0 = io55sC0.map\nSolidC1 = io55sC1.map\nSolidC2 = io55sC2.map\nSolidC3 = io55sC3.map"""
            },
            "Europa": {
                "NormalView": "[NormalView]\nTime=1500\nFogStart=175\nFogEnd=250\nFogBreak=60\nVisibilityRange=250\nIntensity=90\nAmbient=0\nFlatRange=300\nShadowLuma=0\nFogDirection=0\nTerrainShadowLuma=20\nCarAmbient=30",
                "Static": """[Atlases]\nMaterialName = eu_detail_atlas\n\n[Sky]\nSunTexture= sun.0\nSkyType= 0\nSkyHeight = 110\nSkyTexture= \nBackdropTexture = \nBackdropDistance= 400\nBackdropWidth = 800\nBackdropHeight = 100\n\n[Stars]\nRadius = 1000\nTexture00 = smjovian.map\nAlpha00 = 0\nSize00 = 350\nAzimuth00 = 210\nElevation00 = 35\nRoll00 = 300\n\n[StarList]\nSolid = 0\nLayerHeight = 15\nTexture = stars.map\nRadius = 1000\nStart0 = 0\nEnd0 = 360\nSize0 = 350\nCount0 = 13\nStart1 = 220\nEnd1 = 560\nSize1 = 350\nCount1 = 10 \nStart2 = 220\nEnd2 = 560\nSize2 = 350\nCount2 = 11\n\n[Color]\nPalette=europa.ACT\nLuma=europa.LUM\nTranslucency=europa.TBL\nAlpha=europa.ALB\n\n[TextureType0]\nFlatColor= 201\nSolidA0 = eu00sA0.map\nSolidA1 = eu00sA1.map\nSolidA2 = eu00sA2.map\nSolidA3 = eu00sA3.map\nSolidb0 = eu00sA0.map\nSolidb1 = eu00sA1.map\nSolidb2 = eu00sA2.map\nSolidb3 = eu00sA3.map\nSolidc0 = eu00sB0.map\nSolidc1 = eu00sB1.map\nSolidc2 = eu00sB2.map\nSolidc3 = eu00sB3.map\nSolidd0 = eu00sA0.map\nSolidd1 = eu00sA1.map\nSolidd2 = eu00sA2.map\nSolidd3 = eu00sA3.map\nCapTo1_A0 = eu01cA0.map\nCapTo1_A1 = eu01cA1.map\nCapTo1_A2 = eu01cA2.map\nCapTo1_A3 = eu01cA3.map\nDiagonalTo1_A0 = eu01dA0.map\nDiagonalTo1_A1 = eu01dA1.map\nDiagonalTo1_A2 = eu01dA2.map\nDiagonalTo1_A3 = eu01dA3.map\nCapTo4_A0 = eu04cA0.map\nCapTo4_A1 = eu04cA1.map\nCapTo4_A2 = eu04cA2.map\nCapTo4_A3 = eu04cA3.map\nDiagonalTo4_A0 = eu04dA0.map\nDiagonalTo4_A1 = eu04dA1.map\nDiagonalTo4_A2 = eu04dA2.map\nDiagonalTo4_A3 = eu04dA3.map\n\n[TextureType1]\nFlatColor= 131\nSolidA0 = eu11sA0.map\nSolidA1 = eu11sA1.map\nSolidA2 = eu11sA2.map\nSolidA3 = eu11sA3.map\nCapTo2_A0 = eu12cA0.map\nCapTo2_A1 = eu12cA1.map\nCapTo2_A2 = eu12cA2.map\nCapTo2_A3 = eu12cA3.map\nDiagonalTo2_A0 = eu12dA0.map\nDiagonalTo2_A1 = eu12dA1.map\nDiagonalTo2_A2 = eu12dA2.map\nDiagonalTo2_A3 = eu12dA3.map\n\n[TextureType2]\nFlatColor= 101\nSolidA0 = eu22sA0.map\nSolidA1 = eu22sA1.map\nSolidA2 = eu22sA2.map\nSolidA3 = eu22sA3.map\nCapTo3_A0 = eu23cA0.map\nCapTo3_A1 = eu23cA1.map\nCapTo3_A2 = eu23cA2.map\nCapTo3_A3 = eu23cA3.map\nDiagonalTo3_A0 = eu23dA0.map\nDiagonalTo3_A1 = eu23dA1.map\nDiagonalTo3_A2 = eu23dA2.map\nDiagonalTo3_A3 = eu23dA3.map\n\n[TextureType3]\nFlatColor= 177\nSolidA0 = eu33sA0.map\nSolidA1 = eu33sA1.map\nSolidA2 = eu33sA2.map\nSolidA3 = eu33sA3.map\n\n[TextureType4]\nFlatColor= 206\nSolidA0 = eu44sA0.map\nSolidA1 = eu44sA1.map\nSolidA2 = eu44sA2.map\nSolidA3 = eu44sA3.map\nSolidb0 = eu44sB0.map\nSolidb1 = eu44sB1.map\nSolidb2 = eu44sB2.map\nSolidb3 = eu44sB3.map\nSolidc0 = eu44sC0.map\nSolidc1 = eu44sC1.map\nSolidc2 = eu44sC2.map\nSolidc3 = eu44sC3.map"""
            },
            "Ganymede": {
                "NormalView": "[NormalView]\nTime=900\nFogStart=175\nFogEnd=250\nFogBreak=60\nVisibilityRange=250\nIntensity=90\nAmbient=0\nFlatRange=250\nShadowLuma=0\nFogDirection=0\nTerrainShadowLuma=40\nCarAmbient=30",
                "Static": """[Atlases]\nMaterialName = ga_detail_atlas\n\n[Sky]\nSunTexture= sun.0\nSkyType= 0\nSkyHeight = 130\nSkyTexture= \nBackdropDistance= 400\nBackdropWidth = 800\nBackdropHeight = 100\n\n[Stars]\nRadius = 401\nTexture00 = ganyjup.map\nAlpha00 = 0\nSize00 = 150\nAzimuth00 = 180\nElevation00 = 25\nRoll00 = 0\n\n[StarList]\nSolid = 0\nLayerHeight = 15\nTexture = stars.map\nRadius = 1000\nStart0 = 235\nEnd0 = 510\nSize0 = 350\nCount0 = 12\nStart1 = 235\nEnd1 = 510\nSize1 = 350\nCount1 = 9 \nStart2 = 0\nEnd2 = 360\nSize2 = 350\nCount2 = 11\n\n[Color]\nPalette=ganymede.ACT\nLuma=ganymede.LUM\nTranslucency=ganymede.TBL\nAlpha=ganymede.ALB\n\n[TextureType0]\nFlatColor= 201\nSolidA0 = Ga00sa0.map\nSolidA1 = Ga00sa1.map\nSolidA2 = Ga00sa2.map\nSolidA3 = Ga00sa3.map\nSolidb0 = Ga00sb0.map\nSolidb1 = Ga00sb1.map\nSolidb2 = Ga00sb2.map\nSolidb3 = Ga00sb3.map\nSolidc0 = Ga00sc0.map\nSolidc1 = Ga00sc1.map\nSolidc2 = Ga00sc2.map\nSolidc3 = Ga00sc3.map\nDiagonalTo1_A0 = Ga01da0.map\nDiagonalTo1_A1 = Ga01da1.map\nDiagonalTo1_A2 = Ga01da2.map\nDiagonalTo1_A3 = Ga01da3.map\nCapTo1_A0 = Ga01ca0.map\nCapTo1_A1 = Ga01ca1.map\nCapTo1_A2 = Ga01ca2.map\nCapTo1_A3 = Ga01ca3.map\nDiagonalTo4_A0 = Ga04da0.map\nDiagonalTo4_A1 = Ga04da1.map\nDiagonalTo4_A2 = Ga04da2.map\nDiagonalTo4_A3 = Ga04da3.map\nCapTo4_A0 = Ga04ca0.map\nCapTo4_A1 = Ga04ca1.map\nCapTo4_A2 = Ga04ca2.map\nCapTo4_A3 = Ga04ca3.map\n\n[TextureType1]\nFlatColor= 131\nSolidA0 = Ga11Sa0.map\nSolidA1 = Ga11sa1.map\nSolidA2 = Ga11sa2.map\nSolidA3 = Ga11sa3.map\nSolidB0 = Ga11Sb0.map\nSolidB1 = Ga11sb1.map\nSolidB2 = Ga11sb2.map\nSolidB3 = Ga11sb3.map\nDiagonalTo2_A0 = Ga12da0.map\nDiagonalTo2_A1 = Ga12da1.map\nDiagonalTo2_A2 = Ga12da2.map\nDiagonalTo2_A3 = Ga12da3.map\nCapTo2_A0 = Ga12ca0.map\nCapTo2_A1 = Ga12ca1.map\nCapTo2_A2 = Ga12ca2.map\nCapTo2_A3 = Ga12ca3.map\nDiagonalTo4_A0 = Ga14da0.map\nDiagonalTo4_A1 = Ga14da1.map\nDiagonalTo4_A2 = Ga14da2.map\nDiagonalTo4_A3 = Ga14da3.map\nCapTo4_A0 = Ga14ca0.map\nCapTo4_A1 = Ga14ca1.map\nCapTo4_A2 = Ga14ca2.map\nCapTo4_A3 = Ga14ca3.map\n\n[TextureType2]\nFlatColor= 131\nSolidA0 = Ga22Sa0.map\nSolidA1 = Ga22sa1.map\nSolidA2 = Ga22sa2.map\nSolidA3 = Ga22sa3.map\nSolidB0 = Ga22Sb0.map\nSolidB1 = Ga22sb1.map\nSolidB2 = Ga22sb2.map\nSolidB3 = Ga22sb3.map\nSolidC0 = Ga22Sc0.map\nSolidC1 = Ga22sc1.map\nSolidC2 = Ga22sc2.map\nSolidC3 = Ga22sc3.map\nDiagonalTo4_A0 = Ga24da0.map\nDiagonalTo4_A1 = Ga24da1.map\nDiagonalTo4_A2 = Ga24da2.map\nDiagonalTo4_A3 = Ga24da3.map\nCapTo4_A0 = Ga24ca0.map\nCapTo4_A1 = Ga24ca1.map\nCapTo4_A2 = Ga24ca2.map\nCapTo4_A3 = Ga24ca3.map\n\n[TextureType3]\nFlatColor= 201\nSolidA0 = Ga33Sa0.map\nSolidA1 = Ga33sa1.map\nSolidA2 = Ga33sa2.map\nSolidA3 = Ga33sa3.map\nSolidb0 = Ga33Sb0.map\nSolidb1 = Ga33sb1.map\nSolidb2 = Ga33sb2.map\nSolidb3 = Ga33sb3.map\n\n[TextureType4]\nFlatColor= 201\nSolidA0 = Ga44sa0.map\nSolidA1 = Ga44sa1.map\nSolidA2 = Ga44sa2.map\nSolidA3 = Ga44sa3.map\nSolidb0 = Ga44sb0.map\nSolidb1 = Ga44sb1.map\nSolidb2 = Ga44sb2.map\nSolidb3 = Ga44sb3.map"""
            },
            "Achilles": {
                "NormalView": "[NormalView]\nTime=900\nFogStart= 150\nFogEnd= 250\nFogBreak=60\nVisibilityRange=250\nIntensity=40\nAmbient=0\nFlatRange=250\nShadowLuma=0\nFogDirection=1\nTerrainShadowLuma=20\nCarAmbient=20",
                "Static": """[Atlases]\nMaterialName = ac_detail_atlas\n\n[Sky]\nSunTexture= sun.0\nSkyType= 0\nSkyHeight = 210\nSkyTexture= achilles.map\nBackdropTexture =\nBackdropDistance= 400\nBackdropWidth = 800\nBackdropHeight = 100\n\n[Clouds]\nCount = 8\nType = 0\nTileSize = 1000\nTexture0 = acloud2.map\nSize0 = 500\nHeight0 = 200\nTexture1 = acloud.map\nSize1 = 500\nHeight1 = 190\nTexture2 = acloud2.map\nSize2 = 500\nHeight2 = 180\n\n[Color]\nPalette=ACHILLES.ACT\nLuma=ACHILLES.LUM\nTranslucency=ACHILLES.TBL\nAlpha=ACHILLES.ALB\n\n[TextureType0]\nFlatColor= 128\nSolidA0 = ac00sA0.map\nSolidA1 = ac00sA1.map\nSolidA2 = ac00sA2.map\nSolidA3 = ac00sA3.map\nSolidB0 = ac00sA0.map\nSolidB1 = ac00sA1.map\nSolidB2 = ac00sA2.map\nSolidB3 = ac00sA3.map\nSolidC0 = ac00sA0.map\nSolidC1 = ac00sA1.map\nSolidC2 = ac00sA2.map\nSolidC3 = ac00sA3.map\nSolidD0 = ac00sB0.map\nSolidD1 = ac00sB1.map\nSolidD2 = ac00sB2.map\nSolidD3 = ac00sB3.map\nCapTo1_A0 = ac01cA0.map\nCapTo1_A1 = ac01cA1.map\nCapTo1_A2 = ac01cA2.map\nCapTo1_A3 = ac01cA3.map\nDiagonalTo1_A0 = ac01dA0.map\nDiagonalTo1_A1 = ac01dA1.map\nDiagonalTo1_A2 = ac01dA2.map\nDiagonalTo1_A3 = ac01dA3.map\nCapTo5_A0 = ac05cA0.map\nCapTo5_A1 = ac05cA1.map\nCapTo5_A2 = ac05cA2.map\nCapTo5_A3 = ac05cA3.map\nCapTo5_B0 = ac05cB0.map\nCapTo5_B1 = ac05cB1.map\nCapTo5_B2 = ac05cB2.map\nCapTo5_B3 = ac05cB3.map\nCapTo5_C0 = ac05cC0.map\nCapTo5_C1 = ac05cC1.map\nCapTo5_C2 = ac05cC2.map\nCapTo5_C3 = ac05cC3.map\nDiagonalTo5_A0 = ac05dA0.map\nDiagonalTo5_A1 = ac05dA1.map\nDiagonalTo5_A2 = ac05dA2.map\nDiagonalTo5_A3 = ac05dA3.map\n\n[TextureType1]\nFlatColor= 192\nSolidA0 = ac11sa0.map\nSolidA1 = ac11sa1.map\nSolidA2 = ac11sa2.map\nSolidA3 = ac11sa3.map\nCapTo2_A0 = ac12ca0.map\nCapTo2_A1 = ac12ca1.map\nCapTo2_A2 = ac12ca2.map\nCapTo2_A3 = ac12ca3.map\nDiagonalTo2_A0 = ac12da0.map\nDiagonalTo2_A1 = ac12da1.map\nDiagonalTo2_A2 = ac12da2.map\nDiagonalTo2_A3 = ac12da3.map\n\n[TextureType2]\nFlatColor= 112\nSolidA0 = ac22sa0.map\nSolidA1 = ac22sa1.map\nSolidA2 = ac22sa2.map\nSolidA3 = ac22sa3.map\n\n[TextureType3]\nFlatColor= 122\nSolidA0 = ac00sc0.map\nSolidA1 = ac00sc1.map\nSolidA2 = ac00sc2.map\nSolidA3 = ac00sc3.map\nSolidB0 = ac00sD0.map\nSolidB1 = ac00sD1.map\nSolidB2 = ac00sD2.map\nSolidB3 = ac00sD3.map\nSolidC0 = ac00se0.map\nSolidC1 = ac00se1.map\nSolidC2 = ac00se2.map\nSolidC3 = ac00se3.map\nSolidD0 = ac00sg0.map\nSolidD1 = ac00sg1.map\nSolidD2 = ac00sg2.map\nSolidD3 = ac00sg3.map\n\n[TextureType4]\nFlatColor= 86\nSolidA0 = ac00sf0.map\nSolidA1 = ac00sf1.map\nSolidA2 = ac00sf2.map\nSolidA3 = ac00sf3.map\n\n[TextureType5]\nFlatColor= 103\nSolidA0 = ac55sa0.map\nSolidA1 = ac55sa1.map\nSolidA2 = ac55sa2.map\nSolidA3 = ac55sa3.map\nSolidB0 = ac55sB0.map\nSolidB1 = ac55sB1.map\nSolidB2 = ac55sB2.map\nSolidB3 = ac55sB3.map"""
            },
            "Elysium": {
                "NormalView": "[NormalView]\nTime=900\nFogStart= 80\nFogEnd= 250\nFogBreak=40\nVisibilityRange=250\nIntensity=40\nAmbient=0\nFlatRange=250\nShadowLuma=0\nFogDirection=1\nTerrainShadowLuma=20\nCarAmbient=20",
                "Static": """[Atlases]\nMaterialName = el_detail_atlas\n\n[Sky]\nSunTexture= sun.0\nSkyType= 0\nSkyHeight = 210\nSkyTexture=elysium.map \nBackdropTexture =\nBackdropDistance= 400\nBackdropWidth = 800\nBackdropHeight = 100\n\n[Clouds]\nCount = 8\nType = 0\nTileSize = 1000\nTexture0 = acloud2.map\nSize0 = 500\nHeight0 = 100\nTexture1 = acloud.map\nSize1 = 500\nHeight1 = 90\nTexture2 = acloud2.map\nSize2 = 500\nHeight2 = 80\n\n[Color]\nPalette=elysium.act\nLuma=elysium.lum\nTranslucency=elysium.tbl\nAlpha=elysium.alb\n\n[TextureType0]\nFlatColor= 201\nSolidA0 = el00sa0.map\nSolidA1 = el00sa1.map\nSolidA2 = el00sa2.map\nSolidA3 = el00sa3.map\nSolidB0 = el00sb0.map\nSolidB1 = el00sb1.map\nSolidB2 = el00sb2.map\nSolidB3 = el00sb3.map\nSolidC0 = el00sc0.map\nSolidC1 = el00sc1.map\nSolidC2 = el00sc2.map\nSolidC3 = el00sc3.map\nDiagonalTo1_A0 = el01da0.map\nDiagonalTo1_A1 = el01da1.map\nDiagonalTo1_A2 = el01da2.map\nDiagonalTo1_A3 = el01da3.map\nCapTo1_A0 = el01ca0.map\nCapTo1_A1 = el01ca1.map\nCapTo1_A2 = el01ca2.map\nCapTo1_A3 = el01ca3.map\nDiagonalTo2_A0 = el02da0.map\nDiagonalTo2_A1 = el02da1.map\nDiagonalTo2_A2 = el02da2.map\nDiagonalTo2_A3 = el02da3.map\nCapTo2_A0 = el02ca0.map\nCapTo2_A1 = el02ca1.map\nCapTo2_A2 = el02ca2.map\nCapTo2_A3 = el02ca3.map\nDiagonalTo4_A0 = el04da0.map\nDiagonalTo4_A1 = el04da1.map\nDiagonalTo4_A2 = el04da2.map\nDiagonalTo4_A3 = el04da3.map\nCapTo4_A0 = el04ca0.map\nCapTo4_A1 = el04ca1.map\nCapTo4_A2 = el04ca2.map\nCapTo4_A3 = el04ca3.map\n\n[TextureType1]\nFlatColor= 131\nSolidA0 = el11Sa0.map\nSolidA1 = el11sa1.map\nSolidA2 = el11sa2.map\nSolidA3 = el11sa3.map\nSolidB0 = el11Sb0.map\nSolidB1 = el11sb1.map\nSolidB2 = el11sb2.map\nSolidB3 = el11sb3.map\nSolidC0 = el11Sc0.map\nSolidC1 = el11sc1.map\nSolidC2 = el11sc2.map\nSolidC3 = el11sc3.map\nDiagonalTo2_A0 = el12da0.map\nDiagonalTo2_A1 = el12da1.map\nDiagonalTo2_A2 = el12da2.map\nDiagonalTo2_A3 = el12da3.map\nCapTo2_A0 = el12ca0.map\nCapTo2_A1 = el12ca1.map\nCapTo2_A2 = el12ca2.map\nCapTo2_A3 = el12ca3.map\n\n[TextureType2]\nFlatColor= 131\nSolidA0 = el22Sa0.map\nSolidA1 = el22sa1.map\nSolidA2 = el22sa2.map\nSolidA3 = el22sa3.map\nSolidB0 = el22Sb0.map\nSolidB1 = el22sb1.map\nSolidB2 = el22sb2.map\nSolidB3 = el22sb3.map\nSolidC0 = el22Sc0.map\nSolidC1 = el22sc1.map\nSolidC2 = el22sc2.map\nSolidC3 = el22sc3.map\n\n[TextureType3]\nFlatColor= 201\nSolidA0 = el33Sa0.map\nSolidA1 = el33sa1.map\nSolidA2 = el33sa2.map\nSolidA3 = el33sa3.map\n\n[TextureType4]\nFlatColor= 201\nSolidA0 = el04sa0.map\nSolidA1 = el04sa1.map\nSolidA2 = el04sa2.map\nSolidA3 = el04sa3.map\nSolidb0 = el04sb0.map\nSolidb1 = el04sb1.map\nSolidb2 = el04sb2.map\nSolidb3 = el04sb3.map"""
            },
            "Titan": {
                "NormalView": "[NormalView]\nTime=1100\nFogStart=100\nFogEnd=250\nFogBreak=60\nVisibilityRange=250\nIntensity=40\nAmbient=0\nFlatRange=250\nShadowLuma=0",
                "Static": """[Atlases]\nMaterialName = ti_detail_atlas\n\n[Sky]\nSunTexture= sun.0\nSkyType= 0\nSkyHeight = 150\nSkyTexture= titan.map\nBackdropDistance= 400\nBackdropWidth = 800\nBackdropHeight = 100\n\n[Clouds]\nCount = 6\nType = 1\nTileSize = 1000\nTexture0 = acloud2.map\nSize0 = 500\nHeight0 = 140\nTexture1 = acloud2.map\nSize1 = 500\nHeight1 = 130\nTexture2 = acloud2.map\nSize2 = 500\nHeight2 = 120\n\n[Stars]\nRadius = 300\nTexture00 = saturn.map\nSize00 = 200\nAzimuth00 = 180\nElevation00 = 15\nRoll00 = 0\n\n[StarList]\nSolid = 0\nLayerHeight = 15\nTexture = stars.map\nRadius = 1000\nStart0 = 235\nEnd0 = 510\nSize0 = 350\nCount0 = 12\nStart1 = 235\nEnd1 = 510\nSize1 = 350\nCount1 = 9 \nStart2 = 0\nEnd2 = 360\nSize2 = 350\nCount2 = 11\n\n[Color]\nPalette=TITAN.ACT\nLuma=TITAN.LUM\nTranslucency=TITAN.TBL\nAlpha=TITAN.ALB\n\n[TextureType0]\nSolidA0 =ti00sa0.MAP\nSolidA1 =ti00sa1.MAP\nSolidA2 =ti00sa2.MAP\nSolidA3 =ti00sa3.MAP\nCapTo3_A0 =ti03ca0.map\nCapTo3_A1 =ti03ca1.map\nCapTo3_A2 =ti03ca2.map\nCapTo3_A3 =ti03ca3.map\nDiagonalTo3_A0 =ti03dA0.map\nDiagonalTo3_A1 =ti03dA1.map\nDiagonalTo3_A2 =ti03dA2.map\nDiagonalTo3_A3 =ti03dA3.map\n\n[TextureType3]\nSolidA0 =ti33sA0.map\nSolidA1 =ti33sA1.map\nSolidA2 =ti33sA2.map\nSolidA3 =ti33sA3.map"""
            }
        }
        
        return templates.get(world, {"NormalView": nv_default, "Static": ""})

    def log(self, message, tag="info"):
        timestamp = datetime.now().strftime("[%H:%M:%S] ")
        self.root.after(0, lambda: self._log_impl(timestamp, message, tag))

    def _log_impl(self, timestamp, message, tag):
        self.log_box.config(state="normal")
        self.log_box.insert("end", timestamp, "timestamp")
        self.log_box.insert("end", message + "\n", tag)
        self.log_box.see("end")
        self.log_box.config(state="disabled")

    def browse_output(self):
        d = filedialog.askdirectory()
        if d: self.out_dir_var.set(d)
        
    def generate_normal_map(self, image, strength=1.0):
        """GUI compatibility wrapper around the headless atlas normal-map service."""
        return atlas_generate_normal_map(image, strength)

    def generate_specular_map(self, image):
        """GUI compatibility wrapper around the headless atlas specular-map service."""
        return atlas_generate_specular_map(image)

    def setup_hg2_tab(self):
        container = ttk.Frame(self.tab_hg2, padding=20)
        container.pack(fill="both", expand=True)

        # --- LEFT PANEL: HG2 CONTROLS ---
        left_panel = ttk.Frame(container, width=400) 
        left_panel.pack(side="left", fill="y", padx=(0, 20))
        left_panel.pack_propagate(False) 

        ttk.Label(left_panel, text="HEIGHTMAP CONVERTER", font=(self.custom_font_name, 14, "bold"), foreground=BZ_GREEN).pack(anchor="w")
        hg2_frame = ttk.LabelFrame(left_panel, text=" Terrain Settings ", padding=10)
        hg2_frame.pack(fill="x", pady=5)

        ttk.Entry(hg2_frame, textvariable=self.hg2_path).pack(fill="x", pady=2)
        ttk.Button(hg2_frame, text="Browse HG2/PNG", command=self.browse_hg2).pack(fill="x", pady=5)

        # Map Dimension Presets
        ttk.Label(hg2_frame, text="Map Size Preset When Converting PNG to HG2:").pack(anchor="w", pady=(5,0))
        self.preset_var = tk.StringVar(value="Medium (5120m)")
        preset_menu = ttk.Combobox(hg2_frame, textvariable=self.preset_var, values=self.map_presets, state="readonly")
        preset_menu.pack(fill="x", pady=5)
        preset_menu.bind("<<ComboboxSelected>>", self.apply_map_preset)

        # Manual Dimension Controls
        dim_frame = ttk.Frame(hg2_frame)
        dim_frame.pack(fill="x", pady=5)
        
        ttk.Label(dim_frame, text="Width (m):").grid(row=0, column=0, sticky="w")
        ttk.Entry(dim_frame, textvariable=self.hg2_width_meters, width=8).grid(row=0, column=1, padx=5)
        
        ttk.Label(dim_frame, text="Depth (m):").grid(row=1, column=0, sticky="w")
        ttk.Entry(dim_frame, textvariable=self.hg2_depth_meters, width=8).grid(row=1, column=1, padx=5)
        
        ttk.Label(hg2_frame, text="*Must be multiples of 1280", font=(self.custom_font_name, 7, "italic"), foreground="#666666").pack(anchor="w")

        self.create_hg2_slider(hg2_frame, "Brightness:", self.hg2_brightness, 0.1, 2.0, 0.1)
        self.create_hg2_slider(hg2_frame, "Contrast:", self.hg2_contrast, 0.1, 2.0, 0.1)
        self.create_hg2_slider(hg2_frame, "Smoothing:", self.hg2_smooth_val, 0, 10, 1)
        
        ttk.Checkbutton(hg2_frame, text="HG2IMG Legacy PNG (8-bit RG, flipped)", variable=self.hg2img_compat).pack(anchor="w", pady=(4, 0))
        ttk.Checkbutton(hg2_frame, text="HG2IMG Precision (use R low bits)", variable=self.hg2img_precision).pack(anchor="w")
        ttk.Checkbutton(hg2_frame, text="Output HGT (legacy format)", variable=self.hgt_output).pack(anchor="w")

        hg2_btn_frame = ttk.Frame(hg2_frame)
        hg2_btn_frame.pack(fill="x", pady=5)
        self.btn_hg2_png = ttk.Button(hg2_btn_frame, text="HG2 -> PNG", style="Action.TButton",
                  command=self.convert_hg2_to_png)
        self.btn_hg2_png.pack(side="left", expand=True, fill="x", padx=(0,2))
        self.btn_png_hg2 = ttk.Button(hg2_btn_frame, text="PNG -> HG2", style="Action.TButton",
                  command=self.convert_png_to_hg2)
        self.btn_png_hg2.pack(side="left", expand=True, fill="x", padx=(2,0))
        
        wm_frame = ttk.LabelFrame(left_panel, text=" World Machine Workflow ", padding=10)
        wm_frame.pack(fill="x", pady=10)
        ttk.Label(wm_frame, text="Automate importing height, flow,\nand slope maps into the Auto-Painter.", font=(self.custom_font_name, 8, "italic")).pack(pady=2)
        ttk.Button(wm_frame, text="⚡ Rapid Import Project...", command=self.rapid_import_wm).pack(fill="x", pady=5)

        # --- RIGHT PANEL: HG2 PREVIEW ---
        right_panel = ttk.LabelFrame(container, text=" Heightmap Preview ")
        right_panel.pack(side="right", expand=True, fill="both")

        self.hg2_preview_canvas = tk.Canvas(right_panel, bg="#050505", highlightthickness=0)
        self.hg2_preview_canvas.pack(expand=True, fill="both", padx=10, pady=10)

    def setup_sky_tab(self):
        container = ttk.Frame(self.tab_sky, padding=20)
        container.pack(fill="both", expand=True)

        # --- LEFT PANEL: SKYBOX CONTROLS ---
        left_panel = ttk.Frame(container, width=400) 
        left_panel.pack(side="left", fill="y", padx=(0, 20))
        left_panel.pack_propagate(False) 

        ttk.Label(left_panel, text="SKYBOX TOOLS", font=(self.custom_font_name, 14, "bold"), foreground=BZ_GREEN).pack(anchor="w")
        
        sky_input_frame = ttk.LabelFrame(left_panel, text=" Input Panorama ", padding=10)
        sky_input_frame.pack(fill="x", pady=5)
        ttk.Entry(sky_input_frame, textvariable=self.sky_input_path).pack(side="left", fill="x", expand=True, padx=5)
        ttk.Button(sky_input_frame, text="Browse", command=self.browse_skybox_image).pack(side="left")

        sky_cfg_frame = ttk.Frame(left_panel)
        sky_cfg_frame.pack(fill="x", pady=5)
        ttk.Label(sky_cfg_frame, text="Prefix:").pack(side="left")
        ttk.Entry(sky_cfg_frame, textvariable=self.sky_prefix_var, width=8).pack(side="left", padx=5)
        ttk.Label(sky_cfg_frame, text="Res:").pack(side="left", padx=(10, 0))
        ttk.OptionMenu(sky_cfg_frame, self.sky_out_res, self.sky_out_res.get(), 512, 1024, 2048).pack(side="left")
        
        self.create_fine_tune_slider(left_panel, "Rotation Offset (Deg):", self.sky_rotation, 0, 360, 5, "Rotate the skybox horizontally.", command=self.process_skybox)

        # Skybox Export Toggles (Restored)
        sky_exp_opts = ttk.Frame(left_panel)
        sky_exp_opts.pack(fill="x", pady=5)
        ttk.Checkbutton(sky_exp_opts, text="DDS", variable=self.export_dds).pack(side="left")
        ttk.Checkbutton(sky_exp_opts, text="Material", variable=self.export_mat).pack(side="left")
        ttk.Checkbutton(sky_exp_opts, text="TRN", variable=self.export_trn).pack(side="left")

        self.btn_skybox = ttk.Button(left_panel, text="🚀 EXPORT SKYBOX", command=self.export_skybox, 
                  style="Success.TButton")
        self.btn_skybox.pack(fill="x", pady=(5, 15))

        # --- RIGHT PANEL: SKYBOX PREVIEW ---
        right_panel = ttk.LabelFrame(container, text=" Cubemap Preview ")
        right_panel.pack(side="right", expand=True, fill="both")

        self.sky_preview_canvas = tk.Canvas(right_panel, bg="#050505", highlightthickness=0)
        self.sky_preview_canvas.pack(expand=True, fill="both", padx=10, pady=10)

    def apply_map_preset(self, event=None):
            selection = self.preset_var.get()
            if "Custom" in selection: return
            
            # Extract the number from the string e.g. "Small (2560m)" -> 2560
            import re
            match = re.search(r'\((\d+)m\)', selection)
            if match:
                size = int(match.group(1))
                self.hg2_width_meters.set(size)
                self.hg2_depth_meters.set(size)
    def create_hg2_slider(self, parent, label, var, from_, to, res):
        """Helper to create sliders that trigger the preview update"""
        ttk.Label(parent, text=label, font=(self.custom_font_name, 9)).pack(anchor="w")
        s = tk.Scale(parent, from_=from_, to=to, resolution=res, orient="horizontal", 
                     variable=var, command=self.update_hg2_preview,
                     bg=BZ_BG, fg=BZ_FG, troughcolor="#1a1a1a", activebackground=BZ_GREEN, highlightthickness=0)
        s.pack(fill="x", pady=(0, 8))

    def update_hg2_preview(self, *args):
        path = self.hg2_path.get()
        if not path or not os.path.exists(path): return

        try:
            if path.lower().endswith(".hg2"):
                with open(path, "rb") as f:
                    header = f.read(12)
                    _, depth, x_zones, z_zones, _, _ = struct.unpack("<HHHHHH", header)
                    z_width = 2**depth
                    raw_data = np.frombuffer(f.read(), dtype=np.uint16)
                    
                    full_w, full_h = x_zones * z_width, z_zones * z_width
                    arr = np.zeros((full_h, full_w), dtype=np.float32)
                    
                    idx = 0
                    for zy in range(z_zones):
                        for zx in range(x_zones):
                            zone_size = z_width * z_width
                            zone_block = raw_data[idx:idx+zone_size].reshape((z_width, z_width))
                            arr[zy*z_width:(zy+1)*z_width, zx*z_width:(zx+1)*z_width] = zone_block
                            idx += zone_size
            elif path.lower().endswith(".hgt"):
                zone_size = 128
                x_zones = self.hg2_target_zw.get()
                z_zones = self.hg2_target_zl.get()
                
                # Try TRN if available
                trn_path = os.path.splitext(path)[0] + ".trn"
                trn = TRNParser.parse(trn_path)
                if trn.get("Width") and trn.get("Depth"):
                    zw = int(round(trn["Width"] / 1280.0))
                    zl = int(round(trn["Depth"] / 1280.0))
                    if zw > 0 and zl > 0:
                        x_zones, z_zones = zw, zl
                
                with open(path, "rb") as f:
                    raw_data = np.frombuffer(f.read(), dtype=np.uint16)
                
                expected = x_zones * z_zones * zone_size * zone_size
                if raw_data.size != expected:
                    raise ValueError(f"Invalid HGT size. Expected {expected} entries, got {raw_data.size}.")
                
                full_w, full_h = x_zones * zone_size, z_zones * zone_size
                arr = np.zeros((full_h, full_w), dtype=np.float32)
                
                idx = 0
                for zy in range(z_zones):
                    for zx in range(x_zones):
                        zone_block = raw_data[idx:idx+(zone_size*zone_size)].reshape((zone_size, zone_size))
                        arr[zy*zone_size:(zy+1)*zone_size, zx*zone_size:(zx+1)*zone_size] = zone_block
                        idx += zone_size * zone_size
            else:
                img_input = Image.open(path).convert("I;16")
                arr = np.array(img_input).astype(np.float32)

            # Apply Adjusters
            arr *= self.hg2_brightness.get()
            mean = 32768.0
            arr = (arr - mean) * self.hg2_contrast.get() + mean
            
            # High-precision blur in Mode F (prevents banding)
            temp_img = Image.fromarray(arr, mode='F')
            if self.hg2_smooth_val.get() > 0:
                temp_img = temp_img.filter(ImageFilter.GaussianBlur(self.hg2_smooth_val.get()))
            
            final_arr = np.array(temp_img)
            
            # Better Normalization for UI (prevents stepping/banding)
            f_min, f_max = final_arr.min(), final_arr.max()
            if f_max > f_min:
                norm_arr = (final_arr - f_min) / (f_max - f_min)
            else:
                norm_arr = final_arr / 65535.0
                
            preview_8bit = Image.fromarray((norm_arr * 255).astype(np.uint8))
            
            cw = self.hg2_preview_canvas.winfo_width()
            ch = self.hg2_preview_canvas.winfo_height()
            if cw < 10: cw, ch = 600, 600
            
            preview_8bit.thumbnail((cw, ch), self.resample_method)
            self.hg2_tk_photo = ImageTk.PhotoImage(preview_8bit)
            self.hg2_preview_canvas.delete("all")
            self.hg2_preview_canvas.create_image(cw//2, ch//2, image=self.hg2_tk_photo)
            
        except Exception as e:
            print(f"Preview Update Error: {e}")

    def bind_events(self):
        self.canvas.bind("<ButtonPress-1>", self.on_drag_start)
        self.canvas.bind("<B1-Motion>", self.on_drag_motion)
        self.canvas.bind("<ButtonRelease-1>", self.on_drag_end)
        self.canvas.bind("<MouseWheel>", self.zoom_wheel)
        self.canvas.bind("<Button-4>", self.zoom_wheel)
        self.canvas.bind("<Button-5>", self.zoom_wheel)

    def on_drag_start(self, event):
        self.canvas.config(cursor="fleur")
        self.canvas.scan_mark(event.x, event.y)

    def on_drag_motion(self, event):
        self.canvas.scan_dragto(event.x, event.y, gain=1)

    def on_drag_end(self, event):
        self.canvas.config(cursor="")
        
    def browse_skybox_image(self):
        ftypes = [
            ("All Supported", "*.png *.jpg *.jpeg *.dds *.tga *.hdr *.exr"),
            ("Standard Images", "*.png *.jpg *.jpeg"),
            ("DirectDraw Surface", "*.dds"),
            ("Truevision TGA", "*.tga"),
            ("HDR Formats", "*.hdr *.exr")
        ]
        path = filedialog.askopenfilename(filetypes=ftypes)
        if path:
            self.sky_input_path.set(path)
            self.load_skybox_preview(path)
            self.process_skybox()

    def load_skybox_preview(self, path):
        try:
            img = Image.open(path).convert("RGB")
            w, h = img.size
            ratio = w / h
            
            self.sky_mirror_mode = False
            
            # Aspect Ratio Logic
            if abs(ratio - 4.0) < 0.1:
                self.sky_mirror_mode = True
                new_h = h * 2
                new_img = Image.new("RGB", (w, new_h))
                new_img.paste(img, (0, 0))
                mirrored = ImageOps.flip(img)
                new_img.paste(mirrored, (0, h))
                img = new_img
                self.log("Notice: 4:1 Sky detected. Mirrored to 2:1.", "warning")
            elif abs(ratio - 2.0) > 0.1:
                messagebox.showwarning("Projection Warning", f"Image aspect ratio is {ratio:.2f}:1.\nEquirectangular projection requires 2:1.\nResults may be distorted.")

            # Create optimized preview buffer (max width 1024)
            preview_w = min(1024, img.width)
            preview_h = int(preview_w / 2)
            
            preview_img = img.resize((preview_w, preview_h), self.resample_method)
            self.preview_sky_data = np.array(preview_img).astype(np.float32)
            
        except Exception as e:
            self.log(f"Failed to load skybox: {e}", "error")
            self.preview_sky_data = None

    def process_skybox(self):
        if not hasattr(self, 'preview_sky_data') or self.preview_sky_data is None:
            path = self.sky_input_path.get()
            if path and os.path.exists(path): self.load_skybox_preview(path)
            else: return

        try:
            # Use cached numpy array directly
            img_float = self.preview_sky_data
            
            # 2. Settings
            self.rotation_rad = np.radians(self.sky_rotation.get()) + np.pi
            preview_res = 256 # Low res for speed
            
            face_map = {0: 'pz', 1: 'nz', 2: 'px', 3: 'nx', 4: 'py', 5: 'ny'}
            self.generated_faces = {} 

            # 3. Generate preview faces using Order 1 (Linear)
            for i in range(6):
                face_arr = self.generate_cube_face(img_float, i, preview_res, order=1)
                face_arr = np.clip(face_arr, 0, 255).astype(np.uint8)
                key = face_map[i]
                self.generated_faces[key] = Image.fromarray(face_arr)

            # 4. Update the UI
            self.update_skybox_preview(self.generated_faces)
            
        except Exception as e:
            print(f"Preview Error: {e}")

    def export_skybox(self):
        path = self.sky_input_path.get()
        if not path or not hasattr(self, 'generated_faces'):
            messagebox.showwarning("Warning", "Please load an image first.")
            return

        out_dir = filedialog.askdirectory(title="Select Export Folder")
        if not out_dir: return

        cfg = {
            "path": path,
            "out_dir": out_dir,
            "res": self.sky_out_res.get(),
            "prefix": self.sky_prefix_var.get().lower().strip(),
            "exp_mat": self.export_mat.get(),
            "exp_trn": self.export_trn.get(),
            "mirror": getattr(self, 'sky_mirror_mode', False)
        }
        self.btn_skybox.config(text="GENERATING CUBEMAP...", state="disabled")
        threading.Thread(target=self._export_skybox_worker, args=(cfg,), daemon=True).start()

    def _export_skybox_worker(self, cfg):
        """High-quality export with sorted TRN entries and uppercase material names."""
        try:
            # Load original for high-res processing
            img = Image.open(cfg["path"]).convert("RGB")
            
            if cfg.get("mirror", False):
                w, h = img.size
                new_h = h * 2
                new_img = Image.new("RGB", (w, new_h))
                new_img.paste(img, (0, 0))
                mirrored = ImageOps.flip(img)
                new_img.paste(mirrored, (0, h))
                img = new_img
            
            img_data = np.array(img).astype(np.float32)
            res = cfg["res"]
            
            # Use the user-defined prefix (enforce lowercase for filenames)
            base_name = cfg["prefix"]
            
            # Mapping faces to their specific BZ98 TRN parameters
            # Format: suffix: (Azimuth, Elevation, Roll, StarIndex)
            face_params = {
                'nz': (0, 0, 180, "01"),
                'ny': (0, -90, 0, "02"),
                'nx': (270, 0, 180, "03"),
                'pz': (180, 0, 180, "04"),
                'px': (90, 0, 180, "05"),
                'py': (0, 90, 0, "06")
            }
            
            # Map face_idx to suffixes for image generation logic
            face_map = {0: 'pz', 1: 'nz', 2: 'px', 3: 'nx', 4: 'py', 5: 'ny'}

            # 1. Generate and Save Images and .material files
            for i in range(6):
                face_arr = self.generate_cube_face(img_data, i, res, order=3)
                face_arr = np.clip(face_arr, 0, 255).astype(np.uint8)
                suffix = face_map[i]
                img = Image.fromarray(face_arr)
                
                # Save PNG
                img.save(os.path.join(cfg["out_dir"], f"{base_name}{suffix}.png"))

                # 2. Export .material file
                if cfg["exp_mat"]:
                    mat_filename = f"{base_name}{suffix}.material"
                    with open(os.path.join(cfg["out_dir"], mat_filename), "w") as f:
                        # Material name example: PMARSNZ.MAP (Uppercase)
                        mat_name_upper = f"{base_name.upper()}{suffix.upper()}.MAP"
                        f.write(f"material {mat_name_upper}\n")
                        f.write("{\n    technique\n    {\n        pass\n        {\n")
                        f.write("            vertex_program_ref Sky_vertex\n            {\n            }\n")
                        f.write("            fragment_program_ref Sky_fragment\n            {\n            }\n\n")
                        f.write("            lighting off\n            fog_override true none\n")
                        f.write("            scene_blend alpha_blend\n            depth_write off\n")
                        f.write("            texture_unit\n            {\n")
                        f.write(f"                texture {base_name}{suffix}.dds\n")
                        f.write("            }\n        }\n    }\n}\n")

            # 3. Export TRN Entry (Sorted 01 -> 06)
            if cfg["exp_trn"]:
                with open(os.path.join(cfg["out_dir"], "TRN_Entries.txt"), "w") as f:
                    f.write("[Sky]\n\nBackdropTexture =\n\nBackdropDistance= 400\n\n")
                    f.write("BackdropWidth   = 800\n\nBackdropHeight  = 100\n\n[Stars]\n\nRadius      = 4096\n\n")
                    
                    # Sort by the StarIndex ("01", "02", etc.)
                    sorted_items = sorted(face_params.items(), key=lambda x: x[1][3])
                    
                    for suffix, (azi, elev, roll, idx) in sorted_items:
                        f.write(f"Texture{idx}   = {base_name}{suffix}.map\n")
                        f.write(f"Color{idx}     = \"255 255 255 96\"\n")
                        f.write(f"Alpha{idx}     = 0\n")
                        f.write(f"Size{idx}      = 8192\n")
                        f.write(f"Azimuth{idx}   = {azi}\n")
                        f.write(f"Elevation{idx} = {elev}\n")
                        f.write(f"Roll{idx}      = {roll}\n\n")

            self.log("Success: Export Complete. TRN entries sorted 01-06.", "success")
        except Exception as e:
            self.log(f"Export Error: {str(e)}", "error")
        finally:
            self.root.after(0, lambda: self.btn_skybox.config(text="🚀 EXPORT SKYBOX", state="normal"))

    def read_bz_map(self, path, palette=None):
        with open(path, 'rb') as f:
            header = f.read(8)
            if len(header) < 8: return None
            rb, fmt, h, _ = struct.unpack('<4H', header)
            if fmt >= len(BZMapFormat.bpp): return None
            w = rb // BZMapFormat.bpp[fmt]
            data = f.read()
            
            if fmt == BZMapFormat.INDEXED:
                img = Image.frombytes('L', (w, h), data)
                if palette:
                    flat_pal = [v for c in palette for v in c]
                    img.putpalette(flat_pal)
                    img = img.convert("RGBA")
                else:
                    img = img.convert("RGBA")
            elif fmt in (BZMapFormat.ARGB4444, BZMapFormat.RGB565):
                # 16-bit tiles. Pillow has no raw decoder for either packing, so
                # unpack the channels by hand and widen each to 8 bits. Before
                # this branch existed both formats fell through to the 32-bit
                # path, which asks for four bytes per pixel and dies with
                # "not enough image data" -- and 16-bit is what most non-stock
                # 1.5 planet sets ship (Callisto in Legends of War, for one), so
                # the converter could not read them at all.
                v = np.frombuffer(data, dtype='<u2', count=w * h).reshape(h, w)
                if fmt == BZMapFormat.RGB565:
                    r = (((v >> 11) & 0x1F).astype(np.uint16) * 255 + 15) // 31
                    g = (((v >> 5) & 0x3F).astype(np.uint16) * 255 + 31) // 63
                    b = ((v & 0x1F).astype(np.uint16) * 255 + 15) // 31
                    a = np.full(v.shape, 255, dtype=np.uint16)
                else:
                    a = ((v >> 12) & 0xF).astype(np.uint16) * 17
                    r = ((v >> 8) & 0xF).astype(np.uint16) * 17
                    g = ((v >> 4) & 0xF).astype(np.uint16) * 17
                    b = (v & 0xF).astype(np.uint16) * 17
                img = Image.fromarray(np.dstack([r, g, b, a]).astype(np.uint8), 'RGBA')
            else:
                 img = Image.frombytes('RGBA', (w, h), data, 'raw', 'BGRA')

            # BZ .MAP scanlines are stored bottom-up (DIB order), but frombytes
            # fills top-down. Without this flip every tile lands mirrored: solids
            # look fine (noise is symmetric) but caps/diagonals end up with their
            # transition on the N/NE edge instead of the S/SE edge that the Redux
            # terrain renderer rotates from, so no transition lines up in game.
            return img.transpose(Image.FLIP_TOP_BOTTOM)

    def generate_cube_face(self, img, face_idx, res, order=3):
        grid = np.linspace(-1 + (1/res), 1 - (1/res), res)
        x_coords, y_coords = np.meshgrid(grid, grid)

        if face_idx == 0:   # pz
            x_p, y_p, z_p = np.full_like(x_coords, -1), -x_coords, -y_coords
        elif face_idx == 1: # nz
            x_p, y_p, z_p = np.full_like(x_coords, 1), x_coords, -y_coords
        elif face_idx == 2: # px
            x_p, y_p, z_p = x_coords, np.full_like(x_coords, -1), -y_coords
        elif face_idx == 3: # nx
            x_p, y_p, z_p = -x_coords, np.full_like(x_coords, 1), -y_coords
        elif face_idx == 4: # py
            x_p, y_p, z_p = -y_coords, -x_coords, np.full_like(x_coords, 1)
        elif face_idx == 5: # ny
            x_p, y_p, z_p = y_coords, -x_coords, np.full_like(x_coords, -1)
        
        r = np.sqrt(x_p**2 + y_p**2 + z_p**2)
        lat = np.acos(z_p / r)
        lon = np.arctan2(y_p, x_p) + self.rotation_rad
        lon = lon % (2 * np.pi) 

        in_h, in_w = img.shape[:2]
        u_img = (in_w * lon / (2 * np.pi) - 0.5)
        v_img = (in_h * lat / np.pi - 0.5)
        
        coords = np.array([v_img.ravel(), u_img.ravel()])
        channels = []
        for i in range(3):
            ch = map_coordinates(img[:,:,i], coords, order=order, mode='wrap').reshape(res, res)
            channels.append(ch)
            
        return np.stack(channels, axis=-1)

    def update_skybox_preview(self, face_dict):
        # Create a 4x3 grid layout for the preview
        res = next(iter(face_dict.values())).width 
        canvas_img = Image.new("RGB", (res * 4, res * 3), (30, 30, 30))

        # BZ98 Star Layout Mapping
        layout = {
            'nx': (0, 1), 'pz': (1, 1), 'px': (2, 1), 'nz': (3, 1),
            'py': (1, 0), 'ny': (1, 2)
        }

        for face, (grid_x, grid_y) in layout.items():
            if face in face_dict:
                canvas_img.paste(face_dict[face], (grid_x * res, grid_y * res))

        # Update the canvas
        self.root.update_idletasks()
        cw = self.sky_preview_canvas.winfo_width()
        ch = self.sky_preview_canvas.winfo_height()
        if cw < 10: cw, ch = 800, 600
        
        canvas_img.thumbnail((cw, ch), self.resample_method)
        self.world_tk_photo = ImageTk.PhotoImage(canvas_img)
        
        self.sky_preview_canvas.delete("all")
        self.sky_preview_canvas.create_image(cw//2, ch//2, anchor="center", image=self.world_tk_photo)

    def on_res_change(self, *args):
        if self.source_dir: self.browse(initial=False) # Reload images with new res
        self.update_preview()

    def cycle_seed(self):
        self.seed_var.set(random.randint(0, 99999))
        self.update_preview()

    def force_refresh(self, *args):
        self.update_preview()

    def on_mode_change(self, *args):
        all_styles = [
            "Square/Blocky", "Sawtooth", "Interlocking L", "Sine Wave", "Stairs/Steps",
            "Fractal Noise", "Soft Clouds", "Binary Dither", "Voronoi/Cells", 
            "Plasma/Circuit", "Radial/Impact"
        ]
        self.style_dropdown['values'] = all_styles
        if not self.style_var.get() in all_styles:
            self.style_var.set("Square/Blocky")
        self.update_preview()
        
    def apply_style_preset(self, event=None):
        name = self.selected_style_preset.get()
        if name in self.style_presets and name != "Custom":
            p = self.style_presets[name]
            self.style_var.set(p["style"])
            self.depth_var.set(p["depth"])
            self.teeth_count.set(p["teeth"])
            self.jitter_var.set(p["jitter"])
            self.blend_softness.set(p["soft"])
            self.update_preview()

    def zoom_wheel(self, event):
        if event.num == 4 or event.delta > 0: self.zoom_level *= 1.1
        else: self.zoom_level *= 0.9
        self.zoom_level = max(0.1, min(10.0, self.zoom_level))
        self.refresh_canvas()

    def generate_mask(self, mode="diag", cfg=None):
        """GUI compatibility wrapper around the headless atlas mask service."""
        if cfg is None:
            cfg = {
                "res": self.tile_res_var.get(),
                "style": self.style_var.get(),
                "seed": self.seed_var.get(),
                "depth": self.depth_var.get(),
                "teeth": self.teeth_count.get(),
                "jitter": self.jitter_var.get(),
                "softness": self.blend_softness.get(),
            }
        return atlas_generate_transition_mask(mode, cfg)

    def browse(self, initial=True):
        if initial:
            self.source_dir = filedialog.askdirectory()
        if not self.source_dir: return
        res = self.tile_res_var.get(); self.groups = {}
        pattern = re.compile(r's(\d+)(?:_([a-z]))?', re.IGNORECASE)
        for f in sorted(os.listdir(self.source_dir)):
            match = pattern.search(f)
            if match:
                base_id = int(match.group(1)); var = match.group(2).upper() if match.group(2) else "A"
                if base_id not in self.groups: self.groups[base_id] = {}
                try: 
                    img = Image.open(os.path.join(self.source_dir, f)).convert("RGBA").resize((res, res), self.resample_method)
                    self.groups[base_id][var] = img
                except: continue
        self.update_preview()

    def update_preview(self, *args):
        if not self.groups: return
        res = self.tile_res_var.get()
        mode = self.trans_mode_var.get()
        baked = []
        indices = sorted(self.groups.keys())
        c_m, d_m = self.generate_mask("cap"), self.generate_mask("diag")
        
# 1. Solids (Match the repeated index logic)
        for i in indices:
            for var in sorted(self.groups[i].keys()):
                baked.append(self.groups[i][var])
        
        # 2. Transitions (Linear vs Matrix logic)
        for idx, i in enumerate(indices):
            if mode == "Linear":
                targets = [indices[idx + 1]] if idx + 1 < len(indices) else []
            else: # Matrix mode
                targets = indices[idx + 1:]
                
            for j in targets:
                c_i = self.groups[i]["A"].copy()
                c_i.paste(self.groups[j]["A"], (0,0), c_m)
                d_i = self.groups[i]["A"].copy()
                d_i.paste(self.groups[j]["A"], (0,0), d_m)
                baked.append(c_i)
                baked.append(d_i)
        
        gs = math.ceil(math.sqrt(len(baked) + 1))
        total_size = gs * res
        
        # UI update for atlas size
        if total_size > 8192:
            self.info_label.config(text=f"CRITICAL: {total_size}px (Exceeds 8k!)", foreground="#ff5252")
        else:
            self.info_label.config(text=f"Atlas Size: {total_size}x{total_size}", foreground="#4caf50")

        self.full_atlas_preview = Image.new("RGBA", (total_size, total_size), (30, 30, 30, 255))
        for idx, img in enumerate(baked):
            pos = idx + 1
            x, y = (pos % gs) * res, (pos // gs) * res
            self.full_atlas_preview.paste(img, (x,y))
        self.refresh_canvas()

    def refresh_canvas(self):
        if not self.full_atlas_preview: return
        w, h = self.full_atlas_preview.size
        new_size = (int(w * self.zoom_level), int(h * self.zoom_level))
        mode = Image.NEAREST
        self.preview_tk = ImageTk.PhotoImage(self.full_atlas_preview.resize(new_size, mode))
        self.canvas.delete("all")
        self.canvas.create_image(0, 0, anchor="nw", image=self.preview_tk)
        self.canvas.config(scrollregion=self.canvas.bbox("all"))

    def generate(self):
        if not self.groups: return
        cfg = {
            "res": self.tile_res_var.get(),
            "prfx": self.planet_var.get().lower(),
            "mode": self.trans_mode_var.get(),
            "out_dir": self.out_dir_var.get(),
            "exp_dds": self.exp_dds.get(),
            "exp_png": self.exp_png.get(),
            "exp_normal": self.exp_normal.get(),
            "exp_specular": self.exp_specular.get(),
            "exp_emissive": self.exp_emissive.get(),
            "exp_csv": self.exp_csv.get(),
            "exp_trn": self.exp_trn.get(),
            "exp_mat": self.exp_mat.get(),
            "style": self.style_var.get(),
            "seed": self.seed_var.get(),
            "depth": self.depth_var.get(),
            "teeth": self.teeth_count.get(),
            "jitter": self.jitter_var.get(),
            "softness": self.blend_softness.get(),
            "groups": self.groups 
        }
        self.btn_generate.config(text="BUILDING ATLAS...", state="disabled")
        threading.Thread(target=self._generate_worker, args=(cfg,), daemon=True).start()

    def _generate_worker(self, cfg):
        try:
            result = build_custom_atlas(cfg)
            self.log(
                f"Export Done: World bundle generated for {result['prefix']}! "
                f"(Grid: {result['grid']}x{result['grid']})",
                "success",
            )
        except Exception as e:
            self.log(f"Error: {str(e)}", "error")
        finally:
            self.root.after(
                0,
                lambda: self.btn_generate.config(text="2. BUILD ATLAS", state="normal"),
            )

    def setup_mission_tab(self):
        container = ttk.Frame(self.tab_mission, padding=20)
        container.pack(fill="both", expand=True)
        
        # --- LEFT COLUMN: CONTROLS ---
        left_col = ttk.Frame(container, width=300)
        left_col.pack(side="left", fill="y", padx=(0, 20))
        left_col.pack_propagate(False)
        
        # 1. Background Map
        ttk.Label(left_col, text="1. BACKGROUND MAP", font=(self.custom_font_name, 11, "bold"), foreground=BZ_GREEN).pack(anchor="w")
        ttk.Label(left_col, text="Load an image or HG2 to verify alignment.", font=("Consolas", 8), foreground="#888888").pack(anchor="w", pady=(0, 5))
        
        ttk.Button(left_col, text="📂 Load Map Image/HG2", command=self.browse_mission_bg).pack(fill="x", pady=(0, 15))
        
        # 2. Mission Overlay
        ttk.Label(left_col, text="2. MISSION DATA", font=(self.custom_font_name, 11, "bold"), foreground=BZ_GREEN).pack(anchor="w")
        ttk.Label(left_col, text="Load .bzn (ASCII) to visualize objects.", font=("Consolas", 8), foreground="#888888").pack(anchor="w", pady=(0, 5))
        ttk.Button(left_col, text="📂 Load .bzn Mission", command=self.load_mission_overlay).pack(fill="x", pady=(0, 15))
        
        # Info Box
        self.mission_info = tk.Text(left_col, height=10, bg="#050505", fg=BZ_FG, relief="flat", font=("Consolas", 9))
        self.mission_info.pack(fill="x", pady=5)
        self.mission_info.insert("1.0", "Expected TRN Offset: N/A\nObjects Loaded: 0")
        self.mission_info.config(state="disabled")
        
        # --- RIGHT COLUMN: PREVIEW ---
        right_col = ttk.Frame(container)
        right_col.pack(side="right", fill="both", expand=True)
        
        self.mission_canvas = tk.Canvas(right_col, bg="#000000", highlightthickness=0)
        self.mission_canvas.pack(fill="both", expand=True)
        
        # Bind Mouse Zoom/Pan (Reuse logic?)
        self.mission_canvas.bind("<MouseWheel>", self._on_mission_zoom)
        self.mission_canvas.bind("<ButtonPress-1>", self._on_mission_pan_start)
        self.mission_canvas.bind("<B1-Motion>", self._on_mission_pan_move)
        
        self.mission_zoom = 1.0
        self.mission_pan_x = 0
        self.mission_pan_y = 0
        self.mission_bg_img = None
        self.mission_bg_photo = None
        
    def browse_mission_bg(self):
        path = filedialog.askopenfilename(filetypes=[("Map Image", "*.hg2 *.png *.bmp *.jpg")])
        if not path: return
        
        # Load Image
        try:
            if path.lower().endswith(".hg2"):
                # HG2 Loading Logic (Visual)
                with open(path, "rb") as f:
                    header = f.read(12)
                    _, _, z_w, z_l, _, _ = struct.unpack("<HHHHHH", header)
                    raw_data = f.read()
                    arr = np.frombuffer(raw_data, dtype=np.uint16).reshape((z_l*64, z_w*64))
                    # Normalize for display
                    arr_norm = (arr / 4095.0 * 255).astype(np.uint8)
                    img = Image.fromarray(arr_norm)
            else:
                img = Image.open(path).convert("L") # Mode L for grayscale map
                
            self.mission_bg_img = img
            self.redraw_mission_canvas()
            
        except Exception as e:
            messagebox.showerror("Error", f"Failed to load map: {e}")

    def _on_mission_zoom(self, event):
        scale = 1.1 if event.delta > 0 else 0.9
        self.mission_zoom *= scale
        self.redraw_mission_canvas()

    def _on_mission_pan_start(self, event):
        self._pan_start_x = event.x
        self._pan_start_y = event.y

    def _on_mission_pan_move(self, event):
        dx = event.x - self._pan_start_x
        dy = event.y - self._pan_start_y
        self.mission_pan_x += dx
        self.mission_pan_y += dy
        self._pan_start_x = event.x
        self._pan_start_y = event.y
        self.redraw_mission_canvas()
        
    def redraw_mission_canvas(self):
        self.mission_canvas.delete("all")
        cw = self.mission_canvas.winfo_width()
        ch = self.mission_canvas.winfo_height()
        
        # 1. Draw Background
        if self.mission_bg_img:
            # Scale and Position
            w, h = self.mission_bg_img.size
            new_w = int(w * self.mission_zoom)
            new_h = int(h * self.mission_zoom)
            
            # Optimization: Don't resize if huge? Tkinter handles it okayish.
            resized = self.mission_bg_img.resize((new_w, new_h), Image.Resampling.NEAREST)
            self.mission_bg_photo = ImageTk.PhotoImage(resized)
            
            # Center + Pan
            x = cw//2 + self.mission_pan_x
            y = ch//2 + self.mission_pan_y
            self.mission_canvas.create_image(x, y, image=self.mission_bg_photo, anchor="center")
            
            # Store bounds for object mapping
            self.map_draw_rect = (x - new_w//2, y - new_h//2, new_w, new_h)
            
        # 2. Draw Objects
        if hasattr(self, 'mission_objects') and self.mission_objects:
            self.draw_mission_objects_on_canvas(self.mission_canvas)

    def draw_mission_objects_on_canvas(self, canvas):
        # We need the map bounds to map world coords to canvas coords.
        # If no map bg loaded, assume 5120m centered?
        if not hasattr(self, 'map_draw_rect'):
             # Default centered 500x500 box?
             cw = canvas.winfo_width()
             ch = canvas.winfo_height()
             self.map_draw_rect = (cw//2-250, ch//2-250, 500, 500)
             
        mx, my, mw, mh = self.map_draw_rect
        
        # Coordinate Space:
        # Texture Map (0,0) -> (Width, Height) usually corresponds to World (MinX, MinZ) -> (MaxX, MaxZ)
        # BZ Coords: +X (East), +Z (North).
        # Image Coords: +X (Right), +Y (Down).
        # So World Z maps to Image Y (inverted).
        
        # Assume Map Image covers the whole TRN area?
        # If we parsed TRN MinX/MinZ, we can offset.
        offset_x = getattr(self, 'min_x', 0)
        offset_z = getattr(self, 'min_z', 0)
        
        # We need map dimensions in METERS to scale properly.
        # HG2 -> 1px = ~10m? Or 20m? Depends on resolution.
        # If we loaded an HG2, we know pixels. If we don't know grid step, we guess.
        # Config has "tile_res" and "map_presets".
        # Let's assume the loaded image represents the full square world.
        # World Size?
        try:
             world_size = int(self.selected_preset.get().split('(')[1].split('m')[0])
        except:
             world_size = 5120
             
        # Scale Factor: Pixels per Meter
        ppm = mw / world_size
        
        for obj in self.mission_objects:
            wx = obj["pos"][0]
            wz = obj["pos"][2] # Z is height? No, pos=(x,h,z) from my parser
             
            # Normalize to 0-WorldSize based on offset
            # Obj 0,0 is at World 0,0.
            # Map Image 0,0 (Top Left) corresponds to World MinX, MaxZ (since Z goes up)
            # Wait, BZ coordinates: 0,0 is center of specific map? Or corner?
            # TRN Map:
            # (MinX, MinZ) -> Bottom Left of the map?
            # So Image (0, Height) -> (MinX, MinZ)
            # Image (0, 0) -> (MinX, MaxZ)
            
            # Rel to Map Origin
            rel_x = wx - offset_x
            rel_z = wz - offset_z
            
            # Map to Image Pixels
            # img_x = rel_x * ppm
            # img_y = (world_size - rel_z) * ppm (Flip Z)
            
            # Canvas Coords
            cx = mx + (rel_x * ppm)
            cy = my + (mh - (rel_z * ppm)) # Flip Z for image Y 
            
            # Draw
            color = BZ_GREEN
            cls = obj.get("odf", "").lower()
            if "recycle" in cls or "cons" in cls: color = "#ffee00" # Yellow
            elif "fact" in cls: color = "#ff8800" # Orange
            elif "turr" in cls or "tow" in cls: color = "#ff4444" # Red
            elif "scav" in cls: color = "#0088ff" # Blue
            
            canvas.create_rectangle(cx-2, cy-2, cx+2, cy+2, fill=color, outline="")

    def load_auto_painter_config(self):
        path = filedialog.askopenfilename(filetypes=[("Paint Config", "*.trn *.ini *.txt"), ("All Files", "*.*")])
        if not path:
            return

        ext = os.path.splitext(path)[1].lower()
        
        if ext == ".trn":
            # Load TRN -> Auto-populate materials
            data = TRNParser.parse(path)
            if not data.get("TextureTypes"):
                messagebox.showwarning("Warning", "No [TextureTypeX] sections found in TRN.")
                return
                
            if messagebox.askyesno("Confirm", "This will clear existing rules and populate from TRN. Continue?"):
                self.clear_paint_rules()
                
                # Default max height
                max_h = 1000.0
                
                for tid in data["TextureTypes"]:
                    self.add_paint_rule_internal(tid, 0, max_h, 0, 90)
                
                messagebox.showinfo("Loaded", f"Loaded {len(data['TextureTypes'])} materials from TRN.")
                
        else:
            # Load INI/TXT [LayerX] format
            try:
                import configparser
                config = configparser.ConfigParser()
                config.read(path)
                
                new_rules = []
                for section in config.sections():
                    if section.lower().startswith("layer"):
                        try:
                            mat_str = config.get(section, "Material")
                            mat_id = int(mat_str.split('(')[0].strip())
                            
                            min_h = float(config.get(section, "ElevationStart"))
                            max_h = float(config.get(section, "ElevationEnd"))
                            min_s = float(config.get(section, "SlopeStart"))
                            max_s = float(config.get(section, "SlopeEnd"))
                            
                            new_rules.append({
                                'mat_id': mat_id,
                                'min_h': min_h, 'max_h': max_h,
                                'min_s': min_s, 'max_s': max_s
                            })
                        except Exception as e:
                            print(f"Skipping section {section}: {e}")
                            
                if new_rules:
                    if messagebox.askyesno("Confirm", f"Found {len(new_rules)} rules. Replace existing?"):
                        self.paint_rules = new_rules
                        self.refresh_rules_list()
            except Exception as e:
                messagebox.showerror("Error", f"Failed to parse INI: {e}")

    def save_auto_painter_config(self):
        path = filedialog.asksaveasfilename(defaultextension=".ini", filetypes=[("INI Config", "*.ini")])
        if not path:
            return
            
        try:
            with open(path, 'w') as f:
                for i, rule in enumerate(self.paint_rules):
                    f.write(f"[Layer{i}]\n")
                    f.write(f"ElevationStart = {rule['min_h']}\n")
                    f.write(f"ElevationEnd   = {rule['max_h']}\n")
                    f.write(f"SlopeStart     = {rule['min_s']}\n")
                    f.write(f"SlopeEnd       = {rule['max_s']}\n")
                    f.write(f"Material       = {rule['mat_id']}\n\n")
            messagebox.showinfo("Success", "Rules saved.")
        except Exception as e:
            messagebox.showerror("Error", f"Failed to save: {e}")

    def validate_rules(self):
        sorted_rules = sorted(self.paint_rules, key=lambda x: x['min_h'])
        warnings = []
        
        for i in range(len(sorted_rules)):
            r1 = sorted_rules[i]
            for j in range(i+1, len(sorted_rules)):
                r2 = sorted_rules[j]
                
                h_overlap = max(0, min(r1['max_h'], r2['max_h']) - max(r1['min_h'], r2['min_h']))
                if h_overlap > 0:
                    s_overlap = max(0, min(r1['max_s'], r2['max_s']) - max(r1['min_s'], r2['min_s']))
                    if s_overlap > 0:
                        warnings.append(f"Overlap: Rule {i}(Mat{r1['mat_id']}) & {j}(Mat{r2['mat_id']})")
        
        if warnings:
            messagebox.showwarning("Validation Issues", "\n".join(warnings[:10]))
        else:
            messagebox.showinfo("Validation", "No obvious overlaps detected.")

    def auto_balance_rules(self):
        if not self.paint_rules:
            return
        
        count = len(self.paint_rules)
        max_h = 819.1 # Max BZMapIO elevation (8191 / 10)
        chunk = max_h / count
        
        for i, rule in enumerate(self.paint_rules):
            rule['min_h'] = float(i * chunk)
            rule['max_h'] = float((i + 1) * chunk)
            rule['min_s'] = 0
            rule['max_s'] = 90
            
        self.refresh_rules_list()
        messagebox.showinfo("Auto-Balance", f"Balanced {count} rules across 0-{max_h}m.")

    def add_paint_rule_internal(self, mat_id, min_h, max_h, min_s, max_s, mask_path=""): 
        self.paint_rules.append({
            "mat_id": mat_id,
            "min_h": float(min_h),
            "max_h": float(max_h),
            "min_s": float(min_s),
            "max_s": float(max_s), "mask_path": mask_path
        })
        self.refresh_rules_list()

if __name__ == "__main__":
    root = tk.Tk(); app = BZ98TRNArchitect(root); root.mainloop()
