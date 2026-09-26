"""Version-aware Battlezone 1 BZN reader and writer (Battlezone 1.5 and Redux).

This is a Python port of the Battlezone (BZ1) half of BZNParser by John
"Nielk1" Klein (MIT licence; see THIRD_PARTY_NOTICES.md): the token layer of
``BZNStreamReader``/``BZNStreamWriter`` and the version-gated ``Hydrate`` /
``Dehydrate`` pairs of ``BZNFileBattlezone``, ``EntityDescriptor``,
``AiCmdInfo``, ``AreaOfInterest``, ``AiPath`` and every ``GameObject`` class
registered for ``BZNFormat.Battlezone``. BZ2/BZCC and N64 branches are not
ported; Battlezone versions before 1022 (no ``binarySave`` header) are refused.

The C# code keeps a reader and a writer per class. Here each class is one
*schema* function that walks its fields in file order through an ``io``
object; :class:`_Reader` fills a field table from a file, :class:`_Writer`
emits the table at any version. The ``io.version`` gates are copied from the
C# ``reader.Version``/``writer.Version`` gates, so a field that exists only in
some versions is read, written, added or dropped exactly where BZNParser does.

What the writer does with a field it cannot place is not decided here: every
default it had to invent, every field the target version has no slot for and
every type change is recorded in a :class:`WriteReport`, and
:mod:`battlezone.bzn.version_convert` decides what is acceptable.
"""

from __future__ import annotations

import math
import os
import re
import struct
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

# --- binary field types (BZNParser Types.cs BinaryFieldType) ----------------
DATA_VOID = 0
DATA_BOOL = 1
DATA_CHAR = 2
DATA_SHORT = 3
DATA_LONG = 4
DATA_FLOAT = 5
DATA_DOUBLE = 6
DATA_ID = 7
DATA_PTR = 8
DATA_VEC3D = 9
DATA_VEC2D = 10
DATA_MAT3DOLD = 11

MIN_VERSION = 1022          # first version with binarySave/msn_filename
REDUX_MIN_VERSION = 2000    # 20xx versions are Redux; 10xx are 1.x
LUA_MISSIONS = frozenset({"LuaMission", "MultSTMission", "MultDMMission", "Inst4XMission", "Inst03Mission"})
# Fields that record play state, not map content: dropping them is never a loss.
# LuaMission's "started" flag exists in 1044 maps only; the six "last shot /
# collided at" timestamps left the mission format in 1033 (saves keep them).
RUNTIME_STATE = frozenset({"luaMissionStarted", "playerShot", "playerCollide", "friendShot", "friendCollide",
                           "enemyShot", "groundCollide"})

_KIND_TYPE = {
    "bool": DATA_BOOL, "long": DATA_LONG, "ulong": DATA_LONG, "hexlong": DATA_LONG,
    "short": DATA_SHORT, "float": DATA_FLOAT, "id": DATA_ID, "chars": DATA_CHAR,
    "ptr": DATA_PTR, "void": DATA_VOID, "vec3": DATA_VEC3D, "vec2": DATA_VEC2D,
    "mat": DATA_MAT3DOLD,
}
_NEWLINE = b"\r\n"


class BZNError(ValueError):
    """The data is not a BZ1 BZN this module can read, or cannot be written."""


# ---------------------------------------------------------------------------
# numbers
# ---------------------------------------------------------------------------

def f32(value: float) -> float:
    """Round a Python float to the nearest float32, as the game stores it."""
    try:
        return struct.unpack("<f", struct.pack("<f", value))[0]
    except OverflowError:
        return math.copysign(math.inf, value)


def format_g6(value: float) -> str:
    """Text for a float32 in ASCII BZNs.

    Port of BZNParser ``SingleExtension.FormatG6``: C ``%g`` with six
    significant digits evaluated on the exact float32 value, halves rounded
    away from zero, three-digit exponents (``5.96046e-008``), and the MSVC
    spellings for non-finite values.
    """
    if math.isnan(value):
        return "-1.#QNAN"
    if math.isinf(value):
        return "-inf" if value < 0 else "inf"
    bits = struct.unpack("<I", struct.pack("<f", value))[0]
    sign, exponent, mantissa = bits >> 31, (bits >> 23) & 0xFF, bits & 0x7FFFFF
    if exponent == 0 and mantissa == 0:
        return "-0" if sign else "0"
    if exponent == 0:
        num, exp2 = mantissa, -149
    else:
        num, exp2 = (1 << 23) | mantissa, exponent - 150
    den = 1
    if exp2 >= 0:
        num <<= exp2
    else:
        den <<= -exp2
    exp10 = 0
    while num >= den * 10:
        den *= 10
        exp10 += 1
    while num < den:
        num *= 10
        exp10 -= 1
    digits = []
    for _ in range(6):
        digit = num // den
        digits.append(int(digit))
        num = (num % den) * 10
    if num * 2 >= den * 10:
        i = 5
        while i >= 0:
            if digits[i] != 9:
                digits[i] += 1
                break
            digits[i] = 0
            i -= 1
        if i < 0:
            digits = [1, 0, 0, 0, 0, 0]
            exp10 += 1
    text = "".join(str(d) for d in digits)
    if exp10 < -4 or exp10 >= 6:
        mant = text[0] + ("." + text[1:]).rstrip("0").rstrip(".")
        body = f"{mant}e{'+' if exp10 >= 0 else '-'}{abs(exp10):03d}"
    else:
        point = exp10 + 1
        if point <= 0:
            body = "0." + "0" * -point + text
        elif point >= 6:
            body = text + "0" * (point - 6)
        else:
            body = text[:point] + "." + text[point:]
        if "." in body:
            body = body.rstrip("0").rstrip(".")
    return "-" + body if sign else body


def _parse_float(text: str) -> float:
    s = text.strip()
    if s == "":
        return 0.0
    upper = s.upper()
    if "#QNAN" in upper or "#IND" in upper or upper in ("NAN", "-NAN"):
        return math.nan
    if "#INF" in upper or upper in ("INF", "-INF", "+INF"):
        return -math.inf if s.startswith("-") else math.inf
    return f32(float(s))


def _parse_bool(text: str) -> bool:
    s = text.strip()
    if s in ("0", "00000000"):
        return False
    if s in ("1", "00000001"):
        return True
    lowered = s.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    raise BZNError(f"not a boolean: {text!r}")


def _parse_hex(text: str) -> int:
    s = text.strip()
    try:
        return int(s, 16)
    except ValueError as exc:
        raise BZNError(f"not a hexadecimal value: {text!r}") from exc


def _parse_int(text: str) -> int:
    try:
        return int(text.strip())
    except ValueError as exc:
        raise BZNError(f"not an integer: {text!r}") from exc


# ---------------------------------------------------------------------------
# fields
# ---------------------------------------------------------------------------

@dataclass
class Field:
    """One stored value.

    ``value`` is the decoded value (see :data:`KIND_DEFAULTS` for the shape of
    each kind). ``text`` keeps the ASCII spelling of every scalar component
    and ``raw`` the binary payload, so a file rewritten at its own version and
    format comes out byte-identical; other targets are formatted canonically.
    """

    kind: str
    value: Any
    text: Optional[List[str]] = None
    raw: Optional[bytes] = None
    name: str = ""
    # spelling details a same-format rewrite reproduces: the binary type word
    # (some 1.5 files carry garbage in its high byte) and ASCII "name =" lines
    # written without the trailing space
    type_word: Optional[int] = None
    euler_words: Optional[list] = None
    trimmed: bool = False


def _identity_matrix() -> tuple:
    return (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0)


def default_value(kind: str, *, count: int = 1, size: int = 4):
    if kind == "bool":
        return False
    if kind in ("long", "ulong", "hexlong", "short", "ptr"):
        return 0
    if kind == "float":
        return 0.0
    if kind in ("id", "chars"):
        return b""
    if kind == "void":
        return bytes(size)
    if kind == "vec3":
        return [(0.0, 0.0, 0.0)] * count
    if kind == "vec2":
        return [(0.0, 0.0)] * count
    if kind == "mat":
        return _identity_matrix()
    if kind == "euler":
        return (0.0,) * 15
    raise KeyError(kind)


