"""Regenerate the ODF lint data from the loader schema.

Writes battlezone/validation/data/bzrODFparams.txt (keys per section) and
redux_odf_dead.json (sections Redux never reads, and keys that are dead or
read only under another section, from the schema's dead_sections_and_keys).

With ``--source`` (a Battlezone_Source checkout) it also writes
odf_key_hashes.json: the hash constants in the Redux and BZ2 decompiles. The
engines look keys up by hash (Redux: FNV-1a, BZ2: CRC-32), so a key whose
hash appears in neither binary has no reader there. The lint uses this to
tell BZ2/BZCC keys Redux ignores from keys Redux reads outside the recovered
section lists.

The schema is ``research/odf_loader_schema.json`` in the BZ1_Source repository
(github.com/GrizzlyOne95/BZ1_Source): every ODF key the 1.5 and Redux class
loaders read, recovered from the decompiles and hash-verified. The params file
lists, per section, the keys Redux reads there; the mod scanner reports any
other key in a listed section as an unknown field.

Usage::

    python scripts/research/build_odf_params.py <BZ1_Source>/research/odf_loader_schema.json \
        [--source <Battlezone_Source>]

(BZ1_Source is now the BZ1 folder of github.com/GrizzlyOne95/Battlezone_Source.)
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
OUTPUT = REPO_ROOT / "battlezone" / "validation" / "data" / "bzrODFparams.txt"
DEAD_OUTPUT = OUTPUT.with_name("redux_odf_dead.json")

# Dead sections and the section the loader reads instead (from each entry's evidence).
DEAD_SECTIONS = {
    "FlareBuildingClass": "FlareMineClass",
    "MagnetClass": "MagnetMineClass",
    "ScavengerCraftClass": "ScavengerClass",
    "SprayBuildngClass": "SprayBuildingClass",
    "GameObject": "GameObjectClass",
    "SprayBomb": "SprayBombClass",
    "flameClass": "",
}

# XxxClass::Find reads classLabel from the family root section; it is not in
# the per-class key lists. Redux reads the explosion label from
# [ExplosionClass]; a bare [Explosion] root is only kept for dispatch.
ROOT_SECTIONS = ("GameObjectClass", "OrdnanceClass", "WeaponClass", "ExplosionClass", "Explosion")

# Keys whose absence breaks the object in Redux (odf_validator_rules.json).
REQUIRED = {("FlareMineClass", "payloadName")}

# Indexed key families: the schema records the first index (with or without a
# trailing "*"); the loader appends the index to the base name.
_INDEXED = re.compile(r"^(?P<base>.+?)(?P<first>0?1)\*?$")


def _family(key: dict) -> str | None:
    name = key["name"].rstrip("*")
    match = _INDEXED.match(key["name"])
    if not match:
        return None
    note = key.get("note", "")
    if key["name"].endswith("*") or ".." in note or "via" in note or "same scheme" in note \
            or "per-level" in note:
        return match.group("base")
    return None if name[-1] != "1" else match.group("base")


def dead_entries(schema: dict) -> dict:
    """``{"sections": {...}, "keys": {section_lower|"*": {key_lower: {...}}}}`` from dead_sections_and_keys."""
    readers: dict[str, list] = defaultdict(list)   # key_lower -> sections whose Redux loader reads it
    for loader in schema["loaders"]:
        for key in loader.get("keys", ()) if loader.get("section") else ():
            if key.get("present_redux"):
                family = _family(key)
                name = (family + "#") if family else key["name"].rstrip("*")
                if loader["section"] not in readers[name.lower()]:
                    readers[name.lower()].append(loader["section"])
    keys: dict[str, dict] = {}
    for item in schema.get("dead_sections_and_keys", ()):
        label, seen = item["name"], item.get("seen_in", "")
        if label.split(" ")[0] in DEAD_SECTIONS:
            continue
        head = label.split(" under ")[0]
        variants = re.search(r"\(\+([\w/]+)\)", head)   # "xplSoundGround/... (+Vehicle/Building)"
        head = re.sub(r"\(.*?\)", "", head)
        names = [n.strip() for n in head.split("/") if re.fullmatch(r"[A-Za-z]\w*", n.strip() or "-")]
        if variants:
            names += [re.sub(r"Ground$", suffix, n) for n in names for suffix in variants.group(1).split("/")
                      if n.endswith("Ground")]
        where = re.findall(r"\[(\w+)\]", label) or re.findall(r"\[(\w+)\]", seen)
        for name in names:
            # Where a key IS read comes from the loader key lists, not from the
            # note: notes cover groups ("soundSteer/soundThrust ... read only
            # under [HoverCraftClass]") that are only true for some members.
            read_by = readers.get(name.lower(), [])
            for section in where or ["*"]:
                if section in read_by:
                    continue   # the section's own loader reads it; the note is about a sibling key
                keys.setdefault(section.lower(), {})[name.lower()] = {
                    "name": name, "read_in": read_by, "evidence": seen}
    return {
        "source": f"odf_loader_schema.json schema_version {schema.get('schema_version')}",
        "sections": {name.lower(): {"name": name, "read_instead": instead} for name, instead in DEAD_SECTIONS.items()},
        "keys": dict(sorted(keys.items())),
    }


def build(schema: dict) -> str:
    sections: dict[str, dict[str, str]] = defaultdict(dict)
    skipped_15: dict[str, list[str]] = defaultdict(list)
    unresolved: list[str] = []
    for loader in schema["loaders"]:
        section = loader.get("section")
        if not section or not loader.get("keys"):
            continue
        for key in loader["keys"]:
            name = key["name"]
            if name.startswith("unknown_"):
                unresolved.append(f"{section} {key['key_hash']}")
                continue
            if not key.get("present_redux"):
                skipped_15[section].append(name)
                continue
            family = _family(key)
            token = f"{family}#" if family else name
            if (section, name) in REQUIRED:
                token = "!" + token
            info = key["type"] + ("" if key.get("present_15") else ", Redux only")
            sections[section].setdefault(token, info)
    for root in ROOT_SECTIONS:
        sections[root] = {"classLabel": "string, family root", **sections.get(root, {})}

    lines = [
        "// Keys the Battlezone 98 Redux class loaders read, per ODF section.",
        "// Generated by scripts/research/build_odf_params.py from BZ1_Source",
        f"// research/odf_loader_schema.json (schema_version {schema['schema_version']}); do not edit by hand.",
        "//",
        "// Section and key names are case-insensitive. A key under a section that",
        "// does not read it is dead in Redux (the engine uses the default).",
        "//   !key   the object breaks in Redux without it",
        "//   key#   indexed family: key1, key2, ... (targetReticle uses 01, 02, ...)",
        "// Sections not listed here are not checked key by key.",
    ]
    if skipped_15:
        lines.append("// Read by 1.5 only (dead in Redux): " + "; ".join(
            f"[{s}] {', '.join(k)}" for s, k in sorted(skipped_15.items())))
    if unresolved:
        lines.append("// Read by Redux under a name not yet recovered (hash only): " + "; ".join(unresolved))
    for section in sorted(sections, key=str.lower):
        lines.append("")
        lines.append(f"[{section}]")
        width = max(len(token) for token in sections[section])
        for token, info in sections[section].items():
            lines.append(f"{token.ljust(width)}  // {info}")
    return "\n".join(lines) + "\n"


HASH_OUTPUT = OUTPUT.with_name("odf_key_hashes.json")
REDUX_DECOMP = ("BZ1/Redux/Raw .C",)
BZ2_DECOMP = ("BZ2/_analysis/global_decompile/bzone_a130_best_effort",
              "BZ2/_analysis/global_decompile/bzone_b131p_best_effort")
# Ghidra prints a hash as hex, decimal or negative (signed) decimal/hex
# depending on how the value is used, e.g. BZ2's quakeTime is -1245289528.
_CONSTANT = re.compile(r"(?<![\w.])(-?)(?:0x([0-9a-fA-F]{5,8})|(\d{5,10}))(?![\w.])")


def _constants(source: Path, folders) -> list[int]:
    found: set[int] = set()
    for folder in folders:
        for path in (source / folder).rglob("*.c"):
            for sign, hex_digits, decimal in _CONSTANT.findall(path.read_text(encoding="latin-1", errors="ignore")):
                value = int(hex_digits, 16) if hex_digits else int(decimal)
                if value >= 0x10000 and value < 1 << 32:   # small values are never hashes worth matching
                    found.add((-value if sign else value) & 0xFFFFFFFF)
    return sorted(found)


def key_hashes(source: Path) -> dict:
    redux, bz2 = _constants(source, REDUX_DECOMP), _constants(source, BZ2_DECOMP)
    if not redux or not bz2:
        raise SystemExit(f"no decompiled .c files under {source}; expected {REDUX_DECOMP + BZ2_DECOMP}")
    return {"source": "Battlezone_Source decompiles: " + ", ".join(REDUX_DECOMP + BZ2_DECOMP),
            "redux_fnv1a": redux, "bz2_crc32": bz2}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("schema", type=Path)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--source", type=Path, help="Battlezone_Source checkout: also write odf_key_hashes.json")
    args = parser.parse_args(argv)
    schema = json.loads(args.schema.read_text(encoding="utf-8"))
    args.output.write_text(build(schema), encoding="utf-8", newline="\n")
    dead_output = args.output.with_name(DEAD_OUTPUT.name)
    dead_output.write_text(json.dumps(dead_entries(schema), indent=1) + "\n", encoding="utf-8", newline="\n")
    print(f"wrote {args.output} and {dead_output}")
    if args.source:
        hash_output = args.output.with_name(HASH_OUTPUT.name)
        hash_output.write_text(json.dumps(key_hashes(args.source), separators=(",", ":")) + "\n",
                               encoding="utf-8", newline="\n")
        print(f"wrote {hash_output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
