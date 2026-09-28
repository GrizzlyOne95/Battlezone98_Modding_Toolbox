"""Effective ODF fields and unit/weapon stat tables.

Redux has no ODF-to-ODF inheritance (see :mod:`battlezone.odf.inheritance`):
``baseName`` never loads another ODF. What an object actually gets for a field
is decided by, in order:

1. **the ODF file itself**: the project's copy of ``name.odf``, which replaces
   the stock ODF of the same name outright (a stock copy's keys are *not*
   merged in). Within a section the last occurrence of a key wins (the 1.5
   ``ParameterDB::FileData`` constructor stores every key through an
   assignment); a ``NULL`` value is not stored at all.
2. **the prototype default**: ``classLabel`` picks an engine prototype class;
   each class level in its chain (``wingman``: WingmanClass -> HoverCraftClass
   -> CraftClass -> GameObjectClass) reads its own section, and a missing key
   keeps the prototype's value. Defaults come from the recovered loader schema
   (``validation/data/redux_odf_classes.json``); where none was recovered the
   value is shown as unknown.

A key in a section no class in the chain reads, or that the section's loader
does not read, is reported as unread: the game ignores it.

Stock ODFs (``bzone.zfs`` of a Redux install) are only used to resolve names
the project does not define (weapons, ordnance, explosions) and to show which
stock values a project copy replaces. Without a game install everything still
works for project ODFs; references to stock names are then reported as
unresolved.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import sys
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from battlezone.odf.validator import ODFDocument, parse_odf, parse_odf_bytes

DATA_DIR = Path(__file__).resolve().parents[1] / "validation" / "data"
CLASSES_FILE = DATA_DIR / "redux_odf_classes.json"
DEAD_FILE = DATA_DIR / "redux_odf_dead.json"

# Sections whose classLabel XxxClass::Find dispatches on, in the order checked.
# Redux reads the explosion label from [ExplosionClass]; a bare [Explosion]
# root still dispatches but its other keys are unread.
ROOT_SECTIONS = ("GameObjectClass", "WeaponClass", "OrdnanceClass", "ExplosionClass", "Explosion")
_FAMILY_OF_ROOT = {"gameobjectclass": "GameObjectClass", "weaponclass": "WeaponClass",
                   "ordnanceclass": "OrdnanceClass", "explosionclass": "ExplosionClass",
                   "explosion": "ExplosionClass"}
_ODF_REFERENCE_TYPES = ("odf_reference", "odf_reference-indexed")
_NUMBER = re.compile(r"^\s*[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")
_NO_LIFESPAN = 1e29   # OrdnanceClass lifeSpan default is 1e30: never expires

# Prototype labels the loader schema records without a label (see
# class_labels.REDUX_CLASS_LABELS): i76building2 and i76sign are BuildingClass
# variants a static initialiser registers; radarlauncher and lobber come from
# the 1.5 loader schema.
LABEL_ALIASES = {
    ("GameObjectClass", "i76building2"): "BuildingClass",
    ("GameObjectClass", "i76sign"): "BuildingClass",
    ("WeaponClass", "radarlauncher"): "RadarLauncherClass",
    ("WeaponClass", "lobber"): "ObjectLobberClass",
}
_NOT_AN_OBJECT = "not an object ODF"


# ---------------------------------------------------------------------------
# Class model
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class KeyDef:
    name: str                     # "shotDelay", or "weaponName#" for an indexed family
    type: str
    default: object = None        # compiled prototype default, when recovered
    has_default: bool = False
    default_from: str = ""        # defaults to another key of the same section
    default_note: str = ""        # derived at load time (e.g. "ordnance-derived")

    @property
    def indexed(self) -> bool:
        return self.name.endswith("#")

    def matches(self, key_lower: str) -> bool:
        if self.indexed:
            base = self.name[:-1].lower()
            return key_lower.startswith(base) and key_lower[len(base):].isdigit()
        return key_lower == self.name.lower()


@dataclass(frozen=True)
class ClassDef:
    name: str
    base: str
    section: str
    label: str
    keys: Tuple[KeyDef, ...]


class ClassModel:
    """Prototype classes: chain, family (dispatch root) and label lookup."""

    def __init__(self, data: dict):
        self.classes: Dict[str, ClassDef] = {}
        for name, entry in data.get("classes", {}).items():
            keys = tuple(KeyDef(k["name"], k.get("type", ""), k.get("default"), "default" in k,
                                k.get("default_from", ""), k.get("default_note", ""))
                         for k in entry.get("keys", ()))
            self.classes[name] = ClassDef(name, entry.get("base", ""), entry.get("section", ""),
                                          entry.get("label", ""), keys)
        self.by_section: Dict[str, List[str]] = {}
        for cls in self.classes.values():
            if cls.section:
                self.by_section.setdefault(cls.section.lower(), []).append(cls.name)
        self._labels: Dict[Tuple[str, str], str] = {}
        for cls in self.classes.values():
            if cls.label:
                self._labels.setdefault((self.family(cls.name), cls.label.lower()), cls.name)
        for (family, label), name in LABEL_ALIASES.items():
            if name in self.classes and self.family(name) == family:
                self._labels.setdefault((family, label), name)

    def chain(self, name: str) -> Tuple[str, ...]:
        """``name`` and its bases, leaf first. Stops at an unknown base or a cycle."""
        out: List[str] = []
        while name in self.classes and name not in out:
            out.append(name)
            name = self.classes[name].base
        return tuple(out)

    def family(self, name: str) -> str:
        chain = self.chain(name)
        return chain[-1] if chain else ""

    def resolve(self, family: str, label: str) -> Optional[str]:
        return self._labels.get((family, label.lower()))

    def labels(self, family: str) -> List[str]:
        return sorted(label for fam, label in self._labels if fam == family)


@lru_cache(maxsize=1)
def class_model() -> ClassModel:
    try:
        return ClassModel(json.loads(CLASSES_FILE.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return ClassModel({})


@lru_cache(maxsize=1)
def _dead_sections() -> Dict[str, str]:
    try:
        data = json.loads(DEAD_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {key: entry.get("read_instead", "") for key, entry in data.get("sections", {}).items()}


# ---------------------------------------------------------------------------
# Values
# ---------------------------------------------------------------------------

def engine_value(raw: str) -> Optional[str]:
    """What the loader stores for a raw ``key = value`` right-hand side.

    ``NULL`` is not stored (None). A quoted value runs to the closing quote;
    anything else ends at the first whitespace, so a trailing ``// comment``
    is not part of it (1.5 ``ParameterDB::FileData`` parser).
    """
    text = raw.strip()
    if text[:4].upper() == "NULL":
        return None
    if text[:1] in ('"', "'"):
        end = text.find(text[0], 1)
        return text[1:end] if end >= 0 else text[1:]
    return text.split(None, 1)[0] if text else ""


def number(value: Optional[str]) -> Optional[float]:
    """Leading number of a value, like the C runtime's ``atof`` (None when there is none)."""
    if value is None:
        return None
    match = _NUMBER.match(value)
    return float(match.group(0)) if match else None


