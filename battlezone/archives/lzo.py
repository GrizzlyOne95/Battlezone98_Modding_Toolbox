"""Pure-Python LZO1X / LZO1Y codec.

Battlezone ZFS archives store members raw, LZO1X- or LZO1Y-compressed. This
module reads both and writes LZO1X, so archive tooling needs no native
library on any platform.

It is an independent implementation of the LZO1X/LZO1Y bitstream (written
from the format, not derived from the LZO library source), so it carries the
toolbox's MIT license. Output is an ordinary LZO1X stream that any LZO1X
decompressor (the game's included) accepts; it is not byte-identical to
``lzo1x_1_compress`` output, which is not required.

Bitstream summary (``state`` = literals that follow the previous match, 0-3):

=========  ===========================================================
opcode     meaning
=========  ===========================================================
0-15       state 0: literal run of ``t + 3`` bytes (``t == 0``: extended)
           after a literal run: 3-byte match, distance ``2049 + ...``
           state 1-3: 2-byte match, distance ``1 + (t >> 2) + (b << 2)``
16-31      M4: distance 16385-49151, length ``(t & 7) + 2`` (0: extended)
32-63      M3: distance 1-16384, length ``(t & 31) + 2`` (0: extended)
64-255     M2: short match (LZO1X: len 3-8, dist <= 2048;
           LZO1Y: len 3-14, dist <= 1024)
=========  ===========================================================

The low two bits of a match's last offset byte carry the number of literals
(0-3) copied after it. The stream ends with the M4 marker ``11 00 00``.
"""

from __future__ import annotations

from typing import Optional

__all__ = ["LZOError", "compress", "decompress", "decompress_1x", "decompress_1y"]

_M2_MAX_OFFSET = {"1x": 0x0800, "1y": 0x0400}
_M3_MAX_OFFSET = 0x4000
_M4_MAX_OFFSET = 0xBFFF
_EOF_MARKER = b"\x11\x00\x00"


class LZOError(ValueError):
    """The input is not a valid LZO stream (or not the expected size)."""


# ---------------------------------------------------------------------------
# Decompression
# ---------------------------------------------------------------------------

def _copy_match(out: bytearray, dist: int, length: int) -> None:
    start = len(out) - dist
    if start < 0:
        raise LZOError("match distance points before the start of the output")
    if dist >= length:
        out += out[start:start + length]
    else:  # overlapping copy repeats the last `dist` bytes
        pattern = bytes(out[start:])
        reps = length // dist + 1
        out += (pattern * reps)[:length]


def decompress(data: bytes, expected_size: Optional[int] = None, variant: str = "1x") -> bytes:
    """Decompress an LZO1X (``variant="1x"``) or LZO1Y (``"1y"``) stream.

    ``expected_size``, when given, must match the decompressed length.
    Raises :class:`LZOError` on malformed or truncated input.
    """
    variant = variant.lower()
    if variant not in _M2_MAX_OFFSET:
        raise ValueError(f"unknown LZO variant: {variant!r}")
    is_1y = variant == "1y"
    m2_max_offset = _M2_MAX_OFFSET[variant]

    src = bytes(data)
    n = len(src)
    out = bytearray()
    ip = 0

    def byte() -> int:
        nonlocal ip
        if ip >= n:
            raise LZOError("input overrun")
        value = src[ip]
        ip += 1
        return value

    def extended(base: int) -> int:
        # zero bytes add 255 each; the first non-zero byte ends the count
        nonlocal ip
        count = 0
        while True:
            if ip >= n:
                raise LZOError("input overrun")
            b = src[ip]
            ip += 1
            if b:
                return count + base + b
            count += 255

    def literals(count: int) -> None:
        nonlocal ip
        if ip + count > n:
            raise LZOError("input overrun in literal run")
        out.extend(src[ip:ip + count])
        ip += count

    # Instruction interpreter. `mode` tells how an opcode < 16 is read:
    #   "run"   - after a match with state 0 (or at stream start): literal run
    #   "far"   - right after a literal run: 3-byte match beyond M2 range
    #   "near"  - after 1-3 state literals: 2-byte match
    mode = "run"
    if n and src[0] > 17:
        ip = 1
        t = src[0] - 17
        literals(t)
        mode = "near" if t < 4 else "far"

    while True:
        t = byte()
        if t < 16:
            if mode == "run":
                if t == 0:
                    t = extended(15)
                literals(t + 3)
                mode = "far"
                continue
            b = byte()
            if mode == "far":
                dist = 1 + m2_max_offset + (t >> 2) + (b << 2)
                _copy_match(out, dist, 3)
            else:
                dist = 1 + (t >> 2) + (b << 2)
                _copy_match(out, dist, 2)
            state = t & 3
        elif t >= 64:  # M2
            b = byte()
            if is_1y:
                dist = 1 + ((t >> 2) & 3) + (b << 2)
                length = (t >> 4) - 1
            else:
                dist = 1 + ((t >> 2) & 7) + (b << 3)
                length = (t >> 5) + 1
            _copy_match(out, dist, length)
            state = t & 3
        elif t >= 32:  # M3
            length = t & 31
            if length == 0:
                length = extended(31)
            lo, hi = byte(), byte()
            dist = 1 + (lo >> 2) + (hi << 6)
            _copy_match(out, dist, length + 2)
            state = lo & 3
        else:  # M4 (16-31), also the end-of-stream marker
            length = t & 7
            if length == 0:
                length = extended(7)
            lo, hi = byte(), byte()
            dist = ((t & 8) << 11) + (lo >> 2) + (hi << 6)
            if dist == 0:
                break
            dist += 0x4000
            _copy_match(out, dist, length + 2)
            state = lo & 3

        if state:
            literals(state)
            mode = "near"
        else:
            mode = "run"

    if ip != n:
        raise LZOError(f"{n - ip} trailing byte(s) after the end-of-stream marker")
    if expected_size is not None and len(out) != expected_size:
        raise LZOError(f"decompressed {len(out)} bytes, expected {expected_size}")
    return bytes(out)


