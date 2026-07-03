"""Parse Meural-style filename stems used in Tim's existing Art folder.

The convention captured from the 4,896-file Phase 1 inventory:

    "Title; Artist; Year; Medium; Dimensions.jpeg"          (semicolon, 62%)
    "Title, Artist, Year, Medium, Dimensions.jpeg"          (comma, 19%)
    "<num>. Title; Artist; Year; ...jpeg"                   (numbered series prefix)
    "Single-segment name.jpeg"                              (locations, contemporary, 19%)

Parsing strategy in priority order:
  1. Strip a leading "<num>. " if present (preserves the series number).
  2. Try splitting on ";", then on ",". Whichever yields >=3 parts wins.
  3. If neither yields >=3 parts, treat the whole string as the title.
  4. Within a multi-part split: parts[0] = title, parts[1] = artist; locate the
     part containing a year-shaped token; the remaining parts split into
     medium (no dimension keywords) and dimensions (with cm/mm/in/x/×).

Year parsing is separate and lifts the year string into integer year_min /
year_max bounds. Examples:

    "1873"             -> (1873, 1873)
    "1869-71"          -> (1869, 1871)
    "1869 – 1872"      -> (1869, 1872)   # em-dash supported
    "1700s"            -> (1700, 1799)
    "November-December 1888" -> (1888, 1888)
    "c. 1500"          -> (1500, 1500)
    ""                 -> (None, None)
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from fine_art_archive.parsers.year_utils import (
    DECADE_TOKEN,
    YEAR_RANGE_TOKEN,
    YEAR_TOKEN,
    parse_year_range,
)

NUMBERED_PREFIX = re.compile(r"^(\d+)\.\s+(.*)$")
DIM_KEYWORD = re.compile(r"\b(cm|mm|in|inches|×|x)\b", re.IGNORECASE)


@dataclass
class ParsedName:
    """Structured result of parsing a Meural-style filename stem."""

    number: str = ""  # series number prefix like "35"
    title: str = ""
    artist: str = ""
    year: str = ""  # year as originally written
    year_min: int | None = None
    year_max: int | None = None
    medium: str = ""
    dimensions: str = ""
    raw_stem: str = ""
    parse_strategy: str = ""  # "semicolon" | "comma" | "single"

    def to_dict(self) -> dict:
        return asdict(self)


def _strip_numbered_prefix(s: str) -> tuple[str, str]:
    """Return (series_number, rest) if a "<n>. " prefix is present, else ("", s)."""
    m = NUMBERED_PREFIX.match(s)
    if m:
        return m.group(1), m.group(2)
    return "", s


def parse(stem: str) -> ParsedName:
    """Parse a Meural-format filename stem (no extension) into structured fields.

    See module docstring for the convention and strategy.
    """
    result = ParsedName(raw_stem=stem)

    number, s = _strip_numbered_prefix(stem)
    result.number = number

    semi_parts = [p.strip() for p in s.split(";") if p.strip()]
    comma_parts = [p.strip() for p in s.split(",") if p.strip()]

    if len(semi_parts) >= 3:
        parts = semi_parts
        result.parse_strategy = "semicolon"
    elif len(comma_parts) >= 3:
        parts = comma_parts
        result.parse_strategy = "comma"
    else:
        # Single-segment name: keep the (post-prefix) text as title and stop.
        result.title = s.strip()
        result.parse_strategy = "single"
        return result

    result.title = parts[0]
    if len(parts) >= 2:
        result.artist = parts[1]

    # Heuristic: if the artist field looks like a year token, the user's
    # filename probably wrote "Title, Artist; Year; ..." with a comma
    # separating title from artist inside the first semicolon segment.
    # Recover by splitting parts[0] on its last comma.
    artist_looks_like_year = bool(
        result.artist
        and (
            YEAR_TOKEN.fullmatch(result.artist)
            or DECADE_TOKEN.fullmatch(result.artist)
            or YEAR_RANGE_TOKEN.fullmatch(result.artist)
        )
    )
    if artist_looks_like_year and "," in result.title:
        last_comma = result.title.rfind(",")
        recovered_title = result.title[:last_comma].strip()
        recovered_artist = result.title[last_comma + 1 :].strip()
        if recovered_title and recovered_artist:
            # Promote the year-looking field to actual year, fix title/artist.
            year_string = result.artist
            result.title = recovered_title
            result.artist = recovered_artist
            result.year = year_string
            result.year_min, result.year_max = parse_year_range(year_string)
            # Note: the original "year" position (parts[1]) was consumed; the
            # year search below skips it because year is already set.

    # Locate the year token among parts[2:] only if year isn't already set
    # from the heuristic above.
    rest = parts[2:]
    year_idx = None
    if not result.year:
        for i, p in enumerate(rest):
            if YEAR_TOKEN.search(p) or DECADE_TOKEN.search(p):
                year_idx = i
                result.year = p
                result.year_min, result.year_max = parse_year_range(p)
                break

    if year_idx is None:
        # No year found; rest is presumed to be medium-ish.
        result.medium = "; ".join(rest)
        return result

    remaining = rest[:year_idx] + rest[year_idx + 1 :]
    if not remaining:
        return result

    dim_parts = [r for r in remaining if DIM_KEYWORD.search(r)]
    med_parts = [r for r in remaining if not DIM_KEYWORD.search(r)]
    result.medium = "; ".join(med_parts)
    result.dimensions = "; ".join(dim_parts)
    return result