def _format_default(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float) and value.is_integer() and abs(value) < 1e15:
        return str(int(value)) if abs(value) >= 1 or value == 0 else repr(value)
    return str(value)


def _odf_name(value: str) -> str:
    name = value.strip().replace("\\", "/").rsplit("/", 1)[-1]
    return name[:-4] if name.lower().endswith(".odf") else name


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ODFEntry:
    name: str          # lower-case base name without .odf
    filename: str      # as spelled on disk / in the archive
    origin: str        # "project" or "stock"
    location: str      # project: absolute path; stock: the archive path
    rel: str           # project: path relative to the project; stock: "bzone.zfs"

    @property
    def label(self) -> str:
        return self.rel if self.origin == "project" else f"stock {self.filename}"


@dataclass(frozen=True)
class Origin:
    """One candidate value for a field.

    ``kind``: ``file`` (the stored ODF value), ``ignored`` (an earlier
    duplicate or a ``NULL``), ``stock`` (the stock copy's value the project
    file replaces), ``default`` (known prototype default) or ``parent``
    (prototype value not recovered).
    """
    value: Optional[str]
    source: str
    kind: str


@dataclass(frozen=True)
class Field:
    section: str
    key: str
    status: str                    # "set" (from the ODF), "default" (prototype) or "unread"
    chain: Tuple[Origin, ...]      # effective value first, then what it replaces
    reader: str = ""               # class whose loader reads the key
    type: str = ""
    note: str = ""

    @property
    def value(self) -> Optional[str]:
        return self.chain[0].value if self.chain else None

    @property
    def source(self) -> str:
        return self.chain[0].source if self.chain else ""

    @property
    def inherited(self) -> bool:
        return self.status == "default"

    @property
    def overridden(self) -> bool:
        """The ODF's value replaces a stock copy's value or a known prototype default."""
        return self.status == "set" and any(o.kind in ("stock", "default") for o in self.chain[1:])


@dataclass(frozen=True)
class Dispatch:
    root: str                 # section classLabel was read from ("" if none)
    label: str
    family: str
    cls: str                  # engine class ("" if the label is unknown)
    chain: Tuple[str, ...]    # leaf first
    problem: str = ""

    def describe(self) -> str:
        if not self.cls:
            return self.problem or "no class"
        return f"{self.label}: " + " -> ".join(self.chain)


@dataclass
class EffectiveODF:
    name: str
    entry: ODFEntry
    dispatch: Dispatch
    fields: List[Field]
    replaces_stock: bool = False
    other_copies: List[ODFEntry] = field(default_factory=list)

    def get(self, key: str) -> Optional[Field]:
        """The read field for ``key``, leaf class first (unread keys are skipped)."""
        key = key.lower()
        for item in reversed(self.fields):
            if item.status != "unread" and item.key.lower() == key:
                return item
        return None

    def value(self, key: str) -> Optional[str]:
        item = self.get(key)
        return item.value if item else None

    def sections(self) -> List[str]:
        seen: List[str] = []
        for item in self.fields:
            if item.section not in seen:
                seen.append(item.section)
        return seen


