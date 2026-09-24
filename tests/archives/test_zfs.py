import struct
import zlib

import pytest

from battlezone.archives import lzo
from battlezone.archives.zfs import (FLAG_LZO1X, FLAG_LZO1Y, LEGACY_MAGIC, ZFSArchive, ZFSError,
                                     parse_key, write_zfs, xor_bytes)
from bztoolbox.cli import main


def _files(tmp_path, count=5):
    folder = tmp_path / "src"
    folder.mkdir()
    for i in range(count):
        (folder / f"unit{i:03}.odf").write_bytes(b"[GameObjectClass]\r\nclassLabel = \"wingman\"\r\n" * (i + 1))
    (folder / "noise.bin").write_bytes(bytes(range(256)))
    (folder / "empty.txt").write_bytes(b"")
    return folder


def test_parse_key():
    assert parse_key(None) == 0 and parse_key("") == 0
    assert parse_key("0x10") == 16 and parse_key("42") == 42 and parse_key(7) == 7
    assert parse_key("secret") == zlib.crc32(b"secret")


def test_xor_is_its_own_inverse():
    data = bytes(range(250))
    assert xor_bytes(xor_bytes(data, 0xDEADBEEF), 0xDEADBEEF) == data
    assert xor_bytes(b"\x00\x00\x00\x00\x00", 0x04030201) == b"\x01\x02\x03\x04\x01"


@pytest.mark.parametrize("key", [0, 0xCBA07D86, "password"])
def test_roundtrip(tmp_path, key):
    folder = _files(tmp_path, 130)  # more than one directory block
    sources = sorted(folder.iterdir())
    out = tmp_path / "test.zfs"
    entries = write_zfs(out, sources, key=key)
    archive = ZFSArchive(out)
    assert archive.header.key == parse_key(key)
    assert len(archive) == len(sources) == len(entries)
    for source in sources:
        assert archive.read(source.name) == source.read_bytes()
    assert archive.get("NOISE.BIN").method == "Raw"  # incompressible data is stored
    assert archive.get("unit099.odf").method == "LZO1X"
    assert archive.verify() == []
    written = archive.extract(None, tmp_path / "out")
    assert {p.name for p in written} == {p.name for p in sources}


def test_wrong_key_changes_content(tmp_path):
    folder = _files(tmp_path, 1)
    out = tmp_path / "k.zfs"
    write_zfs(out, [folder / "unit000.odf"], key=1234)
    archive = ZFSArchive(out)
    assert archive.read("unit000.odf", key=99) != (folder / "unit000.odf").read_bytes()


def test_name_rules(tmp_path):
    with pytest.raises(ZFSError):
        write_zfs(tmp_path / "a.zfs", [("sixteen_chars.odf", b"x")])
    with pytest.raises(ZFSError):
        write_zfs(tmp_path / "a.zfs", [("a.odf", b"x"), ("A.ODF", b"y")])
    assert not (tmp_path / "a.zfs").exists()


def _handmade(tmp_path, legacy=False, key=0, encrypt_directory=False, method=FLAG_LZO1Y):
    """An archive built field by field, as other tools write them."""
    payload = b"hello zfs " * 40
    body = xor_bytes(payload, key)
    packed = body
    header_size = 36 if legacy else 28
    data_offset = header_size
    if method == FLAG_LZO1Y:
        # an LZO1Y stream: 20 literals (the XOR-ed payload repeats every 20 bytes),
        # then M2 matches in the 1Y encoding copying them forward
        stream = bytearray([17 + 20]) + body[:20]
        remaining = len(body) - 20
        while remaining:
            n = min(12, remaining)
            # 1Y M2: length = (t >> 4) - 1, distance = 1 + ((t >> 2) & 3) + (b << 2)
            d = 19
            stream += bytes([((n + 1) << 4) | ((d & 3) << 2), d >> 2])
            remaining -= n
        stream += b"\x11\x00\x00"
        packed = bytes(stream)
        assert lzo.decompress(packed, variant="1y") == body
    block_offset = data_offset + len(packed)
    record = struct.pack("<16s5I", b"hello.txt", data_offset, 0, len(packed), 0,
                         (len(payload) << 8) | method)
    block = struct.pack("<I", 0) + record + b"\x00" * 36 * 99
    if encrypt_directory:
        block = xor_bytes(block, key)
    fields = struct.pack("<6I", 1, 16, 100, 1, key, block_offset)
    header = (LEGACY_MAGIC + fields) if legacy else (b"ZFSF" + fields)
    path = tmp_path / "hand.zfs"
    path.write_bytes(header + packed + block)
    return path, payload


@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("key,encrypt_directory", [(0, False), (0x1234ABCD, False), (0x1234ABCD, True)])
@pytest.mark.parametrize("method", [0, FLAG_LZO1Y])
def test_reads_foreign_archives(tmp_path, legacy, key, encrypt_directory, method):
    path, payload = _handmade(tmp_path, legacy, key, encrypt_directory, method)
    archive = ZFSArchive(path, decrypt_directory=encrypt_directory)
    assert archive.header.format == ("Legacy LZO205" if legacy else "ZFSF")
    assert [e.name for e in archive] == ["hello.txt"]
    assert archive.read("hello.txt") == payload


def test_rejects_non_archives(tmp_path):
    bad = tmp_path / "bad.zfs"
    bad.write_bytes(b"PK\x03\x04" + b"\x00" * 40)
    with pytest.raises(ZFSError):
        ZFSArchive(bad)
    bad.write_bytes(b"ZF")
    with pytest.raises(ZFSError):
        ZFSArchive(bad)


def test_cli(tmp_path, capsys):
    folder = _files(tmp_path, 3)
    archive = tmp_path / "cli.zfs"
    assert main(["zfs", "pack", str(archive), str(folder), "--key", "pw"]) == 0
    assert main(["zfs", "list", str(archive)]) == 0
    assert "unit002.odf" in capsys.readouterr().out
    assert main(["zfs", "verify", str(archive)]) == 0
    out = tmp_path / "x"
    assert main(["zfs", "extract", str(archive), "unit001.odf", "-o", str(out)]) == 0
    assert (out / "unit001.odf").read_bytes() == (folder / "unit001.odf").read_bytes()
    assert main(["zfs", "list", str(tmp_path / "missing.zfs")]) == 1
