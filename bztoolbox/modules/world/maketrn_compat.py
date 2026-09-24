from __future__ import annotations

import math
import os
import re
import sys
import time
from dataclasses import dataclass

import numpy as np


METERS_PER_HG2_SAMPLE = 5
HG2_SAMPLES_PER_ZONE = 256
HGT_SAMPLES_PER_ZONE = 128
METERS_PER_ZONE = METERS_PER_HG2_SAMPLE * HG2_SAMPLES_PER_ZONE
MAKE_TRN_EMPTY_ELEVATION_MAX = 4094
MSVCR_CLOCKS_PER_SEC = 1000


@dataclass(frozen=True)
class StockGeometry:
    width_meters: int
    depth_meters: int
    zones_x: int
    zones_z: int


@dataclass(frozen=True)
class LegacyHGTConversion:
    hgt_path: str
    trn_path: str
    hg2_path: str
    zones_x: int
    zones_z: int
    min_height: int
    max_height: int


def normalize_make_trn_dimension(meters: int) -> int:
    """Reproduce MakeTRN's /w and /h integer normalization.

    The binary first truncates meters to 5 m samples, then rounds the sample
    count upward to a 256-sample boundary. This is subtly different from a
    straight ceil(meters / 1280) for values that are not multiples of 5.
    Values below 5 m quantize to zero samples in MakeTRN; WorldBuilder rejects
    them instead of attempting to create a zero-sized terrain.
    """
    meters = int(meters)
    if meters <= 0:
        raise ValueError("Terrain dimensions must be positive")
    samples = math.trunc(meters / METERS_PER_HG2_SAMPLE)
    samples = (samples + (HG2_SAMPLES_PER_ZONE - 1)) & ~(HG2_SAMPLES_PER_ZONE - 1)
    if samples <= 0:
        raise ValueError("Terrain dimensions must be at least 5 meters")
    return samples * METERS_PER_HG2_SAMPLE


def make_stock_geometry(width_meters: int, depth_meters: int) -> StockGeometry:
    width = normalize_make_trn_dimension(width_meters)
    depth = normalize_make_trn_dimension(depth_meters)
    return StockGeometry(
        width_meters=width,
        depth_meters=depth,
        zones_x=width // METERS_PER_ZONE,
        zones_z=depth // METERS_PER_ZONE,
    )


def validate_empty_elevation(value: int) -> int:
    """Validate the range actually accepted by MakeTRN 2.1.2's /e parser."""
    value = int(value)
    if not 0 <= value <= MAKE_TRN_EMPTY_ELEVATION_MAX:
        raise ValueError(
            f"Empty elevation must be 0..{MAKE_TRN_EMPTY_ELEVATION_MAX} "
            "for MakeTRN 2.1.2 compatibility"
        )
    return value


def make_trn_runtime_seed() -> int:
    """Approximate MSVCR120 clock() for legacy srand(clock()) behavior.

    Visual C++ clock() uses CLOCKS_PER_SEC=1000. Python process_time() is the
    closest cross-platform source because both measure process CPU time rather
    than wall-clock time. Only the low 32 bits matter to the emulated PRNG.
    """
    return int(time.process_time() * MSVCR_CLOCKS_PER_SEC) & 0xFFFFFFFF


def stock_trn_height(empty_elevation: int) -> float:
    """TRN Height written by MakeTRN's blank-create path."""
    return validate_empty_elevation(empty_elevation) * 0.1