@dataclass(frozen=True)
class Problem:
    odf: str
    kind: str        # "dispatch", "reference", "duplicate"
    message: str


# ---------------------------------------------------------------------------
# Library
# ---------------------------------------------------------------------------

def find_stock_archive(game_dir) -> Optional[Path]:
    """``bzone.zfs`` of a Redux install (or the archive itself when given one)."""
    if not game_dir:
        return None
    path = Path(game_dir)
    if path.is_file() and path.suffix.lower() == ".zfs":
        return path
    candidate = path / "bzone.zfs"
    return candidate if candidate.is_file() else None


class ODFLibrary:
    """The project's ODFs plus stock ODFs to resolve names the project does not define."""

    def __init__(self, project_dir=None, game_dir=None, stock: bool = True, model: Optional[ClassModel] = None):
        self.model = model or class_model()
        self.project_dir = Path(project_dir) if project_dir else None
        self.project: Dict[str, ODFEntry] = {}
        self.duplicates: Dict[str, List[ODFEntry]] = {}
        self.stock: Dict[str, ODFEntry] = {}
        self.stock_source = ""
        self.warnings: List[str] = []
        self._docs: Dict[Tuple[str, str], ODFDocument] = {}
        self._effective: Dict[str, EffectiveODF] = {}
        self._archive = None
        if self.project_dir is not None:
            self._scan_project()
        if stock:
            self._load_stock(game_dir)

    # --- loading -----------------------------------------------------------------
    def _scan_project(self) -> None:
        if not self.project_dir.is_dir():
            self.warnings.append(f"Project folder not found: {self.project_dir}")
            return
        copies: Dict[str, List[ODFEntry]] = {}
        for root, dirs, files in os.walk(self.project_dir):
            dirs.sort(key=str.lower)
            for filename in sorted(files, key=str.lower):
                if not filename.lower().endswith(".odf"):
                    continue
                path = Path(root) / filename
                rel = path.relative_to(self.project_dir).as_posix()
                name = filename[:-4].lower()
                copies.setdefault(name, []).append(ODFEntry(name, filename, "project", str(path), rel))
        for name, entries in copies.items():
            # Shallowest copy first: which copy the game loads when a mod ships
            # several is not determined here, so all of them are reported.
            entries.sort(key=lambda e: (e.rel.count("/"), e.rel.lower()))
            self.project[name] = entries[0]
            if len(entries) > 1:
                self.duplicates[name] = entries

    def _load_stock(self, game_dir) -> None:
        archive_path = find_stock_archive(game_dir)
        if archive_path is None:
            self.warnings.append("No Battlezone 98 Redux install (bzone.zfs) given: stock ODFs are not "
                                 "available, so names the project does not define stay unresolved.")
            return
        try:
            from battlezone.archives.zfs import ZFSArchive

            archive = ZFSArchive(archive_path)
        except Exception as exc:   # unreadable or not a ZFS
            self.warnings.append(f"Could not read {archive_path}: {exc}")
            return
        self._archive = archive
        self.stock_source = str(archive_path)
        for entry in archive:
            filename = entry.name.replace("\\", "/").rsplit("/", 1)[-1]
            if filename.lower().endswith(".odf"):
                name = filename[:-4].lower()
                self.stock.setdefault(name, ODFEntry(name, filename, "stock", str(archive_path), archive_path.name))

    # --- lookup ------------------------------------------------------------------
    def project_names(self) -> List[str]:
        return sorted(self.project)

    def entry(self, name: str) -> Optional[ODFEntry]:
        name = _odf_name(name).lower()
        return self.project.get(name) or self.stock.get(name)

    def document(self, entry: ODFEntry) -> Optional[ODFDocument]:
        key = (entry.origin, entry.name)
        if key not in self._docs:
            try:
                if entry.origin == "project":
                    doc = parse_odf(Path(entry.location))
                else:
                    doc = parse_odf_bytes(self._archive.read(entry.filename), f"{entry.rel}/{entry.filename}")
            except (OSError, KeyError, ValueError) as exc:
                self.warnings.append(f"Could not read {entry.label}: {exc}")
                return None
            self._docs[key] = doc
        return self._docs[key]

    def dispatch(self, doc: ODFDocument) -> Dispatch:
        present = [root for root in ROOT_SECTIONS if root.lower() in doc.sections]
        for root in present:
            label = _stored(doc, root, "classLabel")
            if label is None:
                continue
            family = _FAMILY_OF_ROOT[root.lower()]
            cls = self.model.resolve(family, label)
            if cls is None:
                return Dispatch(root, label, family, "", (),
                                f"classLabel \"{label}\" in [{root}] is not a Redux {family} prototype label")
            return Dispatch(root, label, family, cls, self.model.chain(cls))
        if present:
            return Dispatch(present[0], "", _FAMILY_OF_ROOT[present[0].lower()], "", (),
                            f"[{present[0]}] has no classLabel: the object cannot be built")
        if "gameobject" in doc.sections:
            return Dispatch("", "", "", "", (), "legacy [GameObject] root: Redux dispatches from [GameObjectClass]")
        return Dispatch("", "", "", "", (), f"{_NOT_AN_OBJECT}: no [GameObjectClass], [WeaponClass], "
                                            "[OrdnanceClass] or [ExplosionClass] section")

    # --- effective fields --------------------------------------------------------
    def effective(self, name: str) -> Optional[EffectiveODF]:
        """Every field of ``name`` with its effective value and where it comes from (None: no such ODF)."""
        entry = self.entry(name)
        if entry is None:
            return None
        if entry.name in self._effective and self._effective[entry.name].entry == entry:
            return self._effective[entry.name]
        doc = self.document(entry)
        if doc is None:
            return None
        stock_entry = self.stock.get(entry.name) if entry.origin == "project" else None
        stock_doc = self.document(stock_entry) if stock_entry else None
        dispatch = self.dispatch(doc)
        fields = _fields(self.model, entry, doc, dispatch, stock_entry, stock_doc)
        result = EffectiveODF(entry.name, entry, dispatch, fields, replaces_stock=stock_doc is not None,
                              other_copies=[e for e in self.duplicates.get(entry.name, ()) if e != entry])
        self._effective[entry.name] = result
        return result

    def effective_fields(self, name: str) -> List[Field]:
        result = self.effective(name)
        return result.fields if result else []

    # --- problems ----------------------------------------------------------------
    def problems(self) -> List[Problem]:
        """Dispatch failures, unresolved ODF references and duplicate project files."""
        out: List[Problem] = []
        for name in self.project_names():
            eff = self.effective(name)
            if eff is None:
                continue
            if eff.dispatch.problem and not eff.dispatch.problem.startswith(_NOT_AN_OBJECT):
                out.append(Problem(eff.entry.rel, "dispatch", eff.dispatch.problem))
            for item in eff.fields:
                if item.status != "set" or item.type not in _ODF_REFERENCE_TYPES or not item.value:
                    continue
                if item.key.lower() == "basename":
                    continue   # a name code for .inf text, not an ODF the game loads
                if self.entry(item.value) is None:
                    where = "in the project or stock" if self.stock else "in the project (stock ODFs not loaded)"
                    out.append(Problem(eff.entry.rel, "reference",
                                       f"[{item.section}] {item.key} = {item.value}: no {_odf_name(item.value)}.odf "
                                       f"{where}"))
        for name, entries in sorted(self.duplicates.items()):
            out.append(Problem(entries[0].rel, "duplicate",
                               f"{len(entries)} copies of {entries[0].filename}: " + ", ".join(e.rel for e in entries)))
        return out

    # --- stat tables -------------------------------------------------------------
    def craft_rows(self) -> List[dict]:
        rows = []
        for name in self.project_names():
            eff = self.effective(name)
            if eff is not None and "CraftClass" in eff.dispatch.chain:
                rows.append(craft_row(self, eff))
        return rows

    def weapon_rows(self) -> List[dict]:
        rows = []
        for name in self.project_names():
            eff = self.effective(name)
            if eff is not None and eff.dispatch.family == "WeaponClass" and eff.dispatch.cls:
                rows.append(weapon_row(self, eff))
        return rows


