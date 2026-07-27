"""Resolve a work's holding institution via SPARQL by-creator + title match.

The holder pass reads P195 off a *work* entity, which needs a work QID that
free-text title search cannot find for obscure works. When the artist QID is
known, this instead enumerates the creator's works on Wikidata
(``?w wdt:P170 wd:<creator>``, with collection / inception / accession) and
fuzzy-matches the title -- then returns the matched work's collection as the
holder, but only under strict guards that defeat same-title-different-work
errors (an artist can have two works with the same title, e.g. Caravaggio's two
*St Jerome* paintings in different museums):

  * best title score >= ``SCORE_THRESHOLD``
  * UNAMBIGUOUS: no runner-up within ``AMBIGUITY_MARGIN`` of the best
  * YEAR agreement: if both the sidecar year and the work's inception parse,
    ``|delta| <= YEAR_TOLERANCE`` (missing either side is allowed)
  * the matched collection must be a real QID (SPARQL sometimes yields a
    statement hash for P195)

The SPARQL client is injected (any object with ``.query(str) -> dict | None``
returning the SPARQL-JSON results envelope) so callers supply a throttled/
retrying transport and tests supply a fake.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Protocol

from fine_art_archive.identity.artist_resolver import fold_name

SCORE_THRESHOLD = 0.93
AMBIGUITY_MARGIN = 0.04
YEAR_TOLERANCE = 6
_QID_RE = re.compile(r"Q[0-9]+")
_YEAR_RE = re.compile(r"(1[0-9]{3}|20[0-9]{2})")


class SparqlQuerier(Protocol):
    def query(self, sparql: str) -> dict[str, Any] | None: ...


@dataclass(frozen=True)
class CreatorWork:
    work_qid: str
    label: str
    collection_qid: str | None
    collection_label: str | None
    ror: str | None
    url: str | None
    accession: str | None
    inception: str | None


@dataclass(frozen=True)
class HolderMatch:
    work: CreatorWork
    score: float


def year_of(value: Any) -> int | None:
    match = _YEAR_RE.search(str(value or ""))
    return int(match.group(1)) if match else None


def _local_name(uri: str | None) -> str | None:
    return uri.rsplit("/", 1)[-1] if uri else None


def _binding_value(binding: dict[str, Any], key: str) -> str | None:
    return binding.get(key, {}).get("value")


def creator_works_query(creator_qid: str, *, limit: int = 600) -> str:
    return (
        "SELECT ?w ?wLabel ?coll ?collLabel ?ror ?url ?acc ?inception WHERE { "
        f"?w wdt:P170 wd:{creator_qid} . "
        "OPTIONAL { ?w wdt:P195 ?coll . "
        "OPTIONAL { ?coll wdt:P6782 ?ror } OPTIONAL { ?coll wdt:P856 ?url } } "
        "OPTIONAL { ?w wdt:P217 ?acc } OPTIONAL { ?w wdt:P571 ?inception } "
        'SERVICE wikibase:label { bd:serviceParam wikibase:language "en" } } '
        f"LIMIT {limit}"
    )


def works_by_creator(creator_qid: str, *, client: SparqlQuerier) -> list[CreatorWork]:
    payload = client.query(creator_works_query(creator_qid))
    if not payload:
        return []
    works: list[CreatorWork] = []
    for binding in payload.get("results", {}).get("bindings", []):
        work_qid = _local_name(_binding_value(binding, "w"))
        if work_qid is None:
            continue
        works.append(
            CreatorWork(
                work_qid=work_qid,
                label=_binding_value(binding, "wLabel") or "",
                collection_qid=_local_name(_binding_value(binding, "coll")),
                collection_label=_binding_value(binding, "collLabel"),
                ror=_binding_value(binding, "ror"),
                url=_binding_value(binding, "url"),
                accession=_binding_value(binding, "acc"),
                inception=_binding_value(binding, "inception"),
            )
        )
    return works


def match_work(title: str, sidecar_year: int | None, works: list[CreatorWork]) -> tuple[HolderMatch | None, str]:
    """Return ``(HolderMatch, "match")`` or ``(None, reason)`` under the guards."""
    folded = fold_name(title)
    scored = sorted(
        ((SequenceMatcher(None, folded, fold_name(w.label)).ratio(), w) for w in works),
        key=lambda pair: -pair[0],
    )
    if not scored:
        return None, "no-works"
    best_score, best = scored[0]
    if best_score < SCORE_THRESHOLD:
        return None, "below-threshold"
    if len(scored) > 1 and scored[1][0] >= best_score - AMBIGUITY_MARGIN:
        return None, "ambiguous"
    work_year = year_of(best.inception)
    if sidecar_year is not None and work_year is not None and abs(sidecar_year - work_year) > YEAR_TOLERANCE:
        return None, "year-mismatch"
    if not best.collection_qid or not _QID_RE.fullmatch(best.collection_qid):
        return None, "no-collection"
    return HolderMatch(best, best_score), "match"


def resolve_holder(
    title: str, sidecar_year: int | None, creator_qid: str, *, client: SparqlQuerier
) -> tuple[HolderMatch | None, str]:
    """Resolve a holder for one work from its creator's Wikidata works."""
    if not creator_qid:
        return None, "no-creator"
    return match_work(title, sidecar_year, works_by_creator(creator_qid, client=client))
