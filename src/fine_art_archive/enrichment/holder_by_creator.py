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
YEAR_TOLERANCE = 6  # lenient sanity check when one work already title-matches uniquely
YEAR_DISCRIM_TOLERANCE = 1  # TIGHT: year as the *discriminator* among same-title works
_QID_RE = re.compile(r"Q[0-9]+")
_YEAR_RE = re.compile(r"(1[0-9]{3}|20[0-9]{2})")
# A parenthetical year in a sidecar title ("Self-Portrait (1887)") is an explicit
# disambiguator, not noise; parsed from the raw title before folding drops the parens.
_PAREN_YEAR_RE = re.compile(r"\((?:c\.?\s*)?(1[0-9]{3}|20[0-9]{2})\)")
_LEADING_ARTICLE_RE = re.compile(r"^(?:the|a|an|le|la|il|el|un|une) ")
_TRAILING_YEAR_RE = re.compile(r" (?:1[0-9]{3}|20[0-9]{2})$")


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
    aliases: tuple[str, ...] = ()  # en altLabels, for museum-vs-Wikidata title disagreement


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


# One row per *distinct work* (GROUP BY ?w): the SPARQL otherwise returns one row
# per (work x collection/statement), so a prolific artist whose oeuvre is spread
# across many collections exhausts a row LIMIT before all his works are even
# listed -- silently truncating the candidate set and making some works
# unresolvable. Grouping makes LIMIT count works, not rows, so a high bound is
# non-binding for any real single-artist oeuvre (the most prolific painters have
# ~2-3k works on Wikidata) -- no artist is artificially truncated. altLabels are
# concatenated so a work can also be matched on a title Wikidata records as an
# alias (museums and Wikidata often disagree on the "primary" title).
def creator_works_query(creator_qid: str, *, limit: int = 4000) -> str:
    return (
        "SELECT ?w (SAMPLE(?lbl) AS ?wLabel) "
        "(SAMPLE(?coll) AS ?coll) (SAMPLE(?collLbl) AS ?collLabel) "
        "(SAMPLE(?ror) AS ?ror) (SAMPLE(?url) AS ?url) "
        "(SAMPLE(?acc) AS ?acc) (SAMPLE(?inception) AS ?inception) "
        "(SAMPLE(?loc) AS ?loc) (SAMPLE(?locLbl) AS ?locLabel) (SAMPLE(?locUrl) AS ?locUrl) "
        '(GROUP_CONCAT(DISTINCT ?alt; separator="||") AS ?alts) WHERE { '
        f"?w wdt:P170 wd:{creator_qid} . "
        'OPTIONAL { ?w rdfs:label ?lbl . FILTER(LANG(?lbl) = "en") } '
        'OPTIONAL { ?w skos:altLabel ?alt . FILTER(LANG(?alt) = "en") } '
        "OPTIONAL { ?w wdt:P195 ?coll . "
        'OPTIONAL { ?coll rdfs:label ?collLbl . FILTER(LANG(?collLbl) = "en") } '
        "OPTIONAL { ?coll wdt:P6782 ?ror } OPTIONAL { ?coll wdt:P856 ?url } } "
        "OPTIONAL { ?w wdt:P276 ?loc . "
        'OPTIONAL { ?loc rdfs:label ?locLbl . FILTER(LANG(?locLbl) = "en") } '
        "OPTIONAL { ?loc wdt:P856 ?locUrl } } "
        "OPTIONAL { ?w wdt:P217 ?acc } OPTIONAL { ?w wdt:P571 ?inception } "
        f"}} GROUP BY ?w LIMIT {limit}"
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
                aliases=_aliases(binding),
            )
        )
    return works


def _aliases(binding: dict[str, Any]) -> tuple[str, ...]:
    raw = _binding_value(binding, "alts")
    if not raw:
        return ()
    return tuple(a for a in (part.strip() for part in raw.split("||")) if a)


