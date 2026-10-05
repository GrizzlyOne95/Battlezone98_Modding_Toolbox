"""Read BZ2 SKY fog settings and preserve them in a Redux ACT palette.

The SKY/SKY1 payload starts with fog RGB, multiplier, start, end and visibility
as seven little-endian floats. BZCC's RainClass::Load reads this block into
the globals consumed by Load_Sky's fog setters. The later FOG chunk contains
local fog volumes and is not the global atmospheric color.
"""
from __future__ import annotations

import argparse
import json
import math
import struct
from pathlib import Path

FOG_PALETTE_INDEX = 209


def read_sky_environment(path: str | Path) -> dict:
    data = Path(path).read_bytes()
    if len(data) < 12 or struct.unpack_from("<III", data) != (0x534B595F, 4, 0x10000):
        raise ValueError("Unsupported BZ2 SKY header")
    offset = 12
    while offset < len(data):
        if offset + 8 > len(data):
            raise ValueError("Truncated SKY chunk header")
        tag, size = struct.unpack_from("<II", data, offset)
        offset += 8
        if offset + size > len(data):
            raise ValueError("Truncated SKY chunk payload")
        if tag in (0x534B5920, 0x534B5931):
            if size not in (168, 212, 228):
                raise ValueError(f"Unsupported SKY settings size {size}")
            r, g, b, multiplier, start, end, visibility = struct.unpack_from("<7f", data, offset)
            if not all(math.isfinite(v) for v in (r, g, b, multiplier, start, end, visibility)):
                raise ValueError("Non-finite SKY fog settings")
            if any(not 0 <= v <= 1 for v in (r, g, b, multiplier)) or end <= start:
                raise ValueError("Invalid SKY fog settings")
            rgb = [min(1.0, v * multiplier) for v in (r, g, b)]
            diffuse = struct.unpack_from("<4f", data, offset + 44)
            ambient = struct.unpack_from("<4f", data, offset + 60)
            day_length, hour = struct.unpack_from("<2f", data, offset + 28)
            if not math.isfinite(day_length) or not math.isfinite(hour) or not 0 <= hour <= 24:
                raise ValueError("Invalid SKY time of day")
            if any(not math.isfinite(v) or v < 0 for v in (*diffuse, *ambient)):
                raise ValueError("Invalid SKY sunlight settings")
            minutes = round(hour * 60)
            return dict(source=str(Path(path).resolve()), fog_rgb=rgb,
                        fog_rgb8=[round(v * 255) for v in rgb],
                        fog_multiplier=multiplier, fog_start_m=start,
                        fog_end_m=end, visibility_m=visibility,
                        palette_index=FOG_PALETTE_INDEX,
                        day_length_hours=day_length, time_of_day_hours=hour,
                        redux_time_hhmm=(minutes // 60) * 100 + minutes % 60,
                        sun_diffuse_rgb=[v * diffuse[3] for v in diffuse[:3]],
                        sun_ambient_rgb=[v * ambient[3] for v in ambient[:3]])
        offset += size
    raise ValueError("SKY file has no global SKY/SKY1 settings chunk")


def act_with_sky_fog(base_act: bytes, environment: dict) -> bytes:
    """Keep the base world's color ramps; replace its atmospheric fog entry."""
    if len(base_act) not in (768, 772):
        raise ValueError("Base ACT must be 768 or 772 bytes")
    result = bytearray(base_act[:768])
    result[FOG_PALETTE_INDEX * 3:FOG_PALETTE_INDEX * 3 + 3] = bytes(environment["fog_rgb8"])
    return bytes(result)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sky", type=Path)
    parser.add_argument("--base-act", type=Path)
    parser.add_argument("--output-act", type=Path)
    args = parser.parse_args()
    if bool(args.base_act) != bool(args.output_act):
        parser.error("--base-act and --output-act must be supplied together")
    environment = read_sky_environment(args.sky)
    if args.output_act:
        args.output_act.write_bytes(act_with_sky_fog(args.base_act.read_bytes(), environment))
    print(json.dumps(environment, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
