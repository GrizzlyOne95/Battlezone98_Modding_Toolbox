"""Workshop content scanner (moved from the Workshop Uploader).

Used by the Publishing module for its upload readiness checks and by the
unified :mod:`battlezone.validation` engine.
"""

import configparser
import hashlib
import os
import re

from battlezone.terrain.trn import TRNDocument

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
_INDEX_SUFFIX = re.compile(r"\d+$")


def _param_allowed(key, allowed):
    """``key`` is listed, or is ``base<digits>`` for a listed ``base#`` family."""
    if key in allowed:
        return True
    match = _INDEX_SUFFIX.search(key)
    return bool(match) and key[:match.start()] + "#" in allowed


# Keys that make a section part of the particle/render system. Those sections
# have user-chosen names ([Light], [ShockSphere], ...), so they are never in
# the class header list.
RENDER_KEYS = frozenset({"renderbase", "simulatebase"})
_SECTION_REF = re.compile(r"\.([A-Za-z_][\w]*)\s*$")
_FILE_EXTENSIONS = frozenset({
    "odf", "tga", "dds", "png", "bmp", "jpg", "pic", "map", "wav", "ogg", "msh", "xsi", "geo", "vdf",
    "sdf", "mesh", "skeleton", "material", "lua", "des", "bzn", "trn", "hg2", "mat", "lgt", "act", "cfg",
})


# BZ2/BZCC fields that turn up in Redux ODFs copied from BZCC. Redux ignores
# them silently, so they get a pointed hint instead of "Unknown Field".
# Redux reads damage only from these four keys; if a section sets none of
# them the damage is inherited (Battlezone_Source BZ1/research/ODF_REFERENCE.md).
REDUX_DAMAGE_KEYS = frozenset({"damageballistic", "damageconcussion", "damageflame", "damageimpact"})
BZ2_FIELDS = (
    (re.compile(r"^damagevalue\(\w+\)$", re.I),
     "BZ2/BZCC field, ignored by Redux. Use damageBallistic / damageConcussion / damageFlame / damageImpact"),
    # Redux's explosion loader reads particleClass/Count/Veloc/Bias only.
    (re.compile(r"^particle(inherit|posvar)\d+$", re.I),
     "BZ2/BZCC particle field, ignored by Redux (it reads particleClass/Count/Veloc/Bias)"),
)


_DEAD = None


def load_dead_rules():
    """Sections Redux never reads and keys that are dead where they are written.

    ``data/redux_odf_dead.json`` comes from the recovered loader schema (see
    ``scripts/research/build_odf_params.py``), like the key lists in
    ``bzrODFparams.txt``. A key no Redux loader reads anywhere is dead in
    every section.
    """
    global _DEAD
    if _DEAD is None:
        import json

        try:
            with open(os.path.join(DATA_DIR, "redux_odf_dead.json"), encoding="utf-8") as handle:
                data = json.load(handle)
        except (OSError, ValueError):
            data = {"sections": {}, "keys": {}}
        data["never_read"] = {key: entry for entries in data["keys"].values()
                              for key, entry in entries.items() if not entry["read_in"]}
        _DEAD = data
    return _DEAD


def _fnv1a(name):
    """Redux's ODF name hash: FNV-1a 32 over the lowercased bytes."""
    value = 0x811C9DC5
    for byte in name.lower().encode("latin-1", "ignore"):
        value = ((value ^ byte) * 0x01000193) & 0xFFFFFFFF
    return value


def _crc_table():
    table = []
    for index in range(256):
        value = index << 24
        for _ in range(8):
            value = ((value << 1) ^ 0x04C11DB7) & 0xFFFFFFFF if value & 0x80000000 else (value << 1) & 0xFFFFFFFF
        table.append(value)
    return table


_CRC_TABLE = _crc_table()


