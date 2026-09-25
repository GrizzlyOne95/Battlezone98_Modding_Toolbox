"""Toolbox design system: colour tokens, fonts and ttk styles.

The standalone tools each re-created the same dark / green / cyan Battlezone
look. The shell defines it once here. Shell widgets only use the
``Toolbox.*`` style names so the generic styles (``TButton``, ``Treeview``,
...) that embedded legacy modules still configure for themselves cannot
restyle the shell.
"""

from __future__ import annotations

import sys
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk

from bztoolbox.app import fonts

# --- colour tokens --------------------------------------------------------
BG = "#0a0a0a"          # window background (matches every legacy tool)
SURFACE = "#111411"     # cards, sidebar
SURFACE_ALT = "#181c18" # hover / selected rows
BORDER = "#263026"
FG = "#d4d4d4"
MUTED = "#8a948a"
ACCENT = "#00ff00"      # Battlezone green
ACCENT_DIM = "#004400"
ACCENT_2 = "#00ffff"    # cyan secondary
WARNING = "#ffb000"
ERROR = "#ff4d4d"
INFO = ACCENT_2
SUCCESS = ACCENT

SEVERITY_COLORS = {"error": ERROR, "warning": WARNING, "info": INFO}

# --- fonts ----------------------------------------------------------------
HEADING_FAMILY = "Consolas"
BODY_FAMILY = "Segoe UI" if sys.platform == "win32" else "TkDefaultFont"
MONO_FAMILY = "Consolas" if sys.platform == "win32" else "TkFixedFont"

_fonts_loaded = False


def load_fonts(root: tk.Misc) -> None:
    """Register the bundled Battlezone face once and pick font families."""
    global _fonts_loaded, HEADING_FAMILY, BODY_FAMILY, MONO_FAMILY
    if _fonts_loaded:
        return
    _fonts_loaded = True
    families = set(tkfont.families(root))
    if fonts.bz_font(fallback="") == fonts.BZ_FONT_FAMILY:
        families = set(tkfont.families(root)) | {fonts.BZ_FONT_FAMILY}
    if fonts.BZ_FONT_FAMILY in families:
        HEADING_FAMILY = fonts.BZ_FONT_FAMILY
    elif "Consolas" not in families:
        HEADING_FAMILY = "TkFixedFont" if sys.platform != "win32" else "Courier New"
    if BODY_FAMILY not in families and not BODY_FAMILY.startswith("Tk"):
        BODY_FAMILY = "TkDefaultFont"
    if MONO_FAMILY not in families and not MONO_FAMILY.startswith("Tk"):
        MONO_FAMILY = "TkFixedFont"


def font(kind: str = "body", size: int = 10, weight: str = "normal"):
    family = {"heading": HEADING_FAMILY, "mono": MONO_FAMILY}.get(kind, BODY_FAMILY)
    if family.startswith("Tk"):
        base = tkfont.nametofont(family).actual()
        return (base["family"], size, weight)
    return (family, size, weight)


def apply(root: tk.Misc) -> None:
    """Configure the ``Toolbox.*`` styles for the current ttk theme."""
    load_fonts(root)
    style = ttk.Style(root)
    if style.theme_use() not in ("default", "clam", "alt"):
        style.theme_use("default")
    _configure(style)
    # Legacy modules call ``theme_use(...)``; styles are per-theme in ttk, so
    # re-apply ours whenever the theme changes underneath us.
    if not getattr(root, "_toolbox_theme_bound", False):
        root.bind("<<ThemeChanged>>", lambda _e: _configure(ttk.Style(root)), add="+")
        root._toolbox_theme_bound = True