def decompress_1x(data: bytes, expected_size: Optional[int] = None) -> bytes:
    return decompress(data, expected_size, "1x")


def decompress_1y(data: bytes, expected_size: Optional[int] = None) -> bytes:
    return decompress(data, expected_size, "1y")


# ---------------------------------------------------------------------------
# Compression (LZO1X)
# ---------------------------------------------------------------------------

_MAX_MATCH = 0x10000  # cap per match; longer repeats become several matches


def _extended_length(out: bytearray, value: int) -> None:
    """Write ``value`` (> 0) as the zero-prefixed extension used by long lengths."""
    while value > 255:
        out.append(0)
        value -= 255
    out.append(value)


def _match_length(data: bytes, a: int, b: int, limit: int) -> int:
    """Length of the common prefix of data[a:] and data[b:], at most ``limit``."""
    length = 0
    step = 64
    while length < limit:
        chunk = min(step, limit - length)
        if data[a + length:a + length + chunk] == data[b + length:b + length + chunk]:
            length += chunk
            continue
        if chunk == 1:
            break
        step = max(1, chunk // 8)
    return length


def compress(data: bytes) -> bytes:
    """Compress ``data`` as an LZO1X stream (greedy LZ77, single-entry hash)."""
    src = bytes(data)
    n = len(src)
    out = bytearray()
    state_pos = -1          # output index of the byte holding the last match's state bits
    first = True            # no instruction written yet
    lit_start = 0

    def flush_literals(end: int) -> None:
        nonlocal first, state_pos
        count = end - lit_start
        if count == 0:
            return
        if first and count <= 238:
            out.append(17 + count)
        elif state_pos >= 0 and count <= 3:
            out[state_pos] |= count
        elif count <= 18:
            out.append(count - 3)
        else:
            out.append(0)
            _extended_length(out, count - 18)
        out.extend(src[lit_start:end])
        first = False
        state_pos = -1

    table: dict = {}
    i = 0
    last = n - 4  # need 4 bytes for a hash key
    skip = 0
    while i <= last:
        key = src[i:i + 4]
        cand = table.get(key)
        table[key] = i
        if cand is None or i - cand > _M4_MAX_OFFSET:
            skip += 1
            i += 1 + (skip >> 5)  # speed up through incompressible data
            continue
        dist = i - cand
        length = 4 + _match_length(src, cand + 4, i + 4, min(n - i - 4, _MAX_MATCH - 4))
        if dist > _M3_MAX_OFFSET and length < 5:  # M4 costs 3+ bytes; not worth it
            i += 1
            continue
        skip = 0
        flush_literals(i)
        if length <= 8 and dist <= _M2_MAX_OFFSET["1x"]:
            d = dist - 1
            out.append(((length - 1) << 5) | ((d & 7) << 2))
            state_pos = len(out) - 1
            out.append(d >> 3)
        elif dist <= _M3_MAX_OFFSET:
            if length - 2 <= 31:
                out.append(32 | (length - 2))
            else:
                out.append(32)
                _extended_length(out, length - 2 - 31)
            d = dist - 1
            state_pos = len(out)
            out.append((d & 0x3F) << 2)
            out.append(d >> 6)
        else:
            d = dist - 0x4000
            op = 16 | ((d >> 11) & 8)
            if length - 2 <= 7:
                out.append(op | (length - 2))
            else:
                out.append(op)
                _extended_length(out, length - 2 - 7)
            state_pos = len(out)
            out.append((d & 0x3F) << 2)
            out.append((d >> 6) & 0xFF)
        first = False
        # index a few positions inside the match so later data can refer to it
        end = i + length
        for j in range(i + 1, min(end, last + 1), max(1, length // 8)):
            table[src[j:j + 4]] = j
        i = end
        lit_start = i

    flush_literals(n)
    out += _EOF_MARKER
    return bytes(out)
