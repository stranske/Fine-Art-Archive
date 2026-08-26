"""Measure work Q-ID collisions across an entire sidecar corpus.

Resolver eligibility (:meth:`VariantLinks.may_hold_work_qid`) deliberately
excludes variant holdings and ambiguous mutual pairs from *new* assignments.
Collision auditing must do the opposite: count every sidecar that currently
asserts ``stable_identifiers.wikidata_q``, including holdings and ambiguous
pairs. Under-reporting here is how shared-Q-ID backlogs silently rebuild
(Fine-Art-Archive#591).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from typing import Any

from fine_art_archive.identity.variant_identity import work_qid_of
from fine_art_archive.identity.variants import variant_links

__all__ = [
    "WorkQidCollisionMeasures",
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

    return WorkQidCollisionMeasures(
        sidecars=len(materialized),
        valid_work_qid=valid_work_qid,
        distinct_work_qids=distinct_work_qids,
        qids_on_multiple=qids_on_multiple,
        extra_assignments=extra_assignments,
        holdings_asserting_own_qid=holdings_asserting_own_qid,
        mutual_links_ambiguous=len(links.ambiguous),
        self_referential_variant_entries=len(links.self_referential),
    )


def measures_as_dict(measures: WorkQidCollisionMeasures) -> dict[str, int]:
    """Serialize counters for JSON audit reports."""
    return asdict(measures)