def is_default(f: Field) -> bool:
    value = f.value
    if f.kind == "void":
        return not any(value)
    if f.kind in ("vec3", "vec2", "euler"):
        flat = value if f.kind == "euler" else [c for v in value for c in v]
        return all(c == 0 for c in flat)
    if f.kind == "mat":
        return tuple(value) == _identity_matrix()
    return value == default_value(f.kind)


def describe_value(f: Field) -> str:
    v = f.value
    if f.kind in ("id", "chars"):
        return repr(v.decode("latin-1"))
    if f.kind == "void":
        return v.hex().upper()
    if f.kind in ("ptr", "hexlong"):
        return f"0x{v:08X}"
    if f.kind == "float":
        return format_g6(v)
    if f.kind in ("vec3", "vec2"):
        return "; ".join("(" + ", ".join(format_g6(c) for c in vec) + ")" for vec in v)
    if f.kind in ("mat", "euler"):
        return "(" + ", ".join(format_g6(c) for c in v) + ")"
    return str(v)


# ---------------------------------------------------------------------------
# the byte stream
# ---------------------------------------------------------------------------

class _Stream:
    def __init__(self, data: bytes):
        self.data = data
        self.pos = 0
        self.binary_start: Optional[int] = None

    @property
    def in_binary(self) -> bool:
        return self.binary_start is not None and self.pos >= self.binary_start

    def eof(self) -> bool:
        return self.pos >= len(self.data)

    def line(self) -> str:
        data = self.data
        if self.pos >= len(data):
            raise BZNError("unexpected end of file")
        end = data.find(b"\n", self.pos)
        if end < 0:
            raw, self.pos = data[self.pos:], len(data)
        else:
            raw, self.pos = data[self.pos:end], end + 1
        return raw.rstrip(b"\r").decode("latin-1")

    def next_nonempty_line(self) -> str:
        while True:
            text = self.line()
            if text != "":
                return text

    def token(self) -> Tuple[int, bytes]:
        dtype, payload, _ = self.token_word()
        return dtype, payload

    def token_word(self) -> Tuple[int, bytes, int]:
        data = self.data
        if self.pos + 4 > len(data):
            raise BZNError("unexpected end of binary data")
        type_word, size = struct.unpack_from("<HH", data, self.pos)
        start = self.pos + 4
        if start + size > len(data):
            raise BZNError("binary token runs past the end of the file")
        self.pos = start + size
        return type_word & 0xFF, data[start:start + size], type_word


def _name_matches(expected: str, got: str) -> bool:
    got = got.strip()
    if got == expected:
        return True
    # BZNTokenString.MatchesAllButOne: a one-character typo in the file
    if len(got) != len(expected) - 1:
        return False
    return any(expected[:i] + expected[i + 1:] == got for i in range(len(expected)))


def _split_header(line: str):
    """``name [N] =`` -> ('multi', name, N); ``name = value`` -> ('one', name, value)."""
    if not line.endswith(" =") and " = " not in line and "=" in line:
        line = line.replace("=", " = ")            # BZNStreamReader's "fucky wucky" repair
    stripped = line.lstrip(" ")
    parts = stripped.split(" ", 3)
    if len(parts) >= 2 and parts[1] == "=":
        rest = stripped.split(" ", 2)
        return "one", parts[0], (rest[2] if len(rest) > 2 else "")
    if len(parts) >= 3 and parts[2] == "=" and parts[1].startswith("[") and parts[1].endswith("]"):
        try:
            return "multi", parts[0], int(parts[1][1:-1])
        except ValueError:
            return None
    return None


_LOOKS_LIKE_HEADER = re.compile(r"^\s*[^\s=\[]+\s*(\[\d+\])?\s*=(\s.*)?$")


# ---------------------------------------------------------------------------
# the walker: one schema function per class drives both directions
# ---------------------------------------------------------------------------

class _Walk:
    reading = False

    def __init__(self, version: int, save: bool):
        self.version = version
        self.save = save
        self.obj: Dict[str, Field] = {}

    @property
    def ptr_size(self) -> int:
        return 8 if self.version >= 2012 else 4

    @contextmanager
    def scope(self, fields: Dict[str, Field], context: str = ""):
        saved = self.obj, getattr(self, "context", "")
        self.obj, self.context = fields, context
        try:
            yield fields
        finally:
            self.obj, self.context = saved

    # every schema call funnels into _field(kind, name, key, **options)
    def bool(self, name, key=None, **kw): return self._field("bool", name, key, **kw)
    def long(self, name, key=None, **kw): return self._field("long", name, key, **kw)
    def ulong(self, name, key=None, **kw): return self._field("ulong", name, key, **kw)
    def hexlong(self, name, key=None, **kw): return self._field("hexlong", name, key, **kw)
    def short(self, name, key=None, **kw): return self._field("short", name, key, **kw)
    def float(self, name, key=None, **kw): return self._field("float", name, key, **kw)
    def id(self, name, key=None, **kw): return self._field("id", name, key, **kw)
    def chars(self, name, key=None, size=None, **kw): return self._field("chars", name, key, size=size, **kw)
    def ptr(self, name, key=None, **kw): return self._field("ptr", name, key, **kw)
    def void(self, name, key=None, case="U", **kw): return self._field("void", name, key, case=case, **kw)
    def vec3(self, name, key=None, count=1, **kw): return self._field("vec3", name, key, count=count, **kw)
    def vec2(self, name, key=None, count=None, **kw): return self._field("vec2", name, key, count=count, **kw)
    def mat(self, name, key=None, **kw): return self._field("mat", name, key, **kw)
    def euler(self, name, key=None, **kw): return self._field("euler", name, key, **kw)

    def _field(self, kind, name, key, **kw):   # pragma: no cover - abstract
        raise NotImplementedError

    def validation(self, name: str) -> None:    # pragma: no cover - abstract
        raise NotImplementedError

    def count(self, name: str, key: str, value: int = 0) -> int:  # pragma: no cover - abstract
        raise NotImplementedError


# ---------------------------------------------------------------------------
# reader
# ---------------------------------------------------------------------------