def _configure(style: ttk.Style) -> None:
    body = font("body", 10)
    small = font("body", 9)
    style.configure("Toolbox.TFrame", background=BG)
    style.configure("Toolbox.Surface.TFrame", background=SURFACE)
    style.configure("Toolbox.Card.TFrame", background=SURFACE, relief="solid", borderwidth=1)
    style.configure("Toolbox.TLabel", background=BG, foreground=FG, font=body)
    style.configure("Toolbox.Surface.TLabel", background=SURFACE, foreground=FG, font=body)
    style.configure("Toolbox.Muted.TLabel", background=BG, foreground=MUTED, font=small)
    style.configure("Toolbox.SurfaceMuted.TLabel", background=SURFACE, foreground=MUTED, font=small)
    style.configure("Toolbox.Title.TLabel", background=BG, foreground=ACCENT, font=font("heading", 18, "bold"))
    style.configure("Toolbox.Heading.TLabel", background=BG, foreground=ACCENT_2, font=font("heading", 12, "bold"))
    style.configure("Toolbox.CardTitle.TLabel", background=SURFACE, foreground=ACCENT, font=font("heading", 11, "bold"))
    style.configure("Toolbox.Stat.TLabel", background=SURFACE, foreground=FG, font=font("heading", 20, "bold"))
    style.configure("Toolbox.Brand.TLabel", background=SURFACE, foreground=ACCENT, font=font("heading", 13, "bold"))
    for name, colour in (("Error", ERROR), ("Warning", WARNING), ("Info", INFO), ("Success", SUCCESS)):
        style.configure(f"Toolbox.{name}.TLabel", background=BG, foreground=colour, font=body)
        style.configure(f"Toolbox.Surface{name}.TLabel", background=SURFACE, foreground=colour, font=body)

    style.configure("Toolbox.TButton", background=SURFACE_ALT, foreground=FG, bordercolor=BORDER,
                    focusthickness=1, focuscolor=ACCENT_DIM, padding=(10, 4), font=body, relief="flat")
    style.map("Toolbox.TButton",
              background=[("disabled", SURFACE), ("pressed", ACCENT_DIM), ("active", "#223022")],
              foreground=[("disabled", MUTED), ("active", ACCENT)])
    style.configure("Toolbox.Accent.TButton", background=ACCENT_DIM, foreground=ACCENT, padding=(12, 5),
                    font=font("body", 10, "bold"), relief="flat")
    style.map("Toolbox.Accent.TButton",
              background=[("disabled", SURFACE), ("pressed", "#006600"), ("active", "#005500")],
              foreground=[("disabled", MUTED)])
    style.configure("Toolbox.Link.TButton", background=SURFACE, foreground=ACCENT_2, padding=(4, 1),
                    font=small, relief="flat", borderwidth=0)
    style.map("Toolbox.Link.TButton", foreground=[("active", ACCENT)], background=[("active", SURFACE)])

    style.configure("Toolbox.TEntry", fieldbackground="#050505", foreground=FG, insertcolor=ACCENT,
                    bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER)
    style.configure("Toolbox.TCheckbutton", background=BG, foreground=FG, font=body)
    style.map("Toolbox.TCheckbutton", background=[("active", BG)], foreground=[("active", ACCENT)])
    style.configure("Toolbox.Surface.TCheckbutton", background=SURFACE, foreground=FG, font=body)
    style.map("Toolbox.Surface.TCheckbutton", background=[("active", SURFACE)], foreground=[("active", ACCENT)])
    style.configure("Toolbox.TCombobox", fieldbackground="#050505", foreground=FG, background=SURFACE_ALT,
                    arrowcolor=ACCENT, selectbackground=ACCENT_DIM, selectforeground=ACCENT)
    style.map("Toolbox.TCombobox", fieldbackground=[("readonly", "#050505")], foreground=[("readonly", FG)],
              background=[("readonly", SURFACE_ALT)])

    style.configure("Toolbox.Horizontal.TProgressbar", troughcolor=SURFACE, background=ACCENT,
                    bordercolor=BORDER, lightcolor=ACCENT, darkcolor=ACCENT_DIM)
    style.configure("Toolbox.TSeparator", background=BORDER)

    for tree in ("Toolbox.Nav.Treeview", "Toolbox.Treeview"):
        style.configure(tree, background=SURFACE if "Nav" in tree else "#070907", fieldbackground=SURFACE if "Nav" in tree else "#070907",
                        foreground=FG, bordercolor=BORDER, borderwidth=0, font=body,
                        rowheight=26 if "Nav" in tree else 22)
        style.map(tree, background=[("selected", ACCENT_DIM)], foreground=[("selected", ACCENT)])
    style.layout("Toolbox.Nav.Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
    # raised + border: the column dividers stay visible, so users can see where to drag
    style.configure("Toolbox.Treeview.Heading", background=SURFACE_ALT, foreground=ACCENT_2,
                    font=font("body", 9, "bold"), relief="raised", borderwidth=1,
                    bordercolor=BORDER, lightcolor=BORDER, darkcolor="#000000")
    style.map("Toolbox.Treeview.Heading", background=[("active", SURFACE_ALT)])

    style.configure("Toolbox.TNotebook", background=BG, borderwidth=0)
    style.configure("Toolbox.TNotebook.Tab", background=SURFACE, foreground=MUTED, padding=(12, 4), font=body)
    style.map("Toolbox.TNotebook.Tab", background=[("selected", ACCENT_DIM)], foreground=[("selected", ACCENT)])
    style.configure("Toolbox.Vertical.TScrollbar", background=SURFACE_ALT, troughcolor=BG,
                    bordercolor=BG, arrowcolor=MUTED)
    style.configure("Toolbox.Horizontal.TScrollbar", background=SURFACE_ALT, troughcolor=BG,
                    bordercolor=BG, arrowcolor=MUTED)
