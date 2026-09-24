"""Battlezone ZFS archives: read, extract, verify and write.

Pure Python (see :mod:`battlezone.archives.lzo`), so it works on every
platform without a native LZO library.

Layout (all little-endian)::

    header    "ZFSF" version name_len entries_per_block file_count key first_block
              (legacy MakeZFS archives start with "LZO205BZEF\\xff\\xff" and
              then carry the same six fields)
    block     next_block:uint32, then entries_per_block records of
              name[name_len] offset:uint32 index:uint32 packed_size:uint32
              time:uint32 flags:uint32
    flags     bit 1 (0x2): LZO1X, bit 2 (0x4): LZO1Y, bits 8-31: unpacked size

Encryption (MakeZFS): a 32-bit key, given as a number or as a password whose
CRC32 is the key, XORs the *unpacked* member bytes with the key's four
little-endian bytes, repeating. Some archives also XOR the directory blocks.
"""

from __future__ import annotations

import os
import struct
import time
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Callable, Iterable, List, Optional, Tuple, Union

from battlezone.archives import lzo

__all__ = [
    "ZFSError", "ZFSEntry", "ZFSArchive", "ZFSHeader", "parse_key", "xor_bytes",
    "write_zfs", "FLAG_LZO1X", "FLAG_LZO1Y", "NAME_LENGTH", "ENTRIES_PER_BLOCK",
]

ZFSF_MAGIC = b"ZFSF"
LEGACY_MAGIC = b"LZO205BZEF\xff\xff"
FLAG_LZO1X = 0x2
FLAG_LZO1Y = 0x4
NAME_LENGTH = 16
ENTRIES_PER_BLOCK = 100
VERSION = 1

KeyLike = Union[int, str, None]


class ZFSError(ValueError):
    """The file is not a readable ZFS archive, or a member cannot be decoded."""


def parse_key(value: KeyLike) -> int:
    """A key from user input: an int, a decimal/hex string, or a password (CRC32)."""
    if value is None:
        return 0
    if isinstance(value, int):
        return value & 0xFFFFFFFF
    text = str(value).strip()
    if not text:
        return 0
    try:
        return int(text, 0) & 0xFFFFFFFF
    except ValueError:
        return zlib.crc32(text.encode("utf-8")) & 0xFFFFFFFF


