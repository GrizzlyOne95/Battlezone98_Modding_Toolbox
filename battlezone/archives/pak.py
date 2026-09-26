"""Battlezone II PAK archives ("DOCP"): read, extract, verify and write.

The BZ2 / BZ2R texture packs (``bumps.pak``, ``smtex.pak``, ...) use this
format. Layout (all little-endian)::

    header     "DOCP" version:uint32 (2) group_count group_names_offset
               file_count directory_offset, then 8 uint32s the original
               packer left behind (always the same values; kept verbatim)
    data       member payloads, starting at 0x38
    directory  file_count records of
               group:uint32 name_len:uint8 name[name_len]
               offset:uint32 packed_size:uint32 size:uint32
    groups     group_count records of name_len:uint8 name[name_len]

A member is zlib-compressed when ``packed_size < size``, otherwise stored.
``group`` is 0 for ungrouped members, or a 1-based index into the group
names (the packer's folders, e.g. "ISDF Buildings").
"""

from __future__ import annotations

import os
import struct
import zlib
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Callable, Iterable, List, Optional, Tuple, Union

__all__ = ["PAKError", "PAKEntry", "PAKArchive", "PAKHeader", "write_pak", "files_in_folder", "MAGIC"]

MAGIC = b"DOCP"
VERSION = 2
HEADER = struct.Struct("<4s5I8I")
# the trailing header words every stock pak carries (addresses from the tool that made them)
RESERVED = (0x00406D22, 0, 0x008D4240, 0x23, 1, 0x00417168, 0x23, 0x0040578D)


class PAKError(ValueError):
    """The file is not a readable PAK archive, or a member cannot be decoded."""


@dataclass(frozen=True)
class PAKHeader:
    version: int
    group_count: int
    groups_offset: int
    file_count: int
    directory_offset: int
    reserved: Tuple[int, ...]

    @property
    def format(self) -> str:
        return f"DOCP v{self.version}"


@dataclass
class PAKEntry:
    name: str
    offset: int
    packed_size: int
    size: int
    group: int = 0
    group_name: str = ""
    index: int = 0

    @property
    def compressed(self) -> bool:
        return self.packed_size < self.size

    @property
    def method(self) -> str:
        return "zlib" if self.compressed else "Raw"

    @property
    def extension(self) -> str:
        return os.path.splitext(self.name)[1].lower()

    @property
    def path(self) -> str:
        """``group/name`` for grouped members, else just the name."""
        return f"{self.group_name}/{self.name}" if self.group_name else self.name


def _read_exact(f: BinaryIO, n: int, what: str) -> bytes:
    data = f.read(n)
    if len(data) != n:
        raise PAKError(f"PAK {what} is truncated.")
    return data


def _read_name(f: BinaryIO, what: str) -> str:
    length = _read_exact(f, 1, what)[0]
    return _read_exact(f, length, what).decode("latin-1")


class PAKArchive:
    def __init__(self, path: Union[str, os.PathLike]):
        self.path = Path(path)
        self.warnings: List[str] = []
        with open(self.path, "rb") as f:
            f.seek(0, os.SEEK_END)
            file_size = f.tell()
            f.seek(0)
            raw = f.read(HEADER.size)
            if len(raw) < HEADER.size or raw[:4] != MAGIC:
                raise PAKError(f"Not a Battlezone II PAK archive (signature {raw[:4].hex(' ')}).")
            fields = HEADER.unpack(raw)
            h = self.header = PAKHeader(*fields[1:6], tuple(fields[6:]))
            if h.version != VERSION:
                self.warnings.append(f"Unexpected PAK version {h.version}; reading as version {VERSION}.")
            if h.directory_offset > file_size or h.groups_offset > file_size:
                raise PAKError("PAK directory lies outside the file.")
            if h.file_count > 1_000_000 or h.group_count > 65536:
                raise PAKError(f"Invalid PAK counts: {h.file_count} files, {h.group_count} groups.")

            f.seek(h.groups_offset)
            self.groups = [_read_name(f, "group table") for _ in range(h.group_count)]

            f.seek(h.directory_offset)
            self.entries: List[PAKEntry] = []
            for i in range(h.file_count):
                group = struct.unpack("<I", _read_exact(f, 4, "directory"))[0]
                name = _read_name(f, "directory")
                offset, packed, size = struct.unpack("<3I", _read_exact(f, 12, "directory"))
                group_name = ""
                if group:
                    if group <= len(self.groups):
                        group_name = self.groups[group - 1]
                    else:
                        self.warnings.append(f"{name}: unknown group {group}")
                if offset + packed > file_size:
                    self.warnings.append(f"{name}: data runs past the end of the file")
                self.entries.append(PAKEntry(name, offset, packed, size, group, group_name, i))
        self._by_name = {}
        for entry in self.entries:
            self._by_name.setdefault(entry.name.lower(), entry)
            self._by_name.setdefault(entry.path.lower(), entry)

    def __len__(self) -> int:
        return len(self.entries)

    def __iter__(self):
        return iter(self.entries)

    def get(self, name: str) -> Optional[PAKEntry]:
        return self._by_name.get(name.replace("\\", "/").lower())

    def read(self, entry: Union[PAKEntry, str]) -> bytes:
        """The member's original bytes."""
        if isinstance(entry, str):
            found = self.get(entry)
            if found is None:
                raise KeyError(entry)
            entry = found
        with open(self.path, "rb") as f:
            f.seek(entry.offset)
            data = f.read(entry.packed_size)
        if len(data) != entry.packed_size:
            raise PAKError(f"{entry.name}: data is truncated")
        if entry.compressed:
            try:
                data = zlib.decompress(data)
            except zlib.error as exc:
                raise PAKError(f"{entry.name}: {exc}") from exc
        if len(data) != entry.size:
            raise PAKError(f"{entry.name}: unpacked {len(data)} bytes, directory says {entry.size}")
        return data

    def extract(self, entries: Optional[Iterable[Union[PAKEntry, str]]], out_dir: Union[str, os.PathLike],
                progress: Optional[Callable[[int, int, str], None]] = None,
                cancel: Optional[Callable[[], bool]] = None, use_groups: bool = False) -> List[Path]:
        """Extract ``entries`` (all when None) into ``out_dir``; with ``use_groups``
        grouped members go into a subfolder named after their group."""
        chosen = list(self.entries if entries is None else entries)
        out = Path(out_dir)
        out.mkdir(parents=True, exist_ok=True)
        written = []
        for i, entry in enumerate(chosen, 1):
            if cancel and cancel():
                break
            if isinstance(entry, str):
                found = self.get(entry)
                if found is None:
                    raise KeyError(entry)
                entry = found
            folder = out
            if use_groups and entry.group_name:
                folder = out / _safe_component(entry.group_name)
                folder.mkdir(exist_ok=True)
            target = folder / _safe_component(entry.name)  # never escape out_dir
            target.write_bytes(self.read(entry))
            written.append(target)
            if progress:
                progress(i, len(chosen), entry.name)
        return written

    def verify(self, progress: Optional[Callable[[int, int, str], None]] = None) -> List[str]:
        """Decode every member; returns problems found (empty when all is well)."""
        problems = list(self.warnings)
        for i, entry in enumerate(self.entries, 1):
            try:
                self.read(entry)
            except PAKError as exc:
                problems.append(str(exc))
            if progress:
                progress(i, len(self.entries), entry.name)
        return problems


