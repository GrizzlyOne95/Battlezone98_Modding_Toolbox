import ctypes
import ctypes.util
import random

import pytest

from battlezone.archives import lzo


def _samples():
    rnd = random.Random(1234)
    out = [b"", b"a", b"ab", b"abc", b"abcd" * 3, b"x" * 1000, bytes(range(256)) * 50,
           b"a" * 300 + b"b" * 5 + bytes(rnd.randrange(256) for _ in range(300))]
    for _ in range(120):
        size = rnd.randint(0, 4000)
        alphabet = rnd.randint(1, 256)
        data = bytearray(rnd.randrange(alphabet) for _ in range(size))
        for _ in range(rnd.randint(0, 15)):
            if len(data) > 10:
                a, b = rnd.randrange(len(data)), rnd.randrange(len(data))
                data[b:b] = data[a:a + rnd.randint(1, 300)]
        out.append(bytes(data))
    # distances in every match class (M2, M3, M4) and long lengths
    block = bytes(rnd.randrange(256) for _ in range(70000))
    out.append(block[:30000] + block[:30000] + block[:60000] + block[:5000])
    return out


SAMPLES = _samples()


@pytest.mark.parametrize("index", range(len(SAMPLES)))
def test_roundtrip(index):
    data = SAMPLES[index]
    packed = lzo.compress(data)
    assert lzo.decompress(packed, len(data)) == data


def test_end_marker_and_empty():
    assert lzo.compress(b"") == b"\x11\x00\x00"
    assert lzo.decompress(b"\x11\x00\x00") == b""


def test_rejects_bad_streams():
    packed = lzo.compress(b"hello hello hello hello")
    with pytest.raises(lzo.LZOError):
        lzo.decompress(packed[:-2])
    with pytest.raises(lzo.LZOError):
        lzo.decompress(packed + b"\x00")
    with pytest.raises(lzo.LZOError):
        lzo.decompress(packed, expected_size=3)
    with pytest.raises(lzo.LZOError):
        lzo.decompress(b"\x40\x10\x11\x00\x00")  # match before any output


def test_compresses_repetitive_data():
    data = b"ODF [GameObjectClass] geometryName = \"avtank00.xsi\"\n" * 400
    assert len(lzo.compress(data)) < len(data) // 10


# --- cross-check against the reference LZO library when it is installed ------------

def _liblzo():
    name = ctypes.util.find_library("lzo2")
    if not name:
        return None
    try:
        return ctypes.CDLL(name)
    except OSError:
        return None


LIB = _liblzo()
needs_lib = pytest.mark.skipif(LIB is None, reason="liblzo2 not installed (reference cross-check only)")


def _ref_compress(fn, data, workmem):
    size = len(data) + len(data) // 16 + 64 + 3
    dst = ctypes.create_string_buffer(size)
    dst_len = ctypes.c_size_t(size)
    mem = ctypes.create_string_buffer(workmem)
    assert getattr(LIB, fn)(data, ctypes.c_size_t(len(data)), dst, ctypes.byref(dst_len), mem) == 0
    return dst.raw[:dst_len.value]


@needs_lib
@pytest.mark.parametrize("index", range(0, len(SAMPLES), 7))
def test_reference_decompresses_our_output(index):
    data = SAMPLES[index]
    packed = lzo.compress(data)
    dst = ctypes.create_string_buffer(len(data) + 16)
    dst_len = ctypes.c_size_t(len(data) + 16)
    ret = LIB.lzo1x_decompress_safe(packed, ctypes.c_size_t(len(packed)), dst, ctypes.byref(dst_len), None)
    assert ret == 0 and dst.raw[:dst_len.value] == data


@needs_lib
@pytest.mark.parametrize("fn,variant,workmem", [
    ("lzo1x_1_compress", "1x", 1 << 19), ("lzo1x_999_compress", "1x", 14 * 16384 * 8),
    ("lzo1y_1_compress", "1y", 1 << 19), ("lzo1y_999_compress", "1y", 14 * 16384 * 8),
])
def test_we_decompress_reference_output(fn, variant, workmem):
    for data in SAMPLES[::5]:
        assert lzo.decompress(_ref_compress(fn, data, workmem), len(data), variant) == data