def _stored(doc: ODFDocument, section: str, key: str) -> Optional[str]:
    """The value the loader keeps for ``[section] key`` (last non-NULL occurrence)."""
    value = None
    for name, raw, _line in doc.sections.get(section.lower(), ()):
        if name.lower() == key.lower():
            stored = engine_value(raw)
            if stored is not None:
                value = stored
    return value


def _physical(doc: ODFDocument, section: str) -> Dict[str, List[Tuple[str, str, int]]]:
    out: Dict[str, List[Tuple[str, str, int]]] = {}
    for key, raw, line in doc.sections.get(section.lower(), ()):
        if key.startswith("//"):
            continue
        out.setdefault(key.lower(), []).append((key, raw, line))
    return out


def _index_sort(key: str):
    digits = re.search(r"(\d+)$", key)
    return (key[:digits.start()].lower(), int(digits.group(1))) if digits else (key.lower(), 0)


def _file_origins(where: str, occurrences) -> Tuple[bool, List[Origin]]:
    """Values of one key in one file: the stored one first, then ignored duplicates and NULLs."""
    stored = None
    for index, (_key, raw, _line) in enumerate(occurrences):
        if engine_value(raw) is not None:
            stored = index
    out = []
    if stored is not None:
        out.append(Origin(engine_value(occurrences[stored][1]), f"{where}:{occurrences[stored][2]}", "file"))
    for index, (_key, raw, line) in enumerate(occurrences):
        if index != stored:
            value = engine_value(raw)
            why = "NULL, not stored" if value is None else "earlier duplicate, replaced"
            out.append(Origin(value, f"{where}:{line} ({why})", "ignored"))
    return stored is not None, out


