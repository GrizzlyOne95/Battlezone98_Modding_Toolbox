"""Structured provenance for ODF validation rules.

Evidence entries are intentionally conservative. Exact native addresses and
repository paths are recorded only when independently verified. Redux executable
addresses are not attributed to BZ1_Source unless a concrete matching artifact
path is known.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, Tuple


EVIDENCE_CONFIDENCE = (
    "confirmed-code",
    "code+stock",
    "stock-only",
    "inferred",
)


@dataclass(frozen=True)
class ODFEvidence:
    evidence_id: str
    kind: str
    title: str
    detail: str
    confidence: str = "confirmed-code"
    function: str = ""
    address: str = ""
    related_addresses: Tuple[str, ...] = ()
    repository: str = ""
    path: str = ""
    stock_file: str = ""
    runtime_case: str = ""

    def summary(self) -> str:
        parts = [f"[{self.kind}/{self.confidence}] {self.title}"]
        if self.function:
            location = self.function
            if self.address:
                location += f" @ {self.address}"
            parts.append(location)
        elif self.address:
            parts.append(self.address)
        if self.related_addresses:
            parts.append("related: " + ", ".join(self.related_addresses))
        if self.repository:
            repo = self.repository
            if self.path:
                repo += f"/{self.path}"
            parts.append(repo)
        if self.stock_file:
            parts.append(f"stock: {self.stock_file}")
        if self.runtime_case:
            parts.append(f"runtime: {self.runtime_case}")
        parts.append(self.detail)
        return " — ".join(parts)


EVIDENCE: Dict[str, ODFEvidence] = {
    "redux-flaremine-load": ODFEvidence(
        evidence_id="redux-flaremine-load",
        kind="redux-decomp",
        confidence="confirmed-code",
        title="Redux flare payload loader",
        function="FlareMineClass::Load",
        address="0x004D2B10",
        detail=(
            "The recovered Redux loader populates the flare payload OrdnanceClass "
            "from payloadName only through the FlareMineClass loader section. A "
            "legacy/unconsumed section therefore does not initialize that field."
        ),
    ),
    "redux-flaremine-update-null-payload": ODFEvidence(
        evidence_id="redux-flaremine-update-null-payload",
        kind="redux-decomp",
        confidence="confirmed-code",
        title="Redux flare update null-payload dereference path",
        function="FlareMine::Update(float)",
        address="0x004D2E90",
        related_addresses=("call 0x004D3093", "callee 0x00586FF0", "fault 0x00586FFC"),
        detail=(
            "Update reads the FlareMineClass pointer from the object, then its "
            "payload OrdnanceClass pointer at class offset +0x168. The downstream "
            "call dereferences the payload object; a null payload produces the "
            "confirmed read-at-0x38 access violation."
        ),
    ),
    "redux-ordnance-build-null-payload": ODFEvidence(
        evidence_id="redux-ordnance-build-null-payload",
        kind="redux-decomp",
        confidence="confirmed-code",
        title="Redux ordnance build null-class dereference",
        function="OrdnanceClass::Build",
        address="0x00586FF0",
        related_addresses=("fault 0x00586FFC",),
        detail=(
            "The payload build path dereferences class state at +0x38 without a "
            "null guard, completing the confirmed FlareMine crash chain."
        ),
    ),
    "absozero-flare-crash-repro": ODFEvidence(
        evidence_id="absozero-flare-crash-repro",
        kind="runtime-repro",
        confidence="code+stock",
        title="AbsoZero flare crash reproduction",
        runtime_case="AbsoZero FlareBuildingClass -> FlareMineClass repair",
        detail=(
            "Legacy AbsoZero flare ODFs used [FlareBuildingClass]. Renaming that "
            "section to [FlareMineClass] allowed payload loading and eliminated the "
            "immediate simulation-start crash in live Redux validation."
        ),
    ),
    "stock-flare-section-contract": ODFEvidence(
        evidence_id="stock-flare-section-contract",
        kind="stock-contract",
        confidence="code+stock",
        title="Stock Redux flare ODF section contract",
        stock_file="flare.odf",
        detail="The stock Redux flare ODF uses [FlareMineClass] for flare-specific fields.",
    ),
    "redux-gameobjectclass-contract": ODFEvidence(
        evidence_id="redux-gameobjectclass-contract",
        kind="loader-contract",
        confidence="confirmed-code",
        title="Redux GameObjectClass root contract",
        detail=(
            "Recovered loader dispatch uses [GameObjectClass] for the object-class "
            "root. [GameObject] does not dispatch through that loader path."
        ),
    ),
    "redux-basename-prototype-selection": ODFEvidence(
        evidence_id="redux-basename-prototype-selection",
        kind="loader-contract",
        confidence="confirmed-code",
        title="Redux baseName prototype-selection semantics",
        detail=(
            "Recovered code has a single canonical baseName reader, but it does not "
            "load or merge another ODF file. baseName participates in base/prototype "
            "selection; defaults come from the engine prototype/class chain. A "
            "missing or empty baseName therefore means no base prototype is selected "
            "by this field, but absence is not automatically invalid for every ODF."
        ),
    ),
    "redux-magnetmine-contract": ODFEvidence(
        evidence_id="redux-magnetmine-contract",
        kind="loader-contract",
        confidence="confirmed-code",
        title="Redux MagnetMineClass contract",
        detail=(
            "Recovered magnet-mine loader behavior uses [MagnetMineClass] and "
            "triggerDelay for the mine/ordnance path. Building magnets are a distinct "
            "path and are intentionally excluded by the schema context."
        ),
    ),
    "redux-scavenger-contract": ODFEvidence(
        evidence_id="redux-scavenger-contract",
        kind="loader-contract",
        confidence="confirmed-code",
        title="Redux ScavengerClass contract",
        detail=(
            "Recovered scavenger loader behavior uses [ScavengerClass]; "
            "[ScavengerCraftClass] has no recovered code reader."
        ),
    ),
    "redux-flamepuff-contract": ODFEvidence(
        evidence_id="redux-flamepuff-contract",
        kind="loader-contract",
        confidence="confirmed-code",
        title="Redux FlamePuffClass contract",
        detail=(
            "Recovered flame-puff loader behavior uses [FlamePuffClass]. The code "
            "reads frameDelay; the shipped flameDelay spelling has no recovered "
            "reader. Other legacy-only fields must be judged against the mined key set."
        ),
    ),
    "redux-explosionclass-contract": ODFEvidence(
        evidence_id="redux-explosionclass-contract",
        kind="loader-contract",
        confidence="confirmed-code",
        title="Redux ExplosionClass loader contract",
        detail=(
            "Recovered explosion construction dispatches the explosion object from "
            "classLabel=explosion, but explosion-specific fields are read from "
            "[ExplosionClass]. A legacy [Explosion] section can coexist with the "
            "dispatch path while its keys remain unread."
        ),
    ),
    "redux-spraybuilding-contract": ODFEvidence(
        evidence_id="redux-spraybuilding-contract",
        kind="loader-contract",
        confidence="code+stock",
        title="Redux SprayBuildingClass section contract",
        detail=(
            "Recovered code reads spray-building-specific fields from "
            "[SprayBuildingClass]. The misspelled [SprayBuildngClass] section has no "
            "recovered reader; the mining audit found that spelling in four stock "
            "spray-building ODFs, leaving their intended section fields unread."
        ),
    ),
    "odf-reference-resolution": ODFEvidence(
        evidence_id="odf-reference-resolution",
        kind="package-check",
        confidence="confirmed-code",
        title="ODF reference namespace validation",
        detail=(
            "The referenced ODF name is checked against the combined scanned local "
            "package and known stock ODF filename namespace. Near-miss suggestions "
            "are advisory and never rewrite files."
        ),
    ),
}


def get_evidence(evidence_id: str) -> ODFEvidence | None:
    return EVIDENCE.get(evidence_id)


def resolve_evidence(evidence_ids: Iterable[str]) -> Tuple[ODFEvidence, ...]:
    return tuple(EVIDENCE[eid] for eid in evidence_ids if eid in EVIDENCE)


def validate_evidence_ids(evidence_ids: Iterable[str]) -> Tuple[str, ...]:
    return tuple(eid for eid in evidence_ids if eid not in EVIDENCE)