def _safe_component(name: str) -> str:
    part = Path(name.replace("\\", "/")).name
    return part if part not in ("", ".", "..") else "_"


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------

Source = Union[str, os.PathLike, Tuple[str, bytes], Tuple[str, str, bytes]]


def files_in_folder(folder: Union[str, os.PathLike]) -> List[Tuple[str, Path]]:
    """``(group, path)`` for every file in ``folder``: files directly inside are
    ungrouped, files in a first-level subfolder belong to that folder's group."""
    root = Path(folder)
    found = []
    for path in root.rglob("*"):
        if path.is_file():
            rel = path.relative_to(root).parts
            found.append(("" if len(rel) == 1 else rel[0], path))
    return sorted(found, key=lambda item: (item[0].lower(), item[1].name.lower()))


def write_pak(path: Union[str, os.PathLike], sources: Iterable, compress: bool = True, level: int = 9,
              progress: Optional[Callable[[int, int, str], None]] = None,
              cancel: Optional[Callable[[], bool]] = None) -> List[PAKEntry]:
    """Write a DOCP archive.

    ``sources`` are file paths, ``(group, path)`` pairs (as from
    :func:`files_in_folder`), or ``(group, name, data)`` triples; group ""
    means ungrouped. Members are zlib-compressed when that makes them smaller.
    """
    items: List[Tuple[str, str, Union[Path, bytes]]] = []
    for source in sources:
        if isinstance(source, tuple) and len(source) == 3:
            items.append((source[0], source[1], bytes(source[2])))
        elif isinstance(source, tuple):
            items.append((source[0], Path(source[1]).name, Path(source[1])))
        else:
            items.append(("", Path(source).name, Path(source)))

    groups: List[str] = []
    seen = {}
    for group, name, _ in items:
        for text in (group, name):
            if len(text.encode("latin-1", errors="replace")) > 255:
                raise PAKError(f"{text!r}: PAK names are limited to 255 characters")
        if group and group not in groups:
            groups.append(group)
        key = name.lower()
        if key in seen:
            raise PAKError(f"{name!r}: duplicate name (also in {seen[key] or 'no group'!r})")
        seen[key] = group

    target = Path(path)
    tmp = target.with_name(target.name + ".tmp")
    entries: List[PAKEntry] = []
    try:
        with open(tmp, "wb") as f:
            f.write(b"\x00" * HEADER.size)
            for i, (group, name, source) in enumerate(items):
                if cancel and cancel():
                    raise InterruptedError("cancelled")
                raw = source.read_bytes() if isinstance(source, Path) else source
                payload = raw
                if compress and raw:
                    packed = zlib.compress(raw, level)
                    if len(packed) < len(raw):
                        payload = packed
                group_index = groups.index(group) + 1 if group else 0
                entries.append(PAKEntry(name, f.tell(), len(payload), len(raw), group_index, group, i))
                f.write(payload)
                if progress:
                    progress(i + 1, len(items), name)

            directory_offset = f.tell()
            for e in entries:
                encoded = e.name.encode("latin-1", errors="replace")
                f.write(struct.pack("<IB", e.group, len(encoded)) + encoded)
                f.write(struct.pack("<3I", e.offset, e.packed_size, e.size))
            groups_offset = f.tell()
            for group in groups:
                encoded = group.encode("latin-1", errors="replace")
                f.write(struct.pack("<B", len(encoded)) + encoded)

            f.seek(0)
            f.write(HEADER.pack(MAGIC, VERSION, len(groups), groups_offset, len(entries),
                                directory_offset, *RESERVED))
        os.replace(tmp, target)
    finally:
        if tmp.exists():
            tmp.unlink()
    return entries