def _default_origin(cls: ClassDef, key: KeyDef) -> Origin:
    if key.has_default:
        return Origin(_format_default(key.default), f"{cls.name} prototype default", "default")
    if key.default_from:
        return Origin(None, f"{cls.name} prototype: same as {key.default_from}", "parent")
    if key.default_note:
        return Origin(None, f"{cls.name} prototype ({key.default_note})", "parent")
    return Origin(None, "parent prototype (value not recovered)", "parent")


def _unread_note(model: ClassModel, dispatch: Dispatch, section_lower: str, display: str, key: str,
                 chain_sections: set) -> str:
    dead = _dead_sections()
    if section_lower in chain_sections:
        return f"the [{display}] loader does not read {key}"
    if section_lower in dead:
        instead = dead[section_lower]
        return f"Redux never reads [{display}]" + (f"; it reads [{instead}]" if instead else "")
    if section_lower == "explosion" and dispatch.family == "ExplosionClass":
        return "[Explosion] only dispatches; Redux reads explosion fields from [ExplosionClass]"
    if section_lower in model.by_section:
        if not dispatch.cls:
            return f"[{display}] is not read: the object has no class"
        owners = ", ".join(model.by_section[section_lower])
        return f"[{display}] is read by {owners}, which is not in this object's class chain"
    return f"[{display}] is not an object-class section (render/effect sections are read where referenced)"


def _fields(model: ClassModel, entry: ODFEntry, doc: ODFDocument, dispatch: Dispatch,
            stock_entry: Optional[ODFEntry], stock_doc: Optional[ODFDocument]) -> List[Field]:
    """Read fields per class level (root class first), then every key the chain does not read."""
    fields: List[Field] = []
    consumed: Dict[str, set] = {}
    root = dispatch.root.lower()
    where = entry.rel if entry.origin == "project" else f"stock {entry.filename}"

    def stock_origins(section: str, key_lower: str) -> List[Origin]:
        if stock_doc is None:
            return []
        value = _stored(stock_doc, section, key_lower)
        occurrences = _physical(stock_doc, section).get(key_lower, [])
        if value is None or not occurrences:
            return []
        return [Origin(value, f"stock {stock_entry.filename}:{occurrences[-1][2]} (replaced by the project file)",
                       "stock")]

    def field_for(cls_name: str, section: str, display: str, key: KeyDef, key_lower: str, occurrences,
                  fallback: Origin) -> Field:
        stored, origins = _file_origins(where, occurrences)
        replaced = stock_origins(section, key_lower)
        spelled = occurrences[-1][0] if occurrences else key.name
        if stored:
            return Field(display, spelled, "set", tuple(origins + replaced + [fallback]), cls_name, key.type)
        return Field(display, spelled, "default", tuple([fallback] + origins + replaced), cls_name, key.type)

    for cls_name in reversed(dispatch.chain):
        cls = model.classes[cls_name]
        if not cls.section:
            continue
        section = cls.section
        display = doc.original_sections.get(section.lower(), section)
        physical = _physical(doc, section)
        used = consumed.setdefault(section.lower(), set())
        keys = list(cls.keys)
        if section.lower() == root:
            keys.insert(0, KeyDef("classLabel", "string"))
        section_fields: List[Field] = []
        for key in keys:
            if key.name == "classLabel":
                fallback = Origin(None, "missing: the object cannot be dispatched", "parent")
            else:
                fallback = _default_origin(cls, key)
            names = [key.name.lower()]
            if key.indexed:
                names = sorted((k for k in physical if key.matches(k)), key=_index_sort)
                if not names:
                    section_fields.append(Field(display, key.name, "default", (fallback,), cls_name, key.type))
                    continue
            for key_lower in names:
                used.add(key_lower)
                section_fields.append(field_for(cls_name, section, display, key, key_lower,
                                                physical.get(key_lower, []), fallback))
        # "same as <key>" defaults take that key's effective value in this section.
        values = {f.key.lower(): f.value for f in section_fields}
        for index, item in enumerate(section_fields):
            head = item.chain[0]
            if item.status == "default" and ": same as " in head.source:
                value = values.get(head.source.rsplit("same as ", 1)[1].lower())
                if value is not None:
                    section_fields[index] = Field(item.section, item.key, item.status,
                                                  (Origin(value, head.source, "default"),) + item.chain[1:],
                                                  item.reader, item.type, item.note)
        fields.extend(section_fields)

    chain_sections = {model.classes[c].section.lower() for c in dispatch.chain if model.classes[c].section}
    for section_lower in doc.sections:
        display = doc.original_sections.get(section_lower, section_lower)
        used = consumed.get(section_lower, set())
        for key_lower, occurrences in _physical(doc, section_lower).items():
            if key_lower in used:
                continue
            _stored_ok, origins = _file_origins(where, occurrences)
            if section_lower == root and key_lower == "classlabel":
                # Read for dispatch; shown here when the label did not resolve to a class.
                fields.insert(0, Field(display, occurrences[-1][0], "set", tuple(origins), "",
                                       "string", dispatch.problem))
                continue
            note = _unread_note(model, dispatch, section_lower, display, occurrences[-1][0], chain_sections)
            fields.append(Field(display, occurrences[-1][0], "unread", tuple(origins), "", "", note))
    return fields



