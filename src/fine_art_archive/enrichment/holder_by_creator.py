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


# Immovable categories whose "holder" is a physical location (a church, chapel,
# building), modeled by Wikidata P276, not a P195 museum collection.
IMMOVABLE_CATEGORIES = frozenset({"fresco", "stained_glass", "mural", "wall_painting"})


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
    location_qid: str | None = None
    location_label: str | None = None
    location_url: str | None = None


@dataclass(frozen=True)
class HolderMatch:
    work: CreatorWork
    score: float
    holder_qid: str
    holder_label: str | None
    holder_ror: str | None
    holder_url: str | None
    kind: str  # "collection" (P195) or "location" (P276, immovable works)


def year_of(value: Any) -> int | None:
    match = _YEAR_RE.search(str(value or ""))
    return int(match.group(1)) if match else None


def _local_name(uri: str | None) -> str | None:
    return uri.rsplit("/", 1)[-1] if uri else None


def _binding_value(binding: dict[str, Any], key: str) -> str | None:
    return binding.get(key, {}).get("value")


def creator_works_query(creator_qid: str, *, limit: int = 600) -> str:
    return (
        "SELECT ?w ?wLabel ?coll ?collLabel ?ror ?url ?acc ?inception "
        "?loc ?locLabel ?locUrl WHERE { "
        f"?w wdt:P170 wd:{creator_qid} . "
        "OPTIONAL { ?w wdt:P195 ?coll . "
        "OPTIONAL { ?coll wdt:P6782 ?ror } OPTIONAL { ?coll wdt:P856 ?url } } "
        "OPTIONAL { ?w wdt:P276 ?loc . OPTIONAL { ?loc wdt:P856 ?locUrl } } "
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
                location_qid=_local_name(_binding_value(binding, "loc")),
                location_label=_binding_value(binding, "locLabel"),
                location_url=_binding_value(binding, "locUrl"),
            )
        )
    return works


_LOC_STOPWORDS = frozenset({
    "the", "of", "di", "del", "della", "dei", "de", "la", "le", "il", "a",
    "chapel", "cappella", "church", "chiesa", "basilica", "cathedral", "duomo",
    "san", "santa", "santo", "sant", "saint", "st", "museo", "museum", "palazzo",
    "palace", "gallery", "galleria", "convent", "convento", "monastery",
})


def _norm_tokens(text: str) -> list[str]:
    import unicodedata

    ascii_text = "".join(
        c for c in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(c)
    )
    return [t for t in re.split(r"[^a-z0-9]+", ascii_text) if t]


def location_from_title(title: str, works: list[CreatorWork]) -> tuple[HolderMatch | None, str]:
    """Immovable fallback: match a location whose distinctive name appears in the
    title (e.g. "Capella dei Scrovegni - 20. ..." -> Scrovegni Chapel). Requires
    exactly one distinct matching location to stay unambiguous."""
    locations: dict[str, CreatorWork] = {}
    for w in works:
        if w.location_qid and _QID_RE.fullmatch(w.location_qid) and w.location_qid not in locations:
            locations[w.location_qid] = w
    if not locations:
        return None, "no-location"
    title_tokens = set(_norm_tokens(title))
    matched: list[CreatorWork] = []
    for w in locations.values():
        distinctive = {t for t in _norm_tokens(w.location_label or "") if len(t) >= 4 and t not in _LOC_STOPWORDS}
        if distinctive and distinctive & title_tokens:
            matched.append(w)
    if len(matched) != 1:
        return None, "ambiguous" if matched else "no-location-in-title"
    w = matched[0]
    return HolderMatch(w, 0.95, w.location_qid or "", w.location_label, None, w.location_url, "location"), "match"


def _derive_holder(work: CreatorWork, *, allow_location: bool) -> HolderMatch | None:
    """Prefer a P195 collection; for immovable works fall back to a P276 location."""
    if work.collection_qid and _QID_RE.fullmatch(work.collection_qid):
        return HolderMatch(work, 0.0, work.collection_qid, work.collection_label,
                           work.ror, work.url, "collection")
    if allow_location and work.location_qid and _QID_RE.fullmatch(work.location_qid):
        return HolderMatch(work, 0.0, work.location_qid, work.location_label,
                           None, work.location_url, "location")
    return None


def match_work(
    title: str, sidecar_year: int | None, works: list[CreatorWork], *, allow_location: bool = False
) -> tuple[HolderMatch | None, str]:
    """Return ``(HolderMatch, "match")`` or ``(None, reason)`` under the guards.

    A P195 collection is the holder; for immovable works (``allow_location``) a
    P276 location is accepted as the holder when no collection is recorded.
    """
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
    holder = _derive_holder(best, allow_location=allow_location)
    if holder is None:
        return None, "no-collection"
    return HolderMatch(best, best_score, holder.holder_qid, holder.holder_label,
                       holder.holder_ror, holder.holder_url, holder.kind), "match"


def resolve_holder(
    title: str, sidecar_year: int | None, creator_qid: str, *, client: SparqlQuerier,
    allow_location: bool = False,
) -> tuple[HolderMatch | None, str]:
    """Resolve a holder for one work from its creator's Wikidata works."""
    if not creator_qid:
        return None, "no-creator"
    works = works_by_creator(creator_qid, client=client)
    match, reason = match_work(title, sidecar_year, works, allow_location=allow_location)
    if match is not None:
        return match, reason
    # Immovable fallback: the specific work rarely title-matches (scan-naming),
    # but the location name is usually in the title -> match on the location.
    if allow_location:
        return location_from_title(title, works)
    return None, reason