class _Reader(_Walk):
    reading = True

    def __init__(self, stream: _Stream, version: int, save: bool):
        super().__init__(version, save)
        self.stream = stream

    def fail(self, message: str):
        raise BZNError(f"{message} (offset {self.stream.pos})")

    # -- ASCII helpers ------------------------------------------------------
    def _ascii_header(self, name: str, alts: Sequence[str] = ()):
        line = self.stream.next_nonempty_line()
        self.last_line = line
        parsed = _split_header(line)
        if parsed is None:
            self.fail(f"expected {name}, found {line!r}")
        form, got, extra = parsed
        if not (_name_matches(name, got) or any(_name_matches(a, got) for a in alts)):
            self.fail(f"expected {name}, found {got!r}")
        return form, got.strip(), extra

    def _ascii_values(self, name: str, kind: str, alts=()) -> Tuple[str, List[str]]:
        form, got, extra = self._ascii_header(name, alts)
        if form != "multi":
            self.fail(f"{name}: expected '{name} [n] =', found a one-line field")
        values = []
        for _ in range(extra):
            mark = self.stream.pos
            text = self.stream.line()
            if kind == "float" and _LOOKS_LIKE_HEADER.match(text):
                # buggy printed vectors: the value is missing, the next field follows
                self.stream.pos = mark
                text = ""
            values.append(text)
        return got, values

    def _ascii_oneliner(self, name: str, alts=()) -> Tuple[str, str]:
        form, got, extra = self._ascii_header(name, alts)
        if form != "one":
            self.fail(f"{name}: expected '{name} = value'")
        self.last_trimmed = extra == "" and not self.last_line.endswith("= ")
        return got, extra

    def _ascii_sub_floats(self, names: Sequence[str]) -> List[str]:
        texts = []
        for sub in names:
            _, values = self._ascii_values(sub, "float")
            if len(values) != 1:
                self.fail(f"{sub}: expected one value")
            texts.append(values[0])
        return texts

    # -- binary helpers -----------------------------------------------------
    def _bin(self, name: str, dtype: int) -> bytes:
        mark = self.stream.pos
        got, payload, word = self.stream.token_word()
        if got != dtype:
            self.stream.pos = mark
            self.fail(f"{name}: expected binary type {dtype}, found {got}")
        self.last_type_word = word
        return payload

    # -- the walker ----------------------------------------------------------
    def _field(self, kind, name, key, **kw):
        key = key or name
        if self.stream.in_binary:
            f = self._read_binary(kind, name, **kw)
            if kind != "euler" and self.last_type_word != _KIND_TYPE.get(kind):
                f.type_word = self.last_type_word
        else:
            f = self._read_ascii(kind, name, **kw)
        self.obj[key] = f
        return f.value

    def _read_ascii(self, kind, name, **kw) -> Field:
        alts = kw.get("alts", ())
        if kind in ("bool", "long", "ulong", "hexlong", "short", "float", "id"):
            got, values = self._ascii_values(name, kind, alts)
            if len(values) != 1:
                self.fail(f"{name}: expected one value, found {len(values)}")
            text = values[0]
            if kind == "bool":
                value = _parse_bool(text)
            elif kind == "long":
                value = _parse_int(text)
                if not -0x80000000 <= value <= 0xFFFFFFFF:
                    self.fail(f"{name}: {text!r} is out of range")
                value = value - 0x100000000 if value > 0x7FFFFFFF else value
            elif kind == "ulong":
                value = _parse_int(text) & 0xFFFFFFFF
            elif kind == "hexlong":
                value = _parse_hex(text)
                if value > 0xFFFFFFFF:     # GetUInt32H's decimal fallback
                    value = _parse_int(text) & 0xFFFFFFFF
            elif kind == "short":
                value = _parse_int(text) & 0xFFFF
            elif kind == "float":
                value = _parse_float(text)
            else:
                value = text.encode("latin-1")
            return Field(kind, value, [text], None, got)
        if kind in ("chars", "ptr", "void"):
            got, text = self._ascii_oneliner(name, alts)
            if kind == "chars":
                value = text.encode("latin-1").split(b"\0", 1)[0]
            elif kind == "ptr":
                value = _parse_hex(text) if text.strip() else 0
            else:
                hex_text = text.strip()
                if len(hex_text) % 2:
                    hex_text = "0" + hex_text
                try:
                    value = bytes.fromhex(hex_text)
                except ValueError:
                    self.fail(f"{name}: {text!r} is not hexadecimal")
            return Field(kind, value, [text], None, got, trimmed=self.last_trimmed)
        if kind in ("vec3", "vec2"):
            got, count = self._vector_header(name)
            subs = ("x", "y", "z") if kind == "vec3" else ("x", "z")
            texts = []
            for _ in range(count):
                texts += self._ascii_sub_floats(subs)
            floats = [_parse_float(t) for t in texts]
            n = len(subs)
            value = [tuple(floats[i:i + n]) for i in range(0, len(floats), n)]
            expected = kw.get("count")
            if expected is not None and len(value) != expected:
                self.fail(f"{name}: expected {expected} vectors, found {len(value)}")
            return Field(kind, value, texts, None, got)
        if kind == "mat":
            got, count = self._vector_header(name)
            if count != 1:
                self.fail(f"{name}: expected one matrix")
            texts = self._ascii_sub_floats(("right_x", "right_y", "right_z", "up_x", "up_y", "up_z",
                                            "front_x", "front_y", "front_z", "posit_x", "posit_y", "posit_z"))
            return Field(kind, tuple(_parse_float(t) for t in texts), texts, None, got)
        if kind == "euler":
            got, _ = self._ascii_oneliner(name)
            texts = self._ascii_sub_floats(("mass", "mass_inv", "v_mag", "v_mag_inv", "I", "k_i"))
            for sub in ("v", "omega", "Accel"):
                _, count = self._vector_header(sub)
                if count != 1:
                    self.fail(f"euler {sub}: expected one vector")
                texts += self._ascii_sub_floats(("x", "y", "z"))
            return Field(kind, tuple(_parse_float(t) for t in texts), texts, None, got)
        raise KeyError(kind)

    def _vector_header(self, name: str) -> Tuple[str, int]:
        form, got, extra = self._ascii_header(name)
        if form != "multi":
            self.fail(f"{name}: expected '{name} [n] ='")
        return got, extra

    def _read_binary(self, kind, name, **kw) -> Field:
        if kind == "euler":
            parts = []
            raws = []
            words = []
            for _ in range(6):
                payload = self._bin(name, DATA_FLOAT)
                if len(payload) != 4:
                    self.fail(f"{name}: bad float size")
                parts.append(struct.unpack("<f", payload)[0])
                raws.append(payload)
                words.append(self.last_type_word)
            for _ in range(3):
                payload = self._bin(name, DATA_VEC3D)
                if len(payload) != 12:
                    self.fail(f"{name}: bad vector size")
                parts += struct.unpack("<3f", payload)
                raws.append(payload)
                words.append(self.last_type_word)
            f = Field(kind, tuple(parts), None, b"".join(raws), name)
            f.euler_words = words
            return f
        payload = self._bin(name, _KIND_TYPE[kind])
        size = len(payload)
        if kind == "bool":
            if size != 1:
                self.fail(f"{name}: bad BOOL size {size}")
            value = payload[0] != 0
        elif kind in ("long", "ulong", "hexlong"):
            if size != 4:
                self.fail(f"{name}: bad LONG size {size}")
            value = struct.unpack("<i" if kind == "long" else "<I", payload)[0]
        elif kind == "short":
            if size != 2:
                self.fail(f"{name}: bad SHORT size {size}")
            value = struct.unpack("<H", payload)[0]
        elif kind == "float":
            if size != 4:
                self.fail(f"{name}: bad FLOAT size {size}")
            value = struct.unpack("<f", payload)[0]
        elif kind == "id":
            value = payload.split(b"\0", 1)[0]   # the name; ``raw`` keeps all 8 bytes (param numbers)
        elif kind == "chars":
            value = payload.split(b"\0", 1)[0]
        elif kind == "ptr":
            if size not in (4, 8):
                self.fail(f"{name}: bad PTR size {size}")
            value = int.from_bytes(payload, "little")
        elif kind == "void":
            value = payload
        elif kind in ("vec3", "vec2"):
            n = 3 if kind == "vec3" else 2
            if size % (4 * n):
                self.fail(f"{name}: bad vector size {size}")
            floats = struct.unpack(f"<{size // 4}f", payload)
            value = [tuple(floats[i:i + n]) for i in range(0, len(floats), n)]
            expected = kw.get("count")
            if expected is not None and len(value) != expected:
                self.fail(f"{name}: expected {expected} vectors, found {len(value)}")
        elif kind == "mat":
            if size == 64:
                rot = struct.unpack_from("<9f", payload, 0)
                posit = struct.unpack_from("<3d", payload, 40)
                value = tuple(rot) + tuple(posit)
            elif size == 48:
                value = struct.unpack("<12f", payload)
            else:
                self.fail(f"{name}: bad matrix size {size}")
        else:
            raise KeyError(kind)
        return Field(kind, value, None, payload, name)

    def validation(self, name: str) -> None:
        if self.stream.in_binary:
            return
        line = self.stream.next_nonempty_line()
        if line.strip() != f"[{name}]":
            self.fail(f"expected [{name}], found {line!r}")

    def count(self, name: str, key: str, value: int = 0) -> int:
        return self.long(name, key=key)


# ---------------------------------------------------------------------------
# writer
# ---------------------------------------------------------------------------

@dataclass
class Change:
    """Something the writer had to do that a same-version rewrite would not."""

    action: str             # "added", "dropped", "converted", "unmappable"
    context: str            # "header", "object 12 avtank (seq 105, label ...)", ...
    key: str
    detail: str
    lossy: bool = False     # a non-default value was lost or altered


@dataclass
class WriteReport:
    changes: List[Change] = field(default_factory=list)

    def add(self, *args, **kw) -> None:
        self.changes.append(Change(*args, **kw))

    @property
    def lossy(self) -> List[Change]:
        return [c for c in self.changes if c.lossy]


class _Unmappable(Exception):
    pass