def unpack_hgt_zones(payload: bytes, zones_x: int, zones_z: int) -> np.ndarray:
    """Decode a legacy HGT payload into a north-unmodified raster.

    HGT has no header. It stores 128x128 unsigned-16 blocks in zone-major
    order. Redux/MakeTRN use the low 12 bits of every source sample when
    upgrading the terrain to the 256-sample-per-zone HG2 grid.
    """
    zones_x = int(zones_x)
    zones_z = int(zones_z)
    if zones_x <= 0 or zones_z <= 0:
        raise ValueError("HGT zone dimensions must be positive")
    zone_samples = HGT_SAMPLES_PER_ZONE * HGT_SAMPLES_PER_ZONE
    expected = zones_x * zones_z * zone_samples * 2
    if len(payload) != expected:
        raise ValueError(f"HGT size mismatch: expected {expected} bytes, found {len(payload)}")

    raw = np.frombuffer(payload, dtype="<u2") & 0x0FFF
    out = np.empty(
        (zones_z * HGT_SAMPLES_PER_ZONE, zones_x * HGT_SAMPLES_PER_ZONE),
        dtype=np.uint16,
    )
    cursor = 0
    for zone_z in range(zones_z):
        for zone_x in range(zones_x):
            zone = raw[cursor : cursor + zone_samples].reshape(
                (HGT_SAMPLES_PER_ZONE, HGT_SAMPLES_PER_ZONE)
            )
            z0 = zone_z * HGT_SAMPLES_PER_ZONE
            x0 = zone_x * HGT_SAMPLES_PER_ZONE
            out[z0 : z0 + HGT_SAMPLES_PER_ZONE, x0 : x0 + HGT_SAMPLES_PER_ZONE] = zone
            cursor += zone_samples
    return out


