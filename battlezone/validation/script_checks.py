"""Mission script and AI plan checks.

* ``lua`` - a Redux ``LuaMission`` runs ``<mission>.lua`` beside its ``.bzn``.
  A script that looks up a label the mission does not have, builds an ODF
  that does not exist, or ``require``\\ s a module that is not shipped fails
  silently in game (a nil handle, a missing unit). String-literal arguments of
  the calls in ``data/lua_api.json`` are checked; computed ones are skipped.
* ``aip`` - AI plans (``.aip``, both games): the C-like layout of the stock
  files (``#DATA`` blocks after ``UNIT_CONSTRUCTION_PROGRAM``/``ACCOUNT``/...
  declarations), the ODF names their rows buy or match, and the accounts the
  construction program funds. Scripts reference AIPs with ``SetAIP``; the
  ``lua`` check reports names that do not exist.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Dict, Iterator, List, NamedTuple, Optional, Set, Tuple

from battlezone.bzn.scan import STOCK_SET

_DATA = Path(__file__).with_name("data")


def _issue(*args, **kwargs):
    from battlezone.validation.engine import Issue

    return Issue(*args, **kwargs)


@lru_cache(maxsize=1)
def lua_api() -> dict:
    return json.loads((_DATA / "lua_api.json").read_text(encoding="utf-8"))


def _odf_known(name: str, names_lower: Set[str]) -> bool:
    filename = name.lower() if name.lower().endswith(".odf") else f"{name.lower()}.odf"
    return filename in STOCK_SET or filename in names_lower


# ---------------------------------------------------------------------------
# Lua
# ---------------------------------------------------------------------------

class Token(NamedTuple):
    kind: str       # "name" | "string" | "number" | "op"
    value: str
    line: int


class LuaSyntaxError(ValueError):
    def __init__(self, line: int, message: str):
        super().__init__(message)
        self.line = line


_OPS = ("...", "..", "==", "~=", "<=", ">=", "::", "//", "<<", ">>")
_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_NUMBER = re.compile(r"0[xX][0-9A-Fa-f.]+(?:[pP][+-]?\d+)?|(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")
_LONG_OPEN = re.compile(r"\[(=*)\[")
_ESCAPES = {"n": "\n", "t": "\t", "r": "\r", "a": "\a", "b": "\b", "f": "\f", "v": "\v",
            "\\": "\\", '"': '"', "'": "'", "\n": "\n"}


def lua_tokens(text: str) -> List[Token]:
    """Tokenise Lua source, dropping comments. Raises :class:`LuaSyntaxError`."""
    tokens: List[Token] = []
    i, line, n = 0, 1, len(text)
    while i < n:
        c = text[i]
        if c == "\n":
            line += 1
            i += 1
        elif c in " \t\r\f\v":
            i += 1
        elif text.startswith("--", i):
            long = _LONG_OPEN.match(text, i + 2)
            if long:
                close = "]" + long.group(1) + "]"
                end = text.find(close, long.end())
                if end < 0:
                    raise LuaSyntaxError(line, "unfinished long comment")
                line += text.count("\n", i, end)
                i = end + len(close)
            else:
                end = text.find("\n", i)
                i = n if end < 0 else end
        elif c == "[" and _LONG_OPEN.match(text, i):
            long = _LONG_OPEN.match(text, i)
            close = "]" + long.group(1) + "]"
            end = text.find(close, long.end())
            if end < 0:
                raise LuaSyntaxError(line, "unfinished long string")
            tokens.append(Token("string", text[long.end():end].lstrip("\n"), line))
            line += text.count("\n", i, end)
            i = end + len(close)
        elif c in "\"'":
            start_line, j, out = line, i + 1, []
            while True:
                if j >= n or text[j] == "\n":
                    raise LuaSyntaxError(start_line, "unfinished string")
                ch = text[j]
                if ch == c:
                    break
                if ch == "\\" and j + 1 < n:
                    nxt = text[j + 1]
                    if nxt == "\n":
                        line += 1
                    if nxt == "z":                               # skip following whitespace
                        j += 2
                        while j < n and text[j] in " \t\r\n":
                            line += text[j] == "\n"
                            j += 1
                        continue
                    out.append(_ESCAPES.get(nxt, "\\" + nxt))
                    j += 2
                    continue
                out.append(ch)
                j += 1
            tokens.append(Token("string", "".join(out), start_line))
            i = j + 1
        elif c.isdigit() or (c == "." and i + 1 < n and text[i + 1].isdigit()):
            m = _NUMBER.match(text, i)
            tokens.append(Token("number", m.group(), line))
            i = m.end()
        elif c.isalpha() or c == "_":
            m = _NAME.match(text, i)
            tokens.append(Token("name", m.group(), line))
            i = m.end()
        else:
            op = next((o for o in _OPS if text.startswith(o, i)), c)
            tokens.append(Token("op", op, line))
            i += len(op)
    return tokens


_CLOSE = {"(": ")", "{": "}", "[": "]"}


class Call(NamedTuple):
    name: str
    line: int
    args: List[List[Token]]


def lua_calls(tokens: List[Token]) -> Tuple[List[Call], Set[str]]:
    """Global function calls (``Name(...)`` / ``Name "s"``) and the names the script defines itself."""
    calls: List[Call] = []
    defined: Set[str] = set()
    n = len(tokens)
    for i, tok in enumerate(tokens):
        if tok.kind != "name" or i + 1 >= n:
            continue
        prev = tokens[i - 1] if i else None
        if prev is not None and prev.kind == "op" and prev.value in (".", ":"):
            continue
        if prev is not None and prev.kind == "name" and prev.value == "function":
            defined.add(tok.value)
            continue
        nxt = tokens[i + 1]
        if nxt.kind == "op" and nxt.value == "=" and i + 2 < n and tokens[i + 2].value == "function":
            defined.add(tok.value)
            continue
        if nxt.kind == "string":
            calls.append(Call(tok.value, tok.line, [[nxt]]))
        elif nxt.kind == "op" and nxt.value == "(":
            args: List[List[Token]] = [[]]
            depth, j = [], i + 2
            while j < n:
                t = tokens[j]
                if t.kind == "op" and t.value in _CLOSE:
                    depth.append(_CLOSE[t.value])
                elif t.kind == "op" and depth and t.value == depth[-1]:
                    depth.pop()
                elif t.kind == "op" and not depth and t.value == ")":
                    break
                elif t.kind == "op" and not depth and t.value == ",":
                    args.append([])
                    j += 1
                    continue
                args[-1].append(t)
                j += 1
            calls.append(Call(tok.value, tok.line, [a for a in args if a] if args != [[]] else []))
    return calls, defined


def _literal_args(call: Call, positions) -> Iterator[Tuple[str, int, str]]:
    """``(value, line, call as shown)`` of the string-literal arguments at ``positions``."""
    for position in positions:
        if position <= len(call.args):
            arg = call.args[position - 1]
            if len(arg) == 1 and arg[0].kind == "string" and arg[0].value.strip():
                value = arg[0].value
                yield value, arg[0].line, f'{call.name}({"..., " * (position - 1)}"{value}")'


def _bzn_names(path: Path) -> Optional[Tuple[str, Set[str], Set[str]]]:
    """``(mission class, object labels, path names)`` of a BZN, lower case; ``None`` if unreadable."""
    from battlezone.bzn.bz1 import BZNError, read_bzn

    try:
        bzn = read_bzn(path)
    except (BZNError, OSError, ValueError, EOFError, IndexError, KeyError):
        return None
    labels = {obj.label.lower() for obj in bzn.objects if obj.label}
    paths = {p["label"].value.decode("latin-1").lower() for p in bzn.paths if "label" in p}
    return bzn.mission_name, labels, paths


def _module_known(name: str, provided: Set[str]) -> bool:
    lower = name.lower().replace("\\", "/")
    for candidate in (lower, lower.replace(".", "/"), lower.rsplit(".", 1)[-1], lower.rsplit("/", 1)[-1]):
        if candidate in provided:
            return True
    return False


_DYNAMIC_PATH = re.compile(r"\bpackage\s*\.\s*c?path\b|\bRequireFix\b")
_PRELOAD = re.compile(r"""\bpackage\s*\.\s*preload\s*\[\s*(["'])([^"']+)\1\s*\]\s*=""")


class _Finding(NamedTuple):
    severity: str
    rule: str
    value: str
    message: str
    line: int
    suggestion: str


def _script_findings(text: str, calls: List[Call], defined: Set[str], mission, bzn_name: str,
                     names_lower: Set[str], provided: Set[str]) -> Iterator[_Finding]:
    """Findings of one script. ``mission`` is ``_bzn_names`` of its BZN, ``None`` for a shared module."""
    api = lua_api()
    stock_aip = set(api["stock_aip"])
    shared = mission is None                 # shared modules often cover factions and modules of other mods
    labels: Set[str] = set()
    paths: Set[str] = set()
    if mission is not None:
        labels, paths = set(mission[1]), mission[2]
        for call in calls:
            if call.name in api["set_label"] and call.name not in defined:
                labels.update(v.lower() for v, _, _ in _literal_args(call, api["set_label"][call.name]))
    probed = {v.lower() for call in calls if call.name == "GetPathPointCount" for v, _, _ in _literal_args(call, (1,))}
    dynamic_modules = bool(_DYNAMIC_PATH.search(text))

    for call in calls:
        name = call.name
        if name in defined:
            continue
        for value, line, shown in _literal_args(call, api["odf"].get(name, ())):
            if "." in value and not value.lower().endswith(".odf"):
                continue                                        # OpenODF of a .trn/.ini: not an ODF
            if not _odf_known(value, names_lower):
                yield _Finding("info" if shared else "warning", "lua-missing-odf", value,
                               f"{shown}: no stock or project ODF of that name", line,
                               "Fix the name or add the ODF, unless a required mod provides it.")
        for value, line, shown in _literal_args(call, api["odf_info"].get(name, ())):
            if not _odf_known(value, names_lower):
                yield _Finding("info", "lua-unknown-odf", value,
                               f"{shown}: no stock or project ODF of that name", line, "")
        for value, line, shown in _literal_args(call, api["aip"].get(name, ())):
            filename = value.lower() if "." in value else f"{value.lower()}.aip"
            if filename not in stock_aip and filename not in names_lower:
                yield _Finding("warning", "lua-missing-aip", value,
                               f"{shown}: no stock or project AI plan of that name", line,
                               "Add the .aip to the mod or fix the name; the team gets no plan.")
        if name == "require":
            for value, line, shown in _literal_args(call, (1,)):
                if _module_known(value, provided):
                    continue
                library = api["known_libraries"].get(value.lower())
                if library or dynamic_modules or shared:
                    why = library or ("the script extends the module search path (package.path / RequireFix)"
                                      if dynamic_modules else "required by a shared module")
                    yield _Finding("info", "lua-external-module", value,
                                   f"{shown} is not in the project: {why}", line,
                                   "Make sure players have the mod that provides it.")
                else:
                    yield _Finding("warning", "lua-missing-module", value,
                                   f"{shown}: no .lua module of that name in the project", line,
                                   "Ship the module with the mod or fix the name; the script stops at this line.")
        if mission is None:
            continue
        for value, line, shown in _literal_args(call, api["label"].get(name, ())):
            if value.lower() not in labels:
                hint = " (it is a path)" if value.lower() in paths else ""
                yield _Finding("warning", "lua-missing-label", value,
                               f"{shown}: no object labelled '{value}' in {bzn_name}{hint}", line,
                               "The call returns nil. Label the object in the editor or fix the name.")
        for value, line, shown in _literal_args(call, api["target"].get(name, ())):
            if value.lower() not in labels and value.lower() not in paths:
                probe = value.lower() in probed
                yield _Finding("info" if probe else "warning", "lua-missing-path", value,
                               f"{shown}: no path or object labelled '{value}' in {bzn_name}"
                               + (" (the script tests it with GetPathPointCount)" if probe else ""), line,
                               "Add the path in the editor or fix the name.")


def check_lua(ctx) -> Iterator:
    scripts = ctx.with_suffix(".lua")
    provided: Set[str] = set(lua_api()["builtin_modules"])
    for path in scripts + ctx.with_suffix(".dll", ".luac"):
        provided.add(path.stem.lower())
        provided.add(ctx.rel(path).lower().rsplit(".", 1)[0])
    texts = {path: path.read_bytes().decode("latin-1") for path in scripts}
    for text in texts.values():                          # bundles register modules in package.preload
        provided.update(m.group(2).lower() for m in _PRELOAD.finditer(text))
    bzn_by_stem: Dict[str, List[Path]] = {}
    for bzn in ctx.with_suffix(".bzn"):
        bzn_by_stem.setdefault(bzn.stem.lower(), []).append(bzn)

    for path in scripts:
        ctx.check_cancel()
        rel = ctx.rel(path)
        try:
            tokens = lua_tokens(texts[path])
        except LuaSyntaxError as exc:
            yield _issue("error", "lua", f"Lua syntax: {exc}", rel, line=exc.line, rule_id="lua-syntax",
                         suggestion="The game cannot load the script; close the string or comment.")
            continue
        calls, defined = lua_calls(tokens)
        candidates = bzn_by_stem.get(path.stem.lower(), [])
        bzn_path = next((b for b in candidates if b.parent == path.parent), candidates[0] if candidates else None)
        mission = _bzn_names(bzn_path) if bzn_path is not None else None
        grouped: Dict[Tuple[str, str], List[_Finding]] = {}
        for finding in _script_findings(texts[path], calls, defined, mission, bzn_path.name if bzn_path else "",
                                        ctx.names_lower, provided):
            grouped.setdefault((finding.rule, finding.value.lower()), []).append(finding)
        for findings in grouped.values():                # one issue per name, at its first use
            first = findings[0]
            more = len({f.line for f in findings}) - 1
            message = first.message + (f" (and {more} more use{'s' if more > 1 else ''})" if more else "")
            yield _issue(first.severity, "lua", message, rel, line=first.line, rule_id=first.rule,
                         suggestion=first.suggestion)

    script_stems = {p.stem.lower() for p in scripts}
    for stem, bzns in sorted(bzn_by_stem.items()):
        if stem in script_stems:
            continue
        for bzn in bzns:
            ctx.check_cancel()
            mission = _bzn_names(bzn)
            if mission is not None and mission[0] == "LuaMission":
                yield _issue("warning", "lua", f"{bzn.name} is a LuaMission but there is no {bzn.stem}.lua",
                             ctx.rel(bzn), rule_id="lua-missing-script",
                             suggestion="Ship the mission script, or change the mission class in the editor.")


# ---------------------------------------------------------------------------
# AIP
# ---------------------------------------------------------------------------

# struct -> field kinds, from the stock aipdef.h
AIP_STRUCTS = {
    "UNIT_CONSTRUCTION_PROGRAM": ("account", "number", "number"),
    "ACCOUNT": ("number", "odf", "number", "number"),
    "FORCE_MATCHING": ("odf", "number"),
    "MATCH_UPS": ("odf", "odf"),
    "BUILDING_MATCHING": ("odf", "number", "number"),
}
AIP_CONSTANTS = {"UNLIMITED", "NUMBER_TO_HAVE", "NUMBER_TO_BUILD", "RATIO_TO_BUILD", "RATIO_TO_HAVE",
                 "DONT_CARE", "CENTER_OF_BASE", "PERIMETER", "OUTSIDE_OF_BASE", "NEAR_ENEMY_BASE",
                 "NEAR_ENEMY_TROOPS"}

_AIP_SCALAR = re.compile(r"(int|float|double|char)\s+(\w+)\s*(\[\s*\w*\s*\])?\s*=\s*(.+?)\s*;?$")
_AIP_ARRAY = re.compile(r"(\w+)\s+(\w+)\s*\[\s*(\w+)\s*\]\s*;?$")
_AIP_NUMBER = re.compile(r"[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?[fF]?$")
_AIP_STRING = re.compile(r'"([^"]*)"$')


class AipRow(NamedTuple):
    struct: str
    table: str
    fields: Tuple[str, ...]
    line: int


class AipProblem(NamedTuple):
    line: int
    severity: str
    rule: str
    message: str


def _strip_c_comments(text: str) -> Tuple[List[str], Optional[int]]:
    """Lines with ``//`` and ``/* */`` comments blanked; the line of an unclosed ``/*`` if any."""
    out, i, n, line, opened = [], 0, len(text), 1, None
    buf = []
    in_string = False
    while i < n:
        c = text[i]
        if c == "\n":
            in_string = False
            buf.append(c)
            line += 1
            i += 1
        elif in_string:
            in_string = c != '"'
            buf.append(c)
            i += 1
        elif c == '"':
            in_string = True
            buf.append(c)
            i += 1
        elif text.startswith("//", i):
            end = text.find("\n", i)
            i = n if end < 0 else end
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            if end < 0:
                opened = line
                break
            newlines = text.count("\n", i, end)
            buf.append("\n" * newlines)
            line += newlines
            i = end + 2
        else:
            buf.append(c)
            i += 1
    out = "".join(buf).split("\n")
    return out, opened


def _split_row(row: str) -> List[str]:
    fields, current, in_string = [], [], False
    for ch in row:
        if ch == '"':
            in_string = not in_string
        if ch == "," and not in_string:
            fields.append("".join(current).strip())
            current = []
        else:
            current.append(ch)
    fields.append("".join(current).strip())
    return fields


def parse_aip(text: str) -> Tuple[List[AipRow], Dict[str, int], List[AipProblem]]:
    """Rows of every ``#DATA`` table, the declared tables (name -> line) and layout problems.

    Errors lose the rest of the file (an unclosed comment or ``#DATA`` block);
    warnings are lines the game probably misreads; ``aip-orphan-data`` rows sit
    outside any table, as in stock AIPs whose ``BUILDING_MATCHING``
    declaration is commented out, and are ignored.
    """
    lines, unclosed = _strip_c_comments(text)
    rows: List[AipRow] = []
    tables: Dict[str, int] = {}
    problems: List[AipProblem] = []
    defines: Set[str] = set(AIP_CONSTANTS)
    pending: Optional[Tuple[str, str, int]] = None      # declared table waiting for its #DATA
    current: Optional[Tuple[str, str, int]] = None      # table whose #DATA block is open
    stray = False
    partial: List[str] = []                             # an unfinished row
    partial_line = 0

    def add(line: int, message: str, severity: str = "warning", rule: str = "aip-syntax") -> None:
        problems.append(AipProblem(line, severity, rule, message))

    for number, raw in enumerate(lines, 1):
        line = raw.strip()
        if not line:
            continue
        upper = line.upper()
        if upper.startswith("#DATA"):
            if current is not None:
                add(number, f"#DATA inside the #DATA block opened on line {current[2]}", "error")
            elif pending is None:
                add(number, "#DATA without a table declaration before it; its rows are not used",
                    rule="aip-orphan-data")
                current = ("", "", number)
            else:
                current, pending = (pending[0], pending[1], number), None
            continue
        if upper.startswith("#END_DATA"):
            if partial:
                add(partial_line, "Row does not end with ';'")
                if current is not None and current[0]:
                    rows.append(AipRow(current[0], current[1], tuple(_split_row(" ".join(partial))), partial_line))
                partial = []
            if current is None and not stray:
                add(number, "#END_DATA without #DATA", "info", "aip-orphan-data")
            current, stray = None, False
            continue
        if line.startswith("#"):
            directive = line.split(None, 2)
            if directive[0] == "#define" and len(directive) >= 2:
                defines.add(directive[1])
            elif directive[0] not in ("#include", "#define", "#undef", "#ifdef", "#ifndef", "#endif", "#else"):
                add(number, f"Unknown directive {directive[0]}")
            continue
        if line.count('"') % 2:
            add(number, "Unterminated string")
        if current is not None:                         # a row may span lines; ';' ends it
            struct, table, _start = current
            if not partial:
                partial_line = number
            partial.append(line)
            chunks = " ".join(partial).split(";")
            last = chunks.pop()
            partial = [last] if last.strip() else []
            if struct:
                rows.extend(AipRow(struct, table, tuple(_split_row(chunk)), partial_line) for chunk in chunks)
            if chunks:
                partial_line = number
            continue
        scalar = _AIP_SCALAR.match(line)
        if scalar:
            if not line.endswith(";"):
                add(number, f"'{scalar.group(2)}' does not end with ';'")
            value = scalar.group(4).rstrip(";").strip()
            if scalar.group(1) != "char" and not (_AIP_NUMBER.match(value) or value in defines):
                add(number, f"'{scalar.group(2)}' = {value}: not a number")
            continue
        array = _AIP_ARRAY.match(line)
        if array:
            struct, table = array.group(1), array.group(2)
            if not line.endswith(";"):
                add(number, f"'{table}' does not end with ';'")
            if struct not in AIP_STRUCTS:
                add(number, f"Unknown table type {struct}")
            if pending is not None:
                add(pending[2], f"Table '{pending[1]}' has no #DATA block")
            pending = (struct if struct in AIP_STRUCTS else "", table, number)
            tables[table] = number
            continue
        if line.startswith('"') or _AIP_NUMBER.match(line.split(",")[0].strip()):
            if not stray:
                stray = True
                add(number, "Data rows outside a #DATA block (is their table declaration commented out?); the "
                    "AI does not use them", "info", "aip-orphan-data")
            continue
        add(number, f"Cannot read: {line[:60]}", "error")
    if current is not None:
        add(current[2], "#DATA block is never closed by #END_DATA", "error")
    if pending is not None:
        add(pending[2], f"Table '{pending[1]}' has no #DATA block")
    if unclosed is not None:
        add(unclosed, "/* comment is never closed", "error")
    for row in rows:
        kinds = AIP_STRUCTS[row.struct]
        if len(row.fields) != len(kinds):
            add(row.line, f"{row.struct} row has {len(row.fields)} field(s), expected {len(kinds)}")
            continue
        for kind, value in zip(kinds, row.fields):
            if kind in ("odf", "account") and not _AIP_STRING.match(value):
                add(row.line, f"{value or '(empty)'}: expected a quoted name")
            elif kind == "number" and not (_AIP_NUMBER.match(value) or value in defines):
                add(row.line, f"{value or '(empty)'}: expected a number")
    problems.sort(key=lambda p: p.line)
    return rows, tables, problems



def check_aip(ctx) -> Iterator:
    for path in ctx.with_suffix(".aip"):
        ctx.check_cancel()
        rel = ctx.rel(path)
        rows, tables, problems = parse_aip(path.read_bytes().decode("latin-1"))
        for problem in problems:
            yield _issue(problem.severity, "aip", problem.message, rel, line=problem.line, rule_id=problem.rule,
                         suggestion="Compare with a stock AIP (e.g. misn05.aip)." if problem.rule == "aip-syntax"
                         else "")
        accounts = {name.lower() for name, _line in tables.items()}
        reported: Set[str] = set()
        for row in rows:
            kinds = AIP_STRUCTS[row.struct]
            if len(row.fields) != len(kinds):
                continue
            for kind, value in zip(kinds, row.fields):
                match = _AIP_STRING.match(value)
                if not match:
                    continue
                name = match.group(1)
                if kind == "account" and name.lower() not in accounts:
                    yield _issue("warning", "aip", f"Construction program funds account '{name}', which the file "
                                 "does not declare", rel, line=row.line, rule_id="aip-missing-account",
                                 suggestion=f"Add 'ACCOUNT {name}[MAX_ACCOUNT_LENGTH];' with a #DATA block, or fix "
                                 "the name.")
                elif kind == "odf" and not _odf_known(name, ctx.names_lower) and name.lower() not in reported:
                    reported.add(name.lower())
                    yield _issue("warning", "aip", f"{row.table}: '{name}' is not a stock or project ODF", rel,
                                 line=row.line, rule_id="aip-missing-odf",
                                 suggestion="The AI cannot build or weigh it. Fix the name or add the ODF.")