def _convert_field(f: Field, kind: str, *, size: Optional[int] = None,
                   obj: Optional[Dict[str, Field]] = None, binary: bool = False) -> Tuple[Field, bool, str]:
    """Carry a value across a type change between versions.

    Returns ``(field, lossless, description)``; raises :class:`_Unmappable`
    when the value has no counterpart.
    """
    value = f.value
    # AiCmdInfo.param: LONG before 2012, an 8-byte ID from 2012. BZNParser keeps
    # it as one UInt64, i.e. the ID bytes read little-endian.
    if f.kind in ("ulong", "long") and kind == "id":
        raw = (value & 0xFFFFFFFF).to_bytes(8, "little")
        name = raw.split(b"\0", 1)[0]
        if not binary and raw.rstrip(b"\0") != name:
            # ASCII spells an ID as text up to its first zero byte
            raise _Unmappable(f"LONG {value & 0xFFFFFFFF} has a zero byte inside its ID bytes, which ASCII cannot spell")
        return Field(kind, name, raw=raw), True, f"LONG {value & 0xFFFFFFFF} -> ID bytes {raw.rstrip(b'\0').hex() or '(empty)'}"
    if f.kind == "id" and kind in ("ulong", "long"):
        source = f.raw if f.raw is not None else value
        number = int.from_bytes(source[:8].ljust(8, b"\0"), "little")
        if len(source.rstrip(b"\0")) > 8 or number > 0xFFFFFFFF:
            raise _Unmappable(f"ID {value.decode('latin-1')!r} does not fit a 32-bit LONG")
        return Field(kind, number), True, f"ID bytes {source.rstrip(b'\0').hex() or '(empty)'} -> LONG {number}"
    if f.kind == "void" and kind == "ptr":              # AiPath.old_ptr, <= 2011 VOID vs > 2011 PTR
        return Field(kind, int.from_bytes(value[:8], "little")), True, "VOID bytes -> PTR"
    if f.kind == "ptr" and kind == "void":
        width = size or 4
        if value >= 1 << (8 * width):
            raise _Unmappable(f"pointer 0x{value:X} does not fit {width} bytes")
        return Field(kind, value.to_bytes(width, "little")), True, "PTR -> VOID bytes"
    if f.kind == "bool" and kind == "id":               # GameObject: hasPilot before 1030, curPilot after
        if not value:
            return Field(kind, b""), True, "hasPilot false -> no curPilot"
        prjid = (obj or {}).get("PrjID")
        is_user = (obj or {}).get("isUser")
        prefix = prjid.value[:1] if prjid is not None else b""
        pilot = prefix + (b"suser" if is_user is not None and is_user.value else b"spilo")
        return Field(kind, pilot), True, f"hasPilot true -> curPilot {pilot.decode('latin-1')} (BZNParser's rule)"
    if f.kind == "id" and kind == "bool":
        return Field(kind, value != b""), True, f"curPilot {value.decode('latin-1')!r} -> hasPilot {str(value != b'').lower()}"
    if {f.kind, kind} <= {"long", "ulong", "hexlong"}:
        return Field(kind, value & 0xFFFFFFFF if kind != "long" else
                     (value - (1 << 32) if value & 0x80000000 else value)), True, f"{f.kind} -> {kind}"
    raise _Unmappable(f"{f.kind} cannot become {kind}")


class _Writer(_Walk):
    def __init__(self, version: int, save: bool, binary: bool, report: WriteReport):
        super().__init__(version, save)
        self.out = bytearray()
        self.binary = False
        self.binary_target = binary
        self.report = report
        self.used: set = set()
        self.context = ""
        self.preserve_spelling = True
        # non-zero defaults for a missing value, from the C# writer and class constructors
        huge = f32(-1e30)                                            # -HUGE_NUMBER: "never happened"
        self.semantic_defaults = {
            "luaMissionStarted": not save,                           # bz1_luamission_started ?? SaveType == BZN
            "perceivedTeam": -1,
            "playerShot": huge, "playerCollide": huge, "friendShot": huge,
            "friendCollide": huge, "enemyShot": huge, "groundCollide": huge,
        }

    def _is_default(self, key: str, f: Field) -> bool:
        if key in RUNTIME_STATE:
            return True
        if key in self.semantic_defaults:
            return f.value == self.semantic_defaults[key]
        return is_default(f)

    @contextmanager
    def scope(self, fields: Dict[str, Field], context: str = "", check: bool = True):
        saved_used = self.used
        self.used = set()
        with super().scope(fields, context):
            try:
                yield fields
            finally:
                for key in (fields if check else ()):
                    if key not in self.used and not key.startswith("#"):
                        f = fields[key]
                        self.report.add("dropped", context, key,
                                        f"{f.kind} {describe_value(f)} has no field at version {self.version}",
                                        lossy=not self._is_default(key, f))
                self.used = saved_used

    # -- emission helpers ----------------------------------------------------
    def _line(self, text) -> None:
        self.out += (text.encode("latin-1") if isinstance(text, str) else text) + _NEWLINE

    def _multi(self, name: str, values: Sequence) -> None:
        self._line(f"{name} [{len(values)}] =")
        for v in values:
            self._line(v)

    def _token(self, dtype: int, payload: bytes, type_word: Optional[int] = None) -> None:
        if len(payload) > 0xFFFF:
            raise BZNError("binary token larger than 64 KiB")
        word = type_word if type_word is not None and type_word & 0xFF == dtype else dtype
        self.out += struct.pack("<HH", word, len(payload)) + payload

    # -- the walker ----------------------------------------------------------
    def _resolve(self, kind, key, **kw) -> Field:
        f = self.obj.get(key)
        if f is None:
            if key in self.semantic_defaults:
                value = self.semantic_defaults[key]
            elif key == "dropMat" and "transform" in self.obj:
                value = self.obj["transform"].value      # ClassConstructionRig1: dropMat = transform
            else:
                value = default_value(kind, count=kw.get("count") or 1, size=4)
            f = Field(kind, value)
            self.report.add("added", self.context, key, f"{kind} default {describe_value(f)} "
                            f"(no value in the source)")
            return f
        self.used.add(key)
        if f.kind == kind:
            return f
        try:
            converted, lossless, how = _convert_field(f, kind, size=4 if kind == "void" else None, obj=self.obj,
                                                      binary=self.binary)
        except _Unmappable as exc:
            fallback = Field(kind, default_value(kind, count=kw.get("count") or 1))
            self.report.add("unmappable", self.context, key, f"{exc}; wrote the default {describe_value(fallback)}",
                            lossy=True)
            return fallback
        self.report.add("converted", self.context, key, how, lossy=not lossless)
        return converted

    def _field(self, kind, name, key, **kw):
        key = key or name
        f = self._resolve(kind, key, **kw)
        if kind == "id" and len(f.value) > 8 and (self.binary or self.version < REDUX_MIN_VERSION):
            # IDs are 8 bytes in binary files and in every 1.x game
            self.report.add("unmappable", self.context, key,
                            f"ID {f.value.decode('latin-1')!r} is longer than the 8 bytes version "
                            f"{self.version}{' binary' if self.binary else ''} can hold; truncated to "
                            f"{f.value[:8].decode('latin-1')!r}", lossy=True)
            f = Field("id", f.value[:8])
        if self.binary:
            self._write_binary(kind, f, key=key, **kw)
        else:
            self._write_ascii(kind, name, f, **kw)
        return f.value

    def _write_ascii(self, kind, name, f: Field, **kw) -> None:
        reuse = self.preserve_spelling and f.text is not None and f.kind == kind
        if kind in ("bool", "long", "ulong", "hexlong", "short", "float", "id"):
            if reuse and len(f.text) == 1:
                text = f.text[0]
            else:
                text = self._format_scalar(kind, f.value)
            self._multi(name, [text])
        elif kind in ("chars", "ptr", "void"):
            if reuse:
                text = f.text[0]
            elif kind == "chars":
                text = f.value
            elif kind == "ptr":
                text = f"{f.value:016X}" if f.value > 0xFFFFFFFF else f"{f.value:08X}"
            else:
                text = f.value.hex()
                text = text.upper() if kw.get("case", "U") == "U" else text.lower()
            if isinstance(text, str):
                text = text.encode("latin-1")
            separator = b" =" if reuse and f.trimmed and not text else b" = "
            self.out += name.encode("latin-1") + separator + text + _NEWLINE
        elif kind in ("vec3", "vec2"):
            subs = ("x", "y", "z") if kind == "vec3" else ("x", "z")
            flat = [c for vec in f.value for c in vec]
            texts = f.text if reuse and len(f.text) == len(flat) else [format_g6(c) for c in flat]
            self._line(f"{name} [{len(f.value)}] =")
            for i, text in enumerate(texts):
                self._line(f"  {subs[i % len(subs)]} [1] =")
                self._line(text)
        elif kind == "mat":
            texts = f.text if reuse and len(f.text) == 12 else [format_g6(c) for c in f.value]
            self._line(f"{name} [1] =")
            for sub, text in zip(("right_x", "right_y", "right_z", "up_x", "up_y", "up_z", "front_x",
                                  "front_y", "front_z", "posit_x", "posit_y", "posit_z"), texts):
                self._line(f"  {sub} [1] =")
                self._line(text)
        elif kind == "euler":
            texts = f.text if reuse and len(f.text) == 15 else [format_g6(c) for c in f.value]
            self._line(f"{name} =")
            for sub, text in zip(("mass", "mass_inv", "v_mag", "v_mag_inv", "I", "k_i"), texts[:6]):
                self._line(f" {sub} [1] =")
                self._line(text)
            for i, sub in enumerate(("v", "omega", "Accel")):
                self._line(f" {sub} [1] =")
                for axis, text in zip("xyz", texts[6 + 3 * i: 9 + 3 * i]):
                    self._line(f"  {axis} [1] =")
                    self._line(text)
        else:
            raise KeyError(kind)

    @staticmethod
    def _format_scalar(kind, value) -> str:
        if kind == "bool":
            return "true" if value else "false"
        if kind == "long":
            return str(value - (1 << 32) if value > 0x7FFFFFFF else value)
        if kind in ("ulong", "short"):
            return str(value)
        if kind == "hexlong":
            return format(value & 0xFFFFFFFF, "x")
        if kind == "float":
            return format_g6(value)
        if kind == "id":
            return value.split(b"\0", 1)[0].decode("latin-1")
        raise KeyError(kind)

    def _write_binary(self, kind, f: Field, **kw) -> None:
        raw = f.raw if f.kind == kind and self.preserve_spelling else None
        if kind == "euler":
            values = f.value
            words = f.euler_words if f.kind == kind and self.preserve_spelling else None
            words = words or [None] * 9
            if raw is not None and len(raw) == 60:
                chunks = [raw[4 * i:4 * i + 4] for i in range(6)] + [raw[24 + 12 * i:36 + 12 * i] for i in range(3)]
            else:
                chunks = [struct.pack("<f", values[i]) for i in range(6)] +                          [struct.pack("<3f", *values[6 + 3 * i: 9 + 3 * i]) for i in range(3)]
            for i, chunk in enumerate(chunks):
                self._token(DATA_FLOAT if i < 6 else DATA_VEC3D, chunk, words[i])
            return
        dtype = _KIND_TYPE[kind]
        value = f.value
        if kind == "bool":
            payload = b"\x01" if value else b"\x00"
        elif kind == "long":
            payload = struct.pack("<i", value - (1 << 32) if value > 0x7FFFFFFF else value)
        elif kind in ("ulong", "hexlong"):
            payload = struct.pack("<I", value & 0xFFFFFFFF)
        elif kind == "short":
            payload = struct.pack("<H", value & 0xFFFF)
        elif kind == "float":
            payload = raw if raw is not None and len(raw) == 4 else struct.pack("<f", value)
        elif kind == "id":
            # an ID's raw bytes are its value (param numbers), not just its spelling
            full = f.raw if f.kind == kind and f.raw is not None and len(f.raw) == 8 else None
            payload = full if full is not None and full.split(b"\0", 1)[0] == value[:8] else value[:8].ljust(8, b"\0")
        elif kind == "chars":
            size = kw.get("size")
            if raw is not None and (size is None or len(raw) == size):
                payload = raw
            elif size is not None:
                if len(value) > size:
                    raise BZNError(f"{value!r} does not fit a {size}-byte field")
                payload = value.ljust(size, b"\0")
            else:
                payload = value
        elif kind == "ptr":
            width = self.ptr_size
            if raw is not None and len(raw) == width:
                payload = raw
            else:
                payload = (value & ((1 << (8 * width)) - 1)).to_bytes(width, "little")
        elif kind == "void":
            payload = value
        elif kind in ("vec3", "vec2"):
            flat = [c for vec in value for c in vec]
            payload = raw if raw is not None and len(raw) == 4 * len(flat) else struct.pack(f"<{len(flat)}f", *flat)
        elif kind == "mat":
            if raw is not None and len(raw) == 64:
                payload = raw
            else:
                payload = struct.pack("<9f", *value[:9]) + b"\0\0\0\0" + struct.pack("<3d", *value[9:])
        else:
            raise KeyError(kind)
        self._token(dtype, payload, f.type_word if f.kind == kind and self.preserve_spelling else None)

    def validation(self, name: str) -> None:
        if not self.binary:
            self._line(f"[{name}]")

    def count(self, name: str, key: str, value: int = 0) -> int:
        """A length prefix: written from the data, spelled like the source if it matches."""
        f = self.obj.get(key)
        if f is None or f.kind != "long" or f.value != value:
            f = Field("long", value)
        if self.binary:
            self._write_binary("long", f)
        else:
            self._write_ascii("long", name, f)
        return value