def xor_bytes(data: bytes, key: int) -> bytes:
    """XOR ``data`` with the key's little-endian bytes, repeating from offset 0."""
    key &= 0xFFFFFFFF
    if not key or not data:
        return bytes(data)
    stream = struct.pack("<I", key)
    # int arithmetic over the whole buffer is far faster than a byte loop
    full = (stream * (len(data) // 4 + 1))[:len(data)]
    n = int.from_bytes(data, "little") ^ int.from_bytes(full, "little")
    return n.to_bytes(len(data), "little")


@dataclass(frozen=True)
class ZFSHeader:
    format: str             # "ZFSF" or "Legacy LZO205"
    version: int
    name_length: int
    entries_per_block: int
    file_count: int
    key: int
    first_block: int


@dataclass
class ZFSEntry:
    name: str
    offset: int
    index: int
    packed_size: int
    time: int
    flags: int

    @property
    def size(self) -> int:
        return self.flags >> 8

    @property
    def method(self) -> str:
        if self.flags & FLAG_LZO1X:
            return "LZO1X"
        if self.flags & FLAG_LZO1Y:
            return "LZO1Y"
        return "Raw"

    @property
    def extension(self) -> str:
        return os.path.splitext(self.name)[1].lower()


def _read_header(stream: BinaryIO) -> ZFSHeader:
    stream.seek(0)
    prefix = stream.read(12)
    if len(prefix) < 12:
        raise ZFSError("File is too small to contain a ZFS header.")
    if prefix == LEGACY_MAGIC:
        raw = stream.read(24)
        if len(raw) != 24:
            raise ZFSError("Legacy LZO ZFS header is truncated.")
        fields = struct.unpack("<6I", raw)
        fmt = "Legacy LZO205"
    else:
        stream.seek(0)
        raw = stream.read(28)
        if len(raw) != 28 or raw[:4] != ZFSF_MAGIC:
            raise ZFSError(f"Unsupported ZFS header signature: {prefix.hex(' ')}")
        fields = struct.unpack("<6I", raw[4:])
        fmt = "ZFSF"
    header = ZFSHeader(fmt, *fields)
    # a misidentified file would otherwise produce absurd record sizes/loops
    if not 1 <= header.name_length <= 4096:
        raise ZFSError(f"Invalid ZFS filename field length: {header.name_length}")
    if not 1 <= header.entries_per_block <= 100000:
        raise ZFSError(f"Invalid ZFS entries-per-block value: {header.entries_per_block}")
    if header.file_count > 10_000_000:
        raise ZFSError(f"Invalid ZFS file count: {header.file_count}")
    return header


class ZFSArchive:
    """An opened archive. ``key`` overrides the header key (for directory and
    member decryption); ``decrypt_directory`` forces XOR-decoding of the
    directory blocks (it is otherwise detected from out-of-range pointers)."""

    def __init__(self, path: Union[str, os.PathLike], key: KeyLike = None,
                 decrypt_directory: bool = False):
        self.path = Path(path)
        self.key_override = None if key in (None, "") else parse_key(key)
        self.warnings: List[str] = []
        with open(self.path, "rb") as stream:
            self.header = _read_header(stream)
            self.entries = self._read_directory(stream, decrypt_directory)
        self._by_name = {}
        for entry in self.entries:
            self._by_name.setdefault(entry.name.lower(), entry)

    # --- directory ----------------------------------------------------------
    @property
    def key(self) -> int:
        return self.header.key if self.key_override is None else self.key_override

    @property
    def encrypted(self) -> bool:
        return self.header.key != 0

    def _read_directory(self, f: BinaryIO, force_decrypt: bool) -> List[ZFSEntry]:
        h = self.header
        key = self.key
        f.seek(0, os.SEEK_END)
        file_size = f.tell()
        record = struct.Struct(f"<{h.name_length}s5I")
        limit = h.file_count
        next_block = h.first_block
        if limit == 0 and next_block != 0:
            self.warnings.append("Header reports 0 files but has a directory; reading all blocks.")
            limit = 1 << 62

        if next_block >= file_size and key:
            decoded = struct.unpack("<I", xor_bytes(struct.pack("<I", next_block), key))[0]
            if decoded < file_size:
                next_block = decoded

        entries: List[ZFSEntry] = []
        seen_blocks = set()
        while next_block and len(entries) < limit:
            if next_block >= file_size or next_block in seen_blocks:
                self.warnings.append(f"Invalid directory block pointer {next_block}; stopped reading.")
                break
            seen_blocks.add(next_block)
            f.seek(next_block)
            head = f.read(4)
            if len(head) < 4:
                break
            raw_next = struct.unpack("<I", head)[0]
            block_encrypted = False
            if force_decrypt or (raw_next >= file_size and key):
                decoded = struct.unpack("<I", xor_bytes(head, key))[0]
                if decoded == 0 or decoded < file_size:
                    raw_next = decoded
                    block_encrypted = True
            next_block = raw_next

            for _ in range(h.entries_per_block):
                if len(entries) >= limit:
                    break
                chunk = f.read(record.size)
                if len(chunk) < record.size:
                    break
                if block_encrypted:
                    chunk = xor_bytes(chunk, key)
                name_raw, offset, index, packed, stamp, flags = record.unpack(chunk)
                name = name_raw.split(b"\x00")[0].decode("ascii", errors="ignore").strip()
                if not name:
                    continue
                entries.append(ZFSEntry(name, offset, index, packed, stamp, flags))
        return entries

    # --- members ------------------------------------------------------------
    def __len__(self) -> int:
        return len(self.entries)

    def __iter__(self):
        return iter(self.entries)

    def get(self, name: str) -> Optional[ZFSEntry]:
        return self._by_name.get(name.lower())

    def read(self, entry: Union[ZFSEntry, str], key: KeyLike = None) -> bytes:
        """The member's original bytes (decompressed, then decrypted)."""
        if isinstance(entry, str):
            found = self.get(entry)
            if found is None:
                raise KeyError(entry)
            entry = found
        with open(self.path, "rb") as f:
            f.seek(entry.offset)
            data = f.read(entry.packed_size)
        if len(data) != entry.packed_size:
            raise ZFSError(f"{entry.name}: data is truncated")
        if entry.flags & (FLAG_LZO1X | FLAG_LZO1Y):
            variant = "1x" if entry.flags & FLAG_LZO1X else "1y"
            try:
                data = lzo.decompress(data, variant=variant)
            except lzo.LZOError as exc:
                raise ZFSError(f"{entry.name}: {exc}") from exc
            if len(data) != entry.size:
                self.warnings.append(
                    f"{entry.name}: unpacked {len(data)} bytes, directory says {entry.size}")
        use_key = self.key if key in (None, "") else parse_key(key)
        if self.encrypted and use_key:
            data = xor_bytes(data, use_key)
        return data

    def extract(self, entries: Optional[Iterable[Union[ZFSEntry, str]]], out_dir: Union[str, os.PathLike],
                progress: Optional[Callable[[int, int, str], None]] = None,
                cancel: Optional[Callable[[], bool]] = None, key: KeyLike = None) -> List[Path]:
        """Extract ``entries`` (all when None) into ``out_dir``; returns written paths."""
        chosen = list(self.entries if entries is None else entries)
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        written = []
        for i, entry in enumerate(chosen, 1):
            if cancel and cancel():
                break
            if isinstance(entry, str):
                entry = self.get(entry) or entry
                if isinstance(entry, str):
                    raise KeyError(entry)
            target = out / Path(entry.name.replace("\\", "/")).name  # never escape out_dir
            target.write_bytes(self.read(entry, key))
            written.append(target)
            if progress:
                progress(i, len(chosen), entry.name)
        return written

    def verify(self, progress: Optional[Callable[[int, int, str], None]] = None) -> List[str]:
        """Decode every member; returns problems found (empty when all is well)."""
        problems = []
        before = len(self.warnings)
        for i, entry in enumerate(self.entries, 1):
            try:
                self.read(entry)
            except ZFSError as exc:
                problems.append(str(exc))
            if progress:
                progress(i, len(self.entries), entry.name)
        problems += self.warnings[before:]
        return problems


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------

Source = Union[str, os.PathLike, Tuple[str, bytes]]


def _collect(sources: Iterable[Source]) -> List[Tuple[str, Union[Path, bytes]]]:
    items: List[Tuple[str, Union[Path, bytes]]] = []
    for source in sources:
        if isinstance(source, tuple):
            items.append((source[0], source[1]))
        else:
            path = Path(source)
            items.append((path.name, path))
    return items


def files_in_folder(folder: Union[str, os.PathLike], recursive: bool = False) -> List[Path]:
    """Files to pack from ``folder`` (ZFS names are flat; see :func:`write_zfs`)."""
    root = Path(folder)
    pattern = root.rglob("*") if recursive else root.iterdir()
    return sorted((p for p in pattern if p.is_file()), key=lambda p: p.name.lower())


def write_zfs(path: Union[str, os.PathLike], sources: Iterable[Source], key: KeyLike = 0,
              compress: bool = True, progress: Optional[Callable[[int, int, str], None]] = None,
              cancel: Optional[Callable[[], bool]] = None) -> List[ZFSEntry]:
    """Write a ZFSF archive.

    ``sources`` are file paths, or ``(name, data)`` pairs. Names must be
    unique (case-insensitive) and at most 15 ASCII characters. Members are
    LZO1X-compressed when that makes them smaller, otherwise stored raw. With
    a key, member bytes are XOR-encrypted before compression, the order the
    game (and :meth:`ZFSArchive.read`) undoes.
    """
    key_value = parse_key(key)
    items = _collect(sources)
    seen = {}
    for name, _ in items:
        try:
            encoded = name.encode("ascii")
        except UnicodeEncodeError:
            raise ZFSError(f"{name!r}: ZFS names must be ASCII") from None
        if len(encoded) >= NAME_LENGTH:
            raise ZFSError(f"{name!r}: ZFS names are limited to {NAME_LENGTH - 1} characters")
        if name.lower() in seen:
            raise ZFSError(f"{name!r}: duplicate name (also {seen[name.lower()]!r})")
        seen[name.lower()] = name

    target = Path(path)
    tmp = target.with_name(target.name + ".tmp")
    entries: List[ZFSEntry] = []
    header = struct.Struct("<4s6I")
    record = struct.Struct(f"<{NAME_LENGTH}s5I")
    try:
        with open(tmp, "wb") as f:
            f.write(b"\x00" * header.size)
            for i, (name, source) in enumerate(items):
                if cancel and cancel():
                    raise InterruptedError("cancelled")
                raw = source.read_bytes() if isinstance(source, Path) else bytes(source)
                if len(raw) >= 1 << 24:
                    raise ZFSError(f"{name!r}: members are limited to 16 MB")
                stamp = int(source.stat().st_mtime) if isinstance(source, Path) else int(time.time())
                payload = xor_bytes(raw, key_value)
                flags = len(raw) << 8
                if compress and raw:
                    packed = lzo.compress(payload)
                    if len(packed) < len(payload):
                        payload = packed
                        flags |= FLAG_LZO1X
                entry = ZFSEntry(name, f.tell(), i, len(payload), stamp & 0xFFFFFFFF, flags)
                f.write(payload)
                entries.append(entry)
                if progress:
                    progress(i + 1, len(items), name)

            first_block = f.tell() if entries else 0
            block_size = 4 + ENTRIES_PER_BLOCK * record.size
            for start in range(0, len(entries), ENTRIES_PER_BLOCK):
                batch = entries[start:start + ENTRIES_PER_BLOCK]
                more = start + ENTRIES_PER_BLOCK < len(entries)
                f.write(struct.pack("<I", f.tell() + block_size if more else 0))
                for e in batch:
                    f.write(record.pack(e.name.encode("ascii"), e.offset, e.index,
                                        e.packed_size, e.time, e.flags))
                f.write(b"\x00" * (record.size * (ENTRIES_PER_BLOCK - len(batch))))

            f.seek(0)
            f.write(header.pack(ZFSF_MAGIC, VERSION, NAME_LENGTH, ENTRIES_PER_BLOCK,
                                len(entries), key_value, first_block))
        os.replace(tmp, target)
    finally:
        if tmp.exists():
            tmp.unlink()
    return entries