def interpolate_hgt_to_hg2(legacy: np.ndarray) -> np.ndarray:
    """Upgrade the 128-sample HGT grid to Redux's 256-sample HG2 grid.

    This is the recovered Battlezone triangle interpolation step only. Each
    source quad is split along the A->C diagonal and sampled at half-sample
    positions. Right/bottom neighbors clamp at the far edge. No smoothing,
    filtering, resampling kernel, or height renormalization is applied.

    This is the terrain shape produced by Redux's legacy HGT upgrade path when
    the `nohgtsmoothing` launch option disables the subsequent smoothing pass.
    """
    src = np.asarray(legacy, dtype=np.uint16) & 0x0FFF
    if src.ndim != 2 or src.shape[0] == 0 or src.shape[1] == 0:
        raise ValueError("HGT raster must be a non-empty 2D array")

    src32 = src.astype(np.uint32)
    right = np.empty_like(src32)
    right[:, :-1] = src32[:, 1:]
    right[:, -1] = src32[:, -1]
    down = np.empty_like(src32)
    down[:-1, :] = src32[1:, :]
    down[-1, :] = src32[-1, :]
    diagonal = np.empty_like(src32)
    diagonal[:-1, :-1] = src32[1:, 1:]
    diagonal[-1, :-1] = src32[-1, 1:]
    diagonal[:-1, -1] = src32[1:, -1]
    diagonal[-1, -1] = src32[-1, -1]

    interpolated = np.empty((src.shape[0] * 2, src.shape[1] * 2), dtype=np.uint16)
    interpolated[0::2, 0::2] = src
    interpolated[0::2, 1::2] = ((src32 + right) // 2).astype(np.uint16)
    interpolated[1::2, 0::2] = ((src32 + down) // 2).astype(np.uint16)
    interpolated[1::2, 1::2] = ((src32 + diagonal) // 2).astype(np.uint16)
    return interpolated


def smooth_make_trn_hg2(raster: np.ndarray) -> np.ndarray:
    """Reproduce the legacy post-interpolation 3x3 smoothing pass.

    Function 0x40180b copies the interpolated Redux raster, then replaces every
    sample with the rounded mean of the in-bounds 3x3 neighborhood. Border
    samples therefore use 4 or 6 values rather than replicated edge pixels.
    The integer expression is `(2 * sum + count) / (2 * count)`, i.e. positive
    half-up rounding rather than truncation.
    """
    src = np.asarray(raster, dtype=np.uint16)
    if src.ndim != 2 or src.shape[0] == 0 or src.shape[1] == 0:
        raise ValueError("HG2 raster must be a non-empty 2D array")

    height, width = src.shape
    sums = np.zeros((height, width), dtype=np.uint32)
    counts = np.zeros((height, width), dtype=np.uint16)
    src32 = src.astype(np.uint32)

    for dz in (-1, 0, 1):
        src_z0 = max(0, -dz)
        src_z1 = min(height, height - dz)
        dst_z0 = src_z0 + dz
        dst_z1 = src_z1 + dz
        for dx in (-1, 0, 1):
            src_x0 = max(0, -dx)
            src_x1 = min(width, width - dx)
            dst_x0 = src_x0 + dx
            dst_x1 = src_x1 + dx
            sums[dst_z0:dst_z1, dst_x0:dst_x1] += src32[src_z0:src_z1, src_x0:src_x1]
            counts[dst_z0:dst_z1, dst_x0:dst_x1] += 1

    rounded = (2 * sums + counts.astype(np.uint32)) // (2 * counts.astype(np.uint32))
    return rounded.astype(np.uint16)


def upsample_hgt_to_hg2(legacy: np.ndarray) -> np.ndarray:
    """Reproduce MakeTRN/Redux's normal HGT upgrade including smoothing."""
    return smooth_make_trn_hg2(interpolate_hgt_to_hg2(legacy))


def read_hgt_as_hg2(
    path: os.PathLike | str,
    zones_x: int,
    zones_z: int,
    *,
    smooth: bool = True,
) -> np.ndarray:
    """Read legacy HGT and return a Redux-resolution height raster.

    `smooth=True` preserves the existing MakeTRN-compatible behavior.
    `smooth=False` matches the Redux legacy-upgrade path with `nohgtsmoothing`.
    """
    with open(path, "rb") as stream:
        legacy = unpack_hgt_zones(stream.read(), zones_x, zones_z)
    interpolated = interpolate_hgt_to_hg2(legacy)
    return smooth_make_trn_hg2(interpolated) if smooth else interpolated


def read_hgt_as_hg2_no_smoothing(
    path: os.PathLike | str,
    zones_x: int,
    zones_z: int,
) -> np.ndarray:
    """Explicit helper for Redux-equivalent `nohgtsmoothing` terrain upgrades."""
    return read_hgt_as_hg2(path, zones_x, zones_z, smooth=False)


def convert_hgt_to_hg2_no_smoothing(
    hgt_path: os.PathLike | str,
    hg2_path: os.PathLike | str,
    zones_x: int,
    zones_z: int,
) -> np.ndarray:
    """Convert an authored 1.5 HGT to Redux HG2 without the smoothing pass."""
    from bztoolbox.modules.world.hg2_codec import DEFAULT_ZONE_BITS, write_hg2

    heights = read_hgt_as_hg2_no_smoothing(hgt_path, zones_x, zones_z)
    write_hg2(
        hg2_path,
        heights,
        zones_x=int(zones_x),
        zones_z=int(zones_z),
        zone_bits=DEFAULT_ZONE_BITS,
    )
    return heights


def read_legacy_trn_zone_geometry(trn_path: os.PathLike | str) -> tuple[int, int]:
    """Read legacy TRN Width/Depth and return exact 1280 m terrain zones."""
    width = None
    depth = None
    with open(trn_path, "r", errors="ignore") as stream:
        for raw in stream:
            line = raw.split("//", 1)[0].split(";", 1)[0].strip()
            if not line or "=" not in line:
                continue
            key, value = (part.strip() for part in line.split("=", 1))
            if key.lower() == "width":
                try:
                    width = float(value.rstrip("fF"))
                except ValueError:
                    pass
            elif key.lower() == "depth":
                try:
                    depth = float(value.rstrip("fF"))
                except ValueError:
                    pass

    if not width or not depth:
        raise ValueError(f"{os.path.basename(str(trn_path))} does not define Width and Depth")

    zones_x_f = width / METERS_PER_ZONE
    zones_z_f = depth / METERS_PER_ZONE
    zones_x = int(round(zones_x_f))
    zones_z = int(round(zones_z_f))
    if (
        zones_x <= 0
        or zones_z <= 0
        or abs(zones_x_f - zones_x) > 1e-6
        or abs(zones_z_f - zones_z) > 1e-6
    ):
        raise ValueError(
            f"{os.path.basename(str(trn_path))} Width/Depth must be exact {METERS_PER_ZONE} m zone multiples"
        )
    return zones_x, zones_z


def resolve_legacy_hgt_trn(hgt_path: os.PathLike | str, source_dir: os.PathLike | str | None = None) -> str:
    """Resolve the terrain TRN for an authored HGT.

    Prefer a same-stem TRN. If that does not exist and the source folder has
    exactly one TRN, use it as the unambiguous world-level fallback.
    """
    hgt_path = os.fspath(hgt_path)
    directory = os.fspath(source_dir) if source_dir is not None else os.path.dirname(hgt_path)
    same_stem = os.path.splitext(hgt_path)[0] + ".trn"
    if os.path.isfile(same_stem):
        return same_stem

    trns = sorted(
        os.path.join(directory, name)
        for name in os.listdir(directory)
        if name.lower().endswith(".trn") and os.path.isfile(os.path.join(directory, name))
    )
    if len(trns) == 1:
        return trns[0]
    if not trns:
        raise ValueError(f"No companion TRN found for {os.path.basename(hgt_path)}")
    raise ValueError(
        f"Multiple TRNs found for {os.path.basename(hgt_path)}; add a same-stem TRN to disambiguate"
    )


def convert_legacy_hgt_folder_no_smoothing(
    source_dir: os.PathLike | str,
    output_dir: os.PathLike | str,
) -> list[LegacyHGTConversion]:
    """Port every legacy HGT in a world folder to canonical Redux HG2.

    This is intended as the terrain half of the Legacy Atlas port workflow, so
    an old map folder can be converted without first launching Redux and
    letting the game upgrade each HGT itself.
    """
    source_dir = os.fspath(source_dir)
    output_dir = os.fspath(output_dir)
    hgts = sorted(
        os.path.join(source_dir, name)
        for name in os.listdir(source_dir)
        if name.lower().endswith(".hgt") and os.path.isfile(os.path.join(source_dir, name))
    )
    if not hgts:
        return []

    os.makedirs(output_dir, exist_ok=True)
    results: list[LegacyHGTConversion] = []
    for hgt_path in hgts:
        trn_path = resolve_legacy_hgt_trn(hgt_path, source_dir)
        zones_x, zones_z = read_legacy_trn_zone_geometry(trn_path)
        stem = os.path.splitext(os.path.basename(hgt_path))[0]
        hg2_path = os.path.join(output_dir, stem + ".hg2")
        heights = convert_hgt_to_hg2_no_smoothing(
            hgt_path,
            hg2_path,
            zones_x,
            zones_z,
        )
        results.append(
            LegacyHGTConversion(
                hgt_path=hgt_path,
                trn_path=trn_path,
                hg2_path=hg2_path,
                zones_x=zones_x,
                zones_z=zones_z,
                min_height=int(heights.min()),
                max_height=int(heights.max()),
            )
        )
    return results


def install_world_builder_legacy_hgt_patch() -> None:
    """Integrate HGT terrain upgrading into WorldBuilder's Legacy Atlas page.

    Normal porting is one-click: the existing Convert & Build Atlas worker also
    converts every authored HGT in the selected source folder. A manual single
    HGT button remains available as an advanced fallback.

    Safe to call repeatedly, and callable later than import time. That matters:
    this module is reachable from importers that have not pulled in
    world_builder_core yet -- the CLI reaches it through legacy_batch -- and the
    import-time call below then finds no class to patch and returns. Nothing
    reports that, so the whole HGT integration is simply absent. The
    stock_map_creator integration hub calls this again once the class exists.
    """
    core = sys.modules.get("bztoolbox.modules.world.world_builder_core")
    if core is None:
        return
    base = getattr(core, "BZ98TRNArchitect", None)
    if base is None or getattr(base, "_legacy_hgt_converter_installed", False):
        return

    original_setup = base.setup_legacy_tab
    original_worker = base._generate_legacy_worker
    original_scan = base.scan_legacy_folder

    def setup_legacy_tab_with_hgt(self):
        original_setup(self)

        self.legacy_auto_hgt = core.tk.BooleanVar(value=True)
        self.legacy_hgt_path = core.tk.StringVar()
        self.legacy_hgt_info = core.tk.StringVar(
            value="HGT terrain upgrade: waiting for a legacy source folder."
        )

        frame = core.ttk.LabelFrame(
            self.tab_legacy,
            text=" Legacy Terrain Upgrade (.HGT -> .HG2) ",
            padding=10,
        )
        frame.pack(fill="x", padx=20, pady=(0, 10))

        core.ttk.Checkbutton(
            frame,
            text="Automatically convert authored HGT terrain during CONVERT & BUILD ATLAS",
            variable=self.legacy_auto_hgt,
        ).pack(anchor="w")
        core.ttk.Label(
            frame,
            text=(
                "Uses Redux-equivalent -nohgtsmoothing upgrade semantics: low 12-bit HGT heights, "
                "zone-major layout, recovered 128->256 triangle interpolation, canonical HG2 output. "
                "No 3x3 smoothing, Gaussian filter, or height renormalization."
            ),
            foreground="#888888",
            wraplength=1050,
        ).pack(anchor="w", pady=(3, 5))
        core.ttk.Label(
            frame,
            textvariable=self.legacy_hgt_info,
            foreground=core.BZ_CYAN,
            font=("Consolas", 9),
        ).pack(anchor="w", pady=(0, 6))

        row = core.ttk.Frame(frame)
        row.pack(fill="x")
        entry = core.ttk.Entry(row, textvariable=self.legacy_hgt_path)
        entry.pack(side="left", fill="x", expand=True, padx=(0, 5))

        def browse_hgt():
            path = core.filedialog.askopenfilename(
                title="Select original Battlezone HGT",
                filetypes=[("Battlezone Height Terrain", "*.hgt"), ("All Files", "*.*")],
            )
            if not path:
                return
            self.legacy_hgt_path.set(path)
            try:
                trn_path = resolve_legacy_hgt_trn(path)
                zones_x, zones_z = read_legacy_trn_zone_geometry(trn_path)
                expected = zones_x * zones_z * HGT_SAMPLES_PER_ZONE * HGT_SAMPLES_PER_ZONE * 2
                actual = os.path.getsize(path)
                suffix = "" if actual == expected else f" | WARNING size {actual}, expected {expected}"
                self.legacy_hgt_info.set(
                    f"Manual: {os.path.basename(path)} + {os.path.basename(trn_path)} | "
                    f"{zones_x}x{zones_z} zones -> "
                    f"{zones_x * HG2_SAMPLES_PER_ZONE}x{zones_z * HG2_SAMPLES_PER_ZONE} HG2{suffix}"
                )
            except Exception as exc:
                self.legacy_hgt_info.set(str(exc))

        def convert_selected_hgt():
            hgt_path = self.legacy_hgt_path.get().strip()
            if not hgt_path or not os.path.isfile(hgt_path):
                core.messagebox.showerror("Legacy HGT", "Select a valid .HGT file first.")
                return
            try:
                trn_path = resolve_legacy_hgt_trn(hgt_path)
                zones_x, zones_z = read_legacy_trn_zone_geometry(trn_path)
            except Exception as exc:
                core.messagebox.showerror("Legacy HGT", str(exc))
                return

            default_dir = self.legacy_out_dir.get().strip() or os.path.dirname(hgt_path)
            output = core.filedialog.asksaveasfilename(
                title="Save Redux HG2",
                initialdir=default_dir,
                initialfile=os.path.splitext(os.path.basename(hgt_path))[0] + ".hg2",
                defaultextension=".hg2",
                filetypes=[("Battlezone Redux Heightmap", "*.hg2")],
            )
            if not output:
                return
            try:
                heights = convert_hgt_to_hg2_no_smoothing(
                    hgt_path, output, zones_x, zones_z
                )
                self.log(
                    f"Legacy HGT -> HG2 (-nohgtsmoothing): {os.path.basename(hgt_path)} -> "
                    f"{os.path.basename(output)} | {zones_x}x{zones_z} zones | "
                    f"range {int(heights.min())}..{int(heights.max())}",
                    "success",
                )
                core.messagebox.showinfo(
                    "Legacy HGT Converted",
                    f"Saved {output}\n\n"
                    f"{zones_x}x{zones_z} zones, "
                    f"{heights.shape[1]}x{heights.shape[0]} HG2 samples.\n"
                    "Triangle interpolation only; smoothing was not applied.",
                )
            except Exception as exc:
                self.log(f"Legacy HGT conversion failed: {exc}", "error")
                core.messagebox.showerror("Legacy HGT", str(exc))

        core.ttk.Button(row, text="Browse HGT", command=browse_hgt).pack(side="left", padx=(0, 5))
        self.btn_legacy_hgt_convert = core.ttk.Button(
            row,
            text="Convert Selected HGT Only",
            command=convert_selected_hgt,
        )
        self.btn_legacy_hgt_convert.pack(side="left")

    def scan_legacy_folder_with_hgt(self, path):
        original_scan(self, path)
        if not hasattr(self, "legacy_hgt_info"):
            return
        try:
            hgts = sorted(name for name in os.listdir(path) if name.lower().endswith(".hgt"))
            trns = sorted(name for name in os.listdir(path) if name.lower().endswith(".trn"))
            if hgts:
                self.legacy_hgt_info.set(
                    f"Detected {len(hgts)} HGT terrain file(s) and {len(trns)} TRN file(s). "
                    "HGT -> HG2 will run automatically with the atlas port."
                )
                if len(hgts) == 1:
                    self.legacy_hgt_path.set(os.path.join(path, hgts[0]))
            else:
                self.legacy_hgt_info.set("No .HGT found in this source folder; atlas-only port.")
        except Exception as exc:
            self.legacy_hgt_info.set(f"HGT scan failed: {exc}")

    def generate_legacy_worker_with_hgt(self, src, out):
        # Terrain conversion is independent from texture-atlas conversion. Do it
        # first so even a texture-side failure cannot force users back through
        # the game engine merely to obtain the Redux HG2.
        if getattr(self, "legacy_auto_hgt", None) is not None and self.legacy_auto_hgt.get():
            try:
                results = convert_legacy_hgt_folder_no_smoothing(src, out)
                if not results:
                    self.log("Legacy terrain: no HGT files found; atlas conversion only.", "info")
                for result in results:
                    self.log(
                        f"Legacy terrain: {os.path.basename(result.hgt_path)} -> "
                        f"{os.path.basename(result.hg2_path)} (-nohgtsmoothing equivalent), "
                        f"{result.zones_x}x{result.zones_z} zones, "
                        f"range {result.min_height}..{result.max_height}.",
                        "success",
                    )
            except Exception as exc:
                self.log(f"Legacy HGT port error: {exc}", "error")

        original_worker(self, src, out)

    base.setup_legacy_tab = setup_legacy_tab_with_hgt
    base.scan_legacy_folder = scan_legacy_folder_with_hgt
    base._generate_legacy_worker = generate_legacy_worker_with_hgt
    base._legacy_hgt_converter_installed = True


install_world_builder_legacy_hgt_patch()