# ---------------------------------------------------------------------------
# Stat tables
# ---------------------------------------------------------------------------

# (column, description). Keys are read through the effective fields, so a
# missing key shows the prototype default when one was recovered and is
# listed in "defaulted".
CRAFT_COLUMNS: Tuple[Tuple[str, str], ...] = (
    ("odf", "ODF name"),
    ("file", "project file"),
    ("unitName", "[GameObjectClass] unitName"),
    ("classLabel", "classLabel"),
    ("class", "engine class the label selects"),
    ("scrapCost", "[GameObjectClass] scrapCost (build cost)"),
    ("scrapValue", "[GameObjectClass] scrapValue (scrap returned)"),
    ("pilotCost", "[GameObjectClass] pilotCost"),
    ("buildTime", "[GameObjectClass] buildTime (s)"),
    ("maxHealth", "[GameObjectClass] maxHealth (hit points)"),
    ("maxAmmo", "[GameObjectClass] maxAmmo"),
    ("rangeScan", "[CraftClass] rangeScan (radar range)"),
    ("speedForward", "[HoverCraftClass] velocForward; walkers/persons: velocForwardRun"),
    ("speedReverse", "[HoverCraftClass] velocReverse; walkers/persons: velocReverseRun"),
    ("speedStrafe", "[HoverCraftClass] velocStrafe; walkers/persons: velocStrafeRun"),
    ("accelThrust", "[HoverCraftClass] accelThrust; walkers/persons: accelThrustRun"),
    ("turnRate", "[HoverCraftClass] omegaTurn; walkers/persons: omegaTurnRun"),
    ("weapons", "[GameObjectClass] weaponHardN=weaponNameN (N = 1..5)"),
    ("defaulted", "keys taken from the prototype (not in the ODF)"),
)

WEAPON_COLUMNS: Tuple[Tuple[str, str], ...] = (
    ("odf", "ODF name"),
    ("file", "project file"),
    ("wpnName", "[WeaponClass] wpnName"),
    ("classLabel", "classLabel"),
    ("class", "engine class the label selects"),
    ("ordName", "[WeaponClass] ordName (ordnance ODF)"),
    ("ordnanceFrom", "where the ordnance ODF was found: project, stock or missing"),
    ("ordnanceClass", "the ordnance's classLabel"),
    ("shotDelay", "shotDelay of the weapon's class chain ([CannonClass], [LauncherClass], ...), s between shots"),
    ("shotsPerSecond", "1 / shotDelay"),
    ("ammoCost", "[SpecialItemClass] ammoCost for special items, else the ordnance's [OrdnanceClass] ammoCost"),
    ("damageBallistic", "ordnance [OrdnanceClass] damageBallistic"),
    ("damageConcussion", "ordnance [OrdnanceClass] damageConcussion"),
    ("damageFlame", "ordnance [OrdnanceClass] damageFlame"),
    ("damageImpact", "ordnance [OrdnanceClass] damageImpact"),
    ("damageTotal", "sum of the four damage values (direct hit)"),
    ("dps", "damageTotal * shotsPerSecond (direct hits, no salvo)"),
    ("shotSpeed", "ordnance [OrdnanceClass] shotSpeed"),
    ("lifeSpan", "ordnance [OrdnanceClass] lifeSpan (s)"),
    ("range", "shotSpeed * lifeSpan (straight flight; missiles accelerate)"),
    ("xplVehicle", "ordnance [OrdnanceClass] xplVehicle (explosion on a vehicle hit)"),
    ("splashRadius", "that explosion's [ExplosionClass] damageRadius"),
    ("splashDamage", "sum of that explosion's four [ExplosionClass] damage values"),
    ("defaulted", "keys taken from a prototype (not in the ODFs)"),
)

_DAMAGE_KEYS = ("damageBallistic", "damageConcussion", "damageFlame", "damageImpact")


def _num_text(value: Optional[float]) -> str:
    if value is None:
        return ""
    if value.is_integer() and abs(value) < 1e15:
        return str(int(value))
    return f"{value:.4g}"


class _Reader:
    """Reads effective values and remembers which came from a prototype."""

    def __init__(self, eff: EffectiveODF, prefix: str = ""):
        self.eff = eff
        self.prefix = prefix
        self.defaulted: List[str] = []

    def text(self, key: str) -> str:
        item = self.eff.get(key)
        if item is None:
            return ""
        if item.status == "default":
            self.defaulted.append(self.prefix + item.key)
        return item.value or ""

    def num(self, key: str) -> Optional[float]:
        return number(self.text(key))


