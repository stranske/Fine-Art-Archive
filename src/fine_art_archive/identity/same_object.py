"""Two sidecars, one work Q-ID, two different physical objects.

The fifth reason a work Q-ID lands on more than one sidecar, and the second one
that is not a defect. A work Q-ID identifies a WORK; a sidecar describes an
OBJECT. For anything that exists in multiples those are not the same thing:

  * A woodblock print has many impressions. Hokusai's *South Wind, Clear Sky*
    is Q3565037 whether the sheet is Cleveland 1930.189 or Indianapolis 60.12,
    and the archive holds both on purpose -- "there are a number of different
    versions. Collecting multiple versions is good" (owner, 2026-09-02).
  * Painted versions behave the same way. The archive deliberately holds both
    David's Louvre *Sacre* (INV 3699) and the Versailles replica (MV 7156).

So a shared work Q-ID across DOCUMENTED, DIFFERENT objects is correct, and
counting it as an outstanding defect gives the collision metric another floor
it cannot reach -- the same latched-gate shape that
:mod:`fine_art_archive.identity.crop_siblings` was written for.

**The discriminator is provenance, never the image.** Two impressions of one
print are visually identical; a master and its crop are too. Pixels cannot
separate an object from another object of the same work, which is why the
archive's standing rule is to discriminate on holder, accession and date.

Deliberately conservative in one direction: every member must carry BOTH a
holder and an accession, and they must be pairwise distinct. A group where any
member is missing provenance stays actionable, because "we did not record who
holds it" must never read as "it is a different object" -- that is the same
mistake as treating an unmeasurable check as a negative result.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from fine_art_archive.identity.variant_identity import work_qid_of

__all__ = [
    "DistinctObjectGroup",
    "distinct_object_groups",
    "object_key",
]


@dataclass(frozen=True)
class DistinctObjectGroup:
    """Sidecars sharing a work Q-ID that are provably different objects."""

    work_qid: str
    work_ids: tuple[str, ...]
    #: work_id -> (holder name, museum accession), the evidence that separates them.
    keys: Mapping[str, tuple[str, str]]


def object_key(meta: Mapping[str, Any]) -> tuple[str, str] | None:
    """(holder, accession) identifying the physical object, or None.

    None means "not documented", never "not distinct". Both halves are
    required: a holder alone cannot separate two impressions in one museum, and
    an accession alone is only unique within its institution.
    """
    holder = meta.get("holder")
    name = holder.get("name") if isinstance(holder, Mapping) else None
    stable = meta.get("stable_identifiers")
    accession = stable.get("museum_accession") if isinstance(stable, Mapping) else None
    if not isinstance(name, str) or not name.strip():
        return None
    if not isinstance(accession, str) or not accession.strip():
        return None
    return name.strip(), accession.strip()


def distinct_object_groups(metas: Iterable[Mapping[str, Any]]) -> list[DistinctObjectGroup]:
    """Shared work Q-IDs whose members are documented as different objects."""
    materialized = [m for m in metas if isinstance(m, Mapping)]
    by_qid: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for meta in materialized:
        qid = work_qid_of(meta)
        if qid:
            by_qid[qid].append(meta)

    groups: list[DistinctObjectGroup] = []
    for qid, members in sorted(by_qid.items()):
        if len(members) < 2:
            continue
        keys: dict[str, tuple[str, str]] = {}
        for meta in members:
            work_id = str(meta.get("work_id") or "")
            key = object_key(meta)
            if not work_id or key is None:
                keys = {}
                break
            keys[work_id] = key
        if not keys or len(keys) != len(members):
            continue
        if len(set(keys.values())) != len(keys):
            continue          # two members claim the SAME object: a real duplicate
        groups.append(
            DistinctObjectGroup(
                work_qid=qid,
                work_ids=tuple(sorted(keys)),
                keys=dict(sorted(keys.items())),
            )
        )
    return groups
