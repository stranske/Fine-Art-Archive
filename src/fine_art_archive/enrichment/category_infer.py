"""Infer a work's top-level ``category`` from evidence, highest confidence first.

Fills the ``category`` completeness field for works stranded in the
``(uncategorized)`` bucket. Nothing is emitted when no rule fires: a null
category is always preferred over a wrong one.

Signal order (most reliable first):

1. **Medium technique/material keywords** — an unambiguous physical technique in
   the medium string ("apse mosaic", "stained glass", "bronze") is the single
   most reliable signal and is trusted *above* a work QID, because a large
   minority of the uncategorized works carry mis-resolved QIDs.
2. **Wikidata P31** (instance-of) when a work QID is known, mapped through a
   strict *allowlist* of verified art/building classes. Any P31 class not on the
   allowlist is ignored rather than guessed at, so mis-resolved QIDs (pointing at
   a country, a scholarly article, a chemical tanker, a person, ...) fall
   through instead of producing a wrong category.
3. **Medium paint-vs-draw** via
   :func:`fine_art_archive.enrichment.medium_vocab.parse`.
4. **Title hints** — a deliberately tiny, high-precision last resort (object
   nouns only; building names are excluded because a "Cathedral" in a title is
   as often a painting of one as the building itself).

Every emitted value is a member of the sidecar schema's ``category`` enum
(guarded by a test); the caller still runs ``sidecar.validate`` before writing.

The inference functions are pure and offline. Network fetching of P31 lives in
:func:`fetch_p31_qids` so the mappers stay unit-testable without a client.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from .medium_vocab import parse as parse_medium

# --- Wikidata P31 (instance-of) class QID -> category ------------------------
# Every QID label was verified against live Wikidata before inclusion. Only art
# and building classes that unambiguously imply a category are listed; generic
# classes ("work of art", "visual artwork", "type of building") and off-target
# classes are intentionally absent so mis-resolved QIDs fall through.
P31_CATEGORY: dict[str, str] = {
    # painting
    "Q3305213": "painting",  # painting
    "Q18761202": "painting",  # watercolor painting
    "Q19969434": "painting",  # scroll painting
    # drawing
    "Q93184": "drawing",  # drawing
    # print
    "Q11060274": "print",  # print
    "Q18218093": "print",  # etching print
    "Q11835431": "print",  # engraving
    # sculpture
    "Q860861": "sculpture",  # sculpture
    "Q179700": "sculpture",  # statue
    # fresco
    "Q22669139": "fresco",  # fresco
    "Q134194": "fresco",  # fresco painting
    # mural
    "Q219423": "mural",  # mural
    "Q99516640": "mural",  # wall painting
    # stained glass
    "Q1473346": "stained_glass",  # stained glass
    # tapestry
    "Q184296": "tapestry",  # tapestry
    # mosaic
    "Q133067": "mosaic",  # mosaic
    # photograph
    "Q125191": "photograph",  # photograph
    # architecture (site-anchored buildings)
    "Q16970": "architecture",  # church building
    "Q2577114": "architecture",  # co-cathedral
    "Q120560": "architecture",  # minor basilica
    "Q54831": "architecture",  # amphitheatre
    "Q3196771": "architecture",  # art museum
}

# When several P31 targets map to different categories, the most specific
# technique wins. Generic classes (painting) rank below specific ones (fresco);
# "other" is the true last resort.
_CATEGORY_PRIORITY: tuple[str, ...] = (
    "stained_glass",
    "mosaic",
    "tapestry",
    "fresco",
    "print",
    "sculpture",
    "drawing",
    "photograph",
    "painting",
    "mural",
    "architecture",
    "other",
)


def _best(categories: Iterable[str]) -> str | None:
    """Return the highest-priority category among ``categories`` (or None)."""
    ranked = sorted(
        (c for c in categories if c in _CATEGORY_PRIORITY),
        key=_CATEGORY_PRIORITY.index,
    )
    return ranked[0] if ranked else None


# --- Medium heuristics -------------------------------------------------------
# Tier 1: unambiguous technique/material keywords, trusted above P31. Each is
# matched on word boundaries so substrings do not misfire. Sculpture materials
# are limited to ones that do not double as building stone (limestone, granite,
# sandstone are deliberately excluded).
_TECHNIQUE_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("stained_glass", ("stained glass", "stained-glass")),
    ("mosaic", ("mosaic", "mosaics")),
    ("tapestry", ("tapestry", "tapestries")),
    # "fresc"/"frescoes" cover a common typo and the plural that \b-anchored
    # "fresco" would miss.
    ("fresco", ("fresco", "frescoes", "frescos", "fresc", "affresco")),
    (
        "print",
        (
            "print",
            "engraving",
            "etching",
            "woodcut",
            "woodblock",
            "linocut",
            "lithograph",
            "lithography",
            "drypoint",
            "mezzotint",
            "aquatint",
            "screenprint",
            "serigraph",
            "photogravure",
        ),
    ),
    # Photographic processes. "transparency"/"gelatin silver" are the forms that
    # actually appear; a bare medium of "photograph" is included for completeness.
    (
        "photograph",
        ("photograph", "photographs", "transparency", "gelatin silver", "daguerreotype"),
    ),
    (
        "sculpture",
        ("bronze", "marble", "terracotta", "terra-cotta", "terra cotta", "alabaster"),
    ),
)

# Tier 3: canonical medium tokens (as returned by medium_vocab.parse) that imply
# a class on their own. "wax" canonicalises to "encaustic"; metallic accents
# (gold, silver) are deliberately excluded as non-determining. Ceramics have no
# dedicated enum member, so they resolve to the honest "other".
_PAINT_MEDIUMS = frozenset({"oil", "tempera", "acrylic", "encaustic", "distemper"})
_DRAW_MEDIUMS = frozenset(
    {"watercolour", "gouache", "ink", "chalk", "charcoal", "pastel", "pencil", "graphite", "crayon"}
)
_CERAMIC_KEYWORDS = (
    "earthenware",
    "stoneware",
    "porcelain",
    "faience",
    "majolica",
    "ceramic",
    "fired clay",
)


def _word_in(keyword: str, text: str) -> bool:
    return re.search(rf"\b{re.escape(keyword)}\b", text) is not None


def infer_from_medium_technique(medium: object) -> tuple[str, str] | None:
    """Tier 1: unambiguous technique/material keyword in the medium string."""
    if not isinstance(medium, str) or not medium.strip():
        return None
    low = medium.lower()
    for category, keywords in _TECHNIQUE_KEYWORDS:
        for keyword in keywords:
            if _word_in(keyword, low):
                return category, f"Medium technique {keyword!r} -> {category}."
    return None


# East-Asian catalogue convention: "<colorant> on <textile/paper>" (e.g.
# "Color on silk", "Pigment and gold on cotton" for scrolls and thangkas). Only
# consulted after medium_vocab, so ink -> drawing and watercolour -> drawing
# still win; a lone colorant-on-support is a painting.
_COLORANT_ON = re.compile(r"\b(?:colou?r|pigment)\b.*\bon\b")


def infer_from_medium_material(medium: object) -> tuple[str, str] | None:
    """Tier 3: paint-vs-draw (via medium_vocab), then colorant-on-support / ceramics."""
    if not isinstance(medium, str) or not medium.strip():
        return None
    low = medium.lower()
    parsed = parse_medium(medium)
    if parsed:
        mediums, _supports = parsed
        paint = mediums & _PAINT_MEDIUMS
        if paint:
            return "painting", f"Paint medium {sorted(paint)} -> painting."
        draw = mediums & _DRAW_MEDIUMS
        if draw:
            return "drawing", f"Drawing medium {sorted(draw)} -> drawing."
    if "egg temper" in low:  # typo of "egg tempera" that medium_vocab misses
        return "painting", "Egg tempera (typo) -> painting."
    if _COLORANT_ON.search(low):
        return "painting", "Colorant on textile/paper -> painting."
    for keyword in _CERAMIC_KEYWORDS:
        if _word_in(keyword, low):
            return "other", f"Ceramic medium {keyword!r} -> other (no ceramic enum)."
    return None


def infer_from_medium(medium: object) -> tuple[str, str] | None:
    """Convenience: technique first, then paint/draw material. Returns ``(category, note)``."""
    return infer_from_medium_technique(medium) or infer_from_medium_material(medium)


def infer_from_p31(qids: Iterable[str]) -> tuple[str, str] | None:
    """Tier 2: map a work's P31 target QIDs to a category via the allowlist.

    Returns ``(category, note)`` or ``None`` when no target is on the allowlist.
    """
    matched: dict[str, str] = {}
    for qid in qids:
        category = P31_CATEGORY.get(qid)
        if category is not None:
            matched.setdefault(category, qid)
    category = _best(matched)
    if category is None:
        return None
    return category, f"Wikidata P31 {matched[category]} -> {category}."


# --- Title hints (low confidence, last resort) -------------------------------
# Object nouns only. Building names (cathedral, basilica, ...) are excluded:
# museum titles name the depicted subject as often as the object's own type.
_TITLE_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("altarpiece", ("altarpiece",)),
    ("stained_glass", ("stained glass",)),
    ("fresco", ("fresco",)),
    ("tapestry", ("tapestry",)),
)


def infer_from_title(title: object) -> tuple[str, str] | None:
    """Tier 4: low-confidence category from high-precision title object nouns."""
    if not isinstance(title, str) or not title.strip():
        return None
    low = title.lower()
    for category, keywords in _TITLE_KEYWORDS:
        for keyword in keywords:
            if _word_in(keyword, low):
                return category, f"Title keyword {keyword!r} -> {category} (low confidence)."
    return None


@dataclass(frozen=True)
class CategoryInference:
    """A resolved category with its evidence source."""

    category: str
    source: str  # provenance source: "wikidata" | "medium" | "title"
    note: str


def infer_category(
    meta: Mapping[str, Any], *, p31_qids: Iterable[str] | None = None
) -> CategoryInference | None:
    """Infer a category for ``meta``, or ``None`` if no rule fires.

    ``p31_qids`` is the work's Wikidata P31 targets (fetched by the caller via
    :func:`fetch_p31_qids`); pass ``None`` to skip the P31 stage.
    """
    medium = meta.get("medium")

    result = infer_from_medium_technique(medium)
    if result is not None:
        category, note = result
        return CategoryInference(category, "medium", note)

    if p31_qids is not None:
        result = infer_from_p31(p31_qids)
        if result is not None:
            category, note = result
            return CategoryInference(category, "wikidata", note)

    result = infer_from_medium_material(medium)
    if result is not None:
        category, note = result
        return CategoryInference(category, "medium", note)

    result = infer_from_title(meta.get("title"))
    if result is not None:
        category, note = result
        return CategoryInference(category, "title", note)

    return None


# --- P31 fetch (network; kept separate so the mappers stay pure) --------------
class _Client(Protocol):
    def get(
        self, url: str, *, params: Mapping[str, str] | None = None
    ) -> dict[str, Any] | None: ...


def fetch_p31_qids(work_qid: str, *, client: _Client) -> list[str]:
    """Return the P31 (instance-of) target QIDs for ``work_qid`` from Wikidata.

    Uses the Special:EntityData JSON endpoint. Returns an empty list on any
    network/shape failure so callers degrade gracefully to medium/title rules.
    """
    if not work_qid:
        return []
    payload = client.get(f"https://www.wikidata.org/wiki/Special:EntityData/{work_qid}.json")
    if not isinstance(payload, dict):
        return []
    entity = (payload.get("entities") or {}).get(work_qid)
    if not isinstance(entity, dict):
        return []
    qids: list[str] = []
    for statement in (entity.get("claims") or {}).get("P31", []):
        datavalue = (statement.get("mainsnak") or {}).get("datavalue")
        if isinstance(datavalue, dict):
            value = datavalue.get("value")
            if isinstance(value, dict) and isinstance(value.get("id"), str):
                qids.append(value["id"])
    return qids