def craft_row(library: ODFLibrary, eff: EffectiveODF) -> dict:
    read = _Reader(eff)
    chain = eff.dispatch.chain
    legs = "WalkerClass" in chain or "PersonClass" in chain
    suffix = "Run" if legs else ""
    moves = legs or "HoverCraftClass" in chain
    row = {"odf": eff.name, "file": eff.entry.rel, "unitName": read.text("unitName"),
           "classLabel": eff.dispatch.label, "class": eff.dispatch.cls}
    for column in ("scrapCost", "scrapValue", "pilotCost", "buildTime", "maxHealth", "maxAmmo", "rangeScan"):
        row[column] = _num_text(read.num(column))
    for column, key in (("speedForward", "velocForward"), ("speedReverse", "velocReverse"),
                        ("speedStrafe", "velocStrafe"), ("accelThrust", "accelThrust"), ("turnRate", "omegaTurn")):
        row[column] = _num_text(read.num(key + suffix)) if moves else ""
    weapons = []
    hard = {f.key.lower()[len("weaponhard"):]: f.value for f in eff.fields
            if f.status == "set" and f.key.lower().startswith("weaponhard")}
    for item in eff.fields:
        if item.status == "set" and item.key.lower().startswith("weaponname") and item.value:
            index = item.key.lower()[len("weaponname"):]
            found = library.entry(item.value)
            mark = "" if found is None or found.origin == "project" else " (stock)"
            if found is None:
                mark = " (missing)"
            weapons.append(f"{hard.get(index) or '?'}={item.value}{mark}")
    row["weapons"] = "; ".join(weapons)
    row["defaulted"] = ", ".join(read.defaulted)
    return row


def weapon_row(library: ODFLibrary, eff: EffectiveODF) -> dict:
    read = _Reader(eff)
    row = {"odf": eff.name, "file": eff.entry.rel, "wpnName": read.text("wpnName"),
           "classLabel": eff.dispatch.label, "class": eff.dispatch.cls}
    shot_delay = read.num("shotDelay") if eff.get("shotDelay") else None
    row["shotDelay"] = _num_text(shot_delay)
    row["shotsPerSecond"] = f"{1 / shot_delay:.3g}" if shot_delay and shot_delay > 0 else ""
    ord_name = eff.value("ordName") or ""
    row["ordName"] = ord_name
    ordnance = library.effective(ord_name) if ord_name else None
    row["ordnanceFrom"] = ordnance.entry.origin if ordnance else ("missing" if ord_name else "")
    row["ordnanceClass"] = ordnance.dispatch.label if ordnance else ""
    ord_read = _Reader(ordnance, f"{ordnance.name}:") if ordnance else None
    if "SpecialItemClass" in eff.dispatch.chain:
        row["ammoCost"] = _num_text(read.num("ammoCost"))
    else:
        row["ammoCost"] = _num_text(ord_read.num("ammoCost")) if ord_read else ""
    total = None
    for key in _DAMAGE_KEYS:
        value = ord_read.num(key) if ord_read else None
        row[key] = _num_text(value)
        if value is not None:
            total = (total or 0.0) + value
    row["damageTotal"] = _num_text(total)
    row["dps"] = f"{total / shot_delay:.4g}" if total is not None and shot_delay and shot_delay > 0 else ""
    speed = ord_read.num("shotSpeed") if ord_read else None
    life = ord_read.num("lifeSpan") if ord_read else None
    row["shotSpeed"] = _num_text(speed)
    row["lifeSpan"] = "" if life is None or life >= _NO_LIFESPAN else _num_text(life)
    row["range"] = (_num_text(speed * life) if speed is not None and life is not None and life < _NO_LIFESPAN
                    else "")
    xpl = (ord_read.text("xplVehicle") if ord_read else "") or ""
    row["xplVehicle"] = xpl
    explosion = library.effective(xpl) if xpl else None
    if explosion is not None and explosion.dispatch.family == "ExplosionClass":
        xpl_read = _Reader(explosion, f"{explosion.name}:")
        row["splashRadius"] = _num_text(xpl_read.num("damageRadius"))
        values = [xpl_read.num(k) for k in _DAMAGE_KEYS]
        row["splashDamage"] = _num_text(sum(v for v in values if v is not None)) if any(
            v is not None for v in values) else ""
        read.defaulted.extend(xpl_read.defaulted)
    else:
        row["splashRadius"] = row["splashDamage"] = ""
    if ord_read:
        read.defaulted.extend(ord_read.defaulted)
    row["defaulted"] = ", ".join(read.defaulted)
    return row


def write_csv(rows: Sequence[dict], columns: Sequence[Tuple[str, str]], target) -> None:
    """Write ``rows`` with ``columns`` (header = column names) to a path or text stream."""
    names = [c[0] for c in columns]
    if isinstance(target, (str, os.PathLike)):
        with open(target, "w", encoding="utf-8", newline="") as handle:
            write_csv(rows, columns, handle)
        return
    writer = csv.DictWriter(target, fieldnames=names, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)