def _bz2_crc(name):
    """BZ2's ODF name hash: CRC-32 (MSB first, init/xorout 0xFFFFFFFF) over the lowercased bytes."""
    value = 0xFFFFFFFF
    for byte in name.lower().encode("latin-1", "ignore"):
        value = _CRC_TABLE[((value >> 24) ^ byte) & 0xFF] ^ ((value << 8) & 0xFFFFFFFF)
    return value ^ 0xFFFFFFFF


_READERS = None


def key_readers(key):
    """``(redux_reads, bz2_reads)`` for ``key``: is its hash in each game's decompile?

    Both engines look ODF keys up by hash, so a key whose hash is absent from a
    binary has no reader there (``data/odf_key_hashes.json``). ``(None, None)``
    when the data is not available.
    """
    global _READERS
    if _READERS is None:
        import json

        try:
            with open(os.path.join(DATA_DIR, "odf_key_hashes.json"), encoding="utf-8") as handle:
                data = json.load(handle)
            _READERS = (frozenset(data["redux_fnv1a"]), frozenset(data["bz2_crc32"]))
        except (OSError, ValueError, KeyError):
            _READERS = ()
    if not _READERS:
        return None, None
    return _fnv1a(key) in _READERS[0], _bz2_crc(key) in _READERS[1]


# GetODFFloat(odf, "Section", "key", default); "key" .. i reads an indexed family.
_LUA_ODF_READ = re.compile(
    r"GetODF(?:Float|Int|Long|Bool|String)\s*\([^\n]*?,\s*([\"'])(\w+)\1\s*,\s*([\"'])(\w+)\3(\s*\.\.)?")


def lua_odf_reads(inventory):
    """``{section_lower: {key_lower | family#}}`` read by the mod's own Lua scripts.

    Mods keep custom settings in ODFs (e.g. gunPos1, a [towerai] section) and
    read them with GetODF*; neither engine knows those keys.
    """
    reads = {}
    for entry in inventory:
        if not entry["name_lower"].endswith(".lua"):
            continue
        try:
            with open(entry["path"], "r", encoding="utf-8", errors="ignore") as f:
                text = f.read()
        except OSError:
            continue
        for _, section, _, key, indexed in _LUA_ODF_READ.findall(text):
            reads.setdefault(section.lower(), set()).add(key.lower() + ("#" if indexed else ""))
    return reads


class LintFinding(tuple):
    """``(path, kind, detail, line)`` plus an optional :attr:`fix` for a one-to-one repair.

    Still unpacks as a 4-tuple, so existing callers keep working. ``fix`` is
    ``(action, old, new, label)``; see :mod:`battlezone.validation.fixes`.
    """

    def __new__(cls, path, kind, detail, line, fix=()):
        finding = super().__new__(cls, (path, kind, detail, line))
        finding.fix = tuple(fix)
        return finding


# Keys Redux reads under another name; a one-to-one rename is safe to offer.
# (section_lower or "*", key_lower) -> correct key. Evidence: the loader schema
# (triggetDelay, flameDelay, xplName*) and the binaries (nation is read by
# both games, faction by neither).
MISNAMED_KEYS = {
    ("*", "faction"): "nation",
    ("*", "triggetdelay"): "triggerDelay",
    ("flamepuffclass", "flamedelay"): "frameDelay",
    ("ordnanceclass", "xplnameground"): "xplGround",
    ("ordnanceclass", "xplnamevehicle"): "xplVehicle",
    ("ordnanceclass", "xplnamebuilding"): "xplBuilding",
}


def misnamed_key(section_key, key):
    return MISNAMED_KEYS.get((section_key, key)) or MISNAMED_KEYS.get(("*", key))


def dead_key(dead, section_key, key):
    """The dead-key entry for ``key`` written under ``section_key``, if any."""
    return dead["keys"].get(section_key, {}).get(key) or dead["never_read"].get(key)


