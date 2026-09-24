from __future__ import annotations

import os
import sys
import tempfile
from dataclasses import dataclass

from battlezone.terrain.trn import TRNDocument
from bztoolbox.modules.world.stock_palettes import (
    get_stock_act_bytes,
    get_stock_palette,
    has_stock_palette,
    normalize_act_name,
)


@dataclass(frozen=True)
class LegacyPaletteResolution:
    status: str
    requested: str | None
    path: str | None
    message: str

    @property
    def ok(self) -> bool:
        return self.status in {"explicit", "source", "embedded", "default"}


def _find_file_ci(directory: os.PathLike | str, filename: str) -> str | None:
    wanted = os.path.basename(filename).lower()
    try:
        for name in os.listdir(directory):
            if name.lower() == wanted:
                path = os.path.join(os.fspath(directory), name)
                if os.path.isfile(path):
                    return path
    except OSError:
        pass
    return None


def _validate_act_file(path: os.PathLike | str) -> None:
    size = os.path.getsize(path)
    # Battlezone stock ACTs are 768 bytes. Some generic Adobe ACT writers append
    # a four-byte color-count/transparency trailer; WorldBuilder only consumes
    # the first 768 bytes, so accept that common 772-byte form as an override.
    if size not in (768, 772):
        raise ValueError(
            f"{os.path.basename(os.fspath(path))} is {size} bytes; expected a 768-byte "
            "Battlezone ACT palette (or 772-byte ACT with Adobe trailer)"
        )


def read_trn_palette_reference(trn_path: os.PathLike | str) -> str | None:
    """Return the [Color] Palette= reference from a legacy TRN, if present."""
    return TRNDocument.read(trn_path).palette


def scan_trn_palette_references(source_dir: os.PathLike | str) -> dict[str, str | None]:
    source_dir = os.path.abspath(os.fspath(source_dir))
    result: dict[str, str | None] = {}
    for name in sorted(os.listdir(source_dir), key=str.lower):
        path = os.path.join(source_dir, name)
        if name.lower().endswith(".trn") and os.path.isfile(path):
            result[name] = read_trn_palette_reference(path)
    return result


def _stock_cache_path(name: os.PathLike | str) -> str:
    key = normalize_act_name(name)
    raw = get_stock_act_bytes(key)
    if raw is None:
        raise ValueError(f"No embedded stock palette named {key}")
    cache_dir = os.path.join(tempfile.gettempdir(), "bz98r_worldbuilder_stock_palettes")
    os.makedirs(cache_dir, exist_ok=True)
    path = os.path.join(cache_dir, key)
    rewrite = True
    if os.path.isfile(path):
        try:
            with open(path, "rb") as stream:
                rewrite = stream.read() != raw
        except OSError:
            rewrite = True
    if rewrite:
        with open(path, "wb") as stream:
            stream.write(raw)
    return path


def resolve_legacy_palette(
    source_dir: os.PathLike | str,
    explicit_palette: os.PathLike | str | None = None,
) -> LegacyPaletteResolution:
    """Resolve the palette that should decode indexed MAPs in one atlas pass.

    Resolution order is explicit user override, a palette shipped with the map,
    an exact-name embedded stock palette, then MOON.ACT only when no TRN declares
    a palette at all. Multiple distinct TRN palette declarations are rejected
    because one shared atlas cannot safely decode differently indexed worlds.
    """
    source_dir = os.path.abspath(os.fspath(source_dir))
    explicit = os.fspath(explicit_palette).strip() if explicit_palette else ""
    if explicit:
        if not os.path.isfile(explicit):
            return LegacyPaletteResolution(
                "invalid_explicit", None, None, f"Selected ACT palette does not exist: {explicit}"
            )
        try:
            _validate_act_file(explicit)
        except ValueError as exc:
            return LegacyPaletteResolution("invalid_explicit", None, None, str(exc))
        return LegacyPaletteResolution(
            "explicit", os.path.basename(explicit), os.path.abspath(explicit),
            f"Using explicit palette override {os.path.basename(explicit)}",
        )

    references = scan_trn_palette_references(source_dir)
    declared: dict[str, list[str]] = {}
    for trn_name, palette_name in references.items():
        if not palette_name:
            continue
        key = normalize_act_name(palette_name)
        declared.setdefault(key, []).append(trn_name)

    if len(declared) > 1:
        detail = "; ".join(
            f"{palette}: {', '.join(trns)}" for palette, trns in sorted(declared.items())
        )
        return LegacyPaletteResolution(
            "mixed", None, None,
            "Legacy folder contains multiple TRN palettes; one shared atlas would be invalid. " + detail,
        )

    if declared:
        key = next(iter(declared))
        local = _find_file_ci(source_dir, key)
        if local:
            try:
                _validate_act_file(local)
            except ValueError as exc:
                return LegacyPaletteResolution("invalid_source", key, None, str(exc))
            return LegacyPaletteResolution(
                "source", key, local,
                f"TRN requests {key.upper()}; using palette bundled with the map",
            )
        if has_stock_palette(key):
            path = _stock_cache_path(key)
            return LegacyPaletteResolution(
                "embedded", key, path,
                f"TRN requests {key.upper()}; using embedded stock palette",
            )
        return LegacyPaletteResolution(
            "missing", key, None,
            f"TRN requires {key.upper()}, but it is neither in the source folder nor in the embedded stock palette set",
        )

    path = _stock_cache_path("moon.act")
    return LegacyPaletteResolution(
        "default", "moon.act", path,
        "No TRN [Color] Palette= declaration found; using embedded MOON.ACT compatibility default",
    )


