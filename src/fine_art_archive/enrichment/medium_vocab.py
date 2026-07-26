"""Canonicalisation of free-text ``medium`` strings for conflict resolution.

Museum catalogues and Wikidata describe the same material two ways -- e.g.
"Oil on canvas" vs "oil paint, canvas". This module parses either form into a
canonical ``(mediums, supports)`` pair so equivalent descriptions reconcile to
one uniform rendering, and genuine material disagreements (canvas vs panel,
oil vs pastel) are reported rather than silently merged.
"""

from __future__ import annotations

import re

# medium (paint/drawing material) synonyms -> canonical term
MEDIUMS: dict[str, str] = {
    "oil": "oil", "oils": "oil", "oil paint": "oil",
    "oil colour": "oil", "oil color": "oil",
    "tempera": "tempera", "egg tempera": "tempera",
    "acrylic": "acrylic", "acrylic paint": "acrylic",
    "watercolor": "watercolour", "watercolour": "watercolour",
    "watercolor paint": "watercolour", "watercolour paint": "watercolour",
    "gouache": "gouache", "distemper": "distemper",
    "encaustic": "encaustic", "wax": "encaustic",
    "ink": "ink", "chalk": "chalk", "charcoal": "charcoal",
    "pastel": "pastel", "pencil": "pencil", "graphite": "graphite",
    "crayon": "crayon", "gold": "gold", "gold leaf": "gold", "silver": "silver",
}
# support (physical substrate) synonyms -> canonical term
SUPPORTS: dict[str, str] = {
    "canvas": "canvas", "linen": "canvas",
    "panel": "panel", "wood": "panel", "wood panel": "panel", "timber": "panel",
    "poplar": "panel", "oak": "panel", "mahogany": "panel", "walnut": "panel",
    "board": "board", "paperboard": "board", "cardboard": "board",
    "millboard": "board", "hardboard": "board", "masonite": "board",
    "cardstock": "board",
    "paper": "paper", "copper": "copper",
    "vellum": "vellum", "parchment": "vellum", "ivory": "ivory",
    "plaster": "plaster",
}
_MEDIUM_ORDER = [
    "oil", "tempera", "acrylic", "watercolour", "gouache", "distemper",
    "encaustic", "ink", "chalk", "charcoal", "pastel", "pencil", "graphite",
    "crayon", "gold", "silver",
]
_SUPPORT_ORDER = [
    "canvas", "panel", "board", "paper", "copper", "vellum", "ivory", "plaster",
]


def _strip_leak(text: str) -> str:
    """Drop a leaked ``"Artist Name; "`` prefix, keeping the material segment."""
    if ";" in text:
        for seg in reversed([s.strip() for s in text.split(";")]):
            low = seg.lower()
            if any(k in low for k in MEDIUMS) or any(k in low for k in SUPPORTS):
                return seg
    return text


def parse(value: object) -> tuple[frozenset[str], frozenset[str]] | None:
    """Parse a medium string into canonical ``(mediums, supports)`` sets.

    Returns ``None`` when nothing recognisable is found.
    """
    if not isinstance(value, str) or not value.strip():
        return None
    text = _strip_leak(value.strip().lower())
    text = text.replace(" on ", ",").replace(" and ", ",").replace("/", ",")
    text = re.sub(r"[()]", ",", text)
    mediums: set[str] = set()
    supports: set[str] = set()
    for raw in text.split(","):
        tok = raw.strip(" .")
        if not tok:
            continue
        if tok in MEDIUMS:
            mediums.add(MEDIUMS[tok])
        elif tok in SUPPORTS:
            supports.add(SUPPORTS[tok])
        else:
            word = tok.split()[-1] if tok.split() else tok
            if word in MEDIUMS:
                mediums.add(MEDIUMS[word])
            elif word in SUPPORTS:
                supports.add(SUPPORTS[word])
    if not mediums and not supports:
        return None
    return frozenset(mediums), frozenset(supports)


def render(mediums: frozenset[str], supports: frozenset[str]) -> str:
    """Render canonical sets as a human-readable ``"Oil on canvas"`` string."""
    medium_phrase = " and ".join(m for m in _MEDIUM_ORDER if m in mediums)
    support_phrase = " and ".join(s for s in _SUPPORT_ORDER if s in supports)
    if medium_phrase and support_phrase:
        out = f"{medium_phrase} on {support_phrase}"
    else:
        out = medium_phrase or support_phrase
    return out[:1].upper() + out[1:]


def _combine(a: frozenset[str], b: frozenset[str]) -> tuple[frozenset[str], bool]:
    """Merge one dimension. Equal / empty / subset -> union (more complete);
    disjoint non-empty sets -> genuine conflict."""
    if a == b or not a or not b or a <= b or b <= a:
        return a | b, False
    return a | b, True


def reconcile(value_a: object, value_b: object) -> tuple[str, str | None]:
    """Reconcile two medium descriptions.

    Returns ``(kind, canonical)`` where kind is:
      * ``"agree"``     -- equivalent or one merely more complete -> canonical form
      * ``"conflict"``  -- genuine material disagreement -> canonical is None
      * ``"unparsed"``  -- a side could not be parsed -> canonical is None
    """
    pa, pb = parse(value_a), parse(value_b)
    if pa is None or pb is None:
        return "unparsed", None
    mediums, med_conflict = _combine(pa[0], pb[0])
    supports, sup_conflict = _combine(pa[1], pb[1])
    if med_conflict or sup_conflict:
        return "conflict", None
    return "agree", render(mediums, supports)
