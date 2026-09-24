"""Class-label diffing for BZ2/BZCC to Battlezone 98 Redux ports.

A BZCC ODF's ``classLabel`` is either an engine class (``wingman``) or the
name of another ODF it inherits from (``ivscout``). Redux only accepts engine
classes and has no ODF-to-ODF inheritance (see odf_inheritance.py), so every
ported ODF must end up with a Redux engine label, and every BZN object must
be cloned from a Redux prototype whose record layout matches that label.

This module resolves source chains, maps BZCC engine classes to Redux ones
with an explicit safety tier, and checks BZN prototype choices:

``exact``         same engine class, same role. Safe to map automatically.
``approximate``   no Redux class; the suggested one keeps placement but loses
                  behaviour (for example ``terrain`` props become buildings).
                  Only mapped automatically when approximations are allowed.
``role-changed``  the label exists in Redux but means something else
                  (BZCC ``recycler`` is a building, Redux ``recycler`` is a
                  deployable craft). Never mapped automatically.
``unsupported``   no Redux equivalent. The object is skipped unless mapped
                  by hand.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, field
import json
import os
from pathlib import Path
import re
import sys


# Labels used by the stock Redux ODFs (StockODFFiles survey, 796 ODFs), plus
# "bullet" and "i76building2", which the Redux executable registers next to
# i76building and i76sign but no stock ODF uses.
REDUX_CLASS_LABELS = frozenset("""
ammopack anchor apc armory artifact barracks beam beamgun bolt bouncebomb
bullet camerapod cannon chargegun commtower constructionrig daywrecker
detonator dispenser explosion factory flamepuff flare geyser grenade
groundblast howitzer i76building i76building2 i76sign imagelauncher imagemissile
imagerefract lobber machinegun magnet minelayer missile mortar person
planarexpl popper poppergun portal powerplant proximity quakeblast
radardamper radarlauncher recycler repairdepot repairkit rocket sav scavenger
scrap scrapfield scrapsilo seismic shockblast snipergun snipershell spawnpnt
spraybomb supplydepot switcher targeting terrainexpose thermallauncher
thermalmissile torpedo tracer tug turret turrettank walker weaponmine wingman
wpnpower
""".split())

# Redux classes whose mission-save BZN records hold only the base GameObject
# fields, so a prototype of one can place an object of another. Evidence:
# Redux Building::Save and PowerUp::Save write nothing extra in mission saves
# (tempBuilding / vhclFlags are skipped), and in the named BZ1 1.5 decompile
# these Building and PowerUp subclasses have no Save override. Mine, ScrapSilo,
# ScrapDropoff, craft and turrets do, so they must match exactly.
# i76building2 is i76building without a radar blip.
STATIC_RECORD_CLASSES = frozenset("""
i76building i76building2 i76sign artifact barracks commtower geyser powerplant
repairdepot scrap scrapfield spawnpnt supplydepot
ammopack repairkit wpnpower camerapod daywrecker
""".split())

# BZCC engine classes, from the classLabel values in the BZCC 2.0 bz2r_res
# ODFs that do not name another ODF (plus explosion and flaremine, which do
# both). Anything else in a BZCC classLabel is treated as an ODF reference.
BZCC_ENGINE_LABELS = frozenset("""
ammopack anchor animal apc arccannon armory artifact artillery assaulttank
barracks beacon beam blink boid bomber bomberbay bouncebomb bullet camerapod
cannon chargegun cnozzle commbunker commtower computer constructionrig
damagefield daywrecker deposit detonator dispenser explosion extractor
factory flag flare flaremine forcefield fv_walker grenade i76building i76sign
imagelauncher imagemissile imagerefract iv_walker jammer jetpack kingofhill
lasermissile laserpopper leader lockdown machinegun magnet magnetgun
magnetshell missile moneybag morphtank mortar multilauncher objectspawn
person plant pointlight popper powered powerlung powerplant proximity pulse
radardamper radarlauncher radarmissile radarpopper recycler recyclervehicle
repairkit satchel satchelpack sav scavenger scrap seeker seismic sensor
service servicepod shieldup snipershell spawnpnt spotlight spraybomb
spraymine supplydepot targeting techcenter teleportal terrain terrainexpose
thermallauncher thermalmissile torpedo torpedolauncher tripmine tug turret
turrettank weaponmine wingman wpnpower
""".split())


@dataclass(frozen=True)
class ClassRule:
    redux: str | None
    tier: str
    note: str = ""


_EXACT = """
ammopack anchor apc artifact barracks beam bouncebomb bullet camerapod cannon
chargegun commtower constructionrig daywrecker detonator dispenser explosion
flare grenade i76building i76sign imagelauncher imagemissile imagerefract
machinegun magnet missile mortar person popper powerplant proximity
radardamper radarlauncher repairkit sav scavenger scrap seismic snipershell
spawnpnt spraybomb supplydepot targeting terrainexpose thermallauncher
thermalmissile torpedo tug turret turrettank weaponmine wingman wpnpower
""".split()

BZCC_TO_REDUX: dict[str, ClassRule] = {label: ClassRule(label, "exact") for label in _EXACT}
BZCC_TO_REDUX.update({
    "recycler": ClassRule("recycler", "role-changed",
                          "BZCC recycler is a building; Redux recycler is a deployable craft"),
    "factory": ClassRule("factory", "role-changed",
                         "BZCC factory is a building; Redux factory is a deployable craft"),
    "armory": ClassRule("armory", "role-changed",
                        "BZCC armory is a building; Redux armory is a deployable craft"),
    "terrain": ClassRule("i76building", "approximate", "static terrain prop"),
    "plant": ClassRule("i76building", "approximate", "loses plant animation"),
    "extractor": ClassRule("i76building", "approximate", "loses scrap extraction"),
    "techcenter": ClassRule("i76building", "approximate", "loses tech-centre function"),
    "commbunker": ClassRule("i76building", "approximate", "loses comm-bunker function"),
    "computer": ClassRule("i76building", "approximate", "loses computer function"),
    "bomberbay": ClassRule("i76building", "approximate", "loses bomber production"),
    "powered": ClassRule("i76building", "approximate", "loses power requirement"),
    "powerlung": ClassRule("powerplant", "approximate", "Scion power lung"),
    "flag": ClassRule("i76sign", "approximate", "loses capture-the-flag logic"),
    "beacon": ClassRule("i76sign", "approximate", "loses beacon logic"),
    "deposit": ClassRule("geyser", "approximate", "BZCC pool becomes a deploy geyser"),
    "recyclervehicle": ClassRule("recycler", "approximate", "BZCC recycler craft"),
    "assaulttank": ClassRule("wingman", "approximate", "loses assault-class targeting"),
    "morphtank": ClassRule("wingman", "approximate", "loses morphing"),
    "iv_walker": ClassRule("walker", "approximate"),
    "fv_walker": ClassRule("walker", "approximate"),
    "teleportal": ClassRule("portal", "approximate"),
    "servicepod": ClassRule("repairkit", "approximate", "loses ammo refill"),
    "flaremine": ClassRule("flare", "approximate", "check the FlareMineClass payload"),
})
for _label in BZCC_ENGINE_LABELS - BZCC_TO_REDUX.keys():
    BZCC_TO_REDUX[_label] = ClassRule(None, "unsupported")

AUTO_TIERS = ("exact",)
AUTO_TIERS_APPROXIMATE = ("exact", "approximate")

_LABEL_RE = re.compile(r'^\s*classLabel\s*=\s*"?([^";\s/]+)', re.IGNORECASE | re.MULTILINE)
_TUNNEL_RE = re.compile(r'^\s*tunnelCount\s*=\s*"?(\d+)', re.IGNORECASE | re.MULTILINE)
TUNNEL_NOTE = ("BZCC tunnel: tunnelCount={} passable lanes in the building footprint. "
               "Redux has no tunnel support, so the object blocks units and AI pathing; "
               "see docs/BZCC_TO_BZR_PORT.md, Tunnels")


def read_class_label(path: Path) -> str:
    match = _LABEL_RE.search(path.read_text(encoding="latin-1"))
    return match.group(1).lower() if match else ""


def _walk(root: Path, recursive: bool):
    if not recursive:
        yield root, sorted(p.name for p in root.iterdir() if p.is_file())
        return
    for directory, dirs, files in os.walk(root):
        dirs.sort()  # deterministic "first wins" across subfolders
        yield Path(directory), sorted(files)


class OdfIndex:
    """Case-insensitive ODF lookup over directories; earlier roots win."""

    def __init__(self, roots=(), recursive: bool = True):
        self.paths: dict[str, Path] = {}
        self.duplicates: dict[str, list[Path]] = {}
        self._labels: dict[str, str] = {}
        for root in roots:
            self.add(Path(root), recursive)

    def add(self, root: Path, recursive: bool = True) -> None:
        for directory, files in _walk(root, recursive):
            for name in files:
                if not name.lower().endswith(".odf"):
                    continue
                key = name[:-4].lower()
                path = directory / name
                if key in self.paths:
                    self.duplicates.setdefault(key, [self.paths[key]]).append(path)
                else:
                    self.paths[key] = path

    def __contains__(self, name: str) -> bool:
        return name.lower() in self.paths

    def label(self, name: str) -> str | None:
        key = name.lower()
        if key not in self.paths:
            return None
        if key not in self._labels:
            self._labels[key] = read_class_label(self.paths[key])
        return self._labels[key]


@dataclass
class SourceClass:
    odf: str
    chain: list[str]
    engine_label: str | None
    problem: str = ""


def resolve_source(name: str, index: OdfIndex) -> SourceClass:
    """Follow a BZCC classLabel chain to its engine class."""
    chain = [name.lower()]
    current = name.lower()
    while True:
        label = index.label(current)
        if label is None:
            return SourceClass(name, chain, None, f"source ODF {current!r} not found")
        if not label:
            return SourceClass(name, chain, None, f"{current!r} has no classLabel")
        if label in BZCC_ENGINE_LABELS:
            return SourceClass(name, chain, label)
        if label in chain:
            return SourceClass(name, chain + [label], None, "classLabel cycle")
        chain.append(label)
        current = label


def records_compatible(target_label: str | None, prototype_label: str | None) -> bool:
    if not target_label or not prototype_label:
        return False
    if target_label == prototype_label:
        return True
    return target_label in STATIC_RECORD_CLASSES and prototype_label in STATIC_RECORD_CLASSES


@dataclass
class ClassDiff:
    source_odf: str
    chain: list[str]
    source_label: str | None
    tier: str
    suggested_label: str | None
    note: str = ""
    target_odf: str = ""
    target_label: str | None = None
    prototype: str = ""
    prototype_label: str | None = None
    prototype_candidates: list[str] = field(default_factory=list)
    status: str = ""
    problems: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def safe(self) -> bool:
        return self.status == "ok"


def _mapping_rule(mapping: dict, odf: str) -> tuple[str, str | None]:
    rule = mapping.get(odf.lower())
    if isinstance(rule, str):
        return rule, rule
    if isinstance(rule, dict):
        target = rule.get("odf", odf)
        return target, rule.get("prototype", target)
    return odf, None


def diff_classes(source_odfs, source_index: OdfIndex, redux_index: OdfIndex,
                 prototypes=(), mapping: dict | None = None,
                 allow_approximate: bool = False) -> list[ClassDiff]:
    """Diff each source ODF's class against Redux and check its prototype.

    ``prototypes`` are the template PrjIDs; ``mapping`` is the bzcc_port
    --map content. A diff is ``ok`` only when the Redux target ODF carries a
    valid Redux label that agrees with the source class and the chosen
    prototype has a compatible BZN record.
    """
    mapping = {k.lower(): v for k, v in (mapping or {}).items()}
    by_label: dict[str, list[str]] = {}
    for proto in prototypes:
        label = redux_index.label(proto)
        if label:
            by_label.setdefault(label, []).append(proto.lower())
    tiers = AUTO_TIERS_APPROXIMATE if allow_approximate else AUTO_TIERS
    diffs = []
    for odf in sorted({name.lower() for name in source_odfs}):
        source = resolve_source(odf, source_index)
        rule = BZCC_TO_REDUX.get(source.engine_label or "", ClassRule(None, "unsupported"))
        diff = ClassDiff(odf, source.chain, source.engine_label, rule.tier, rule.redux, rule.note)
        if source.problem:
            diff.problems.append(source.problem)
        if len(source.chain) > 1:
            diff.notes.append(
                f"inherits from {' -> '.join(source.chain[1:])}; Redux has no ODF inheritance, "
                "so the Redux ODF must carry the inherited keys itself")
        target, prototype = _mapping_rule(mapping, odf)
        diff.target_odf = target.lower()
        diff.target_label = redux_index.label(target)
        compatible = [p for label, protos in by_label.items()
                      if records_compatible(diff.target_label or rule.redux, label) for p in protos]
        exact = by_label.get(diff.target_label or rule.redux or "", [])
        diff.prototype_candidates = exact + [p for p in compatible if p not in exact]
        if rule.note:
            diff.notes.append(rule.note)
        for name in source.chain:
            path = source_index.paths.get(name)
            tunnels = path and _TUNNEL_RE.search(path.read_text(encoding="latin-1"))
            if tunnels and int(tunnels.group(1)):
                diff.notes.append(TUNNEL_NOTE.format(tunnels.group(1)))
                break
        if prototype is None and rule.tier in tiers and diff.prototype_candidates:
            prototype = diff.prototype_candidates[0]
        if prototype:
            diff.prototype = prototype.lower()
            diff.prototype_label = redux_index.label(prototype)
        diff.status = _status(diff, rule, tiers, explicit=odf in mapping)
        diffs.append(diff)
    return diffs


def _status(diff: ClassDiff, rule: ClassRule, tiers, explicit: bool) -> str:
    if len(diff.target_odf.encode("cp1252")) > 8:
        diff.problems.append("Redux BZN IDs are limited to 8 bytes; map it to a shorter ODF name")
        return "id-too-long"
    if diff.target_label is None:
        diff.problems.append(f"no Redux ODF {diff.target_odf!r}; copy and convert the source ODF")
        return "missing-redux-odf"
    if diff.target_label not in REDUX_CLASS_LABELS:
        diff.problems.append(f"Redux ODF classLabel {diff.target_label!r} is not a Redux class"
                             + (f"; use {rule.redux!r}" if rule.redux else ""))
        return "invalid-redux-label"
    if not explicit and rule.tier not in tiers:
        diff.problems.append(f"{rule.tier} class {diff.source_label!r}: map it by hand"
                             + (f" ({rule.note})" if rule.note else ""))
        return rule.tier
    if not explicit and rule.redux and not records_compatible(diff.target_label, rule.redux):
        diff.problems.append(f"Redux ODF says {diff.target_label!r} but source class "
                             f"{diff.source_label!r} maps to {rule.redux!r}")
        return "label-mismatch"
    if not diff.prototype:
        diff.problems.append(f"template has no {diff.target_label!r} prototype")
        return "no-prototype"
    if diff.prototype_label is None:
        diff.problems.append(f"prototype {diff.prototype!r} has no Redux ODF, class unknown")
        return "unknown-prototype"
    if not records_compatible(diff.target_label, diff.prototype_label):
        diff.problems.append(f"prototype {diff.prototype!r} is {diff.prototype_label!r} but "
                             f"{diff.target_odf!r} is {diff.target_label!r}; their BZN records "
                             "are not known to match")
        return "prototype-mismatch"
    return "ok"


def rewrite_label(text: str, label: str) -> str:
    """Replace the first classLabel value, keeping the line's layout."""
    def swap(match):
        return match.group(0).replace(match.group(1), label, 1)
    new, count = _LABEL_RE.subn(swap, text, count=1)
    if not count:
        raise ValueError("ODF has no classLabel")
    return new


