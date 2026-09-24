"""Evidence-backed Battlezone 98 Redux ODF loader schema.

This module is intentionally data-only. The validator consumes these curated
rules so new loader findings can be added without growing a chain of one-off
conditionals. Each hard rule should be traceable to structured provenance in
odf_evidence.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple


@dataclass(frozen=True)
class KeyAlias:
    legacy: str
    canonical: str
    severity: str = "ERROR"
    message: str = ""
    legacy_only: bool = False
    evidence_ids: Tuple[str, ...] = ()


@dataclass(frozen=True)
class RequiredKey:
    name: str
    severity: str
    message: str
    suggestion: str
    evidence_ids: Tuple[str, ...] = ()


@dataclass(frozen=True)
class LegacyKey:
    name: str
    severity: str
    message: str
    suggestion: str
    evidence_ids: Tuple[str, ...] = ()


@dataclass(frozen=True)
class ReferenceKey:
    name: str
    severity: str
    evidence_ids: Tuple[str, ...] = ("odf-reference-resolution",)


@dataclass(frozen=True)
class LoaderRule:
    rule_id: str
    expected_section: str
    legacy_sections: Tuple[str, ...] = ()
    class_labels: Tuple[str, ...] = ()
    required_sections: Tuple[str, ...] = ()
    section_severity: str = "ERROR"
    section_message: str = ""
    source: str = ""
    evidence_ids: Tuple[str, ...] = ()
    key_aliases: Tuple[KeyAlias, ...] = ()
    required_keys: Tuple[RequiredKey, ...] = ()
    legacy_keys: Tuple[LegacyKey, ...] = ()
    # Retained for schema compatibility. Absence-based section diagnostics must
    # be backed by direct loader/prototype evidence before use.
    missing_section_severity: str = ""
    missing_section_message: str = ""
    missing_section_suggestion: str = ""


LOADER_RULES = (
    LoaderRule(
        rule_id="game-object-root",
        expected_section="GameObjectClass",
        legacy_sections=("GameObject",),
        section_severity="ERROR",
        section_message=(
            "Redux object-class data is dispatched from [GameObjectClass]; the "
            "legacy [GameObject] section is not consumed by this loader path."
        ),
        source="Redux GameObjectClass loader dispatch",
        evidence_ids=("redux-gameobjectclass-contract",),
        key_aliases=(
            KeyAlias(
                legacy="basename",
                canonical="baseName",
                severity="WARNING",
                message=(
                    "Use Redux's canonical baseName spelling when migrating this "
                    "legacy section. baseName selects a base/prototype; it is not "
                    "ODF file inheritance."
                ),
                legacy_only=True,
                evidence_ids=(
                    "redux-gameobjectclass-contract",
                    "redux-basename-prototype-selection",
                ),
            ),
        ),
    ),
    LoaderRule(
        rule_id="flare-mine",
        expected_section="FlareMineClass",
        legacy_sections=("FlareBuildingClass",),
        class_labels=("flare",),
        required_sections=("MineClass",),
        section_severity="CRITICAL",
        section_message=(
            "Redux loads flare-specific data from [FlareMineClass]. The legacy "
            "[FlareBuildingClass] section has no loader reader, so payloadName can "
            "remain null and the flare firing path can dereference a null payload "
            "OrdnanceClass pointer."
        ),
        source="Recovered Redux flare loader/update/build crash chain",
        evidence_ids=(
            "redux-flaremine-load",
            "redux-flaremine-update-null-payload",
            "redux-ordnance-build-null-payload",
            "stock-flare-section-contract",
            "absozero-flare-crash-repro",
        ),
        required_keys=(
            RequiredKey(
                name="payloadName",
                severity="CRITICAL",
                message=(
                    "FlareMineClass has no payloadName; the firing path can reach "
                    "OrdnanceClass::Build with a null payload class."
                ),
                suggestion="Set payloadName to a valid ordnance ODF base name.",
                evidence_ids=(
                    "redux-flaremine-load",
                    "redux-flaremine-update-null-payload",
                    "redux-ordnance-build-null-payload",
                    "absozero-flare-crash-repro",
                ),
            ),
        ),
    ),
    LoaderRule(
        rule_id="magnet-mine",
        expected_section="MagnetMineClass",
        legacy_sections=("MagnetClass",),
        class_labels=("magnet",),
        required_sections=("OrdnanceClass", "MineClass"),
        section_severity="ERROR",
        section_message=(
            "This is the magnet mine/ordnance loader path. Redux reads mine-specific "
            "magnet parameters from [MagnetMineClass], not [MagnetClass]."
        ),
        source="Recovered Redux MagnetMineClass loader contract",
        evidence_ids=("redux-magnetmine-contract",),
        key_aliases=(
            KeyAlias(
                legacy="triggetDelay",
                canonical="triggerDelay",
                severity="ERROR",
                message=(
                    "The misspelled triggetDelay key has no recovered reader; the "
                    "Redux MagnetMineClass loader reads triggerDelay."
                ),
                evidence_ids=("redux-magnetmine-contract",),
            ),
        ),
    ),
    LoaderRule(
        rule_id="scavenger",
        expected_section="ScavengerClass",
        legacy_sections=("ScavengerCraftClass",),
        class_labels=("scavenger",),
        required_sections=("CraftClass",),
        section_severity="ERROR",
        section_message=(
            "Redux reads scavenger-specific fields from [ScavengerClass]; "
            "[ScavengerCraftClass] has no recovered loader reader."
        ),
        source="Recovered Redux ScavengerClass loader contract",
        evidence_ids=("redux-scavenger-contract",),
    ),
    LoaderRule(
        rule_id="flame-puff",
        expected_section="FlamePuffClass",
        legacy_sections=("flameClass",),
        class_labels=("flamepuff",),
        required_sections=("OrdnanceClass",),
        section_severity="ERROR",
        section_message=(
            "This ODF is classLabel=flamepuff. Redux reads flame-puff data from "
            "[FlamePuffClass], not the legacy [flameClass] section."
        ),
        source="Recovered Redux FlamePuffClass loader contract",
        evidence_ids=("redux-flamepuff-contract",),
        key_aliases=(
            KeyAlias(
                legacy="flameDelay",
                canonical="frameDelay",
                severity="WARNING",
                message=(
                    "flameDelay has no recovered reader on the Redux FlamePuffClass "
                    "loader; the code reads frameDelay."
                ),
                evidence_ids=("redux-flamepuff-contract",),
            ),
        ),
        legacy_keys=(
            LegacyKey(
                name="flameLength",
                severity="WARNING",
                message="flameLength is not part of the recovered Redux FlamePuffClass key set.",
                suggestion="Remove or replace it only after matching the intended effect to a code-read FlamePuffClass field.",
                evidence_ids=("redux-flamepuff-contract",),
            ),
            LegacyKey(
                name="variance",
                severity="WARNING",
                message="variance is not part of the recovered Redux FlamePuffClass key set.",
                suggestion="Remove or replace it only after matching the intended effect to a code-read FlamePuffClass field.",
                evidence_ids=("redux-flamepuff-contract",),
            ),
            LegacyKey(
                name="shotColor",
                severity="WARNING",
                message="shotColor is not part of the recovered Redux FlamePuffClass key set.",
                suggestion="Remove or replace it only after matching the intended effect to a code-read FlamePuffClass field.",
                evidence_ids=("redux-flamepuff-contract",),
            ),
        ),
    ),
    LoaderRule(
        rule_id="explosion-section",
        expected_section="ExplosionClass",
        legacy_sections=("Explosion",),
        class_labels=("explosion",),
        required_sections=("OrdnanceClass",),
        section_severity="ERROR",
        section_message=(
            "This ODF dispatches the explosion ordnance path, but Redux reads "
            "explosion-specific fields from [ExplosionClass]. Keys placed under "
            "legacy [Explosion] are not consumed by that loader."
        ),
        source="Recovered Redux ExplosionClass loader contract",
        evidence_ids=("redux-explosionclass-contract",),
    ),
    LoaderRule(
        rule_id="spray-building-section",
        expected_section="SprayBuildingClass",
        legacy_sections=("SprayBuildngClass",),
        required_sections=("BuildingClass",),
        section_severity="ERROR",
        section_message=(
            "Redux reads spray-building-specific fields from [SprayBuildingClass]. "
            "The misspelled [SprayBuildngClass] section has no recovered reader, so "
            "its fields are ignored."
        ),
        source="Recovered Redux SprayBuildingClass loader + stock-content audit",
        evidence_ids=("redux-spraybuilding-contract",),
    ),
)


REFERENCE_KEYS = {
    "FlareMineClass": (
        ReferenceKey(
            name="payloadName",
            severity="ERROR",
            evidence_ids=("redux-flaremine-load", "odf-reference-resolution"),
        ),
    ),
    "OrdnanceClass": (
        ReferenceKey(name="xplGround", severity="WARNING"),
        ReferenceKey(name="xplVehicle", severity="WARNING"),
        ReferenceKey(name="xplBuilding", severity="WARNING"),
    ),
}


SCHEMA_VERSION = 6
