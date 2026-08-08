"""Detect and repair mis-resolved ``stable_identifiers.wikidata_q`` values.

A batch of works carry a work QID that does not point at an artwork at all -- an
earlier free-text title resolver matched the title string to the wrong entity.
Two distinct corruptions show up, both diagnosable from the QID's ``P31``:

1. **Title/artist swap.** The sidecar ``title`` actually holds the *artist's*
   name and the ``artist`` field holds the real title, and the "work QID" is the
   artist's *person* QID (P31 human) -- e.g. ``title="Katsushika Hokusai"``,
   ``artist="Under the Wave off Kanagawa..."``, QID ``Q5586`` (Hokusai). When
   that person is themselves an artist (a P106 art occupation, which separates a
   painter from a mis-resolved *sitter* like a president), the fields can be
   un-swapped deterministically: the person becomes the artist (their QID is the
   artist QID), the old ``artist`` string becomes the title, and the person-QID
   is removed from ``stable_identifiers`` so the real work QID can be re-resolved
   downstream by the by-creator pass.

2. **Otherwise mis-resolved.** The QID is a place, a non-artist person (a
   sitter), or some other non-artwork. Nothing about the correct work can be
   inferred safely, so the wrong QID is simply cleared -- removing a value that
   was poisoning P170-artist and P31-category resolution.

Every decision is gated on the QID's live Wikidata type; a QID that *is* an
artwork is never touched. Network access is injected for offline testing.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Protocol

from fine_art_archive.identity.artist_lookup import ART_OCCUPATIONS
from fine_art_archive.identity.artist_resolver import fold_name

# "Artwork" is decided by the Wikidata class HIERARCHY, not a hand-listed set: a
# QID is an artwork iff a P31 target is a subclass* of "work of art" (Q838948).
# ("visual artwork" Q4502142 and every concrete class -- painting, altarpiece,
# polyptych, mural, painting-series -- are subclasses of it, so the single pinned
# root covers them all.) A static direct-P31 allowlist is fragile: it silently
# misclassifies those subclasses as non-art and would wrongly clear them. The
# root is *pinned* (not a ``?var``/VALUES) so WDQS can optimise the transitive
# path -- an unbound target times the query out.
_ARTWORK_ROOT = "Q838948"
_HUMAN = "Q5"
_TITLE_MATCH_THRESHOLD = 0.90
_TITLE_WORD_RE = re.compile(r"[^\W\d_]{3,}")  # >=3-letter word: a real title has one


class SparqlQuerier(Protocol):
    def query(self, sparql: str) -> dict[str, Any] | None: ...


@dataclass(frozen=True)
class QidType:
    """Live Wikidata type facts for a work QID."""

    label: str | None
    is_artwork: bool
    is_human: bool
    is_artist: bool  # human with a P106 art occupation


@dataclass(frozen=True)
class Repair:
    action: str  # "unswap" | "clear"
    # unswap payload (None for clear):
    artist_name: str | None = None
    artist_qid: str | None = None
    new_title: str | None = None
    note: str = ""


def classify_query(work_qid: str) -> str:
    return (
        "SELECT ?label (COUNT(DISTINCT ?art) AS ?nart) (COUNT(DISTINCT ?hum) AS ?nhum) "
        '(GROUP_CONCAT(DISTINCT ?occ; separator=" ") AS ?occs) WHERE { '
        f"BIND(wd:{work_qid} AS ?w) "
        'OPTIONAL { ?w rdfs:label ?label . FILTER(LANG(?label) = "en") } '
        f"OPTIONAL {{ ?w wdt:P31/wdt:P279* wd:{_ARTWORK_ROOT} . BIND(1 AS ?art) }} "
        "OPTIONAL { ?w wdt:P31 wd:Q5 . BIND(1 AS ?hum) } "
        "OPTIONAL { ?w wdt:P106 ?occ } } GROUP BY ?label"
    )


def _row_to_type(row: Mapping[str, Any]) -> QidType:
    def _val(key: str) -> str:
        return row.get(key, {}).get("value", "") or ""

    is_human = _val("nhum") not in ("", "0")
    occupations = {occ.rsplit("/", 1)[-1] for occ in _val("occs").split() if occ}
    return QidType(
        label=_val("label") or None,
        is_artwork=_val("nart") not in ("", "0"),
        is_human=is_human,
        is_artist=is_human and bool(occupations & ART_OCCUPATIONS),
    )


def classify_qid(work_qid: str, *, client: SparqlQuerier) -> QidType | None:
    """Classify a QID via the Wikidata class hierarchy. ``None`` on query failure."""
    if not work_qid:
        return None
    payload = client.query(classify_query(work_qid))
    if not isinstance(payload, dict):
        return None
    bindings = payload.get("results", {}).get("bindings", [])
    return _row_to_type(bindings[0]) if bindings else None


def classify_batch_query(work_qids: list[str]) -> str:
    values = " ".join(f"wd:{q}" for q in work_qids)
    return (
        "SELECT ?w ?label (COUNT(DISTINCT ?art) AS ?nart) (COUNT(DISTINCT ?hum) AS ?nhum) "
        '(GROUP_CONCAT(DISTINCT ?occ; separator=" ") AS ?occs) WHERE { '
        f"VALUES ?w {{ {values} }} "
        'OPTIONAL { ?w rdfs:label ?label . FILTER(LANG(?label) = "en") } '
        f"OPTIONAL {{ ?w wdt:P31/wdt:P279* wd:{_ARTWORK_ROOT} . BIND(1 AS ?art) }} "
        "OPTIONAL { ?w wdt:P31 wd:Q5 . BIND(1 AS ?hum) } "
        "OPTIONAL { ?w wdt:P106 ?occ } } GROUP BY ?w ?label"
    )


def classify_qids(
    work_qids: list[str], *, client: SparqlQuerier, chunk: int = 80
) -> dict[str, QidType]:
    """Batch-classify many QIDs. Missing QIDs (query failure) are simply absent."""
    out: dict[str, QidType] = {}
    unique = list(dict.fromkeys(q for q in work_qids if q))
    for start in range(0, len(unique), chunk):
        batch = unique[start : start + chunk]
        payload = client.query(classify_batch_query(batch))
        if not isinstance(payload, dict):
            continue
        for row in payload.get("results", {}).get("bindings", []):
            qid = row.get("w", {}).get("value", "").rsplit("/", 1)[-1]
            if qid:
                out[qid] = _row_to_type(row)
    return out


def decide_repair(meta: Mapping[str, Any], qtype: QidType) -> Repair | None:
    """Return the repair for a work whose QID ``qtype`` is not an artwork."""
    if qtype.is_artwork:
        return None  # a real artwork QID is never touched
    title = str(meta.get("title") or "").strip()
    artist = meta.get("artist")
    artist_name = str(artist.get("name") or "").strip() if isinstance(artist, Mapping) else ""

    # Title/artist swap: the QID is an *artist* whose name matches the title,
    # and the artist field holds something else that looks like a real title (has
    # a word -- so a junk artist field like a bare date "1599-60" does NOT get
    # promoted to the title; that work falls through to a plain clear).
    if (
        qtype.is_artist
        and qtype.label
        and title
        and artist_name
        and _TITLE_WORD_RE.search(artist_name)
        and SequenceMatcher(None, fold_name(title), fold_name(qtype.label)).ratio()
        >= _TITLE_MATCH_THRESHOLD
        and fold_name(qtype.label) not in fold_name(artist_name)
    ):
        work_qid = (meta.get("stable_identifiers") or {}).get("wikidata_q")
        return Repair(
            action="unswap",
            artist_name=qtype.label,
            artist_qid=work_qid,  # the mis-resolved "work QID" is the artist's person QID
            new_title=artist_name,  # the old artist field is the real title
            note=(
                f"Un-swapped title/artist: work QID {work_qid} is the artist "
                f"{qtype.label!r} (P106 artist); title held the artist name, "
                f"artist field held the title {artist_name!r}."
            ),
        )

    # Absence of evidence is not evidence of absence. `_row_to_type` derives
    # every flag from OPTIONAL clauses, so a QID we learned NOTHING about —
    # deleted, redirected, or simply lagging in WDQS — returns a row with no
    # label and every flag False, which is byte-identical to "positively not an
    # artwork". Clearing on that erases a correct, hard-won identifier on a
    # transient condition, and the superseded value is not recorded anywhere
    # (`field_provenance.prior_value` is declared in the schema but not yet
    # implementable). A genuine non-artwork essentially always carries an
    # English label, so "no label AND no facts at all" is the signal that the
    # query answered nothing.
    if qtype.label is None and not (qtype.is_artwork or qtype.is_human or qtype.is_artist):
        return Repair(
            action="unverifiable",
            note=(
                "Query returned no facts for this QID (no label, no type) — "
                "cannot distinguish 'wrong QID' from 'WDQS did not answer', so "
                "the identifier is left untouched."
            ),
        )

    kind = "person" if qtype.is_human else "place/other"
    return Repair(
        action="clear",
        note=(f"Cleared mis-resolved work QID -> {kind} (not an artwork; label {qtype.label!r})."),
    )
