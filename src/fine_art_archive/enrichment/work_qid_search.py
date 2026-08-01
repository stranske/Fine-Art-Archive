"""Creator-independent work-QID search (Stage 3 of the exhaustion pipeline).

The by-creator resolver (Stage 1) only finds a work QID among the *creator's*
Wikidata oeuvre, so it misses works whose creator we can't confirm, or whose
label the P170 SPARQL doesn't surface. This stage searches Wikidata for the
title directly (``wbsearchentities``), then keeps only candidates that are
**artworks** (P31/P279* -> work of art) with a strong normalized-title match and
year agreement, and accepts one when:

  * exactly one such artwork is *by the sidecar's creator* (when known), OR
  * exactly one such artwork exists at all -- a **globally-unique artwork**
    match, accepted even without a confirmed creator.

This is the safe inverse of the free-text resolver that mis-attributed QIDs in
the first place: the mandatory ``P31=artwork`` gate means a title that also names
a person/place (``New York``, ``Juan de Pareja``) can never resolve to that
person/place, and the uniqueness + title-score + year guards keep a generic
title (many artwork hits) from resolving at all.

Both transports are injected: a ``.get(url, params=...)`` JSON client for the
search API and a ``.query(sparql)`` client for the candidate-type lookup.
"""

from __future__ import annotations

from collections.abc import Mapping
from difflib import SequenceMatcher
from typing import Any, Protocol

from fine_art_archive.enrichment.holder_by_creator import _score_for, year_of

WIKIDATA_API = "https://www.wikidata.org/w/api.php"
_ARTWORK_ROOT = "Q838948"  # work of art (covers every visual-artwork subclass)
TITLE_THRESHOLD = 0.90
YEAR_TOLERANCE = 6
_SEARCH_LIMIT = 12


class JsonGetter(Protocol):
    def get(
        self, url: str, *, params: Mapping[str, str] | None = None
    ) -> dict[str, Any] | None: ...


class SparqlQuerier(Protocol):
    def query(self, sparql: str) -> dict[str, Any] | None: ...


class Candidate:
    __slots__ = ("qid", "is_artwork", "creators", "score", "year")

    def __init__(
        self, qid: str, is_artwork: bool, creators: set[str], score: float, year: int | None
    ):
        self.qid = qid
        self.is_artwork = is_artwork
        self.creators = creators
        self.score = score
        self.year = year


def title_search_candidates(title: str, *, client: JsonGetter) -> list[str]:
    """Wikidata ``wbsearchentities`` QIDs for a title (label/alias match)."""
    if not title.strip():
        return []
    payload = client.get(
        WIKIDATA_API,
        params={
            "action": "wbsearchentities",
            "format": "json",
            "language": "en",
            "uselang": "en",
            "type": "item",
            "limit": str(_SEARCH_LIMIT),
            "search": title.strip(),
        },
    )
    hits = (payload or {}).get("search")
    if not isinstance(hits, list):
        return []
    return [h["id"] for h in hits if isinstance(h, dict) and str(h.get("id", "")).startswith("Q")]


def candidate_details_query(qids: list[str]) -> str:
    values = " ".join(f"wd:{q}" for q in qids)
    return (
        'SELECT ?w ?wLabel (GROUP_CONCAT(DISTINCT ?alt; separator="||") AS ?alts) '
        "(COUNT(DISTINCT ?art) AS ?nart) "
        '(GROUP_CONCAT(DISTINCT ?creator; separator=" ") AS ?creators) '
        "(SAMPLE(?inception) AS ?inception) WHERE { "
        f"VALUES ?w {{ {values} }} "
        'OPTIONAL { ?w rdfs:label ?wLabel . FILTER(LANG(?wLabel) = "en") } '
        'OPTIONAL { ?w skos:altLabel ?alt . FILTER(LANG(?alt) = "en") } '
        f"OPTIONAL {{ ?w wdt:P31/wdt:P279* wd:{_ARTWORK_ROOT} . BIND(1 AS ?art) }} "
        "OPTIONAL { ?w wdt:P170 ?creator } "
        "OPTIONAL { ?w wdt:P571 ?inception } "
        "} GROUP BY ?w ?wLabel"
    )


def _local(uri: str) -> str:
    return uri.rsplit("/", 1)[-1]


def _candidates(title: str, rows: list[dict[str, Any]]) -> list[Candidate]:
    title_norm = _score_for(title)
    out: list[Candidate] = []
    for row in rows:
        qid = _local(row.get("w", {}).get("value", ""))
        if not qid:
            continue
        label = row.get("wLabel", {}).get("value", "")
        alts = [a for a in row.get("alts", {}).get("value", "").split("||") if a]
        score = max(
            (SequenceMatcher(None, title_norm, _score_for(c)).ratio() for c in (label, *alts) if c),
            default=0.0,
        )
        creators = {_local(c) for c in row.get("creators", {}).get("value", "").split() if c}
        out.append(
            Candidate(
                qid=qid,
                is_artwork=row.get("nart", {}).get("value", "0") not in ("", "0"),
                creators=creators,
                score=score,
                year=year_of(row.get("inception", {}).get("value")),
            )
        )
    return out


def resolve_by_title_search(
    title: str,
    sidecar_year: int | None,
    creator_qid: str | None,
    *,
    json_client: JsonGetter,
    sparql_client: SparqlQuerier,
) -> tuple[str | None, str]:
    """Return ``(work_qid, reason)`` or ``(None, reason)`` for a title search.

    ``reason``: ``match-creator`` / ``match-global-unique`` / ``no-search-hit`` /
    ``no-artwork-hit`` / ``ambiguous``.
    """
    qids = title_search_candidates(title, client=json_client)
    if not qids:
        return None, "no-search-hit"
    payload = sparql_client.query(candidate_details_query(qids))
    if not isinstance(payload, dict):
        return None, "no-search-hit"
    rows = payload.get("results", {}).get("bindings", [])
    candidates = _candidates(title, rows)

    def _year_ok(cand: Candidate) -> bool:
        return not (
            sidecar_year is not None
            and cand.year is not None
            and abs(sidecar_year - cand.year) > YEAR_TOLERANCE
        )

    strong = [c for c in candidates if c.is_artwork and c.score >= TITLE_THRESHOLD and _year_ok(c)]
    if not strong:
        return None, "no-artwork-hit"

    if creator_qid:
        by_creator = [c for c in strong if creator_qid in c.creators]
        if len(by_creator) == 1:
            return by_creator[0].qid, "match-creator"
        if len(by_creator) > 1:
            return None, "ambiguous"

    # Globally-unique artwork match (accepted even without a confirmed creator).
    if len(strong) == 1:
        return strong[0].qid, "match-global-unique"
    return None, "ambiguous"
