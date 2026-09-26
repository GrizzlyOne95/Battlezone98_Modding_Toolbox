"""Softimage PIC images (``.pic``): decode, encode and a Pillow plugin.

Battlezone II's original textures are PICs written by a Photoshop plugin
(SOFT.8BI); they sit in the demo's ``data.pak`` and BZ2R's ``bumps.pak``.
Pure Python, so Pillow gains ``.pic`` everywhere once :func:`register` runs.

Layout (big-endian)::

    header   magic:uint32 (0x5380F634) version:float32 comment[80] "PICT"
             width:uint16 height:uint16 ratio:float32 fields:uint16 pad:uint16
    packets  chained:uint8 size:uint8 (8) type:uint8 channels:uint8,
             repeated while chained != 0. channels is a mask of
             R 0x80, G 0x40, B 0x20, A 0x10; each packet covers its channels.
    pixels   per scanline, top row first, one run of ``width`` pixels per
             packet, holding that packet's channels in R, G, B, A order.
             type 0: raw.  type 1: (count:uint8, pixel) runs.
             type 2 ("mixed"): n < 128 -> n+1 literal pixels;
             n > 128 -> the next pixel repeated n-127 times;
             n == 128 -> count:uint16 then a pixel repeated count times.

Every stock BZ2 PIC is mixed RLE with an RGB packet and, when it has alpha,
a second alpha packet; :func:`encode` writes the same shape.
"""

from __future__ import annotations

import struct
from typing import BinaryIO, List, Tuple

__all__ = ["MAGIC", "PICError", "PICHeader", "read_header", "decode", "encode", "register", "is_pic"]

MAGIC = 0x5380F634
HEADER = struct.Struct(">If80s4sHHfHH")
CHANNELS = ((0x80, 0), (0x40, 1), (0x20, 2), (0x10, 3))  # mask bit -> RGBA index
RAW, PURE_RLE, MIXED_RLE = 0, 1, 2
COMMENT = b"Battlezone Modding Toolbox"


class PICError(ValueError):
    """The data is not a Softimage PIC this module can decode."""


class PICHeader:
    def __init__(self, version: float, comment: str, width: int, height: int, ratio: float,
                 fields: int, packets: List[Tuple[int, int, int]], data_offset: int):
        self.version, self.comment = version, comment
        self.width, self.height, self.ratio, self.fields = width, height, ratio, fields
        self.packets = packets          # (size, type, channel mask)
        self.data_offset = data_offset

    @property
    def has_alpha(self) -> bool:
        return any(mask & 0x10 for _, _, mask in self.packets)


def is_pic(prefix: bytes) -> bool:
    return len(prefix) >= 4 and struct.unpack(">I", prefix[:4])[0] == MAGIC


def read_header(data: bytes) -> PICHeader:
    if len(data) < HEADER.size + 4 or not is_pic(data):
        raise PICError("Not a Softimage PIC image.")
    _, version, comment, pict, width, height, ratio, fields, _ = HEADER.unpack_from(data)
    if pict != b"PICT":
        raise PICError(f"Unsupported PIC image id {pict!r}.")
    if not (0 < width <= 16384 and 0 < height <= 16384):
        raise PICError(f"Invalid PIC size {width}x{height}.")
    packets, offset = [], HEADER.size
    while True:
        if offset + 4 > len(data) or len(packets) >= 8:
            raise PICError("PIC channel packets are truncated.")
        chained, size, kind, mask = data[offset:offset + 4]
        offset += 4
        if size != 8:
            raise PICError(f"Only 8-bit PIC channels are supported (got {size}).")
        if kind not in (RAW, PURE_RLE, MIXED_RLE):
            raise PICError(f"Unknown PIC compression type {kind}.")
        if not mask & 0xF0:
            raise PICError("PIC packet has no channels.")
        packets.append((size, kind, mask))
        if not chained:
            break
    text = comment.split(b"\x00")[0].decode("latin-1")
    return PICHeader(version, text, width, height, ratio, fields, packets, offset)


def _decode_run(data: bytes, pos: int, kind: int, width: int, n: int) -> Tuple[bytes, int]:
    """One scanline of one packet: ``width`` pixels of ``n`` bytes."""
    need = width * n
    if kind == RAW:
        run = data[pos:pos + need]
        if len(run) != need:
            raise PICError("PIC pixel data is truncated.")
        return run, pos + need
    out = bytearray()
    try:
        while len(out) < need:
            if kind == PURE_RLE:
                count = data[pos]
                pixel = data[pos + 1:pos + 1 + n]
                pos += 1 + n
                out += pixel * count
                continue
            count = data[pos]
            pos += 1
            if count < 128:
                length = (count + 1) * n
                out += data[pos:pos + length]
                pos += length
            else:
                if count == 128:
                    count = (data[pos] << 8) | data[pos + 1]
                    pos += 2
                else:
                    count -= 127
                out += data[pos:pos + n] * count
                pos += n
    except IndexError:
        raise PICError("PIC pixel data is truncated.") from None
    if len(out) != need:
        raise PICError("PIC run overflows its scanline.")
    return bytes(out), pos


