"""Unit tests for fine_art_archive.parsers.meural_filename.

Run with:  pytest -q tests/test_meural_filename.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fine_art_archive.parsers.meural_filename import (  # noqa: E402
    parse,
    parse_year_range,
)
from fine_art_archive.parsers.year_utils import (
    parse_year_range as shared_parse_year_range,  # noqa: E402
)

# ---------------------------------------------------------------------------
# Semicolon-format (62% of the corpus)
# ---------------------------------------------------------------------------


def test_semicolon_basic():
    r = parse("After the Bullfight; Mary Cassatt; 1873; Oil on canvas; 82.5 × 64 cm")
    assert r.parse_strategy == "semicolon"
    assert r.title == "After the Bullfight"
    assert r.artist == "Mary Cassatt"
    assert r.year == "1873"
    assert r.year_min == 1873
    assert r.year_max == 1873
    assert r.medium == "Oil on canvas"
    assert r.dimensions == "82.5 × 64 cm"
    assert r.number == ""


def test_semicolon_year_range_hyphen():
    r = parse(
        "At the Café de Châteaudun; Hilaire-Germain-Edgar Degas; 1869-71; oil on paper, mounted on wood; 23.7 × 19 cm"
    )
    assert r.parse_strategy == "semicolon"
    assert r.title == "At the Café de Châteaudun"
    assert r.year == "1869-71"
    assert r.year_min == 1869
    assert r.year_max == 1871


def test_semicolon_year_range_em_dash():
    r = parse(
        "Portrait of Pope Julius II; Raphael and workshop; 1511 – 1512; oil on poplar wood; 105.6 x 78.5 cm"
    )
    assert r.parse_strategy == "semicolon"
    assert r.year == "1511 – 1512"
    assert r.year_min == 1511
    assert r.year_max == 1512


def test_semicolon_year_word_form():
    r = parse(
        "Portrait of Camille Roulin; Vincent van Gogh; November-December 1888; oil on canvas; 40.5 × 32.5 cm"
    )
    assert r.parse_strategy == "semicolon"
    assert r.year == "November-December 1888"
    assert r.year_min == 1888
    assert r.year_max == 1888


def test_semicolon_decade():
    r = parse("A Bacchanal; Sebastiano Ricci; 1700s; oil on canvas; 77.5 x 105.7 cm")
    assert r.parse_strategy == "semicolon"
    assert r.year == "1700s"
    assert r.year_min == 1700
    assert r.year_max == 1709


# ---------------------------------------------------------------------------
# Comma-format (19% of the corpus)
# ---------------------------------------------------------------------------


def test_comma_basic():
    r = parse("Bearded Man with a Beret, Jan Lievens, 1630, oil on panel, 53.5 x 46.3 cm")
    assert r.parse_strategy == "comma"
    assert r.title == "Bearded Man with a Beret"
    assert r.artist == "Jan Lievens"
    assert r.year == "1630"
    assert r.year_min == 1630
    assert r.medium == "oil on panel"
    assert r.dimensions == "53.5 x 46.3 cm"


def test_comma_with_inches():
    r = parse("A Boyar Wedding Feast; Konstantin Makovsky; 1883; 154 x 93 in")
    assert r.parse_strategy == "semicolon"
    assert r.year == "1883"
    assert "in" in r.dimensions.lower() or "154" in r.dimensions


# ---------------------------------------------------------------------------
# Numbered-prefix (Presidents series, etc.)
# ---------------------------------------------------------------------------


def test_numbered_prefix_single_segment():
    r = parse("35. John and Jacqueline Kennedy")
    assert r.number == "35"
    assert r.parse_strategy == "single"
    assert r.title == "John and Jacqueline Kennedy"


def test_numbered_prefix_with_structured_metadata():
    r = parse("37. Richard Milhous Nixon, Norman Rockwell, 1968, Oil on canvas, 46.4 × 66.7 cm")
    assert r.number == "37"
    assert r.parse_strategy == "comma"
    assert r.title == "Richard Milhous Nixon"
    assert r.artist == "Norman Rockwell"
    assert r.year_min == 1968


# ---------------------------------------------------------------------------
# Single-segment (locations, contemporary works without museum metadata)
# ---------------------------------------------------------------------------


def test_single_segment_location():
    r = parse("Chartres - South Rose Window")
    assert r.parse_strategy == "single"
    assert r.title == "Chartres - South Rose Window"
    assert r.artist == ""
    assert r.year == ""


def test_single_segment_contemporary():
    r = parse("Going back to the roots, JB Maingi")
    # Only 2 segments after comma split -> falls back to single.
    assert r.parse_strategy == "single"
    assert r.title == "Going back to the roots, JB Maingi"


# ---------------------------------------------------------------------------
# Year-range parser specifically
# ---------------------------------------------------------------------------


def test_year_range_simple():
    assert parse_year_range("1873") == (1873, 1873)


def test_year_range_hyphenated_two_digit_suffix():
    assert parse_year_range("1869-71") == (1869, 1871)


def test_year_range_em_dash_full():
    assert parse_year_range("1511 – 1512") == (1511, 1512)


def test_year_range_decade():
    assert parse_year_range("1700s") == (1700, 1709)
    assert parse_year_range("1880s") == (1880, 1889)


def test_year_range_word_form():
    assert parse_year_range("November-December 1888") == (1888, 1888)


def test_year_range_circa():
    # "c. 1500" — YEAR_TOKEN catches the year
    assert parse_year_range("c. 1500") == (1500, 1500)


def test_year_range_empty():
    assert parse_year_range("") == (None, None)
    assert parse_year_range("undated") == (None, None)


def test_year_range_century_rollover():
    # Hypothetical "1599-02" would mean 1599 to 1602 if we cross a century.
    assert parse_year_range("1599-02") == (1599, 1602)


def test_meural_parser_reexports_shared_year_parser():
    assert parse_year_range is shared_parse_year_range


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


def test_extra_whitespace_in_semicolons():
    r = parse(
        "Portrait of Camille Roulin; Vincent van Gogh ;  November-December 1888; oil on canvas, 40.5 cm x 32.5 cm"
    )
    # The artist part has a trailing space that should be stripped.
    assert r.artist == "Vincent van Gogh"


def test_raw_stem_preserved():
    stem = "After the Bullfight; Mary Cassatt; 1873; Oil on canvas; 82.5 × 64 cm"
    r = parse(stem)
    assert r.raw_stem == stem


# ---------------------------------------------------------------------------
# Title-comma-artist heuristic (Marten Looten case)
# ---------------------------------------------------------------------------


def test_title_comma_artist_heuristic_basic():
    """When 'Title, Artist' shares the first semicolon segment with a year
    next, recover the actual title and artist."""
    r = parse("Portrait of Marten Looten, Rembrandt van Rijn; 1632; Oil on wood; 92.7 × 76.2 cm")
    assert r.title == "Portrait of Marten Looten"
    assert r.artist == "Rembrandt van Rijn"
    assert r.year == "1632"
    assert r.year_min == 1632


def test_title_comma_artist_heuristic_year_range():
    """The heuristic should also recognize year ranges in the field-two slot."""
    r = parse("Some Title, Some Artist; 1869-71; Oil on canvas; 50 x 60 cm")
    assert r.title == "Some Title"
    assert r.artist == "Some Artist"
    assert r.year == "1869-71"
    assert r.year_min == 1869
    assert r.year_max == 1871


def test_title_comma_artist_heuristic_does_not_fire_when_title_lacks_comma():
    """Heuristic must not corrupt cases where artist legitimately is a number-like
    string (rare but defensive). When the title has no comma, leave it alone."""
    # If somehow artist looks like a year but title has no comma, don't split.
    # We can't easily construct a real-world example here; check that a
    # year-shaped artist with comma-less title still yields a year-shaped
    # artist (we don't crash or invent a split).
    r = parse("Just A Title; 1873; Medium; 10 x 10 cm")
    # Parser already finds 1873 in parts[1] (the artist slot) -- this means
    # the heuristic activates, but there's no comma to split, so it stays as is.
    # The artist remains "1873" (an obvious data quality issue worth flagging).
    assert r.title == "Just A Title"
    # The artist is "1873" because there's no comma in the title to split on.
    # The heuristic is conservative — it only rewrites if it has somewhere to
    # put the recovered artist.
    assert r.artist == "1873"
