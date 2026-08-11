"""Renditions of a work: display crops, details, and captures.

The archive stores a painting more than once on purpose. A master is kept
alongside 16:9 and 9:16 re-cuts prepared for picture frames, and the schema says
of file variants: "These are NOT duplicates: each is fit for a specific device."
When those re-cuts were ingested as their own ``work_id`` rather than as
``files.variants[]`` entries, three problems follow:

* the rendition repeats the parent's identity, and the two copies drift;
* the rendition and its parent both claim the same work Q-ID, which
  :mod:`fine_art_archive.identity.work_qid_uniqueness` must read as a collision
  because it cannot tell a crop sibling from two works fighting over one Q-ID;
* a rendition that never got the identity at all looks like an unresolved work,
  and enrichment passes go back out to the network to re-derive what the parent
  already knows.

``derived_from`` names the parent and the kind of rendition. This module reads
that link: it resolves inheritance so a rendition takes identity from its
parent, and it answers whether two works are the same object, which is what
lets the uniqueness guard stop reporting crop siblings as collisions.

Detection is deliberately not here. A crop is recognised by comparing the image
file's aspect ratio against the work's own recorded ``dimensions_original`` --
an image-processing job that belongs to the pass that writes the link, not to
the model that reads it.
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
    "same_object",
]

DERIVATION_KINDS = frozenset({"display-crop", "detail", "capture"})

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

# Within ``stable_identifiers``, these denote the *work* and so are shared by
# every rendition of it. Others (a IIIF manifest, a Commons file) point at a
# particular image and are not inherited.
INHERITABLE_IDENTIFIERS: tuple[str, ...] = (
    "wikidata_q",
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

    @property
    def is_crop(self) -> bool:
        return self.kind == "display-crop"


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


def same_object(
    a_work_id: str,
    b_work_id: str,
    *,
    load: Callable[[str], dict[str, Any] | None],
) -> bool:
    """Do these two work_ids depict the same physical work?

    True when one is a rendition of the other, or both are renditions of one
    parent. This is what makes a shared work Q-ID correct rather than a
    collision -- and it stays False for two genuinely different works, so the
    uniqueness guard keeps its teeth.
    """
    if a_work_id == b_work_id:
        return True
    return family_root(a_work_id, load=load) == family_root(b_work_id, load=load)


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
    overwritten: where the rendition already holds something different, the
    field name is reported in ``conflicts`` and left alone. Silently replacing
    it would paper over exactly the disagreements worth looking at -- four
    renditions in this archive hold a *different* work Q-ID from their parent,
    and one of the two is wrong.
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