def decode(data: bytes) -> Tuple[int, int, str, bytes]:
    """``(width, height, mode, pixels)``: mode is "RGBA" when the image has an
    alpha channel, else "RGB"; pixels are top row first."""
    import numpy as np

    h = read_header(data)
    mode = "RGBA" if h.has_alpha else "RGB"
    image = np.zeros((h.height, h.width, 4), dtype=np.uint8)
    image[..., 3] = 255
    plan = []
    for _, kind, mask in h.packets:
        targets = [index for bit, index in CHANNELS if mask & bit]
        plan.append((kind, targets))
    pos = h.data_offset
    for y in range(h.height):
        for kind, targets in plan:
            run, pos = _decode_run(data, pos, kind, h.width, len(targets))
            image[y, :, targets] = np.frombuffer(run, dtype=np.uint8).reshape(h.width, len(targets)).T
    if mode == "RGB":
        image = image[..., :3]
    return h.width, h.height, mode, image.tobytes()


def _encode_run(row: bytes, n: int) -> bytes:
    """Mixed-RLE encode one scanline of ``n``-byte pixels."""
    pixels = [row[i:i + n] for i in range(0, len(row), n)]
    out = bytearray()
    literal: List[bytes] = []

    def flush():
        while literal:
            chunk = literal[:128]
            del literal[:128]
            out.append(len(chunk) - 1)
            out.extend(b"".join(chunk))

    i = 0
    while i < len(pixels):
        j = i + 1
        while j < len(pixels) and pixels[j] == pixels[i] and j - i < 65535:
            j += 1
        count = j - i
        if count >= 2:
            flush()
            if count <= 128:
                out.append(count + 127)
            else:
                out.append(128)
                out.extend(struct.pack(">H", count))
            out.extend(pixels[i])
        else:
            literal.append(pixels[i])
        i = j
    flush()
    return bytes(out)


def encode(width: int, height: int, mode: str, pixels: bytes, comment: bytes = COMMENT) -> bytes:
    """A mixed-RLE PIC from "RGB" or "RGBA" pixels (top row first)."""
    import numpy as np

    if mode not in ("RGB", "RGBA"):
        raise PICError(f"PIC images are RGB or RGBA, not {mode}.")
    channels = len(mode)
    image = np.frombuffer(pixels, dtype=np.uint8).reshape(height, width, channels)
    packets = [(0xE0, image[..., :3])]
    if channels == 4:
        packets.append((0x10, image[..., 3:]))
    out = bytearray(HEADER.pack(MAGIC, 2.62, comment[:79], b"PICT", width, height, 1.0, 3, 0))
    for i, (mask, _) in enumerate(packets):
        out += bytes((1 if i + 1 < len(packets) else 0, 8, MIXED_RLE, mask))
    for y in range(height):
        for _, plane in packets:
            out += _encode_run(plane[y].tobytes(), plane.shape[2])
    return bytes(out)


# ---------------------------------------------------------------------------
# Pillow plugin
# ---------------------------------------------------------------------------

_registered = False


def register() -> None:
    """Teach Pillow to open (and save) ``.pic`` files. Safe to call repeatedly."""
    global _registered
    if _registered:
        return
    from PIL import Image, ImageFile

    class SoftPicImageFile(ImageFile.ImageFile):
        format = "SOFTPIC"
        format_description = "Softimage PIC"

        def _open(self):
            prefix = self.fp.read(HEADER.size + 32)
            try:
                header = read_header(prefix)
            except PICError as exc:
                raise SyntaxError(str(exc)) from exc
            self._pic_header = header
            self._mode = "RGBA" if header.has_alpha else "RGB"
            self._size = (header.width, header.height)
            self.info["comment"] = header.comment
            self.tile = []

        def load(self):
            if getattr(self, "_pic_loaded", False):
                return Image.Image.load(self)
            self.fp.seek(0)
            data = self.fp.read()
            try:
                width, height, mode, pixels = decode(data)
            except PICError as exc:
                raise OSError(str(exc)) from exc
            self.im = Image.frombytes(mode, (width, height), pixels).im
            self._pic_loaded = True
            if getattr(self, "_exclusive_fp", False) and self.fp:
                self.fp.close()
            self.fp = None
            return Image.Image.load(self)

    def _accept(prefix: bytes) -> bool:
        return is_pic(prefix)

    def _save(im, fp: BinaryIO, filename) -> None:
        image = im if im.mode in ("RGB", "RGBA") else im.convert("RGBA" if "A" in im.mode else "RGB")
        if image.mode == "RGBA" and image.getchannel("A").getextrema() == (255, 255):
            image = image.convert("RGB")   # like the stock files: no alpha packet when opaque
        fp.write(encode(image.width, image.height, image.mode, image.tobytes()))

    Image.register_open(SoftPicImageFile.format, SoftPicImageFile, _accept)
    Image.register_save(SoftPicImageFile.format, _save)
    Image.register_extension(SoftPicImageFile.format, ".pic")
    Image.register_mime(SoftPicImageFile.format, "image/x-softimage-pic")
    _registered = True
