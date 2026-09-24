from __future__ import annotations

import os
import re
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

import numpy as np

from bztoolbox.modules.world.hg2_codec import DEFAULT_ZONE_BITS, write_hg2
from bztoolbox.modules.world.maketrn_compat import (
    StockGeometry,
    install_world_builder_legacy_hgt_patch,
    stock_trn_height,
    validate_empty_elevation,
)
from bztoolbox.modules.world.mat_codec import PaintStats, generate_mat, parse_trn_painter, write_mat
from bztoolbox.modules.world.legacy_port import install_world_builder_legacy_package_patch
from bztoolbox.modules.world.legacy_palette import install_world_builder_legacy_palette_patch
from bztoolbox.modules.world.legacy_preflight_hook import install_world_builder_legacy_preflight_patch
from bztoolbox.modules.world.legacy_batch_gui import install_world_builder_legacy_batch_patch

# WorldBuilder imports this module after world_builder_core and maketrn_compat,
# so this is a stable integration point for the optional Legacy Atlas package
# finalizer, stock-palette resolver, launchability preflight, and batch GUI
# without coupling mission/package policy to the terrain codecs.
# The HGT patch installs first so it stays the innermost wrapper, matching the
# order it gets when maketrn_compat's own import-time call succeeds. It is a
# no-op in that case; it only does the work when this module is the first point
# at which world_builder_core exists.
install_world_builder_legacy_hgt_patch()
install_world_builder_legacy_package_patch()
install_world_builder_legacy_palette_patch()
install_world_builder_legacy_preflight_patch()
install_world_builder_legacy_batch_patch()


@dataclass(frozen=True)
class StockBuildConfig:
    name: str
    out_dir: str
    geometry: StockGeometry
    empty_elevation: int
    time_of_day: int
    music_track: int
    music_loop_first: int
    music_loop_last: int
    music_loop_skip: int
    ambient: tuple[float, float, float]
    diffuse: tuple[float, float, float]
    specular: tuple[float, float, float]
    normal_view: str
    static_trn: str
    paint_rules: Sequence[Mapping[str, object]]
    legacy_seed: int
    min_x: int = 0
    min_z: int = 0
    source_heights: np.ndarray | None = None


@dataclass(frozen=True)
class StockBuildResult:
    trn_path: str
    hg2_path: str
    mat_path: str
    mat_stats: PaintStats
    mat_width: int
    mat_height: int


def _validate_name(name: str) -> str:
    value = str(name)
    if not value or len(value) > 8 or not value.isalnum():
        raise ValueError("Map name must be 1-8 alphanumeric characters")
    return value


def _rgb_section(name: str, rgb: Iterable[float]) -> str:
    red, green, blue = (float(value) for value in rgb)
    return (
        f"[{name}]\n"
        f"Red = {red:.4f}f\n"
        f"Green = {green:.4f}f\n"
        f"Blue = {blue:.4f}f\n"
    )


def build_stock_trn_text(config: StockBuildConfig) -> str:
    """Build a stock TRN while preserving recovered MakeTRN size/origin semantics."""
    _validate_name(config.name)
    empty = validate_empty_elevation(config.empty_elevation)
    geometry = config.geometry
    if geometry.zones_x <= 0 or geometry.zones_z <= 0:
        raise ValueError("Stock terrain must contain at least one zone")

    normal_view = re.sub(
        r"Time\s*=\s*\d+",
        f"Time={int(config.time_of_day)}",
        config.normal_view,
        count=1,
        flags=re.IGNORECASE,
    ).rstrip()
    static = config.static_trn.rstrip()

    parts = [
        "[Size]\n"
        f"MinX={int(config.min_x)}\n"
        f"MinZ={int(config.min_z)}\n"
        f"Width={geometry.width_meters}\n"
        f"Depth={geometry.depth_meters}\n"
        f"Height={stock_trn_height(empty):.6f}\n",
        normal_view + "\n",
    ]
    if static:
        parts.append(static + "\n")
    parts.extend(
        [
            "[World]\n"
            f"MusicTrack={int(config.music_track)}\n"
            f"MusicLoopFirst={int(config.music_loop_first)}\n"
            f"MusicLoopLast={int(config.music_loop_last)}\n"
            f"MusicLoopSkip={int(config.music_loop_skip)}\n",
            _rgb_section("Sun_Ambient", config.ambient),
            _rgb_section("Sun_Diffuse", config.diffuse),
            _rgb_section("Sun_Specular", config.specular),
        ]
    )
    return "\n".join(part.rstrip() for part in parts if part).rstrip() + "\n"


def _build_heights(config: StockBuildConfig) -> np.ndarray:
    geometry = config.geometry
    zone_size = 1 << DEFAULT_ZONE_BITS
    expected_shape = (geometry.zones_z * zone_size, geometry.zones_x * zone_size)
    if config.source_heights is None:
        return np.full(expected_shape, config.empty_elevation, dtype=np.uint16)

    heights = np.asarray(config.source_heights)
    if heights.shape != expected_shape:
        raise ValueError(
            f"Source height raster {heights.shape} does not match terrain geometry {expected_shape}"
        )
    if not np.issubdtype(heights.dtype, np.integer):
        raise ValueError("Source height raster must contain integer HG2 samples")
    if np.any(heights < 0) or np.any(heights > 0xFFFF):
        raise ValueError("Source height raster contains values outside uint16 range")
    return heights.astype(np.uint16, copy=True)


def build_stock_map(config: StockBuildConfig) -> StockBuildResult:
    """Generate TRN, canonical Redux HG2, and MakeTRN-compatible MAT."""
    name = _validate_name(config.name)
    empty = validate_empty_elevation(config.empty_elevation)
    geometry = config.geometry
    os.makedirs(config.out_dir, exist_ok=True)

    heights = _build_heights(config)

    hg2_path = os.path.join(config.out_dir, f"{name}.hg2")
    trn_path = os.path.join(config.out_dir, f"{name}.trn")
    mat_path = os.path.join(config.out_dir, f"{name}.mat")

    write_hg2(
        hg2_path,
        heights,
        zones_x=geometry.zones_x,
        zones_z=geometry.zones_z,
        zone_bits=DEFAULT_ZONE_BITS,
    )
    with open(trn_path, "w", encoding="cp1252", newline="\r\n") as stream:
        stream.write(build_stock_trn_text(config))

    trn = parse_trn_painter(trn_path)
    mat_data, stats = generate_mat(
        heights,
        list(config.paint_rules),
        geometry.zones_x,
        geometry.zones_z,
        cap_transitions=trn.cap_transitions,
        diagonal_transitions=trn.diagonal_transitions,
        min_x=trn.min_x,
        min_z=trn.min_z,
        world_width=trn.width or float(geometry.width_meters),
        world_depth=trn.depth or float(geometry.depth_meters),
        legacy_seed=int(config.legacy_seed) & 0xFFFFFFFF,
        fallback_elevation=empty,
        strict=True,
    )
    write_mat(mat_path, mat_data, geometry.zones_x, geometry.zones_z)

    return StockBuildResult(
        trn_path=trn_path,
        hg2_path=hg2_path,
        mat_path=mat_path,
        mat_stats=stats,
        mat_width=mat_data.shape[1],
        mat_height=mat_data.shape[0],
    )
