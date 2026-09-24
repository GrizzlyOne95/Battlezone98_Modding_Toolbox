"""Texture Manager entrypoint with stock palette selection for the MAP converter."""
from __future__ import annotations

import os

from bztoolbox.modules.textures import tex_man as legacy
from bztoolbox.modules.textures import tex_man_entry as compat
from bztoolbox.modules.textures.makemap_compat import read_palette
from bztoolbox.modules.textures.stock_palettes import STOCK_PALETTE_NAMES, get_stock_palette

WORKSPACE_PALETTE_LABEL = "[Workspace Palette]"
EXTERNAL_PALETTE_LABEL = "[External .ACT]"


def _active_palette(app):
    """Resolve the MAP palette in priority order: stock, external ACT, workspace."""
    selection_var = getattr(app, "map_stock_palette_var", None)
    selection = selection_var.get() if selection_var is not None else WORKSPACE_PALETTE_LABEL

    if selection in STOCK_PALETTE_NAMES:
        return get_stock_palette(selection)

    override = app.custom_pal_path.get() if hasattr(app, "custom_pal_path") else ""
    if override and os.path.exists(override) and override.lower().endswith(".act"):
        return read_palette(override)

    return [tuple(c) for c in app.palette]


def install_stock_palette_integration():
    """Add a stock-palette selector to the legacy MAP tab without changing the legacy UI module."""
    original_setup = legacy.BZReduxSuite.setup_map_tab
    original_load_override = legacy.BZReduxSuite.ui_load_override_pal
    original_reset = legacy.BZReduxSuite.reset_map_palette

    def select_stock_palette(app, _event=None):
        selection = app.map_stock_palette_var.get()
        if selection not in STOCK_PALETTE_NAMES:
            if selection == WORKSPACE_PALETTE_LABEL:
                app.custom_pal_path.set("[Built-in Workspace Palette]")
                app.update_pal_preview()
            return

        palette = get_stock_palette(selection)
        app.custom_pal_path.set(f"[Stock Palette: {selection}]")
        app.update_pal_preview(palette)

    def load_override_palette(app):
        original_load_override(app)
        override = app.custom_pal_path.get()
        if override and os.path.exists(override) and override.lower().endswith(".act"):
            app.map_stock_palette_var.set(EXTERNAL_PALETTE_LABEL)

    def reset_palette(app):
        original_reset(app)
        if hasattr(app, "map_stock_palette_var"):
            app.map_stock_palette_var.set(WORKSPACE_PALETTE_LABEL)

    def setup_map_tab_with_stock_palettes(app):
        original_setup(app)

        palette_override_frame = None
        for child in app.tab_map.winfo_children():
            try:
                labels = [
                    str(grandchild.cget("text"))
                    for grandchild in child.winfo_children()
                    if grandchild.winfo_class() in ("TLabel", "Label")
                ]
            except Exception:
                continue
            if "Palette Override:" in labels:
                palette_override_frame = child
                break

        app.map_stock_palette_var = legacy.tk.StringVar(value=WORKSPACE_PALETTE_LABEL)
        stock_frame = compat.ttk.Frame(app.tab_map)
        pack_options = {"pady": (5, 0), "padx": 20, "fill": "x"}
        if palette_override_frame is not None:
            pack_options["before"] = palette_override_frame
        stock_frame.pack(**pack_options)

        compat.ttk.Label(stock_frame, text="Stock Palette:").pack(side="left", padx=10)
        combo = compat.ttk.Combobox(
            stock_frame,
            textvariable=app.map_stock_palette_var,
            values=(WORKSPACE_PALETTE_LABEL,) + STOCK_PALETTE_NAMES,
            state="readonly",
            width=28,
        )
        combo.pack(side="left", padx=5)
        combo.bind("<<ComboboxSelected>>", lambda event: select_stock_palette(app, event))
        compat.ttk.Label(
            stock_frame,
            text=f"{len(STOCK_PALETTE_NAMES)} bundled stock .ACT palettes",
        ).pack(side="left", padx=8)

    legacy.BZReduxSuite.ui_load_override_pal = load_override_palette
    legacy.BZReduxSuite.reset_map_palette = reset_palette
    legacy.BZReduxSuite.setup_map_tab = setup_map_tab_with_stock_palettes

    # The verified MakeMAP path and Advanced dialog both resolve their current
    # palette through this global function at conversion time.
    compat._active_palette = _active_palette


def main():
    install_stock_palette_integration()
    compat.main()


if __name__ == "__main__":
    main()
