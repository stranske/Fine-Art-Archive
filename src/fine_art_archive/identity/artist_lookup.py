"""Resolve an artist *name* to a Wikidata person QID, independent of any work.

The source pass reads ``artist_qid`` off the *work* entity's P170, which needs a
work QID that free-text search often cannot find. This module instead resolves
the artist directly from ``artist.name`` -- far more tractable -- and gates the
result to real artists (human ``P31=Q5`` with a visual-art ``P106`` occupation)
so sitter/subject names ("Calvin Coolidge") and junk ("1692", "Jr.") do not
produce false creators.

The HTTP client is injected (any object with ``.get(url, params=...) -> dict``)
so callers supply a throttled/retrying transport and tests supply a fake.
"""

from __future__ import annotations

import contextlib
import re
from difflib import SequenceMatcher
from typing import Any, Protocol

from fine_art_archive.identity.artist_resolver import fold_name, resolve_artist

WIKIDATA_API = "https://www.wikidata.org/w/api.php"
FUZZY_THRESHOLD = 0.88
ALIAS_CONFIDENCE = 0.9

# Wikidata P106 occupations that qualify a person as a visual artist.
ART_OCCUPATIONS = frozenset(
    {
        "Q1028181",   # painter
        "Q483501",    # artist
        "Q3391743",   # visual artist
        "Q1281618",   # sculptor
        "Q11569986",  # printmaker
        "Q329439",    # draughtsperson
        "Q644687",    # illustrator
        "Q33231",     # photographer
        "Q1925963",   # graphic artist
        "Q15296811",  # watercolorist
        "Q10862983",  # etcher
        "Q16947657",  # lithographer
        "Q1114448",   # cartoonist
        "Q18216771",  # woodcut artist
        "Q7541856",   # engraver
        "Q42973",     # architect
    }
)

_ATTRIBUTION = (
    "attribut", "circle of", "after ", "follower", "workshop", "manner of",
    "studio of", "school of", "style of", "imitator", "unknown", "anonymous",
    "unidentified",
)


class JsonGetter(Protocol):
    def get(self, url: str, *, params: dict[str, str] | None = None) -> dict[str, Any] | None: ...


def clean_name(name: str) -> str:
    """Normalise a raw ``artist.name`` into a searchable person name."""
    n = re.sub(r"\(.*?\)", " ", name.strip())  # drop "(Tiziano Vecellio)"
    for sep in (";", " & ", " and "):  # first artist of a multi-artist credit
        if sep in n:
            n = n.split(sep, 1)[0]
    if "," in n:  # "Kandinsky, Vassily" -> "Vassily Kandinsky"
        first, rest = n.split(",", 1)
        if rest.strip() and not re.search(r"\d", rest):
            n = f"{rest.strip()} {first.strip()}"
    return re.sub(r"\s+", " ", n).strip(" .;,&")


def _ids(entity: dict[str, Any], prop: str) -> list[str]:
    out: list[str] = []
    for claim in (entity.get("claims") or {}).get(prop, []) or []:
        with contextlib.suppress(KeyError, TypeError):
            out.append(claim["mainsnak"]["datavalue"]["value"]["id"])
    return out


def _names(entity: dict[str, Any]) -> list[str]:
    names: list[str] = []
    label = ((entity.get("labels") or {}).get("en") or {}).get("value")
    if label:
        names.append(label)
    for alias in (entity.get("aliases") or {}).get("en") or []:
        value = alias.get("value")
        if value:
            names.append(value)
    return names


def resolve_artist_qid(raw_name: str, *, client: JsonGetter) -> tuple[str | None, str | None]:
    """Return ``(qid, method)`` for an artist name, or ``(None, reason)``.

    Tries the offline alias table first, then a Wikidata search gated to real
    artists with a fuzzy name match.
    """
    if not raw_name or not raw_name.strip():
        return None, "no-name"
    low = raw_name.lower()
    if any(marker in low for marker in _ATTRIBUTION):
        return None, "attribution-qualified"
    name = clean_name(raw_name)
    if len(name) < 3 or re.fullmatch(r"[\d\W]+", name):
        return None, "not-a-name"

    local = resolve_artist(name, allow_wikidata=False)
    if getattr(local, "q", None) and getattr(local, "confidence", 0.0) >= ALIAS_CONFIDENCE:
        return local.q, f"alias ({local.method})"

    search = client.get(
        WIKIDATA_API,
        params={
            "action": "wbsearchentities", "format": "json", "language": "en",
            "limit": "10", "search": name, "type": "item",
        },
    )
    hits = (search or {}).get("search")
    if not isinstance(hits, list) or not hits:
        return None, "no-search-hit"
    qids = [h["id"] for h in hits if isinstance(h, dict) and str(h.get("id", "")).startswith("Q")]
    if not qids:
        return None, "no-search-hit"

    entities_payload = client.get(
        WIKIDATA_API,
        params={
            "action": "wbgetentities", "ids": "|".join(qids),
            "props": "claims|labels|aliases", "languages": "en", "format": "json",
        },
    )
    entities = (entities_payload or {}).get("entities") or {}
    folded = fold_name(name)
    best: tuple[float, str] | None = None
    for qid in qids:
        entity = entities.get(qid)
        if not isinstance(entity, dict):
            continue
        if "Q5" not in _ids(entity, "P31"):
            continue
        if not (set(_ids(entity, "P106")) & ART_OCCUPATIONS):
            continue
        for candidate in _names(entity):
            score = SequenceMatcher(None, folded, fold_name(candidate)).ratio()
            if best is None or score > best[0]:
                best = (score, qid)
    if best is not None and best[0] >= FUZZY_THRESHOLD:
        return best[1], f"wikidata artist match ({best[0]:.2f})"
    return None, "no-artist-match"
