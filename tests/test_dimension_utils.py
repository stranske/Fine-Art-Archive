"""Tests for shared dimension parsing and comparison.

Ported from the local workspace fork of `collect/dedupe.py` during the
2026-08-08 audit's D8 fork-consolidation step. `dim_compat` was the only
capability the fork held that the repo lacked; the fork's dimension *parser*
was superseded by `enrichment.source_resolver.parse_dimensions` and was not
ported.
"""

from __future__ import annotations

import math

import pytest

from fine_art_archive.collect import dedupe
from fine_art_archive.parsers.dimension_utils import dim_compat, parse_dimension_pair


class TestParseDimensionPair:
    def test_canonical_forms(self) -> None:
        assert parse_dimension_pair("53.5 x 46.3 cm") == (46.3, 53.5)
        assert parse_dimension_pair("53.5 × 46.3 cm") == (46.3, 53.5)
        assert parse_dimension_pair("40.5 cm x 32.5 cm") == (32.5, 40.5)

    def test_european_comma_decimal(self) -> None:
        assert parse_dimension_pair("73,5 x 92,3 cm") == (73.5, 92.3)

    def test_unit_conversion(self) -> None:
        height, width = parse_dimension_pair("10 x 20 inches")
        assert math.isclose(height, 25.4, abs_tol=1e-3)
        assert math.isclose(width, 50.8, abs_tol=1e-3)

        millimetres = parse_dimension_pair("535 x 463 mm")
        assert millimetres is not None
        assert math.isclose(millimetres[0], 46.3, abs_tol=1e-6)

    def test_surrounding_prose_is_ignored(self) -> None:
        assert parse_dimension_pair("oil on canvas, 40.5 cm x 32.5 cm") == (32.5, 40.5)
        assert parse_dimension_pair("55.5 cm x 47 cm (1)") == (47.0, 55.5)

    def test_order_independent(self) -> None:
        assert parse_dimension_pair("46.3 x 53.5 cm") == parse_dimension_pair("53.5 x 46.3 cm")

    @pytest.mark.parametrize("value", ["", "oil on canvas", "unknown", "0 x 0 cm"])
    def test_unparseable_returns_none(self, value: str) -> None:
        assert parse_dimension_pair(value) is None


class TestDimCompat:
    def test_match_within_tolerance(self) -> None:
        assert dim_compat("53.5 x 46.3 cm", "53.5 x 46.3 cm")[0] == "match"
        # Catalogue rounding.
        assert dim_compat("53.5 x 46.3 cm", "53 x 46 cm")[0] == "match"
        # Order-swapped.
        assert dim_compat("53.5 x 46.3 cm", "46.3 x 53.5 cm")[0] == "match"

    def test_mismatch_outside_tolerance(self) -> None:
        # The two 1887 Van Gogh self-portraits: 42x34 cardboard vs 19x14.1.
        status, difference = dim_compat("42 x 34 cm", "19 cm x 14.1 cm")
        assert status == "mismatch"
        assert difference is not None and difference > 0.5

        assert dim_compat("60 x 85 cm", "80 x 100 cm")[0] == "mismatch"

    @pytest.mark.parametrize(
        ("left", "right"),
        [("", "53 x 46 cm"), ("oil on canvas", "53 x 46 cm"), ("", "")],
    )
    def test_absent_when_either_side_unparseable(self, left: str, right: str) -> None:
        status, difference = dim_compat(left, right)
        assert status == "absent"
        assert difference is None

    def test_inches_versus_cm(self) -> None:
        # 21x17 in is 53.34x43.18 cm: height agrees within 1%, width is 6.5%
        # off, so the 5% threshold correctly bites.
        assert dim_compat("21 x 17 inches", "53 x 46 cm")[0] == "mismatch"
        # A genuinely equivalent pair still matches across units.
        assert dim_compat("21 x 18 inches", "53.5 x 45.5 cm")[0] == "match"

    def test_tolerance_is_configurable(self) -> None:
        assert dim_compat("21 x 17 inches", "53 x 46 cm", tolerance=0.10)[0] == "match"


class TestDedupeReExports:
    """The workspace ops script imports these private names from `dedupe`."""

    def test_private_aliases_resolve_to_the_shared_helpers(self) -> None:
        assert dedupe._dim_compat is dim_compat
        assert dedupe._parse_dimensions is parse_dimension_pair

    def test_alias_is_callable_through_dedupe(self) -> None:
        assert dedupe._dim_compat("53.5 x 46.3 cm", "53 x 46 cm")[0] == "match"
