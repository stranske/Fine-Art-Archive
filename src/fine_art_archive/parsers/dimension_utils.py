"""Shared physical-dimension parsing and comparison helpers.

Two works with the same title and artist are routinely different works — a
study and the finished painting, or two versions in a series. Physical size is
the cheapest signal that separates them, so duplicate detection compares
dimension strings rather than trusting title/artist agreement alone.

Scope note: :func:`fine_art_archive.enrichment.source_resolver.parse_dimensions`
is the richer parser and stays authoritative for *sidecar metadata* — it accepts
mappings, strips HTML, and reads labelled ``height:``/``width:`` forms. This
module answers the narrower question "are these two size strings the same size",
returning an order-independent pair. The two should eventually converge on one
parser; they are separate today because ``source_resolver`` imports
``collect.host_registry``, so importing it from ``collect.dedupe`` would close a
dependency cycle.
"""

from __future__ import annotations

import re

DimCompat = str  # "match" | "mismatch" | "absent"

_DIM_NUM = r"\d+(?:[.,]\d+)?"
DIMENSION_PAIR_TOKEN = re.compile(
    rf"({_DIM_NUM})\s*(cm|mm|m|in|inch|inches)?\s*[×x]\s*"
    rf"({_DIM_NUM})\s*(cm|mm|m|in|inch|inches)?",
    re.IGNORECASE,
)

_TO_CM = {
    "mm": 0.1,
    "cm": 1.0,
    "m": 100.0,
    "in": 2.54,
    "inch": 2.54,
    "inches": 2.54,
}


def parse_dimension_pair(value: str) -> tuple[float, float] | None:
    """Return ``(smaller_cm, larger_cm)`` from a free-form dimension string.

    Handles the forms that actually occur in the inventory::

        "53.5 x 46.3 cm"      "53.5 × 46.3 cm"       "40.5 cm x 32.5 cm"
        "73,5 x 92,3 cm"      "26 x 37.5 in"         "62 x 47 inches"
        "oil on canvas, 40.5 cm x 32.5 cm"           "55.5 cm x 47 cm (1)"

    A leading medium clause and a trailing parenthetical are ignored. European
    comma decimals are accepted. The pair is sorted ascending so that a work
    catalogued ``53.5 x 46.3`` compares equal to the same work catalogued
    ``46.3 x 53.5``.

    Returns ``None`` when no dimension-shaped token is present, or when a
    parsed value is non-finite or non-positive.
    """
    if not value:
        return None
    match = DIMENSION_PAIR_TOKEN.search(value)
    if match is None:
        return None

    first_raw, first_unit, second_raw, second_unit = match.groups()
    try:
        first = float(first_raw.replace(",", "."))
        second = float(second_raw.replace(",", "."))
    except ValueError:
        return None

    # The trailing unit wins when present: "N x N cm" states the unit once, at
    # the end. Fall back to a leading unit, then to cm (the dominant unit in
    # this inventory).
    unit = (second_unit or first_unit or "cm").lower()
    factor = _TO_CM.get(unit, 1.0)
    first *= factor
    second *= factor

    if first <= 0 or second <= 0:
        return None
    return tuple(sorted((first, second)))  # type: ignore[return-value]


def dim_compat(a: str, b: str, *, tolerance: float = 0.05) -> tuple[DimCompat, float | None]:
    """Compare two dimension strings.

    Returns ``(status, max_relative_difference)`` where status is:

    - ``"match"`` — both parsed, and both sides agree within ``tolerance``
    - ``"mismatch"`` — both parsed, at least one side outside ``tolerance``
    - ``"absent"`` — at least one side missing or unparseable

    The 5% default absorbs catalogue rounding (53.5 vs 53.34) and cm-vs-inch
    conversion artefacts, while still separating genuinely different works —
    the two 1887 Van Gogh self-portraits at 42x34 cm and 19x14.1 cm come out
    as ``mismatch``.

    ``"absent"`` is deliberately distinct from ``"mismatch"``: a missing
    dimension is not evidence of difference, and callers must not treat it as
    such.
    """
    parsed_a = parse_dimension_pair(a)
    parsed_b = parse_dimension_pair(b)
    if parsed_a is None or parsed_b is None:
        return ("absent", None)

    def relative(x: float, y: float) -> float:
        denominator = max(x, y)
        return abs(x - y) / denominator if denominator else 0.0

    difference = max(
        relative(parsed_a[0], parsed_b[0]),
        relative(parsed_a[1], parsed_b[1]),
    )
    return ("match" if difference <= tolerance else "mismatch", difference)
