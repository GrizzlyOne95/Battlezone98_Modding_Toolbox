"""Compatibility layer for the former local ODF inheritance resolver.

Recovered loader evidence shows that Redux's ``baseName`` field does **not**
load another ODF and merge its sections/keys. Defaults come from the engine's
prototype/class chain instead. Treating ``baseName = parent`` as file-level ODF
inheritance therefore fabricates effective state that the game never sees.

The public helpers are intentionally retained for now because ``odf_validator``
imports them, but they are conservative no-ops: every document is evaluated on
its own physical contents and no missing/cycle/parent diagnostics are produced.
A later cleanup can remove this compatibility module once the validator is
refactored around the mined loader/prototype model.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, Sequence, Tuple


@dataclass(frozen=True)
class BaseReference:
    """Retained API shape; file-level baseName references are no longer resolved."""

    parent: str
    section: str
    line: int


@dataclass(frozen=True)
class InheritanceState:
    status: str  # currently always "complete"
    chain: Tuple[Any, ...]
    target: str = ""
    cycle: Tuple[str, ...] = ()

    @property
    def complete(self) -> bool:
        return self.status == "complete"


@dataclass
class InheritanceGraph:
    states: Dict[str, InheritanceState]
    duplicates: Dict[str, Tuple[Any, ...]]

    def state_for(self, doc: Any) -> InheritanceState:
        return self.states.get(_doc_id(doc), InheritanceState("complete", (doc,)))


def _doc_id(doc: Any) -> str:
    return str(doc.path).replace("\\", "/").lower()


def canonical_base_reference(doc: Any) -> BaseReference | None:
    """Return ``None`` because baseName is not an ODF file-inheritance edge.

    This deliberately prevents validator code written for the old model from
    suppressing or synthesizing findings based on an alleged parent ODF.
    """

    return None


def build_inheritance_graph(
    documents: Sequence[Any],
    known_odfs: Iterable[str] = (),
) -> InheritanceGraph:
    """Return independent document states; no ODF-to-ODF graph is constructed."""

    del known_odfs
    states = {
        _doc_id(doc): InheritanceState("complete", (doc,))
        for doc in documents
    }
    return InheritanceGraph(states=states, duplicates={})


def merge_effective_sections(
    state: InheritanceState,
) -> tuple[Dict[str, list], Dict[str, str]]:
    """Return only the physical child document's sections.

    ``state.chain`` contains exactly one document under the corrected model.
    Copying the containers avoids accidental mutation by callers while keeping
    original key spelling and source line numbers intact.
    """

    if not state.chain:
        return {}, {}

    doc = state.chain[0]
    sections = {
        section: list(entries)
        for section, entries in doc.sections.items()
    }
    names = dict(doc.original_sections)
    return sections, names
