"""Derived items: a section of a work presented in its own right.

``derived_from`` marks a sidecar as a detail of a fresco, a reconstruction, or a
distinct state of a print -- something genuinely presentable that nonetheless
has no identity of its own. This module reads that link so callers can resolve
the parent's identity instead of copying it.

Two boundaries matter, and both are drawn by the schema rather than here.

**A derived item never holds its own work Q-ID.** The invariant is
``derived_from set => stable_identifiers.wikidata_q is null``, and it exists
because giving details work-level identity is how a single Q-ID came to sit on
fifty separate Scrovegni sidecars. Writing one is worse than a wrong field: the
invariant repair clears it, the next resolver run sets it again, and the two
oscillate. Use :func:`resolved_work_qid` to ask which Wikidata work a detail
depicts; do not store the answer.

**A display crop is not a derived item.** A 16:9 re-cut for a picture frame is
device fitness, which ``files.variants[]`` models -- "These are NOT duplicates:
each is fit for a specific device" -- not curatorial selection of a section.
Crops that were ingested as their own ``work_id`` are a modelling problem to be
fixed by merging them into the parent's variants, not by pointing
``derived_from`` at the parent and letting both hold the identity.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

__all__ = [
    "DERIVATION_KINDS",
    "INHERITABLE_FIELDS",
    "Derivation",
    "derivation_of",
    "family_root",
    "inherit",
    "resolved_work_qid",
    "violates_identity_invariant",
]

# Mirrors the ``derived_from.kind`` enum in schemas/meta.schema.json. There is
# deliberately no display-crop member: a 16:9 re-cut is device fitness, which
# ``files.variants[]`` models, not curatorial selection of a section.
DERIVATION_KINDS = frozenset({"detail", "reconstruction", "state", "capture"})

# Identity travels from parent to rendition; per-file facts do not. ``files``,
# ``display_hints``, ``ratings`` and ``history`` describe *this* image and must
# stay local, which is why they are absent here.
INHERITABLE_FIELDS: tuple[str, ...] = (
    "artist",
    "title",
    "title_alternate",
    "year",
    "year_min",
    "year_max",
    "medium",
    "category",
    "dimensions_original",
    "holder",
    "site",
    "rights",
    "stable_identifiers",
)

# Within ``stable_identifiers``, these describe the parent work and are safe to
# copy onto a derived item. ``wikidata_q`` is deliberately absent: the schema
# invariant is that a sidecar with ``derived_from`` set holds a *null*
# ``wikidata_q``, and writing one does not merely add a wrong field -- it starts
# an oscillation, because the invariant repair clears it and the next resolver
# run sets it again (observed flipping five times in seventy minutes on
# 8d8f6ab-the-birth-of-venus-botticelli). Read the parent's identity with
# :func:`resolved_work_qid` instead of storing a copy.
INHERITABLE_IDENTIFIERS: tuple[str, ...] = (
    "part_of_q",
    "museum_accession",
    "museum_institution_ror",
    "ulan_for_artist",
)


@dataclass(frozen=True)
class Derivation:
    """A rendition's link to the work it depicts."""

    parent_work_id: str
    kind: str
    region: str | None = None
    detected_by: str | None = None
    image_correlation: float | None = None


def derivation_of(meta: dict[str, Any]) -> Derivation | None:
    """Parse ``derived_from``, or None when this work stands on its own."""
    raw = meta.get("derived_from")
    if not isinstance(raw, dict):
        return None
    parent = raw.get("work_id")
    kind = raw.get("kind")
    if not isinstance(parent, str) or not parent:
        return None
    if kind not in DERIVATION_KINDS:
        return None
    correlation = raw.get("image_correlation")
    return Derivation(
        parent_work_id=parent,
        kind=kind,
        region=raw.get("region"),
        detected_by=raw.get("detected_by"),
        image_correlation=float(correlation) if isinstance(correlation, (int, float)) else None,
    )


def family_root(
    work_id: str,
    *,
    load: Callable[[str], dict[str, Any] | None],
    max_depth: int = 8,
) -> str:
    """Follow ``derived_from`` to the work every rendition in the chain depicts.

    A rendition of a rendition is legal (a crop cut from a detail), so this
    walks rather than taking one step. A cycle or a missing parent resolves to
    the last work actually reached, so a broken link degrades to "stands alone"
    instead of raising.
    """
    seen = {work_id}
    current = work_id
    for _ in range(max_depth):
        meta = load(current)
        if meta is None:
            return current
        derivation = derivation_of(meta)
        if derivation is None:
            return current
        parent = derivation.parent_work_id
        if parent in seen:
            return current
        seen.add(parent)
        current = parent
    return current


def resolved_work_qid(
    work_id: str,
    *,
    load: Callable[[str], dict[str, Any] | None],
) -> str | None:
    """The work Q-ID that applies to this sidecar, following ``derived_from``.

    A derived item has no identity of its own -- it inherits the parent's -- but
    that identity is *resolved*, never stored. Storing it would breach the
    schema invariant and start the repair/resolver oscillation described on
    :data:`INHERITABLE_IDENTIFIERS`. Callers that need to know which Wikidata
    work a detail depicts should ask this rather than read the field.
    """
    root = family_root(work_id, load=load)
    meta = load(root)
    if meta is None:
        return None
    stable = meta.get("stable_identifiers")
    if not isinstance(stable, dict):
        return None
    qid = stable.get("wikidata_q")
    return qid if isinstance(qid, str) and qid else None


def violates_identity_invariant(meta: dict[str, Any]) -> bool:
    """True when a derived item also claims a work Q-ID of its own.

    The pairing the schema forbids, and the shape that put one Q-ID on fifty
    separate Scrovegni sidecars.
    """
    if derivation_of(meta) is None:
        return False
    stable = meta.get("stable_identifiers")
    if not isinstance(stable, dict):
        return False
    qid = stable.get("wikidata_q")
    return isinstance(qid, str) and bool(qid)


def _is_empty(value: Any) -> bool:
    return value is None or value == {} or value == [] or value == ""


def inherit(
    meta: dict[str, Any],
    parent: dict[str, Any],
    *,
    fields: Iterable[str] | None = None,
) -> tuple[dict[str, Any], list[str], list[str]]:
    """Fill a rendition's empty identity fields from its parent.

    Returns ``(meta, filled, conflicts)``. Existing values are never
    overwritten: where the derived item already holds something different, the
    field name is reported in ``conflicts`` and left alone. Copies drift -- a
    parent reading "Claude Monet, May 1888" against a detail reading "Monet,
    1888" -- and picking a winner is a curatorial call, not one this function
    should make silently.
    """
    filled: list[str] = []
    conflicts: list[str] = []
    wanted = tuple(fields) if fields is not None else INHERITABLE_FIELDS

    for field in wanted:
        parent_value = parent.get(field)
        if _is_empty(parent_value):
            continue

        if field == "stable_identifiers":
            local = meta.setdefault("stable_identifiers", {})
            if not isinstance(local, dict):
                conflicts.append(field)
                continue
            for key in INHERITABLE_IDENTIFIERS:
                inherited = parent_value.get(key) if isinstance(parent_value, dict) else None
                if _is_empty(inherited):
                    continue
                if _is_empty(local.get(key)):
                    local[key] = inherited
                    filled.append(f"stable_identifiers.{key}")
                elif local[key] != inherited:
                    conflicts.append(f"stable_identifiers.{key}")
            continue

        if _is_empty(meta.get(field)):
            meta[field] = parent_value
            filled.append(field)
        elif meta[field] != parent_value:
            conflicts.append(field)

    return meta, filled, conflicts
