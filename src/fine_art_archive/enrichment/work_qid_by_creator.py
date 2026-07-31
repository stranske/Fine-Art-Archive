"""Resolve a work's Wikidata QID via SPARQL by-creator + title match.

A work stranded without ``stable_identifiers.wikidata_q`` cannot be categorised
through the P31 (instance-of) path, and free-text title search cannot find the
QID for anything but the most famous works. When the *artist* QID is known this
instead enumerates the creator's works on Wikidata (``?w wdt:P170 wd:<creator>``)
and matches the title under the same strict guards the holder pass uses -- best
title score, unambiguity over the runner-up, year agreement -- then returns the
matched work's QID.

This reuses :func:`fine_art_archive.enrichment.holder_by_creator.match_work_entity`,
which settles work *identity* independently of whether the work records a
holder. The holder pass writes a work QID only as a side effect of finding a
collection, so a work whose match is real but which has no P195/P276 holder on
Wikidata never gets its QID from that path; this resolver fills exactly that gap.

Because every candidate comes from the creator's own oeuvre (P170), a match is
by construction an artwork -- this cannot yield the person / place / article
mis-resolutions that free-text title search produces, so no P31 allowlist guard
is needed here. A wrong *creator* QID is self-defending: the creator's works
will not title-match the sidecar at the threshold, so the pass declines rather
than writing a wrong work QID.
"""

from __future__ import annotations

from dataclasses import dataclass

from fine_art_archive.enrichment.holder_by_creator import (
    SparqlQuerier,
    match_work_entity,
    works_by_creator,
    year_of,
)

__all__ = ["WorkQidMatch", "resolve_work_qid", "year_of"]


@dataclass(frozen=True)
class WorkQidMatch:
    work_qid: str
    label: str
    score: float


def resolve_work_qid(
    title: str, sidecar_year: int | None, creator_qid: str, *, client: SparqlQuerier
) -> tuple[WorkQidMatch | None, str]:
    """Resolve one work's QID from its creator's Wikidata works.

    Returns ``(WorkQidMatch, "match")`` or ``(None, reason)`` where ``reason`` is
    one of ``no-creator`` / ``no-works`` / ``below-threshold`` / ``ambiguous`` /
    ``year-mismatch``.
    """
    if not creator_qid:
        return None, "no-creator"
    works = works_by_creator(creator_qid, client=client)
    best, score, reason = match_work_entity(title, sidecar_year, works)
    if best is None:
        return None, reason
    return WorkQidMatch(best.work_qid, best.label, score), "match"