def write_redux_odfs(diffs: list[ClassDiff], source_index: OdfIndex, out_dir: Path,
                     allow_approximate: bool = False) -> list[dict]:
    """Copy source ODFs with a Redux classLabel where that is safe.

    Only single-level ODFs (no inheritance) in an automatic tier are
    written; everything else is reported for hand conversion.
    """
    tiers = AUTO_TIERS_APPROXIMATE if allow_approximate else AUTO_TIERS
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for diff in diffs:
        if diff.tier not in tiers or not diff.suggested_label or len(diff.chain) != 1:
            continue
        source = source_index.paths.get(diff.source_odf)
        if source is None:
            continue
        text = source.read_text(encoding="latin-1")
        destination = out_dir / f"{diff.target_odf}.odf"
        destination.write_text(rewrite_label(text, diff.suggested_label), encoding="latin-1",
                               newline="")
        written.append({"source": str(source), "output": str(destination),
                        "from": diff.source_label, "to": diff.suggested_label, "tier": diff.tier})
    return written


def summary(diffs: list[ClassDiff]) -> dict:
    counts: dict[str, int] = {}
    for diff in diffs:
        counts[diff.status] = counts.get(diff.status, 0) + 1
    return {"odfs": len(diffs), "safe": sum(d.safe for d in diffs), "by_status": counts,
            "diffs": [asdict(d) for d in diffs]}