_LOC_STOPWORDS = frozenset(
    {
        "the",
        "of",
        "di",
        "del",
        "della",
        "dei",
        "de",
        "la",
        "le",
        "il",
        "a",
        "chapel",
        "cappella",
        "church",
        "chiesa",
        "basilica",
        "cathedral",
        "duomo",
        "san",
        "santa",
        "santo",
        "sant",
        "saint",
        "st",
        "museo",
        "museum",
        "palazzo",
        "palace",
        "gallery",
        "galleria",
        "convent",
        "convento",
        "monastery",
    }
)


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
        distinctive = {
            t
            for t in _norm_tokens(w.location_label or "")
            if len(t) >= 4 and t not in _LOC_STOPWORDS
        }
        if distinctive and distinctive & title_tokens:
            matched.append(w)
    if len(matched) != 1:
        return None, "ambiguous" if matched else "no-location-in-title"
    w = matched[0]
    return (
        HolderMatch(
            w,
            0.95,
            w.location_qid or "",
            _clean_label(w.location_label),
            None,
            w.location_url,
            "location",
        ),
        "match",
    )


def _clean_label(label: str | None) -> str | None:
    """Drop a QID-shaped label. Wikidata's label service returns the bare QID
    (e.g. "Q214867") when an entity has no English label; storing that as a
    holder *name* is wrong, so treat it as absent and let the registry fill in."""
    if label is not None and _QID_RE.fullmatch(label):
        return None
    return label


def _derive_holder(work: CreatorWork, *, allow_location: bool) -> HolderMatch | None:
    """Prefer a P195 collection; for immovable works fall back to a P276 location."""
    if work.collection_qid and _QID_RE.fullmatch(work.collection_qid):
        return HolderMatch(
            work,
            0.0,
            work.collection_qid,
            _clean_label(work.collection_label),
            work.ror,
            work.url,
            "collection",
        )
    if allow_location and work.location_qid and _QID_RE.fullmatch(work.location_qid):
        return HolderMatch(
            work,
            0.0,
            work.location_qid,
            _clean_label(work.location_label),
            None,
            work.location_url,
            "location",
        )
    return None


def match_work(
    title: str, sidecar_year: int | None, works: list[CreatorWork], *, allow_location: bool = False
) -> tuple[HolderMatch | None, str]:
    """Return ``(HolderMatch, "match")`` or ``(None, reason)`` under the guards.

    A P195 collection is the holder; for immovable works (``allow_location``) a
    P276 location is accepted as the holder when no collection is recorded.
    """
    best, best_score, reason = match_work_entity(title, sidecar_year, works)
    if best is None:
        return None, reason
    holder = _derive_holder(best, allow_location=allow_location)
    if holder is None:
        return None, "no-collection"
    return (
        HolderMatch(
            best,
            best_score,
            holder.holder_qid,
            holder.holder_label,
            holder.holder_ror,
            holder.holder_url,
            holder.kind,
        ),
        "match",
    )


def _score_for(text: str) -> str:
    """Fold a title/label and drop benign, symmetric differences before scoring.

    A leading article ("The Burial of Saint Lucy" vs "Burial of Saint Lucy") and a
    trailing year token (folding "Self-Portrait (1887)" -> "self portrait 1887")
    cost SequenceMatcher points without changing which work is meant. Stripping
    them from *both* sides is safe: it can only raise the score of a true match,
    never invent one between genuinely different titles.
    """
    folded = fold_name(text)
    folded = _LEADING_ARTICLE_RE.sub("", folded)
    folded = _TRAILING_YEAR_RE.sub("", folded)
    return folded.strip()


def _best_title_score(title_norm: str, work: CreatorWork) -> float:
    """Best normalized SequenceMatcher score over the work's label + its aliases."""
    candidates = (work.label, *work.aliases)
    return max(
        (SequenceMatcher(None, title_norm, _score_for(c)).ratio() for c in candidates if c),
        default=0.0,
    )


def _ranked_distinct(title: str, works: list[CreatorWork]) -> list[tuple[float, CreatorWork]]:
    """Best title score per DISTINCT work_qid, highest first."""
    title_norm = _score_for(title)
    best_by_qid: dict[str, tuple[float, CreatorWork]] = {}
    for work in works:
        score = _best_title_score(title_norm, work)
        current = best_by_qid.get(work.work_qid)
        if current is None or score > current[0]:
            best_by_qid[work.work_qid] = (score, work)
    return sorted(best_by_qid.values(), key=lambda pair: -pair[0])


