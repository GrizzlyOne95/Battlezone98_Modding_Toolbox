import struct
import zlib

import pytest

from battlezone.archives.pak import HEADER, MAGIC, PAKArchive, PAKError, files_in_folder, write_pak
from bztoolbox.cli import main


def _stock_like(path):
    """A tiny archive laid out byte-for-byte like the stock BZ2R bumps.pak."""
    body = b"\x01\x02\x03\x04" * 64
    packed = zlib.compress(body)
    raw = b"RAW!"
    data_start = HEADER.size
    directory = (struct.pack("<IB", 1, 10) + b"a_bump.pic" + struct.pack("<3I", data_start, len(packed), len(body))
                 + struct.pack("<IB", 0, 5) + b"b.bmp" + struct.pack("<3I", data_start + len(packed), 4, 4))
    groups = struct.pack("<B", 14) + b"ISDF Buildings"
    dir_offset = data_start + len(packed) + len(raw)
    header = HEADER.pack(MAGIC, 2, 1, dir_offset + len(directory), 2, dir_offset, *([0] * 8))
    path.write_bytes(header + packed + raw + directory + groups)
    return body, raw


def test_reads_stock_layout(tmp_path):
    body, raw = _stock_like(tmp_path / "s.pak")
    archive = PAKArchive(tmp_path / "s.pak")
    assert archive.groups == ["ISDF Buildings"]
    a, b = archive.entries
    assert (a.name, a.group_name, a.method) == ("a_bump.pic", "ISDF Buildings", "zlib")
    assert (b.name, b.group, b.method) == ("b.bmp", 0, "Raw")
    assert archive.read(a) == body and archive.read("b.bmp") == raw
    assert archive.verify() == []


def test_reads_demo_version_1(tmp_path):
    """Version 1 (the BZ2 demo's data.pak): no packed size, nested group paths."""
    odf = b"[GameObjectClass]\r\nclassLabel = \"plant\"\r\n"
    wav = b"RIFF\x04\x00\x00\x00WAVE"
    start = HEADER.size
    directory = (struct.pack("<IB", 1, 12) + b"iochnk01.odf" + struct.pack("<2I", start, len(odf))
                 + struct.pack("<IB", 0, 10) + b"abetty.wav" + struct.pack("<2I", start + len(odf), len(wav)))
    groups = struct.pack("<B", 14) + b"effects\\chunks"
    dir_offset = start + len(odf) + len(wav)
    header = HEADER.pack(MAGIC, 1, 1, dir_offset + len(directory), 2, dir_offset, *([0] * 8))
    path = tmp_path / "data.pak"
    path.write_bytes(header + odf + wav + directory + groups)

    archive = PAKArchive(path)
    assert archive.header.format == "DOCP v1" and archive.warnings == []
    a, b = archive.entries
    assert (a.path, a.method, a.size) == ("effects/chunks/iochnk01.odf", "Raw", len(odf))
    assert archive.read("effects/chunks/iochnk01.odf") == odf and archive.read(b) == wav
    archive.extract(None, tmp_path / "out", use_groups=True)
    assert (tmp_path / "out" / "effects" / "chunks" / "iochnk01.odf").read_bytes() == odf
    assert (tmp_path / "out" / "abetty.wav").read_bytes() == wav


def test_group_paths_cannot_escape(tmp_path):
    out = tmp_path / "e.pak"
    write_pak(out, [("..\\..\\C:\\evil", "x.odf", b"1")])
    written = PAKArchive(out).extract(None, tmp_path / "out", use_groups=True)
    assert written == [tmp_path / "out" / "evil" / "x.odf"]


def test_empty_archive(tmp_path):
    out = tmp_path / "empty.pak"
    write_pak(out, [])
    assert out.stat().st_size == HEADER.size
    assert len(PAKArchive(out)) == 0


def test_roundtrip_with_groups(tmp_path):
    src = tmp_path / "src"
    (src / "Fury Ships").mkdir(parents=True)
    (src / "effects" / "chunks").mkdir(parents=True)
    (src / "loose.tga").write_bytes(bytes(range(256)))
    (src / "Fury Ships" / "fvtank.pic").write_bytes(b"texture " * 400)
    (src / "effects" / "chunks" / "iochnk01.odf").write_bytes(b"[GameObjectClass]\r\n")
    out = tmp_path / "t.pak"
    write_pak(out, files_in_folder(src))
    archive = PAKArchive(out)
    assert archive.header.version == 2
    assert archive.groups == ["effects\\chunks", "Fury Ships"]
    assert archive.get("Fury Ships/fvtank.pic").compressed
    assert not archive.get("loose.tga").compressed
    written = archive.extract(None, tmp_path / "out", use_groups=True)
    assert sorted(p.relative_to(tmp_path / "out").as_posix() for p in written) == [
        "Fury Ships/fvtank.pic", "effects/chunks/iochnk01.odf", "loose.tga"]
    assert (tmp_path / "out" / "Fury Ships" / "fvtank.pic").read_bytes() == b"texture " * 400


def test_duplicate_names_rejected(tmp_path):
    with pytest.raises(PAKError):
        write_pak(tmp_path / "d.pak", [("a", "x.pic", b"1"), ("b", "X.PIC", b"2")])


def test_rejects_other_files(tmp_path):
    (tmp_path / "x.pak").write_bytes(b"PK\x03\x04" + b"\x00" * 100)
    with pytest.raises(PAKError):
        PAKArchive(tmp_path / "x.pak")


def test_corrupt_member_reported(tmp_path):
    out = tmp_path / "c.pak"
    write_pak(out, [("", "a.pic", b"abc" * 1000)])
    data = bytearray(out.read_bytes())
    data[HEADER.size + 4] ^= 0xFF
    out.write_bytes(bytes(data))
    assert PAKArchive(out).verify()


def test_cli(tmp_path, capsys):
    src = tmp_path / "src"
    (src / "G").mkdir(parents=True)
    (src / "G" / "a.pic").write_bytes(b"a" * 300)
    out = tmp_path / "t.pak"
    assert main(["pak", "pack", str(out), str(src)]) == 0
    assert main(["pak", "list", str(out)]) == 0
    assert "G/a.pic" in capsys.readouterr().out
    assert main(["pak", "verify", str(out)]) == 0
    assert main(["pak", "extract", str(out), "-g", "-o", str(tmp_path / "x")]) == 0
    assert (tmp_path / "x" / "G" / "a.pic").read_bytes() == b"a" * 300