def install_world_builder_legacy_palette_patch() -> None:
    """Make Legacy Atlas palette selection deterministic and stock-aware."""
    core = sys.modules.get("bztoolbox.modules.world.world_builder_core")
    if core is None:
        return
    base = getattr(core, "BZ98TRNArchitect", None)
    if base is None or getattr(base, "_legacy_stock_palettes_installed", False):
        return

    original_find = base._find_file_ci
    original_scan = base.scan_legacy_folder
    original_worker = base._generate_legacy_worker

    # Keep the long-standing Moon fallback byte-for-byte aligned with the stock
    # palette pack rather than maintaining a second hand-copied constant.
    moon = get_stock_palette("moon.act")
    if moon is not None:
        core.BUILTIN_MOON_PALETTE = moon

    # world_builder_core defines _find_file_ci as a staticmethod. Preserve that
    # call shape so both instance calls and any direct class-level calls remain
    # compatible after adding the embedded stock fallback.
    def find_file_ci_with_stock(directory, name):
        found = original_find(directory, name)
        if found:
            return found
        if str(name).lower().endswith(".act") and has_stock_palette(name):
            return _stock_cache_path(name)
        return None

    def scan_legacy_folder_with_palette(self, path):
        original_scan(self, path)
        try:
            explicit = self.legacy_pal_path.get() if hasattr(self, "legacy_pal_path") else None
            resolution = resolve_legacy_palette(path, explicit)
            if hasattr(self, "legacy_package_info"):
                current = self.legacy_package_info.get().strip()
                palette_text = "Palette: " + resolution.message
                self.legacy_package_info.set(
                    f"{current} | {palette_text}" if current else palette_text
                )
        except Exception as exc:
            if hasattr(self, "legacy_package_info"):
                current = self.legacy_package_info.get().strip()
                suffix = f"Palette scan failed: {exc}"
                self.legacy_package_info.set(f"{current} | {suffix}" if current else suffix)

    def generate_legacy_worker_with_palette(self, src, out):
        explicit = self.legacy_pal_path.get() if hasattr(self, "legacy_pal_path") else None
        try:
            resolution = resolve_legacy_palette(src, explicit)
        except Exception as exc:
            self.log(f"Palette validation failed: {exc}", "error")
            self.root.after(
                0,
                lambda: self.btn_legacy_gen.config(text="CONVERT & BUILD ATLAS", state="normal"),
            )
            return

        if not resolution.ok:
            self.log(f"Palette validation failed: {resolution.message}", "error")
            self.root.after(
                0,
                lambda: self.btn_legacy_gen.config(text="CONVERT & BUILD ATLAS", state="normal"),
            )
            return

        level = "warning" if resolution.status == "default" else "info"
        self.log(f"Palette: {resolution.message}.", level)
        original_worker(self, src, out)

    base._find_file_ci = staticmethod(find_file_ci_with_stock)
    base.scan_legacy_folder = scan_legacy_folder_with_palette
    base._generate_legacy_worker = generate_legacy_worker_with_palette
    base._legacy_stock_palettes_installed = True