def tied_candidates(title: str, works: list[CreatorWork]) -> list[CreatorWork]:
    """The same-title cluster (>1 distinct work tied within the margin), else []."""
    ranked = _ranked_distinct(title, works)
    if not ranked or ranked[0][0] < SCORE_THRESHOLD:
        return []
    best_score = ranked[0][0]
    tied = [work for score, work in ranked if score >= best_score - AMBIGUITY_MARGIN]
    return tied if len(tied) > 1 else []


def match_work_entity(
    title: str,
    sidecar_year: int | None,
    works: list[CreatorWork],
    *,
    holder_qid: str | None = None,
) -> tuple[CreatorWork | None, float, str]:
    """Identify *which* creator work a title refers to, under the shared guards.

    Returns ``(work, score, "match")`` or ``(None, score, reason)``. This is the
    holder-independent core of :func:`match_work`: it settles work *identity*
    without requiring the matched work to record a holder, so a work-QID resolver
    can accept a match that :func:`match_work` would reject as ``no-collection``.

    Guards (precision over recall on load-bearing QIDs):

    * best normalized title score (over label + altLabels) >= ``SCORE_THRESHOLD``;
    * the score is deduplicated per work_qid, so the same work returned in several
      collection rows is one answer, not a self-competitor;
    * among *distinct* works tied within ``AMBIGUITY_MARGIN`` of the best, the
      **year disambiguates**: a same-title cluster (an artist's several
      "Self-Portrait"s) resolves only if a year -- taken from a parenthetical in
      the sidecar title, else the sidecar year -- uniquely selects one work whose
      inception matches within the TIGHT ``YEAR_DISCRIM_TOLERANCE``. Zero or >1
      survivors -> ``ambiguous`` (decline, never guess).
    * when exactly one work tops the field, the year is only a lenient
      ``YEAR_TOLERANCE`` sanity check.
    """
    ranked = _ranked_distinct(title, works)
    if not ranked:
        return None, 0.0, "no-works"
    best_score, best = ranked[0]
    if best_score < SCORE_THRESHOLD:
        return None, best_score, "below-threshold"

    tied = [(score, work) for score, work in ranked if score >= best_score - AMBIGUITY_MARGIN]
    if len(tied) == 1:
        work_year = year_of(best.inception)
        if (
            sidecar_year is not None
            and work_year is not None
            and abs(sidecar_year - work_year) > YEAR_TOLERANCE
        ):
            return None, best_score, "year-mismatch"
        return best, best_score, "match"

    # Same-title cluster (Stage 2). Try the strongest discriminator first: the
    # HOLDER -- a work's collection is definitive, so if the sidecar's holder
    # matches exactly one tied candidate's collection, that is the work.
    if holder_qid:
        by_holder = [work for _score, work in tied if work.collection_qid == holder_qid]
        if len(by_holder) == 1:
            return by_holder[0], best_score, "match"

    # Then the year discriminator (parenthetical in the title, else sidecar year).
    paren_year = _title_year(title)
    discriminator = paren_year if paren_year is not None else sidecar_year
    if discriminator is None:
        return None, best_score, "ambiguous"
    survivors = [
        (score, work)
        for score, work in tied
        if (wy := year_of(work.inception)) is not None
        and abs(discriminator - wy) <= YEAR_DISCRIM_TOLERANCE
    ]
    if len(survivors) == 1:
        return survivors[0][1], survivors[0][0], "match"
    return None, best_score, "ambiguous"


def _title_year(title: str) -> int | None:
    """Return a parenthetical year in a title ("Self-Portrait (1887)"), else None."""
    match = _PAREN_YEAR_RE.search(title or "")
    return int(match.group(1)) if match else None


def resolve_holder(
    title: str,
    sidecar_year: int | None,
    creator_qid: str,
    *,
    client: SparqlQuerier,
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
