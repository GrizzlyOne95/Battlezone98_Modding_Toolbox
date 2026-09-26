import io
import struct

import numpy as np
import pytest
from PIL import Image

from battlezone.images import softpic
from battlezone.images.softpic import HEADER, MAGIC, PICError, decode, encode, read_header
from bztoolbox.cli import main

softpic.register()


def _pic(width, height, packets, body):
    """A PIC laid out like the stock BZ2 files (version 2.62, 'PICT', fields 3)."""
    head = HEADER.pack(MAGIC, 2.62, b"Saved in Photoshop Plugin", b"PICT", width, height, 1.0, 3, 0)
    chain = b"".join(bytes((1 if i + 1 < len(packets) else 0, 8, kind, mask))
                     for i, (kind, mask) in enumerate(packets))
    return head + chain + body


def test_mixed_rle_runs():
    # row 0: 2 literal pixels, then 3 x red; row 1: long form (128) repeat of 5 x blue
    body = (bytes([1]) + b"\x01\x02\x03\x04\x05\x06" + bytes([130]) + b"\xff\x00\x00"
            + bytes([128]) + struct.pack(">H", 5) + b"\x00\x00\xff")
    w, h, mode, pixels = decode(_pic(5, 2, [(2, 0xE0)], body))
    assert (w, h, mode) == (5, 2, "RGB")
    rows = np.frombuffer(pixels, np.uint8).reshape(2, 5, 3)
    assert rows[0].tolist() == [[1, 2, 3], [4, 5, 6], [255, 0, 0], [255, 0, 0], [255, 0, 0]]
    assert rows[1].tolist() == [[0, 0, 255]] * 5


def test_raw_and_pure_rle_with_alpha_packet():
    # RGB raw, then a separate alpha packet in pure RLE, per scanline
    body = b"\x0a\x0b\x0c\x0d\x0e\x0f" + bytes([2, 0x80])
    w, h, mode, pixels = decode(_pic(2, 1, [(0, 0xE0), (1, 0x10)], body))
    assert mode == "RGBA"
    assert list(pixels) == [10, 11, 12, 0x80, 13, 14, 15, 0x80]


@pytest.mark.parametrize("mode", ["RGB", "RGBA"])
def test_roundtrip(mode):
    rng = np.random.default_rng(1)
    image = rng.integers(0, 256, (37, 300, len(mode)), dtype=np.uint8)
    image[5] = 7                    # a row of one colour: long repeat (> 128)
    image[6, 10:20] = 99            # a short repeat inside literals
    data = encode(300, 37, mode, image.tobytes())
    assert read_header(data).packets == ([(8, 2, 0xE0)] + ([(8, 2, 0x10)] if mode == "RGBA" else []))
    assert decode(data) == (300, 37, mode, image.tobytes())


def test_errors():
    with pytest.raises(PICError):
        decode(b"\x89PNG" + b"\x00" * 200)
    good = encode(4, 4, "RGB", bytes(range(48)))
    with pytest.raises(PICError):
        decode(good[:-3])


def test_pillow_plugin(tmp_path):
    rgba = Image.new("RGBA", (64, 32), (10, 20, 30, 128))
    rgba.putpixel((3, 4), (255, 0, 0, 0))
    rgba.save(tmp_path / "a.pic")
    with Image.open(tmp_path / "a.pic") as im:
        assert (im.format, im.mode, im.size) == ("SOFTPIC", "RGBA", (64, 32))
        assert im.getpixel((3, 4)) == (255, 0, 0, 0) and im.getpixel((0, 0)) == (10, 20, 30, 128)
        im.convert("RGB").save(tmp_path / "a.png")
    # opaque alpha is dropped, like the stock files
    Image.new("RGBA", (8, 8), (1, 2, 3, 255)).save(tmp_path / "o.pic")
    assert Image.open(tmp_path / "o.pic").mode == "RGB"
    # Pillow finds it by content, not only by extension
    assert Image.open(io.BytesIO((tmp_path / "a.pic").read_bytes())).format == "SOFTPIC"


def test_cli_convert(tmp_path, capsys):
    src = tmp_path / "src"
    src.mkdir()
    Image.new("RGB", (16, 16), (200, 100, 50)).save(src / "tex.pic", format="SOFTPIC")
    assert main(["pic", str(src), "-o", str(tmp_path / "png")]) == 0
    assert Image.open(tmp_path / "png" / "tex.png").getpixel((0, 0)) == (200, 100, 50)
    assert main(["pic", str(tmp_path / "png"), "--to", "pic", "-o", str(tmp_path / "back")]) == 0
    assert Image.open(tmp_path / "back" / "tex.pic").getpixel((5, 5)) == (200, 100, 50)
    assert main(["pic", str(tmp_path / "png"), "--to", "pic", "-o", str(tmp_path / "back")]) == 0
    assert "skip" in capsys.readouterr().out
