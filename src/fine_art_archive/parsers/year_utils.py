"""Shared year and filename-fragment parsing helpers."""

from __future__ import annotations

import re
from re import Pattern

YEAR_TOKEN = re.compile(r"\b(1[0-9]{3}|2[0-9]{3})\b")
DECADE_TOKEN = re.compile(r"\b([12][0-9]{3})s\b")
YEAR_RANGE_TOKEN = re.compile(r"\b\d{4}\s*[-–—]\s*\d{2,4}\b")
CIRCA_TOKEN = re.compile(r"\bc\.?\s*\d{4}\b", re.I)


def parse_year_range(s: str) -> tuple[int | None, int | None]:
    """Extract (year_min, year_max) integers from a free-form year string."""
    if not s:
        return None, None

    dec = DECADE_TOKEN.search(s)
    if dec and not YEAR_TOKEN.search(s.replace(dec.group(0), "", 1)):
        d = int(dec.group(1))
        return d, d + 9

    range_match = re.match(r".*?(\d{4})\s*[-–—]\s*(\d{2,4})\b.*", s)
    if range_match:
        lo = int(range_match.group(1))
        hi_raw = int(range_match.group(2))
        if hi_raw >= 1000:
            hi = hi_raw
        else:
            century = (lo // 100) * 100
            hi = century + hi_raw
            if hi < lo:
                hi += 100
        return lo, hi

    years = [int(m.group(1)) for m in YEAR_TOKEN.finditer(s)]
    if not years:
        return None, None
    return min(years), max(years)


def looks_like_year(
    s: str, *, dimension_pattern: Pattern[str] | None = None
) -> tuple[bool, float, str]:
    """Classify whether a fragment contains year-shaped content."""
    if YEAR_RANGE_TOKEN.search(s):
        return True, 0.95, "year-range"
    if DECADE_TOKEN.search(s) and not YEAR_TOKEN.search(s.replace("s", " ", 1)):
        return True, 0.90, "decade"
    if CIRCA_TOKEN.search(s):
        return True, 0.85, "circa-year"
    if YEAR_TOKEN.search(s):
        if len(s) <= 30 and not (dimension_pattern and dimension_pattern.search(s)):
            return True, 0.80, "single-year"
        return True, 0.60, "year-token-in-longer-text"
    return False, 0.0, ""


def split_with_separators(stem: str) -> list[str]:
    """Split on semicolons, falling back to commas for comma-format names."""
    semi = [s.strip() for s in stem.split(";") if s.strip()]
    if len(semi) >= 3:
        return semi
    comma = [s.strip() for s in stem.split(",") if s.strip()]
    return comma if len(comma) >= 3 else semi or [stem]