# ---------------------------------------------------------------------------
# schemas: EntityDescriptor, AiCmdInfo, GameObject and every BZ1 class
# ---------------------------------------------------------------------------

def entity_descriptor(io: _Walk) -> None:
    """``EntityDescriptor.Hydrate``/``Write`` for BZNFormat.Battlezone."""
    io.validation("GameObject")
    io.id("PrjID")
    io.short("seqno")
    io.vec3("pos")
    io.ulong("team")
    io.chars("label", size=40)
    io.ulong("isUser")
    io.ptr("obj_addr")           # version >= 1002 (older versions write raw void bytes)
    io.mat("transform")          # version > 1001


def ai_cmd_info(io: _Walk, prefix: str) -> None:
    """``AiCmdInfoExtensions.GetAiCmdInfo``/``WriteAiCmdInfo`` (BZ1)."""
    io.long("priority", f"{prefix}.priority")
    io.void("what", f"{prefix}.what", case="L")
    io.long("who", f"{prefix}.who")
    io.ptr("where", f"{prefix}.where")
    if io.version >= 2012:
        io.id("param", f"{prefix}.param")
    else:
        io.ulong("param", f"{prefix}.param")


def game_object(io: _Walk) -> None:
    v = io.version
    io.float("illumination")
    io.vec3("pos", "pos2")
    io.euler("euler")
    io.ulong("seqNo")
    if v > 1030:
        io.chars("name", size=32)
    if (1046 <= v < 2000) or v >= 2010:
        io.bool("isCritical")
    if v <= 1017:
        io.ulong("liveColor")
        io.ulong("deadColor")
        io.ulong("teamNumber")
        io.long("teamSlot")
    io.bool("isObjective")
    io.bool("isSelected")
    io.hexlong("isVisible")
    io.hexlong("seen")
    if v < 1033:
        for name in ("playerShot", "playerCollide", "friendShot", "friendCollide", "enemyShot", "groundCollide"):
            io.float(name)
    io.float("healthRatio")
    io.long("curHealth")
    io.long("maxHealth")
    if v < 1015:
        io.float("heatRatio")
        io.long("curHeat")
        io.long("maxHeat")
    io.float("ammoRatio")
    io.long("curAmmo")
    io.long("maxAmmo")
    if not io.save:
        ai_cmd_info(io, "nextCmd")
        if v > 1021:
            io.bool("aiProcess")
    else:
        ai_cmd_info(io, "curCmd")
        ai_cmd_info(io, "nextCmd")
        io.bool("aiProcess")
    if v > 1007:
        io.bool("isCargo")
    if v > 1016:
        io.ulong("independence")
        if v < 1030:
            io.bool("hasPilot", "curPilot")
        else:
            io.id("curPilot")
    if v > 1031:
        io.long("perceivedTeam")


def craft(io: _Walk) -> None:
    v = io.version
    if v < 1019:
        for name in ("energy0current", "energy0maximum", "energy1current", "energy1maximum",
                     "energy2current", "energy2maximum"):
            io.ulong(name)
        io.vec3("bumpers", count=6)
    if v > 1027:
        io.long("abandoned")
    if v >= 2000:
        if v < 2002:
            io.float("cloakTransitionTime")
        io.void("cloakState")
        io.float("cloakTransBeginTime")
        io.float("cloakTransEndTime")
    game_object(io)