def sections_reading(allowed_params, key):
    """Listed sections whose loader reads ``key`` (indexed families included)."""
    return sorted(section for section, keys in allowed_params.items() if _param_allowed(key, keys))


def bz2_field_hint(key):
    for pattern, hint in BZ2_FIELDS:
        if pattern.match(key):
            return hint
    return None


def _read_odf_sections(lines):
    """``([(header, line, [(key, line), ...]), ...], referenced_section_names)``."""
    sections = []
    references = set()
    current = None
    for i, raw in enumerate(lines):
        line = raw.split("//")[0].split("--")[0].strip()
        if not line:
            continue
        if line.startswith("[") and line.endswith("]"):
            current = (line[1:-1], i + 1, [])
            sections.append(current)
        elif "=" in line and current is not None:
            key, value = line.split("=", 1)
            current[2].append((key.strip(), i + 1))
            match = _SECTION_REF.search(value.strip().strip('"').strip())
            if match and match.group(1).lower() not in _FILE_EXTENSIONS:
                references.add(match.group(1).lower())
    return sections, references


def _is_render_section(header_key, params, references):
    """A render/particle definition: sets a render key, or is named as ``odf.Section``."""
    if header_key in references:
        return True
    return any(key.lower() in RENDER_KEYS for key, _ in params)


