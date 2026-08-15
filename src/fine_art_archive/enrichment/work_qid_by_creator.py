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
    tied_candidates,
    works_by_creator,
    year_of,
)

__all__ = ["WorkQidMatch", "resolve_work_qid", "year_of"]

# Wikidata length-unit QIDs -> centimetres.
_UNIT_TO_CM = {"Q174728": 1.0, "Q174789": 0.1, "Q11573": 100.0, "Q218593": 2.54}
_DIM_TOLERANCE_CM = 2.0


def _dimensions_query(qids: list[str]) -> str:
    values = " ".join(f"wd:{q}" for q in qids)
    return (
        "SELECT ?w ?h ?hu ?wd ?wu WHERE { "
        f"VALUES ?w {{ {values} }} "
        "OPTIONAL { ?w p:P2048/psv:P2048 [wikibase:quantityAmount ?h; wikibase:quantityUnit ?hu] } "
        "OPTIONAL { ?w p:P2049/psv:P2049 [wikibase:quantityAmount ?wd; wikibase:quantityUnit ?wu] } "
        "}"
    )


def _to_cm(amount: str | None, unit_uri: str | None) -> float | None:
    if amount is None:
        return None
    unit = (unit_uri or "").rsplit("/", 1)[-1]
    try:
        return float(amount) * _UNIT_TO_CM.get(unit, 1.0)
    except (TypeError, ValueError):
        return None


def fetch_dimensions(
    qids: list[str], *, client: SparqlQuerier
) -> dict[str, tuple[float | None, float | None]]:
    """Return ``{qid: (height_cm, width_cm)}`` for the given works (P2048/P2049)."""
    if not qids:
        return {}
    payload = client.query(_dimensions_query(qids))
    out: dict[str, tuple[float | None, float | None]] = {}
    if not isinstance(payload, dict):
        return out
    for row in payload.get("results", {}).get("bindings", []):
        qid = row.get("w", {}).get("value", "").rsplit("/", 1)[-1]
        if not qid:
            continue
        h = _to_cm(row.get("h", {}).get("value"), row.get("hu", {}).get("value"))
        w = _to_cm(row.get("wd", {}).get("value"), row.get("wu", {}).get("value"))
        out[qid] = (h, w)
    return out


def _dims_match(
    candidate: tuple[float | None, float | None], sidecar: tuple[float | None, float | None]
) -> bool:
    (ch, cw), (sh, sw) = candidate, sidecar
    if ch is None or cw is None or sh is None or sw is None:
        return False
    return abs(ch - sh) <= _DIM_TOLERANCE_CM and abs(cw - sw) <= _DIM_TOLERANCE_CM


# Coarse medium keywords -> the sidecar ``category`` a P31 class corresponds to.
# Prints in particular routinely produce a same-title cluster (a painting AND its
# print edition, both P170=creator, both "Aaron"); the medium tells them apart.
_MEDIUM_KEYWORDS: dict[str, tuple[str, ...]] = {
    "print": (
        "print",
        "lithograph",
        "etching",
        "engraving",
        "woodcut",
        "woodblock",
        "screenprint",
        "serigraph",
        "aquatint",
        "drypoint",
        "mezzotint",
        "linocut",
    ),
    "painting": ("painting", "fresco", "mural", "tempera", "oil on"),
    "sculpture": ("sculpture", "statue", "relief", "bronze", "bust", "carving", "statuette"),
    "drawing": ("drawing", "sketch", "pastel", "watercolor", "watercolour", "gouache", "cartoon"),
    "photograph": ("photograph", "photo"),
}


def _coarse_medium(text: str) -> str | None:
    low = text.lower()
    for medium, keywords in _MEDIUM_KEYWORDS.items():
        if any(kw in low for kw in keywords):
            return medium
    return None


def _p31_labels_query(qids: list[str]) -> str:
    values = " ".join(f"wd:{q}" for q in qids)
    return (
        "SELECT ?w ?typeLabel WHERE { "
        f"VALUES ?w {{ {values} }} "
        "?w wdt:P31 ?type . "
        'SERVICE wikibase:label { bd:serviceParam wikibase:language "en". '
        "?type rdfs:label ?typeLabel } }"
    )


def fetch_media(qids: list[str], *, client: SparqlQuerier) -> dict[str, set[str]]:
    """Return ``{qid: {coarse-medium, ...}}`` from each work's P31 class labels."""
    if not qids:
        return {}
    payload = client.query(_p31_labels_query(qids))
    out: dict[str, set[str]] = {}
    if not isinstance(payload, dict):
        return out
    for row in payload.get("results", {}).get("bindings", []):
        qid = row.get("w", {}).get("value", "").rsplit("/", 1)[-1]
        medium = _coarse_medium(row.get("typeLabel", {}).get("value", ""))
        if qid and medium:
            out.setdefault(qid, set()).add(medium)
    return out


@dataclass(frozen=True)
class WorkQidMatch:
    work_qid: str
    label: str
    score: float


def resolve_work_qid(
    title: str,
    sidecar_year: int | None,
    creator_qid: str,
    *,
    client: SparqlQuerier,
    holder_qid: str | None = None,
    dimensions: tuple[float | None, float | None] | None = None,
    category: str | None = None,
) -> tuple[WorkQidMatch | None, str]:
    """Resolve one work's QID from its creator's Wikidata works.

    Same-title clusters are disambiguated by (in order) the holder (``holder_qid``,
    the definitive P195 collection) and the year (both inside ``match_work_entity``),
    then, on a remaining tie, the **medium** (``category`` = the sidecar's
    painting/print/sculpture/drawing) and the **dimensions** (``(height_cm,
    width_cm)``). The medium tie-break is what tells a painting from its own print
    edition -- a routine same-title collision (e.g. Benton's "Aaron" exists as both
    a PAFA painting and an NGA lithograph).

    Returns ``(WorkQidMatch, "match")`` or ``(None, reason)`` where ``reason`` is
    one of ``no-creator`` / ``no-works`` / ``below-threshold`` / ``ambiguous`` /
    ``year-mismatch``.
    """
    if not creator_qid:
        return None, "no-creator"
    works = works_by_creator(creator_qid, client=client)
    best, score, reason = match_work_entity(title, sidecar_year, works, holder_qid=holder_qid)
    if best is not None:
        return WorkQidMatch(best.work_qid, best.label, score), "match"

    if reason != "ambiguous":
        return None, reason
    tied = tied_candidates(title, works)
    if not tied:
        return None, reason

    # Medium tie-break: keep only candidates whose Wikidata P31 medium matches the
    # sidecar's category. Resolves the painting-vs-print same-title collision.
    want_medium = _coarse_medium(category or "")
    if want_medium:
        media = fetch_media([w.work_qid for w in tied], client=client)
        hits = [w for w in tied if want_medium in media.get(w.work_qid, set())]
        if len(hits) == 1:
            return WorkQidMatch(hits[0].work_qid, hits[0].label, score), "match"
        if hits:  # medium narrowed the cluster; disambiguate the remainder below
            tied = hits

    # Dimensions tie-break for a still-ambiguous same-title cluster.
    if dimensions and any(v is not None for v in dimensions):
        dims = fetch_dimensions([w.work_qid for w in tied], client=client)
        hits = [w for w in tied if _dims_match(dims.get(w.work_qid, (None, None)), dimensions)]
        if len(hits) == 1:
            return WorkQidMatch(hits[0].work_qid, hits[0].label, score), "match"
    return None, reason