_HOVER_LEGACY = ("setAltitude", "accelDragStop", "accelDragFull", "alphaTrack", "alphaDamp", "pitchPitch",
                 "pitchThrust", "rollStrafe", "rollSteer", "velocForward", "velocReverse", "velocStrafe",
                 "accelThrust", "accelBrake", "omegaSpin", "omegaTurn", "alphaSteer", "accelJump",
                 "thrustRatio", "throttle", "airBorne")


def hover_craft(io: _Walk) -> None:
    if 1001 < io.version < 1026:
        for name in _HOVER_LEGACY:
            io.float(name, f"hover.{name}")
    craft(io)


def walker(io: _Walk) -> None:
    if 1001 < io.version < 1026:
        for name in _HOVER_LEGACY:
            io.float(name, f"hover.{name}")
    craft(io)


def producer(io: _Walk) -> None:
    v = io.version
    if v < 1011:
        io.float("setAltitude", "producer.setAltitude")
    if v != 1042:
        io.float("timeDeploy")
        io.float("timeUndeploy")
    io.ptr("undefptr", "powerSource")
    io.void("state")
    io.float("delayTimer")
    io.float("nextRepair")
    if v >= 1006:
        io.id("buildClass")
        io.float("buildDoneTime")
        if v <= 1026:
            io.long("buildCost")
            io.float("buildUpdateTime")
            io.float("buildDt")
            io.long("buildDc")
    if v <= 1010:
        craft(io)
    else:
        hover_craft(io)


def apc(io: _Walk) -> None:
    io.long("soldierCount")
    io.void("state")
    hover_craft(io)


def construction_rig(io: _Walk) -> None:
    if io.version > 1030:
        io.mat("dropMat")
        io.id("dropClass")
        if io.version >= 2001:
            io.ulong("lastRecycled")
    producer(io)


def recycler(io: _Walk) -> None:
    io.ptr("undefptr", "recycler.undefptr")
    producer(io)


def scavenger(io: _Walk) -> None:
    v = io.version
    if (1039 <= v < 2000) or v > 2004:
        io.ulong("scrapHeld")
    hover_craft(io)


def turret_tank(io: _Walk) -> None:
    v = io.version
    if v != 1042:
        io.float("undeffloat", "omegaTurret")
        io.float("undeffloat", "alphaTurret")
        io.float("undeffloat", "timeDeploy")
        io.float("undeffloat", "timeUndeploy")
    io.void("undefraw", "state")
    io.float("undeffloat", "delayTimer")
    if v != 1042:
        io.bool("undefbool", "wantTurret")
    hover_craft(io)


def howitzer(io: _Walk) -> None:
    if io.version < 1020:
        hover_craft(io)
    else:
        turret_tank(io)


def tug(io: _Walk) -> None:
    # 1045 files sometimes name this pointer "state" (a BZNParser malformation)
    io.ptr("undefptr", "cargo", alts=("state",) if io.version == 1045 else ())
    hover_craft(io)


def person(io: _Walk) -> None:
    io.float("nextScream")
    craft(io)


def building(io: _Walk) -> None:
    if io.save:
        io.bool("tempBuilding")
    game_object(io)


def barracks(io: _Walk) -> None:
    if io.save:
        io.long("nextEmptyCheck")
    building(io)


def mine(io: _Walk) -> None:
    if io.version >= 1038 and io.save:
        io.float("lifeTimer")
    building(io)


def power_up(io: _Walk) -> None:
    game_object(io)


def torpedo(io: _Walk) -> None:
    v = io.version
    if v < 1031:
        if v < 1019:
            for name in ("energy0current", "energy0maximum", "energy1current", "energy1maximum",
                         "energy2current", "energy2maximum"):
                io.ulong(name)
            io.vec3("bumpers", count=6)
        elif v > 1027:
            io.long("abandoned")
        game_object(io)
    else:
        power_up(io)


def portal(io: _Walk) -> None:
    if io.version >= 2004:
        io.ulong("portalState")
        io.float("portalBeginTime")
        io.float("portalEndTime")
        io.bool("isIn")
    game_object(io)


def scrap_silo(io: _Walk) -> None:
    if io.version > 1020:
        io.ptr("undefptr", "scrapsilo.undefptr")
    game_object(io)


# classLabel -> schema, from every [ObjectClass(BZNFormat.Battlezone, ...)] in BZNParser
SCHEMAS: Dict[str, Callable[[_Walk], None]] = {
    "apc": apc,
    "ammopack": power_up, "camerapod": power_up, "daywrecker": power_up, "repairkit": power_up,
    "wpnpower": power_up, "powerup": power_up,
    "armory": producer, "factory": producer, "producer": producer,
    "barracks": barracks,
    "i76building": building, "i76building2": building, "i76sign": building, "repairdepot": building,
    "artifact": building, "commtower": building, "geyser": building, "powerplant": building,
    "scrapfield": building, "shieldtower": building, "spraybomb": building, "supplydepot": building,
    "constructionrig": construction_rig,
    "craft": craft,
    "flare": mine, "magnet": mine, "proximity": mine, "weaponmine": mine,
    "hover": hover_craft, "minelayer": hover_craft, "sav": hover_craft, "wingman": hover_craft,
    "howitzer": howitzer,
    "turrettank": turret_tank,
    "person": person,
    "portal": portal,
    "recycler": recycler,
    "scavenger": scavenger,
    "scrap": game_object, "spawnpnt": game_object,
    "scrapsilo": scrap_silo,
    "torpedo": torpedo,
    "tug": tug,
    "turret": craft,             # ClassTurretCraft: BZ1 has no fields of its own
    "walker": walker,
}


# ---------------------------------------------------------------------------
# file-level schemas
# ---------------------------------------------------------------------------

def aoi_schema(io: _Walk) -> None:
    io.validation("AOI")
    io.ptr("undefptr", "path")
    io.ulong("team")
    io.bool("interesting")
    io.bool("inside")
    io.long("value")
    io.ulong("force")


def path_schema(io: _Walk) -> None:
    io.validation("AiPath")
    if io.version > 2011:
        io.ptr("old_ptr")
    else:
        io.void("old_ptr", case="L")
    size = io.ulong("size", "label.size")
    if size > 0:
        io.chars("label")
    io.long("pointCount")
    io.vec2("points")
    io.void("pathType", case="L")


# ---------------------------------------------------------------------------
# object class resolution
# ---------------------------------------------------------------------------

_HINTS_FILE = Path(__file__).with_name("data") / "bz1_class_labels.txt"
_hint_cache: Optional[Dict[str, List[str]]] = None


def stock_class_hints() -> Dict[str, List[str]]:
    """ODF name -> BZ1 class labels, from BZNParser's ``BZ1_ClassLabels.txt``."""
    global _hint_cache
    if _hint_cache is None:
        table: Dict[str, List[str]] = {}
        try:
            text = _HINTS_FILE.read_text(encoding="latin-1")
        except OSError:
            text = ""
        for line in text.splitlines():
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) >= 2:
                odf, label = parts[0].strip().lower(), parts[1].strip()
                if label in SCHEMAS and label not in table.setdefault(odf, []):
                    table[odf].append(label)
        _hint_cache = table
    return _hint_cache


def odf_class_hints(folders: Iterable[os.PathLike | str]) -> Dict[str, List[str]]:
    """ODF name -> classLabel for every ``*.odf`` under ``folders`` (custom units)."""
    from battlezone.odf.class_labels import read_class_label

    table: Dict[str, List[str]] = {}
    for folder in folders:
        root = Path(folder)
        if not root.is_dir():
            continue
        for path in root.rglob("*"):
            if path.suffix.lower() != ".odf" or not path.is_file():
                continue
            try:
                label = read_class_label(path)
            except OSError:
                continue
            if label and label.lower() in SCHEMAS:
                table.setdefault(path.stem.lower(), [label.lower()])
    return table


# ---------------------------------------------------------------------------
# the file model
# ---------------------------------------------------------------------------

@dataclass
class BZNObject:
    class_label: str
    fields: Dict[str, Field]
    candidates: List[str] = field(default_factory=list)   # other labels that parsed identically
    hinted: bool = False
    basis: str = "parse"     # how the class was chosen: "hint" (stock table / ODF), "label" or "parse"
    expected: List[str] = field(default_factory=list)     # hinted classes the data did not fit

    def _text(self, key: str) -> str:
        f = self.fields.get(key)
        return f.value.decode("latin-1") if f is not None else ""

    @property
    def prjid(self) -> str:
        return self._text("PrjID")

    @property
    def label(self) -> str:
        return self._text("label")

    @property
    def seqno(self) -> int:
        f = self.fields.get("seqno")
        return f.value if f is not None else 0

    def describe(self, index: int) -> str:
        label = f", label {self.label}" if self.label else ""
        return f"object {index} {self.prjid} ({self.class_label}, seqno {self.seqno}{label})"


