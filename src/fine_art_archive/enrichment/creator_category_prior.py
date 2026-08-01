"""Infer a work's ``category`` from its creator's art occupation (a hedged prior).

The last slice of the uncategorized bucket is famous works whose sidecar carries
a real artist + title but no work QID and no usable medium, so neither P31 nor
the medium heuristics fire, and the title diverges too much from Wikidata for a
safe work-QID match. For these there is still one signal: **what the artist
makes**. When an artist's mapped Wikidata occupations resolve to exactly one art
category (e.g. Caravaggio is only a *painter*), an untyped work by them is very
likely that category.

This is a *prior*, not per-work evidence -- a prolific master who paints *and*
draws *and* prints (van Gogh, Rembrandt) is deliberately abstained on, because
the prior cannot say which of the three a given untyped work is. Even for a
single-occupation artist the specific work is not individually verified, so the
caller records the category with provenance status ``unverified`` (a first-class
status the schema already uses for ~2500 works), never ``available``.

The mappers are pure and offline; occupation fetching lives in
:func:`fetch_occupations`.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any, Protocol

# Verified Wikidata occupation (P106) QID -> category. Every label was checked
# against live Wikidata; only single-medium art occupations are listed. Broad or
# ambiguous ones ("graphic artist", "installation artist", "artist") are omitted
# so an artist tagged with them alone abstains rather than guesses.
OCCUPATION_CATEGORY: dict[str, str] = {
    "Q1028181": "painting",  # painter
    "Q33231": "photograph",  # photographer
    "Q1281618": "sculpture",  # sculptor
    "Q11569986": "print",  # printmaker
    "Q10862983": "print",  # etcher
    "Q15296811": "drawing",  # draftsperson
}

# Title object-nouns that name the work's own type. When one appears and it names
# a *different* category than the occupation prior, abstain -- the title is
# stronger evidence than the artist's general medium. (Matched on word
# boundaries, so "Drawing" in "Fishermen Drawing Nets" is not caught here because
# it maps to no type noun below.)
_TITLE_TYPE: dict[str, str] = {
    "mural": "mural",
    "fresco": "fresco",
    "mosaic": "mosaic",
    "tapestry": "tapestry",
    "stained glass": "stained_glass",
    "altarpiece": "altarpiece",
    "sculpture": "sculpture",
}


def category_from_occupations(occupation_qids: Iterable[str]) -> str | None:
    """Return the single category the occupations resolve to, or None (abstain)."""
    categories = {OCCUPATION_CATEGORY[qid] for qid in occupation_qids if qid in OCCUPATION_CATEGORY}
    return next(iter(categories)) if len(categories) == 1 else None


def _title_conflict(title: object, category: str) -> bool:
    if not isinstance(title, str) or not title.strip():
        return False
    low = title.lower()
    for keyword, type_category in _TITLE_TYPE.items():
        if type_category != category and re.search(rf"\b{re.escape(keyword)}\b", low):
            return True
    return False


def infer_prior(meta: Mapping[str, Any], occupation_qids: Iterable[str]) -> tuple[str, str] | None:
    """Return ``(category, note)`` for a creator-occupation prior, or None to abstain."""
    category = category_from_occupations(occupation_qids)
    if category is None:
        return None
    if _title_conflict(meta.get("title"), category):
        return None
    return category, (
        f"Creator prior: artist's sole mapped art occupation implies {category}; "
        "specific work unverified."
    )


class _Client(Protocol):
    def get(
        self, url: str, *, params: Mapping[str, str] | None = None
    ) -> dict[str, Any] | None: ...


def fetch_occupations(artist_qid: str, *, client: _Client) -> list[str]:
    """Return the P106 (occupation) target QIDs for ``artist_qid`` from Wikidata.

    Empty list on any network/shape failure so callers degrade to abstaining.
    """
    if not artist_qid:
        return []
    payload = client.get(f"https://www.wikidata.org/wiki/Special:EntityData/{artist_qid}.json")
    if not isinstance(payload, dict):
        return []
    entity = (payload.get("entities") or {}).get(artist_qid)
    if not isinstance(entity, dict):
        return []
    qids: list[str] = []
    for statement in (entity.get("claims") or {}).get("P106", []):
        datavalue = (statement.get("mainsnak") or {}).get("datavalue")
        if isinstance(datavalue, dict):
            value = datavalue.get("value")
            if isinstance(value, dict) and isinstance(value.get("id"), str):
                qids.append(value["id"])
    return qids