class ModScanner:
    def __init__(self, resource_dir=None, logger=None):
        self.resource_dir = resource_dir
        self.logger = logger

    def _resource(self, name):
        """Rule list lookup: an explicit resource dir wins, else the bundled copy."""
        if self.resource_dir:
            candidate = os.path.join(self.resource_dir, name)
            if os.path.exists(candidate):
                return candidate
        return os.path.join(DATA_DIR, name)

    def log(self, msg):
        if self.logger:
            self.logger(msg)

    def _section_names(self):
        """Lower-case section -> its spelling in the key list (for messages)."""
        names = {}
        path = self._resource("bzrODFparams.txt")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    match = re.match(r"^\[([A-Za-z0-9_]+)\]\s*$", line.strip())
                    if match:
                        names[match.group(1).lower()] = match.group(1)
        return names

    def _load_odf_rules(self):
        allowed_headers = set()
        allowed_params = {}
        required_params = {}

        header_list_path = self._resource("odfHeaderList.txt")
        if os.path.exists(header_list_path):
            with open(header_list_path, "r", encoding="utf-8", errors="ignore") as f:
                allowed_headers = {line.strip().lower() for line in f if line.strip()}

        params_list_path = self._resource("bzrODFparams.txt")
        if os.path.exists(params_list_path):
            current_class = None
            with open(params_list_path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("-") or line.startswith("//"):
                        continue

                    if line.startswith("[") and line.endswith("]"):
                        current_class = line[1:-1].strip()
                        if re.match(r"^[A-Za-z0-9_]+$", current_class):
                            current_class = current_class.lower()
                            allowed_params[current_class] = set()
                            required_params[current_class] = set()
                        else:
                            current_class = None
                        continue

                    if not current_class:
                        continue

                    token = line.split()[0]
                    is_required = token.startswith("!")
                    param = token.lstrip("!").rstrip("?").strip().lower()
                    if not param:
                        continue

                    allowed_params[current_class].add(param)
                    if is_required:
                        required_params[current_class].add(param)

        return allowed_headers, allowed_params, required_params

    def build_inventory(self, mod_dir):
        inventory = []
        for root, _, files in os.walk(mod_dir):
            for name in files:
                path = os.path.join(root, name)
                stat = os.stat(path)
                inventory.append({
                    "name": name,
                    "name_lower": name.lower(),
                    "path": path,
                    "rel_path": os.path.relpath(path, mod_dir).replace("\\", "/").lower(),
                    "size": stat.st_size,
                    "mtime_ns": getattr(stat, "st_mtime_ns", int(stat.st_mtime * 1_000_000_000)),
                })
        return inventory

    def fingerprint_inventory(self, inventory):
        digest = hashlib.sha1()
        for entry in sorted(inventory, key=lambda item: item["rel_path"]):
            digest.update(entry["rel_path"].encode("utf-8", errors="ignore"))
            digest.update(str(entry["mtime_ns"]).encode("ascii", errors="ignore"))
            digest.update(str(entry["size"]).encode("ascii", errors="ignore"))
        return digest.hexdigest()

    def collect_findings(self, mod_dir, inventory=None):
        inventory = inventory if inventory is not None else self.build_inventory(mod_dir)
        issues = self.scan_mod_safety(mod_dir, inventory=inventory)
        issues.extend(self.scan_asset_references(mod_dir, inventory=inventory))
        validation_errors, validation_warnings = self.validate_content_structure(mod_dir)
        trn_line_endings, trn_duplicate_headers = self.scan_trn_safety(mod_dir, inventory=inventory)
        legacy_files = self.scan_legacy_files(mod_dir, inventory=inventory)
        return {
            "inventory": inventory,
            "issues": issues,
            "validation_errors": validation_errors,
            "validation_warnings": validation_warnings,
            "trn_line_endings": trn_line_endings,
            "trn_duplicate_headers": trn_duplicate_headers,
            "legacy_files": legacy_files,
        }

    def scan_mod_safety(self, mod_dir, inventory=None):
        allowed_headers, allowed_params, required_params = self._load_odf_rules()

        if not allowed_headers:
            return []

        dead = load_dead_rules()
        allowed_params_names = self._section_names()
        issues = []
        inventory = inventory if inventory is not None else self.build_inventory(mod_dir)
        lua_reads = lua_odf_reads(inventory)
        for entry in inventory:
            if not entry["name_lower"].endswith(".odf"):
                continue
            path = entry["path"]
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    sections, references = _read_odf_sections(f)
            except Exception as e:
                self.log(f"Warning: Could not scan {entry['name']}: {e}")
                continue

            for header, header_line, params in sections:
                header_key = header.lower()
                inherits_damage = not any(key.lower() in REDUX_DAMAGE_KEYS for key, _ in params)
                lua_keys = lua_reads.get(header_key, set())
                for key, line_no in params:
                    hint = None if _param_allowed(key.lower(), lua_keys) else bz2_field_hint(key)
                    if hint:
                        if inherits_damage and key.lower().startswith("damagevalue"):
                            hint += (". This section sets none of them, so its damage is inherited "
                                     "from the class, not taken from these values")
                        issues.append((path, "BZ2 Field", f"[{header}] {key}: {hint}", line_no))
                dead_section = dead["sections"].get(header_key)
                if dead_section:
                    instead = dead_section["read_instead"]
                    fix = ()
                    if instead and instead.lower() not in {h.lower() for h, _, _ in sections}:
                        fix = ("rename-section", header, instead,
                               f"Rename [{header}] to [{instead}]. Its {len(params)} key(s) are ignored today "
                               "and will start being read, which can change how the object plays.")
                    issues.append(LintFinding(path, "Dead Section",
                                              f"[{header}] is never read by Redux, so all its keys are ignored"
                                              + (f"; Redux reads [{instead}]" if instead else ""), header_line, fix))
                    continue
                if header_key not in allowed_headers and header_key not in allowed_params:
                    if header_key in lua_reads:
                        continue  # a custom section the mod's Lua reads
                    if _is_render_section(header_key, params, references):
                        continue  # particle / render definition; its fields are free-form
                    issues.append((path, "Invalid Header", header, header_line))
                if header_key in allowed_params:
                    found_params = set()
                    for key, line_no in params:
                        key_key = key.lower()
                        if _param_allowed(key_key, lua_keys):
                            found_params.add(key_key)   # read by the mod's Lua, whatever the engine does
                            continue
                        if bz2_field_hint(key):
                            continue   # reported above as a BZ2 field
                        correct = misnamed_key(header_key, key_key)
                        if correct:
                            present = {k.lower() for k, _ in params}
                            if correct.lower() in present:
                                fix = ("remove-line", key, correct,
                                       f"Remove the {key} line: Redux ignores it and {correct} is already set here.")
                            else:
                                fix = ("rename-key", key, correct, f"Rename {key} to {correct}.")
                            issues.append(LintFinding(path, "Wrong Key",
                                                      f"[{header}] {key}: Redux reads {correct}, not {key}",
                                                      line_no, fix))
                            continue
                        entry = dead_key(dead, header_key, key_key)
                        if entry:
                            where = (f"Redux reads it only under [{'], ['.join(entry['read_in'])}]"
                                     if entry["read_in"] else "no Redux loader reads it")
                            issues.append((path, "Dead Field", f"[{header}] {key}: {where}", line_no))
                        elif _param_allowed(key_key, allowed_params[header_key]):
                            found_params.add(key_key)
                        else:
                            elsewhere = [allowed_params_names.get(n, n) for n in sections_reading(allowed_params, key_key)]
                            redux_reads, bz2_reads = key_readers(key_key)
                            if elsewhere:
                                issues.append((path, "Unknown Field", f"[{header}] {key} (Redux reads it under "
                                               f"[{'], ['.join(elsewhere)}], not here)", line_no))
                            elif redux_reads:
                                found_params.add(key_key)   # read by Redux outside the recovered section lists
                            elif bz2_reads:
                                issues.append((path, "BZ2 Field", f"[{header}] {key}: BZ2/BZCC reads this key, "
                                               "Redux has no reader for it, so it is ignored", line_no))
                            elif redux_reads is False and not any(ch.isdigit() for ch in key):
                                # neither binary hashes this name; an indexed key (effectName1) may be
                                # built at run time, so only plain keys are called dead
                                issues.append((path, "Dead Field", f"[{header}] {key}: no reader in the "
                                               "Redux or BZ2 binaries", line_no))
                            else:
                                note = " (no reader in the Redux or BZ2 binaries)" if redux_reads is False else ""
                                issues.append((path, "Unknown Field", f"[{header}] {key}{note}", line_no))
                    missing = required_params.get(header_key, set()) - found_params
                    if missing:
                        issues.append((path, "Missing Fields", f"[{header}] missing: {', '.join(sorted(missing))}", header_line))
        return issues

    def scan_asset_references(self, mod_dir, inventory=None):
        issues = []
        existing_files = set()
        files_to_process = []

        odf_pattern = re.compile(r'(geometryName|cockpitName|turretName)\s*=\s*"([^"]+)"', re.IGNORECASE)
        material_pattern = re.compile(r'texture\s+([^\s]+)', re.IGNORECASE)

        inventory = inventory if inventory is not None else self.build_inventory(mod_dir)
        for entry in inventory:
            name_lower = entry["name_lower"]
            existing_files.add(name_lower)
            if name_lower.endswith(".odf") or name_lower.endswith(".material"):
                files_to_process.append(entry)

        for entry in files_to_process:
            is_odf = entry["name_lower"].endswith(".odf")
            path = entry["path"]
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as f:
                    for i, line in enumerate(f):
                        if "//" in line:
                            line = line.split("//")[0]
                        line = line.strip()
                        if not line:
                            continue

                        if is_odf:
                            match = odf_pattern.search(line)
                            if match:
                                asset = match.group(2).lower()
                                if asset and asset not in existing_files:
                                    issues.append((path, "Missing Asset", f"Missing {match.group(1)}: {asset}", i + 1))
                        else:
                            match = material_pattern.search(line)
                            if match:
                                asset = match.group(1).lower()
                                if asset and asset not in existing_files:
                                    issues.append((path, "Missing Asset", f"Missing texture: {asset}", i + 1))
            except Exception:
                pass
        return issues

    def scan_trn_safety(self, mod_dir, inventory=None):
        le_issues = []
        dup_issues = []
        inventory = inventory if inventory is not None else self.build_inventory(mod_dir)
        for entry in inventory:
            if not entry["name_lower"].endswith(".trn"):
                continue
            path = entry["path"]
            try:
                doc = TRNDocument.read(path)
                if doc.line_endings != "crlf":
                    le_issues.append(path)
                if len(doc.sections_named("size")) > 1:
                    dup_issues.append(path)
            except Exception as e:
                self.log(f"Warning: Could not scan TRN {entry['name']}: {e}")
        return le_issues, dup_issues

    def scan_legacy_files(self, mod_dir, inventory=None):
        legacy_files = []
        inventory = inventory if inventory is not None else self.build_inventory(mod_dir)
        for entry in inventory:
            if entry["name_lower"].endswith(".map"):
                legacy_files.append(entry["path"])
        return legacy_files

    def validate_content_structure(self, mod_dir, remove_system_files=True):
        """Check the Workshop content-root layout.

        The uploader historically deletes ``desktop.ini`` before checking; the
        read-only validation engine passes ``remove_system_files=False``.
        """
        errors = []
        warnings = []

        try:
            files = os.listdir(mod_dir)
        except Exception as e:
            errors.append(f"Could not access content folder: {e}")
            return errors, warnings

        for name in files[:]:
            if name.lower() == "desktop.ini" and not remove_system_files:
                files.remove(name)
                continue
            if name.lower() == "desktop.ini":
                try:
                    os.remove(os.path.join(mod_dir, name))
                    self.log(f"Removed hidden system file: {name}")
                    files.remove(name)
                except Exception as e:
                    self.log(f"Warning: Could not remove {name}: {e}")

        ini_files = [name for name in files if name.lower().endswith(".ini") and os.path.isfile(os.path.join(mod_dir, name))]

        if not ini_files:
            errors.append("Missing configuration (.ini) file in content root.")
            return errors, warnings

        target_ini = ini_files[0]
        ini_path = os.path.join(mod_dir, target_ini)

        config = configparser.ConfigParser()
        try:
            with open(ini_path, "r", encoding="utf-8-sig") as f:
                config.read_file(f)
        except Exception:
            try:
                config.read(ini_path)
            except Exception as e:
                errors.append(f"Failed to parse {target_ini}: {e}")
                return errors, warnings

        if "WORKSHOP" not in config:
            errors.append(f"{target_ini} missing [WORKSHOP] section.")
            return errors, warnings

        map_type = config["WORKSHOP"].get("maptype", "").lower().strip().strip('"').strip("'")
        valid_types = ["instant_action", "multiplayer", "mod"]

        if map_type not in valid_types:
            errors.append(f"Invalid mapType '{map_type}' in {target_ini}.\nMust be one of: {', '.join(valid_types)}")
            return errors, warnings

        base_name = os.path.splitext(target_ini)[0]
        files_lower = set(name.lower() for name in files)

        def check_ext(ext, required=True):
            if f"{base_name}{ext}".lower() not in files_lower:
                kind = "essential" if required else "optional"
                (errors if required else warnings).append(f"Missing {kind} file: {base_name}{ext}")

        if map_type in ["multiplayer", "instant_action"]:
            for ext in [".hg2", ".trn", ".mat", ".bzn", ".lgt"]:
                check_ext(ext)

            if map_type == "multiplayer":
                for ext in [".bmp", ".des", ".vxt"]:
                    check_ext(ext, required=False)
                if "MULTIPLAYER" not in config:
                    errors.append(f"{target_ini} missing [MULTIPLAYER] section.")
                else:
                    for key in ["minplayers", "maxplayers", "gametype"]:
                        if key not in config["MULTIPLAYER"]:
                            warnings.append(f"[MULTIPLAYER] missing '{key}'")

        return errors, warnings