@dataclass
class BZNFile:
    version: int
    binary: bool
    save: bool                            # parsed as a save game (missionSave false and the SAVE layout fit)
    header: Dict[str, Field]
    objects: List[BZNObject]
    mission: Dict[str, Field]             # name, sObject, Lua state, AiMission size
    aois: List[Dict[str, Field]]
    paths: List[Dict[str, Field]]
    trailing_vec2d: bool = False
    notes: List[str] = field(default_factory=list)

    @property
    def mission_name(self) -> str:
        f = self.mission.get("name")
        return f.value.decode("latin-1") if f is not None else ""

    @property
    def terrain_name(self) -> str:
        f = self.header.get("TerrainName")
        return f.value.decode("latin-1") if f is not None else ""

    @property
    def is_redux(self) -> bool:
        return self.version >= REDUX_MIN_VERSION

    def write(self, version: Optional[int] = None, *, binary: Optional[bool] = None,
              report: Optional[WriteReport] = None, preserve_spelling: bool = True) -> bytes:
        """Serialise at ``version`` (default: the source version)."""
        return write_bzn(self, version if version is not None else self.version,
                         binary=self.binary if binary is None else binary, report=report,
                         preserve_spelling=preserve_spelling)


def _header_schema(io: _Walk, stream: Optional[_Stream] = None) -> None:
    """``BZNFileBattlezone`` header after ``version``, for versions >= 1022.

    ``binarySave`` switches the rest of the file to binary: the reader marks
    the stream (``stream``), the writer flips its output mode.
    """
    v = io.version
    if v > 1022:
        binary = io.bool("binarySave")
        if binary:
            if stream is not None:
                stream.binary_start = stream.pos
            elif isinstance(io, _Writer):
                io.binary = True
        io.chars("msn_filename", size=16)
    io.ulong("seq_count")
    if v >= 1016:
        io.bool("missionSave")
    if v != 1001:
        io.chars("TerrainName", size=100)
    if (io.save and v > 1002) or v in (1011, 1012):
        io.float("start_time")


def _mission_schema(io: _Walk) -> None:
    v = io.version
    name = io.chars("name", size=40).decode("latin-1")
    io.ptr("sObject")
    if name in LUA_MISSIONS:
        if (v == 1044) if not io.save else (v >= 1044):
            io.bool("undefbool", "luaMissionStarted")
    io.validation("AiMission")
    if name == "AiMission":
        io.long("size", "aiMissionSize")


class _ParseState:
    def __init__(self, data: bytes, version: int, save: bool, hints: Dict[str, List[str]]):
        self.stream = _Stream(data)
        self.reader = _Reader(self.stream, version, save)
        self.hints = hints


def _read_version(stream: _Stream) -> int:
    line = stream.next_nonempty_line()
    parsed = _split_header(line)
    if parsed is None or not _name_matches("version", parsed[1]) or parsed[0] != "multi":
        raise BZNError("not an ASCII-headed Battlezone BZN (no 'version [1] =' line); "
                       "N64 and BZ2 files are not supported")
    try:
        return int(stream.line().strip())
    except ValueError as exc:
        raise BZNError("unreadable BZN version") from exc


def _read_tail(r: _Reader, mission: Dict[str, Field], aois: list, paths: list) -> bool:
    """TailParse: mission, AOIs, AiPaths. Returns whether a (0,0) VEC2D trails."""
    with r.scope(mission, "mission"):
        _mission_schema(r)
    r.validation("AOIs")
    with r.scope(mission):
        count = r.count("size", "#aois")
    for _ in range(count):
        with r.scope({}) as aoi:
            aoi_schema(r)
        aois.append(aoi)
    r.validation("AiPaths")
    with r.scope(mission):
        count = r.count("count", "#paths")
    for _ in range(count):
        with r.scope({}) as path:
            path_schema(r)
        paths.append(path)
    stream = r.stream
    trailing = False
    if not stream.eof() and stream.in_binary:
        mark = stream.pos
        try:
            dtype, payload = stream.token()
        except BZNError:
            stream.pos = mark
        else:
            if dtype == DATA_VEC2D and len(payload) == 8 and struct.unpack("<2f", payload) == (0.0, 0.0):
                trailing = True
            else:
                stream.pos = mark
    if not stream.in_binary:
        while not stream.eof():
            if stream.line().strip():
                raise BZNError(f"data left after the last AiPath (offset {stream.pos})")
    if not stream.eof():
        raise BZNError(f"data left after the last AiPath (offset {stream.pos})")
    return trailing


def _next_is_ok(state: _ParseState, remaining: int) -> bool:
    stream, r = state.stream, state.reader
    mark = stream.pos
    try:
        if remaining == 0:
            _read_tail(r, {}, [], [])
            return True
        if not stream.in_binary:
            return stream.next_nonempty_line().strip() == "[GameObject]"
        with r.scope({}):
            entity_descriptor(r)
        return True
    except (BZNError, struct.error, UnicodeError):
        return False
    finally:
        stream.pos = mark


def _read_object(state: _ParseState, remaining: int) -> BZNObject:
    stream, r = state.stream, state.reader
    descriptor: Dict[str, Field] = {}
    with r.scope(descriptor):
        entity_descriptor(r)
    after = stream.pos
    prjid = descriptor["PrjID"].value.decode("latin-1").lower()
    hinted = [label for label in state.hints.get(prjid, []) if label in SCHEMAS]
    # the editor names objects "<odf><n>_<classLabel>"; use that to break ties
    suffix = descriptor["label"].value.decode("latin-1").rsplit("_", 1)[-1].lower() if "label" in descriptor else ""
    preferred = suffix if suffix in SCHEMAS else None
    orders = [hinted] if hinted else []
    orders.append(sorted(SCHEMAS))
    for attempt, labels in enumerate(orders):
        results = []
        tried: Dict[Callable, str] = {}
        for label in labels:
            schema = SCHEMAS[label]
            if schema in tried:
                continue
            tried[schema] = label
            stream.pos = after
            fields = dict(descriptor)
            try:
                with r.scope(fields):
                    schema(r)
            except (BZNError, struct.error, UnicodeError):
                continue
            end = stream.pos
            if _next_is_ok(state, remaining - 1):
                results.append((end, label, fields))
        if results:
            shortest = min(end for end, _, _ in results)
            best = [(label, fields) for end, label, fields in results if end == shortest]
            stream.pos = shortest
            basis = "hint" if hinted and attempt == 0 else "parse"
            if basis == "parse" and preferred is not None:
                for i, (label, _) in enumerate(best):
                    if SCHEMAS[label] is SCHEMAS[preferred]:
                        best.insert(0, (preferred, best.pop(i)[1]))
                        basis = "label"
                        break
            label, fields = best[0]
            return BZNObject(label, fields, [other for other, _ in best[1:]], hinted=basis == "hint", basis=basis,
                             expected=hinted if attempt else [])
    stream.pos = after
    raise BZNError(f"object {descriptor['PrjID'].value.decode('latin-1')!r} (seqno "
                   f"{descriptor['seqno'].value}) does not parse as any BZ1 class at version {r.version}")


def _parse(data: bytes, save: bool, hints: Dict[str, List[str]]) -> BZNFile:
    probe = _Stream(data)
    version = _read_version(probe)
    if version < MIN_VERSION:
        raise BZNError(f"BZN version {version} predates 1022 and is not supported")
    state = _ParseState(data, version, save, hints)
    stream, r = state.stream, state.reader
    stream.pos = probe.pos
    # BZ2 files carry saveType here; BZ1 goes straight to binarySave
    mark = stream.pos
    first = _split_header(stream.next_nonempty_line())
    stream.pos = mark
    if first is not None and first[1] in ("saveType", "saveGameDesc", "msn_filename"):
        raise BZNError("this is a Battlezone II / Combat Commander BZN, not Battlezone 1")
    header: Dict[str, Field] = {}
    with r.scope(header, "header"):
        _header_schema(r, stream)
    binary = stream.binary_start is not None
    with r.scope(header, "header"):
        count = r.count("size", "#objects")
    if count < 0:
        raise BZNError("negative object count")
    objects = []
    for i in range(count):
        objects.append(_read_object(state, count - i))
    notes = [f"{obj.describe(i)} does not fit its ODF's class ({', '.join(obj.expected)}); read as {obj.class_label}"
             for i, obj in enumerate(objects) if obj.expected]
    mission: Dict[str, Field] = {}
    aois: list = []
    paths: list = []
    trailing = _read_tail(r, mission, aois, paths)
    return BZNFile(version, binary, save, header, objects, mission, aois, paths, trailing, notes)