def sort_key(value: str):
    """Numbers before text, numbers by value (for sortable tables)."""
    parsed = number(value) if value and _NUMBER.fullmatch(value.strip()) else None
    return (0, parsed, "") if parsed is not None else (1 if value else 2, 0.0, (value or "").lower())


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _library_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("project", help="mod folder")
    parser.add_argument("--game", help="Battlezone 98 Redux install folder (or its bzone.zfs) for stock ODFs")
    parser.add_argument("--no-stock", action="store_true", help="do not load stock ODFs")


def _open(args, game_dir) -> ODFLibrary:
    library = ODFLibrary(args.project, None if args.no_stock else (args.game or game_dir), stock=not args.no_stock)
    for warning in library.warnings:
        print(f"note: {warning}", file=sys.stderr)
    return library


def _print_table(rows: Sequence[dict], columns: Sequence[Tuple[str, str]], out) -> None:
    names = [c[0] for c in columns if c[0] not in ("file", "defaulted")]
    widths = {n: min(40, max([len(n)] + [len(str(r.get(n, ""))) for r in rows])) for n in names}
    out.write("  ".join(n.ljust(widths[n]) for n in names).rstrip() + "\n")
    for row in rows:
        out.write("  ".join(str(row.get(n, ""))[:40].ljust(widths[n]) for n in names).rstrip() + "\n")


def stats_main(argv: Optional[Sequence[str]] = None, game_dir=None) -> int:
    parser = argparse.ArgumentParser(prog="bztoolbox odf stats",
                                     description="Craft and weapon stat tables from a project's effective ODF values.")
    _library_args(parser)
    parser.add_argument("--kind", choices=("craft", "weapon"), help="only this table (default: both)")
    parser.add_argument("--csv", metavar="OUT", help="write CSV; without --kind, OUT-craft.csv and OUT-weapon.csv")
    args = parser.parse_args(argv)
    if not Path(args.project).is_dir():
        parser.error(f"not a folder: {args.project}")
    library = _open(args, game_dir)
    tables = [(kind, rows, columns) for kind, rows, columns in (
        ("craft", library.craft_rows, CRAFT_COLUMNS), ("weapon", library.weapon_rows, WEAPON_COLUMNS))
        if args.kind in (None, kind)]
    for kind, rows_fn, columns in tables:
        rows = rows_fn()
        if args.csv:
            target = args.csv
            if args.kind is None:
                stem, ext = os.path.splitext(args.csv)
                target = f"{stem}-{kind}{ext or '.csv'}"
            write_csv(rows, columns, target)
            print(f"{len(rows)} {kind} row(s) written to {target}")
        else:
            print(f"== {kind} ({len(rows)})")
            _print_table(rows, columns, sys.stdout)
    return 0


_MARKS = {"set": " ", "default": "~", "unread": "!"}


def _shown(value: Optional[str]) -> str:
    return "(unknown)" if value is None else (value if value else '""')


def format_effective(eff: EffectiveODF, defaults: bool = True) -> str:
    out = io.StringIO()
    out.write(f"{eff.entry.label}\n")
    out.write(f"class: {eff.dispatch.describe()}\n")
    if eff.replaces_stock:
        out.write(f"replaces stock {eff.entry.filename}: stock keys missing from the project copy are not used\n")
    for other in eff.other_copies:
        out.write(f"other copy: {other.rel}\n")
    out.write("  ' ' from the ODF   '~' prototype default   '!' not read by the game\n")
    for section in eff.sections():
        rows = [f for f in eff.fields if f.section == section and (defaults or f.status != "default")]
        if not rows:
            continue
        out.write(f"\n[{section}]\n")
        width = max(len(f.key) for f in rows)
        for item in rows:
            line = f"{_MARKS[item.status]} {item.key.ljust(width)} = {_shown(item.value)}"
            detail = item.note if item.status == "unread" else item.source
            out.write(f"{line}    <- {detail}\n")
            for replaced in item.chain[1:]:
                if replaced.kind in ("stock", "ignored") and item.status != "unread":
                    out.write(f"  {' ' * width}   replaces {_shown(replaced.value)}  ({replaced.source})\n")
    return out.getvalue()


def show_main(argv: Optional[Sequence[str]] = None, game_dir=None) -> int:
    parser = argparse.ArgumentParser(prog="bztoolbox odf show",
                                     description="Effective fields of one ODF and where each value comes from.")
    _library_args(parser)
    parser.add_argument("name", help="ODF name (with or without .odf)")
    parser.add_argument("--no-defaults", action="store_true", help="hide fields the ODF does not set")
    args = parser.parse_args(argv)
    library = _open(args, game_dir)
    eff = library.effective(args.name)
    if eff is None:
        print(f"error: no {_odf_name(args.name)}.odf in the project"
              + (" or stock" if library.stock else ""), file=sys.stderr)
        return 1
    sys.stdout.write(format_effective(eff, defaults=not args.no_defaults))
    return 0


if __name__ == "__main__":
    raise SystemExit(stats_main())