def format_table(diffs: list[ClassDiff]) -> str:
    rows = [("source", "BZCC class", "tier", "Redux ODF", "Redux class", "prototype", "status")]
    for d in diffs:
        rows.append((d.source_odf, d.source_label or "?", d.tier, d.target_odf,
                     d.target_label or "-", d.prototype or "-", d.status))
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    lines = ["  ".join(c.ljust(w) for c, w in zip(r, widths)).rstrip() for r in rows]
    for d in diffs:
        for problem in d.problems:
            lines.append(f"  {d.source_odf}: {problem}")
    for d in diffs:
        for note in d.notes:
            lines.append(f"  {d.source_odf} (note): {note}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    from battlezone.bzn.bzcc_port import PortError, load_template, source_mission

    parser = argparse.ArgumentParser(description="Diff BZCC ODF class labels against Redux.")
    parser.add_argument("source", type=Path, help="BZ2/BZCC .bzn")
    parser.add_argument("--source-odfs", type=Path, action="append", required=True,
                        help="BZCC ODF directory, searched recursively (repeatable; first wins)")
    parser.add_argument("--redux-odfs", type=Path, action="append", required=True,
                        help="Redux ODF directory, mod first then stock (repeatable; first wins)")
    parser.add_argument("--template", type=Path, help="Redux template BZN supplying prototypes")
    parser.add_argument("--map", dest="mapping", type=Path, help="bzcc_port --map JSON")
    parser.add_argument("--allow-approximate", action="store_true",
                        help="treat approximate classes as automatic")
    parser.add_argument("--write-odfs", type=Path, metavar="DIR",
                        help="write relabelled copies of safely convertible source ODFs")
    parser.add_argument("--json", type=Path, help="write the full diff as JSON")
    args = parser.parse_args(argv)
    try:
        mission = source_mission(args.source.read_bytes())
        prototypes = ()
        if args.template:
            prototypes = tuple(load_template(args.template.read_bytes())[3])
        mapping = json.loads(args.mapping.read_text(encoding="utf-8")) if args.mapping else {}
        diffs = diff_classes([o.odf for o in mission.objects], OdfIndex(args.source_odfs),
                             OdfIndex(args.redux_odfs), prototypes, mapping,
                             args.allow_approximate)
    except (OSError, ValueError, PortError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(format_table(diffs))
    result = summary(diffs)
    if args.write_odfs:
        result["written_odfs"] = write_redux_odfs(diffs, OdfIndex(args.source_odfs),
                                                  args.write_odfs, args.allow_approximate)
        print(f"wrote {len(result['written_odfs'])} ODFs to {args.write_odfs}")
    if args.json:
        args.json.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(f"{result['safe']}/{result['odfs']} ODFs safe")
    return 0 if result["safe"] == result["odfs"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