def read_bzn(source, *, odf_dirs: Sequence[os.PathLike | str] = (),
             hints: Optional[Dict[str, List[str]]] = None) -> BZNFile:
    """Parse a BZ1 BZN (bytes or a path), ASCII or binary, version 1022 and later.

    Object classes are not stored in BZNs. They come from ``hints`` (default:
    BZNParser's stock table plus the ``classLabel`` of every ODF under
    ``odf_dirs``); objects whose ODF is unknown are tried against every class,
    keeping the shortest parse that lets the next object (or the mission tail)
    parse too - BZNParser's own disambiguation.
    """
    data = Path(source).read_bytes() if isinstance(source, (str, os.PathLike)) else bytes(source)
    table = dict(stock_class_hints() if hints is None else hints)
    if odf_dirs:
        table.update(odf_class_hints(odf_dirs))
    probe = _Stream(data)
    _read_version(probe)
    mission_save = _peek_mission_save(data)
    if mission_save is False:
        # BZNParser: missionSave false -> try the SAVE layout, fall back to a map
        try:
            parsed = _parse(data, True, table)
            parsed.notes.append("missionSave is false and the save-game layout fits: read as a save game")
            return parsed
        except BZNError:
            parsed = _parse(data, False, table)
            parsed.notes.append("missionSave is false but the data is a mission map; read as a map")
            return parsed
    return _parse(data, False, table)


def _peek_mission_save(data: bytes) -> Optional[bool]:
    try:
        parsed = _parse_header_only(data)
    except (BZNError, struct.error):
        return None
    f = parsed.get("missionSave")
    return None if f is None else bool(f.value)


def _parse_header_only(data: bytes) -> Dict[str, Field]:
    stream = _Stream(data)
    version = _read_version(stream)
    r = _Reader(stream, version, False)
    header: Dict[str, Field] = {}
    with r.scope(header):
        _header_schema(r, stream)
    return header


# ---------------------------------------------------------------------------
# writing
# ---------------------------------------------------------------------------

def write_bzn(bzn: BZNFile, version: int, *, binary: bool = False,
              report: Optional[WriteReport] = None, preserve_spelling: bool = True) -> bytes:
    """Serialise ``bzn`` at ``version``. Changes are recorded in ``report``.

    ``preserve_spelling`` reuses the source's text and binary payloads for
    fields whose type did not change (a same-version rewrite is then
    byte-identical); ``False`` formats every value the way BZNParser does.
    """
    if version < MIN_VERSION:
        raise BZNError(f"cannot write version {version}; the earliest supported version is {MIN_VERSION}")
    report = report if report is not None else WriteReport()
    w = _Writer(version, bzn.save, binary, report)
    w.preserve_spelling = preserve_spelling
    w._multi("version", [str(version)])
    header = dict(bzn.header)
    if header.get("binarySave") is None or bool(header["binarySave"].value) != binary:
        header["binarySave"] = Field("bool", binary)
    # BZNParser writes missionSave from the layout: a mission map is "true". The
    # 1.5 loader reads missionSave == false as a shell save game.
    mission_save = not bzn.save
    source_flag = bzn.header.get("missionSave")
    if source_flag is None or bool(source_flag.value) != mission_save:
        if source_flag is not None:
            report.add("converted", "header", "missionSave",
                       f"{str(bool(source_flag.value)).lower()} -> {str(mission_save).lower()} "
                       f"(the data is laid out as a {'save game' if bzn.save else 'mission map'})")
        header["missionSave"] = Field("bool", mission_save)
    with w.scope(header, "header"):
        _header_schema(w)
        w.count("size", "#objects", len(bzn.objects))
    for index, obj in enumerate(bzn.objects):
        schema = SCHEMAS.get(obj.class_label)
        if schema is None:
            raise BZNError(f"no schema for class {obj.class_label!r}")
        with w.scope(obj.fields, obj.describe(index)):
            entity_descriptor(w)
            schema(w)
    with w.scope(dict(bzn.mission), "mission"):
        _mission_schema(w)
    w.validation("AOIs")
    with w.scope(bzn.mission, "mission", check=False):
        w.count("size", "#aois", len(bzn.aois))
    for index, aoi in enumerate(bzn.aois):
        with w.scope(aoi, f"AOI {index}"):
            aoi_schema(w)
    w.validation("AiPaths")
    with w.scope(bzn.mission, "mission", check=False):
        w.count("count", "#paths", len(bzn.paths))
    for index, path in enumerate(bzn.paths):
        label = path.get("label")
        name = label.value.decode("latin-1") if label is not None else ""
        with w.scope(path, f"AiPath {index} {name}".rstrip()):
            path_schema(w)
    if w.binary and bzn.trailing_vec2d and version == bzn.version:
        w._token(DATA_VEC2D, bytes(8))       # the (0, 0) some binary files end with
    return bytes(w.out)


# ---------------------------------------------------------------------------
# comparison
# ---------------------------------------------------------------------------

def _comparable(f: Field):
    if f.kind in ("float", "vec3", "vec2", "mat", "euler"):
        values = [f.value] if f.kind == "float" else (
            [c for v in f.value for c in v] if f.kind in ("vec3", "vec2") else list(f.value))
        return tuple("nan" if isinstance(c, float) and math.isnan(c) else c for c in values)
    return f.value


def compare_fields(a: Dict[str, Field], b: Dict[str, Field], context: str,
                   tolerance: float = 0.0) -> List[str]:
    """Differences between two field tables (keys, kinds and values)."""
    problems = []
    for key in sorted(set(a) | set(b)):
        if key.startswith("#"):
            continue
        fa, fb = a.get(key), b.get(key)
        if fa is None or fb is None:
            problems.append(f"{context}: {key} only in {'second' if fa is None else 'first'}")
            continue
        if fa.kind != fb.kind:
            problems.append(f"{context}: {key} is {fa.kind} vs {fb.kind}")
            continue
        va, vb = _comparable(fa), _comparable(fb)
        if va == vb:
            continue
        if tolerance and isinstance(va, tuple) and len(va) == len(vb) and all(
                isinstance(x, float) and isinstance(y, float) and abs(x - y) <= tolerance * max(1.0, abs(x))
                for x, y in zip(va, vb)):
            continue
        problems.append(f"{context}: {key} {describe_value(fa)} != {describe_value(fb)}")
    return problems


def compare_bzn(a: BZNFile, b: BZNFile, *, tolerance: float = 0.0,
                ignore_header: Sequence[str] = ("binarySave",)) -> List[str]:
    """Field-by-field differences between two parsed files."""
    problems = []
    ha = {k: v for k, v in a.header.items() if k not in ignore_header}
    hb = {k: v for k, v in b.header.items() if k not in ignore_header}
    problems += compare_fields(ha, hb, "header", tolerance)
    if len(a.objects) != len(b.objects):
        problems.append(f"object count {len(a.objects)} != {len(b.objects)}")
    for i, (oa, ob) in enumerate(zip(a.objects, b.objects)):
        context = oa.describe(i)
        if oa.class_label != ob.class_label and ob.class_label not in oa.candidates \
                and oa.class_label not in ob.candidates:
            problems.append(f"{context}: class {oa.class_label} != {ob.class_label}")
        problems += compare_fields(oa.fields, ob.fields, context, tolerance)
    problems += compare_fields(a.mission, b.mission, "mission", tolerance)
    for kind, la, lb in (("AOI", a.aois, b.aois), ("AiPath", a.paths, b.paths)):
        if len(la) != len(lb):
            problems.append(f"{kind} count {len(la)} != {len(lb)}")
        for i, (fa, fb) in enumerate(zip(la, lb)):
            problems += compare_fields(fa, fb, f"{kind} {i}", tolerance)
    return problems
