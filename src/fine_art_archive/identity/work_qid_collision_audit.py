"""Measure work Q-ID collisions across an entire sidecar corpus.

Resolver eligibility (:meth:`VariantLinks.may_hold_work_qid`) deliberately
excludes variant holdings and ambiguous mutual pairs from *new* assignments.
Collision auditing must do the opposite: count every sidecar that currently
asserts ``stable_identifiers.wikidata_q``, including holdings and ambiguous
pairs. Under-reporting here is how shared-Q-ID backlogs silently rebuild
(Fine-Art-Archive#591).

That total is necessary and it is not sufficient, because not every collision is
a defect. A work too wide for any panel is held as several complementary crops,
and each of them depicts that work, so each *correctly* carries its Q-ID. On
2026-09-01 ``qids_on_multiple`` was 2 and BOTH were complementary-crop pairs:
the metric read as two outstanding defects with nothing that could ever clear
them, and the weekly review had put the same two pairs to the owner five times.
A count whose drainable quantity is zero is a latched gate, and reporting the
blocking number without the drainable one is what let it sit.

So the totals are partitioned rather than filtered. ``qids_on_multiple`` still
counts everything, which keeps #591's regression caught; ``crop_sibling_qids``
names the subset that is correct by construction, ``distinct_object_qids`` the
second such subset (two impressions of a print, two painted versions -- the
Q-ID names the WORK, a sidecar describes an OBJECT); and ``actionable_qids`` is
what is actually left to fix. Only the last one is allowed to drive a review
surface, and only the last one can reach zero.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from typing import Any

from fine_art_archive.identity.crop_siblings import crop_sibling_groups
from fine_art_archive.identity.same_object import distinct_object_groups
from fine_art_archive.identity.variant_identity import work_qid_of
from fine_art_archive.identity.variants import variant_links

__all__ = [
    "WorkQidCollisionMeasures",
    "actionable_offenders",
    "measure_work_qid_collisions",
    "measures_as_dict",
    "worst_offenders",
]


@dataclass(frozen=True)
class WorkQidCollisionMeasures:
    """Stable collision counters for archive audits and weekly review JSON."""

    sidecars: int
    valid_work_qid: int
    distinct_work_qids: int
    qids_on_multiple: int
    extra_assignments: int
    holdings_asserting_own_qid: int
    mutual_links_ambiguous: int
    self_referential_variant_entries: int
    #: Of ``qids_on_multiple``, those shared by complementary crops of one work.
    #: Correct by construction -- nothing here is a defect and nothing can
    #: clear it, so it must never be presented as outstanding work.
    crop_sibling_qids: int = 0
    #: Of ``qids_on_multiple``, those shared by DOCUMENTED DIFFERENT OBJECTS --
    #: two impressions of a print, two painted versions. Also correct by
    #: construction: the archive wants both, and the Q-ID names the work, not
    #: the object.
    distinct_object_qids: int = 0
    #: ``qids_on_multiple`` minus the two categories above: the drainable
    #: count, and the only one a review surface may act on. This is the number
    #: that reaches zero.
    actionable_qids: int = 0


def worst_offenders(metas: Iterable[Mapping[str, Any]], *, limit: int = 10) -> dict[str, list[str]]:
    """Return shared Q-IDs mapped to every sidecar that currently holds them."""
    holders: dict[str, list[str]] = defaultdict(list)
    for meta in metas:
        qid = work_qid_of(meta)
        if not qid:
            continue
        work_id = str(meta.get("work_id") or "")
        holders[qid].append(work_id)

    shared = {qid: sorted(work_ids) for qid, work_ids in holders.items() if len(work_ids) > 1}
    ordered = sorted(
        shared.items(),
        key=lambda item: (-len(item[1]), item[0]),
    )
    return dict(ordered[:limit])


def actionable_offenders(
    metas: Iterable[Mapping[str, Any]], *, limit: int = 10
) -> dict[str, list[str]]:
    """Shared Q-IDs that are actually defects — the review surface's input.

    :func:`worst_offenders` is the raw listing and deliberately hides nothing.
    This is what a surface that ASKS SOMEONE TO DECIDE must read instead: it
    drops the complementary-crop groups, which are correct by construction and
    have no remedy to choose between. Putting those in front of a person is how
    the same two Tintoretto and Van Gogh pairs came back five weeks running.
    """
    materialized = [meta for meta in metas if isinstance(meta, Mapping)]
    excused = {group.work_qid for group in crop_sibling_groups(materialized)}
    excused |= {group.work_qid for group in distinct_object_groups(materialized)}
    kept = {
        qid: work_ids
        for qid, work_ids in worst_offenders(materialized, limit=limit + len(excused)).items()
        if qid not in excused
    }
    return dict(list(kept.items())[:limit])


def measure_work_qid_collisions(metas: Iterable[Mapping[str, Any]]) -> WorkQidCollisionMeasures:
    """Count collisions from every sidecar that asserts a work Q-ID today."""
    materialized = [meta for meta in metas if isinstance(meta, Mapping)]
    holders: dict[str, list[str]] = defaultdict(list)
    valid_work_qid = 0

    for meta in materialized:
        qid = work_qid_of(meta)
        if not qid:
            continue
        valid_work_qid += 1
        work_id = str(meta.get("work_id") or "")
        holders[qid].append(work_id)

    distinct_work_qids = len(holders)
    qids_on_multiple = sum(1 for work_ids in holders.values() if len(work_ids) > 1)
    extra_assignments = valid_work_qid - distinct_work_qids

    links = variant_links(materialized)
    by_work_id = {
        str(meta.get("work_id")): meta
        for meta in materialized
        if isinstance(meta.get("work_id"), str) and meta.get("work_id")
    }
    holdings_asserting_own_qid = sum(
        1 for work_id in links.holdings if work_qid_of(by_work_id.get(work_id, {}))
    )

    crop_groups = crop_sibling_groups(materialized)
    crop_sibling_qids = sum(
        1 for group in crop_groups if len(holders.get(group.work_qid, ())) > 1
    )
    excused_as_crops = {group.work_qid for group in crop_groups}
    distinct_object_qids = sum(
        1
        for group in distinct_object_groups(materialized)
        if len(holders.get(group.work_qid, ())) > 1
        and group.work_qid not in excused_as_crops
    )

    return WorkQidCollisionMeasures(
        sidecars=len(materialized),
        valid_work_qid=valid_work_qid,
        distinct_work_qids=distinct_work_qids,
        qids_on_multiple=qids_on_multiple,
        extra_assignments=extra_assignments,
        holdings_asserting_own_qid=holdings_asserting_own_qid,
        mutual_links_ambiguous=len(links.ambiguous),
        self_referential_variant_entries=len(links.self_referential),
        crop_sibling_qids=crop_sibling_qids,
        distinct_object_qids=distinct_object_qids,
        actionable_qids=qids_on_multiple - crop_sibling_qids - distinct_object_qids,
    )


def measures_as_dict(measures: WorkQidCollisionMeasures) -> dict[str, int]:
    """Serialize counters for JSON audit reports."""
    return asdict(measures)
