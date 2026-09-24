"""Read and selectively extract BZ2/BZCC DOCP version 2 PAK members."""
from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath


MAX_MEMBER_SIZE = 512 * 1024 * 1024


def safe_member_name(name: str) -> str:
    normalized = name.replace("\\", "/")
    path = PureWindowsPath(name)
    parts = normalized.split("/")
    if (not normalized or path.is_absolute() or path.drive or normalized.startswith("/")
            or any(part in ("", ".", "..") or ":" in part for part in parts)):
        raise ValueError(f"Unsafe PAK member path: {name!r}")
    return normalized


@dataclass(frozen=True)
class PakEntry:
    name: str
    offset: int
    stored_size: int
    size: int


class PakArchive:
    """Index one DOCP archive; member data is loaded only on request."""

    def __init__(self, path: str | Path):
        self.path = Path(path).resolve()
        file_size = self.path.stat().st_size
        with self.path.open("rb") as stream:
            header = stream.read(56)
            if len(header) != 56 or header[:4] != b"DOCP":
                raise ValueError(f"Not a BZ2/BZCC DOCP PAK: {self.path}")
            version, directory_count, records_end, file_count, toc_offset = struct.unpack_from(
                "<IIIII", header, 4)
            if version != 2 or not 56 <= toc_offset <= records_end <= file_size:
                raise ValueError(f"Unsupported or damaged PAK header: {self.path}")
            if file_count > 1_000_000 or directory_count > 65535:
                raise ValueError(f"Unreasonable PAK directory size: {self.path}")
            stream.seek(toc_offset)
            records = []
            for _ in range(file_count):
                prefix = stream.read(5)
                if len(prefix) != 5 or stream.tell() > records_end:
                    raise ValueError(f"Truncated PAK file table: {self.path}")
                directory_id, name_length = struct.unpack("<IB", prefix)
                name_bytes = stream.read(name_length)
                sizes = stream.read(12)
                if len(name_bytes) != name_length or len(sizes) != 12 or stream.tell() > records_end:
                    raise ValueError(f"Truncated PAK file record: {self.path}")
                offset, stored_size, size = struct.unpack("<III", sizes)
                if (directory_id > directory_count or offset < 56
                        or offset + stored_size > toc_offset or size > MAX_MEMBER_SIZE):
                    raise ValueError(f"Invalid PAK member bounds: {self.path}")
                records.append((directory_id, name_bytes.decode("cp1252"), offset, stored_size, size))
            if stream.tell() != records_end:
                raise ValueError(f"PAK file table length mismatch: {self.path}")
            directories = [""]
            for _ in range(directory_count):
                length_bytes = stream.read(1)
                if not length_bytes:
                    raise ValueError(f"Truncated PAK directory table: {self.path}")
                value = stream.read(length_bytes[0])
                if len(value) != length_bytes[0]:
                    raise ValueError(f"Truncated PAK directory name: {self.path}")
                directories.append(safe_member_name(value.decode("cp1252")))
            if stream.tell() != file_size:
                raise ValueError(f"PAK directory table length mismatch: {self.path}")

        self.members: dict[str, PakEntry] = {}
        for directory_id, filename, offset, stored_size, size in records:
            name = safe_member_name(
                f"{directories[directory_id]}/{filename}" if directory_id else filename)
            key = name.casefold()
            if key in self.members:
                raise ValueError(f"Duplicate PAK member {name!r}: {self.path}")
            self.members[key] = PakEntry(name, offset, stored_size, size)

    def get(self, name: str) -> PakEntry | None:
        return self.members.get(safe_member_name(name).casefold())

    def read(self, name: str) -> bytes:
        entry = self.get(name)
        if entry is None:
            raise FileNotFoundError(f"{name!r} not found in {self.path}")
        with self.path.open("rb") as stream:
            stream.seek(entry.offset)
            stored = stream.read(entry.stored_size)
        if len(stored) != entry.stored_size:
            raise ValueError(f"Truncated PAK member {entry.name!r}")
        if entry.stored_size == entry.size:
            data = stored
        else:
            decoder = zlib.decompressobj()
            try:
                data = decoder.decompress(stored, entry.size + 1)
            except zlib.error as exc:
                raise ValueError(f"Damaged PAK member {entry.name!r}") from exc
            if not decoder.eof or decoder.unused_data or decoder.unconsumed_tail:
                raise ValueError(f"Damaged or oversized PAK member {entry.name!r}")
        if len(data) != entry.size:
            raise ValueError(f"PAK member size mismatch for {entry.name!r}")
        return data

    def extract(self, name: str, output_dir: str | Path) -> Path:
        entry = self.get(name)
        if entry is None:
            raise FileNotFoundError(f"{name!r} not found in {self.path}")
        root = Path(output_dir).resolve()
        target = (root / entry.name).resolve()
        if not target.is_relative_to(root):
            raise ValueError(f"PAK member escapes output folder: {entry.name!r}")
        data = self.read(entry.name)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return target
