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

That second boundary has a consequence for every pass that WRITES a work Q-ID,
and :func:`variant_links` is where it is stated once. The invariant over
``derived_from`` is enforced by the schema's own ``allOf``; the same rule over
``files.variants[]`` is not, because a variant entry lives in the OWNER's
sidecar and says nothing inside the holding's. So nothing stopped a resolver
from filling in the crop, and every pass that filled work Q-IDs restored the
sharing the crop repair had just cleared -- the schema records a value rewritten
onto the Birth of Venus crop twice in one day on 2026-08-09, and a dry run on
2026-08-11 proposed restoring Q185372, Q1091086 and Q151047 onto the Girl with a
Pearl Earring, Third of May and Birth of Venus crops minutes after they were
cleared. None of those passes was wrong about the artwork: a crop of a work IS
that work, so a title+creator match finds the right Q-ID for it. What was
missing is the statement that the crop's sidecar is a HOLDING rather than the
work, which is what the queue rule here supplies.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

__all__ = [
    "DERIVATION_KINDS",
    "INHERITABLE_FIELDS",
    "Derivation",
    "VariantHolding",
    "VariantLinks",
    "derivation_of",
    "family_root",
    "inherit",
    "resolved_work_qid",
    "variant_links",
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


@dataclass(frozen=True)
class VariantHolding:
    """A sidecar that another sidecar has declared to be one of its variants."""

    work_id: str
    owner_work_id: str
    role: str


@dataclass(frozen=True)
class VariantLinks:
    """Who holds a variant of whom, across a set of sidecars.

    ``holdings`` maps a held sidecar's ``work_id`` to the owner that lists it.
    Two link shapes are deliberately kept OUT of it, because neither settles
    which side bears the identity:

    ``self_referential``
        a sidecar listing its own ``work_id``. Nothing can inherit from itself,
        so this is a defect in the link, not in the identity.
    ``ambiguous``
        A lists B and B lists A. A 2026-08-09 pass wrote entries in the
        direction opposite to today's, so several pairs now claim each other.
        Whoever wrote the entry does not settle which file is the crop, and
        guessing would strip the Q-ID from the authoritative capture.

    Both are still barred from a resolver queue by :meth:`may_hold_work_qid`:
    declining to write is recoverable, writing the identity onto the wrong side
    of the relationship is what this whole rule exists to prevent.
    """

    holdings: Mapping[str, VariantHolding]
    ambiguous: frozenset[str]
    self_referential: frozenset[str]

    @classmethod
    def from_sidecars(
        cls,
        paths: Iterable[Any],
        *,
        load: Callable[[Any], dict[str, Any]],
    ) -> VariantLinks:
        """Build the relation by loading each sidecar path.

        Unreadable sidecars are skipped rather than raised on, for the reason
        :meth:`WorkQidClaims.from_sidecars` gives: the archive audit counts and
        reports them, and one parse failure must not disable the guard.
        """
        metas: list[dict[str, Any]] = []
        for path in paths:
            try:
                metas.append(load(path))
            except Exception:  # noqa: BLE001 - see docstring
                continue
        return variant_links(metas)

    def may_hold_work_qid(self, work_id: str) -> bool:
        """False when a pass must not write ``stable_identifiers.wikidata_q`` here."""
        return self.exclusion_reason(work_id) is None

    def exclusion_reason(self, work_id: str) -> str | None:
        """Why this sidecar is barred from a work-QID queue, or None."""
        if work_id in self.holdings:
            return "variant-holding"
        if work_id in self.ambiguous:
            return "variant-link-ambiguous"
        return None


def _held_work_id(rel_path: Any) -> str | None:
    """The ``work_id`` a ``files.variants[].rel_path`` points at.

    ``rel_path`` is relative to ``<archive_root>/Art/`` per the schema, so a
    holding inside the archive reads ``works/<work_id>/<file>``. Anything else
    (a path outside ``works/``, a bare filename) names no sidecar and is not a
    holding statement.
    """
    text = str(rel_path or "")
    if not text.startswith("works/"):
        return None
    parts = text.split("/")
    return parts[1] if len(parts) > 2 and parts[1] else None


def variant_links(metas: Iterable[dict[str, Any]]) -> VariantLinks:
    """Read every sidecar's ``files.variants[]`` into one holding relation.

    A resolver calls this once per run and skips anything
    :meth:`VariantLinks.may_hold_work_qid` refuses: a sidecar named in another
    sidecar's variants is a second HOLDING of a work, not a work, and is not
    eligible for a work Q-ID of its own. Identity stays on the owner and the
    holding reaches it through the entry that names it.
    """
    edges: dict[str, list[tuple[str, str]]] = {}
    self_referential: set[str] = set()

    for meta in metas:
        owner = meta.get("work_id")
        if not isinstance(owner, str) or not owner:
            continue
        files = meta.get("files")
        entries = files.get("variants") if isinstance(files, dict) else None
        for entry in entries or []:
            if not isinstance(entry, dict):
                continue
            held = _held_work_id(entry.get("rel_path"))
            if held is None:
                continue
            if held == owner:
                self_referential.add(owner)
                continue
            edges.setdefault(held, []).append((owner, str(entry.get("role") or "unknown")))

    holdings: dict[str, VariantHolding] = {}
    ambiguous: set[str] = set()
    for held, owners in edges.items():
        if any(held in [o for o, _role in edges.get(owner, [])] for owner, _role in owners):
            ambiguous.add(held)
            continue
        owner, role = owners[0]
        holdings[held] = VariantHolding(work_id=held, owner_work_id=owner, role=role)

    return VariantLinks(
        holdings=holdings,
        ambiguous=frozenset(ambiguous),
        self_referential=frozenset(self_referential),
    )


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
