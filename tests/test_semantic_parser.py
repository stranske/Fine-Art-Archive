"""Unit tests for fine_art_archive.parsers.semantic.

Run with:  pytest -q tests/test_semantic_parser.py

Deterministic fixture tests for the semantic parser covering:
- classify_fragment() for years, year ranges, dimensions, medium phrases, 
  known artist names, series markers, and default title fragments
- split_with_separators() semicolon vs comma splitting
- parse_semantic() for title-first, artist-first, out-of-order, multi-comma,
  numbered prefix, and suffix-artist examples
- Ambiguous competing artist/name fragments
- canonical_artist_first() edge cases
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import fine_art_archive.parsers.semantic as semantic
from fine_art_archive.parsers.semantic import (
    ParsedFilename,
    classify_fragment,
    canonical_artist_first,
    load_canonical_corpus,
    matches_known_artist,
    parse_semantic,
    split_with_separators,
)


# ---------------------------------------------------------------------------
# Test corpus setup helper
# ---------------------------------------------------------------------------

_TEST_CORPUS_PATH = Path(__file__).parent / "test_canonical_artists.yaml"


def _load_test_corpus():
    """Load the test canonical artist corpus."""
    if _TEST_CORPUS_PATH.exists():
        return load_canonical_corpus(_TEST_CORPUS_PATH)
    return (0, 0)


def _reset_corpus():
    """Reset the corpus to clean state."""
    semantic._KNOWN_ARTISTS_FULL = set()
    semantic._KNOWN_ARTISTS_SURNAMES = set()
    semantic._WIKIDATA_ATTESTED = set()


# ---------------------------------------------------------------------------
# matches_known_artist() tests
# ---------------------------------------------------------------------------


def test_matches_known_artist_wikidata_full():
    """Wikidata-attested artists should return 'wikidata' on full match."""
    _reset_corpus()
    _load_test_corpus()
    assert matches_known_artist("Claude Monet") == "wikidata"
    assert matches_known_artist("Vincent van Gogh") == "wikidata"
    _reset_corpus()


def test_matches_known_artist_wikidata_alias():
    """Wikidata-attested artist aliases should return 'wikidata'."""
    _reset_corpus()
    _load_test_corpus()
    assert matches_known_artist("Van Gogh") == "wikidata"
    assert matches_known_artist("Claude Oscar Monet") == "wikidata"
    _reset_corpus()


def test_matches_known_artist_full():
    """Non-Wikidata but known artists should return 'full'."""
    _reset_corpus()
    _load_test_corpus()
    assert matches_known_artist("James Ensor") == "full"
    assert matches_known_artist("Camille Pissarro") == "full"
    _reset_corpus()


def test_matches_known_artist_full_alias():
    """Known artist aliases should return 'full'."""
    _reset_corpus()
    _load_test_corpus()
    assert matches_known_artist("Ensor") == "full"
    assert matches_known_artist("Boudin") == "full"
    _reset_corpus()


def test_matches_known_artist_surname():
    """Surname-only matches should return 'surname'."""
    _reset_corpus()
    _load_test_corpus()
    assert matches_known_artist("Monet") == "surname"
    assert matches_known_artist("Renoir") == "surname"
    assert matches_known_artist("Degas") == "surname"
    _reset_corpus()


def test_matches_known_artist_no_match():
    """Unknown names should return None."""
    _reset_corpus()
    _load_test_corpus()
    assert matches_known_artist("Unknown Artist") is None
    assert matches_known_artist("") is None
    assert matches_known_artist("   ") is None
    _reset_corpus()


def test_matches_known_artist_case_insensitive():
    """Artist matching should be case-insensitive."""
    _reset_corpus()
    _load_test_corpus()
    assert matches_known_artist("claudE mOnEt") == "wikidata"
    assert matches_known_artist("VINCENT VAN GOGH") == "wikidata"
    assert matches_known_artist("monet") == "surname"
    _reset_corpus()


def test_matches_known_artist_diacritics():
    """Artist matching should be diacritic-insensitive."""
    _reset_corpus()
    _load_test_corpus()
    # Diego Velázquez has diacritics
    assert matches_known_artist("Diego Velazquez") == "wikidata"  # stripped variant
    assert matches_known_artist("Diego Velázquez") == "wikidata"  # original
    _reset_corpus()


# ---------------------------------------------------------------------------
# classify_fragment() tests
# ---------------------------------------------------------------------------


def test_classify_fragment_year_single():
    """Single year should classify as year."""
    _reset_corpus()
    _load_test_corpus()
    result = classify_fragment("1873")
    assert result.type == "year"
    assert result.confidence >= 0.80
    assert "single-year" in result.evidence
    _reset_corpus()


def test_classify_fragment_year_range_hyphen():
    """Year range with hyphen should classify as year."""
    _reset_corpus()
    _load_test_corpus()
    result = classify_fragment("1869-71")
    assert result.type == "year"
    assert result.confidence >= 0.95
    assert "year-range" in result.evidence
    _reset_corpus()


def test_classify_fragment_dimensions_with_unit():
    """Dimensions with units should classify as dimensions."""
    _reset_corpus()
    _load_test_corpus()
    result = classify_fragment("82.5 × 64 cm")
    assert result.type == "dimensions"
    assert result.confidence >= 0.95
    assert "dimensions-with-unit" in result.evidence
    _reset_corpus()


def test_classify_fragment_medium_oil_on_canvas():
    """Oil on canvas should classify as medium."""
    _reset_corpus()
    _load_test_corpus()
    result = classify_fragment("Oil on canvas")
    assert result.type == "medium"
    assert result.confidence >= 0.95
    assert "medium-keyword:oil on canvas" in result.evidence
    _reset_corpus()


def test_classify_fragment_series():
    """'from the series' should classify as series."""
    _reset_corpus()
    _load_test_corpus()
    result = classify_fragment("from the series The Large Landscapes")
    assert result.type == "series"
    assert result.confidence >= 0.90
    assert "series-keyword" in result.evidence
    _reset_corpus()


def test_classify_fragment_name_wikidata():
    """Wikidata-attested artist name should classify as name."""
    _reset_corpus()
    _load_test_corpus()
    result = classify_fragment("Claude Monet")
    assert result.type == "name"
    assert result.confidence >= 0.99
    assert "wikidata" in result.evidence
    _reset_corpus()


def test_classify_fragment_title_default():
    """Non-classifiable fragments should default to title."""
    _reset_corpus()
    _load_test_corpus()
    result = classify_fragment("After the Bullfight")
    assert result.type == "title"
    assert result.confidence == 0.40
    assert "default-residue" in result.evidence
    _reset_corpus()


def test_classify_fragment_empty():
    """Empty fragments should be handled gracefully."""
    _reset_corpus()
    _load_test_corpus()
    result = classify_fragment("")
    assert result.type == "title"
    assert result.confidence == 0.40
    _reset_corpus()


# ---------------------------------------------------------------------------
# split_with_separators() tests
# ---------------------------------------------------------------------------


def test_split_with_separators_semicolon_multiple():
    """Semicolon-separated strings should split on semicolons when >=3 fragments."""
    result = split_with_separators("Title; Artist; 1873; Oil on canvas")
    assert result == ["Title", "Artist", "1873", "Oil on canvas"]


def test_split_with_separators_comma_fallback():
    """Comma-separated strings should split on commas when semicolons yield <3 fragments."""
    result = split_with_separators("Title, Artist, 1873")
    assert result == ["Title", "Artist", "1873"]


def test_split_with_separators_single_fragment():
    """Single fragment with no separators should return original."""
    result = split_with_separators("Single Fragment")
    assert result == ["Single Fragment"]


def test_split_with_separators_empty_string():
    """Empty string should return empty list."""
    result = split_with_separators("")
    assert result == []


def test_split_with_separators_whitespace_handling():
    """Extra whitespace should be stripped from fragments."""
    result = split_with_separators("  Title  ;  Artist  ;  1873  ")
    assert result == ["Title", "Artist", "1873"]


# ---------------------------------------------------------------------------
# parse_semantic() tests
# ---------------------------------------------------------------------------


def test_parse_semantic_title_first_basic():
    """Basic title-first format: Title; Artist; Year; Medium; Dimensions."""
    _reset_corpus()
    _load_test_corpus()
    result = parse_semantic("After the Bullfight; Mary Cassatt; 1873; Oil on canvas; 82.5 × 64 cm")
    assert result.title == "After the Bullfight"
    assert result.artist == "Mary Cassatt"
    assert result.year == "1873"
    assert result.medium == "Oil on canvas"
    assert result.dimensions == "82.5 × 64 cm"
    assert result.artist_confidence >= 0.95
    assert not result.ambiguous
    _reset_corpus()


def test_parse_semantic_artist_first_basic():
    """Artist-first format: Artist; Title; Year; Medium; Dimensions."""
    _reset_corpus()
    _load_test_corpus()
    result = parse_semantic("Claude Monet; Water Lilies; 1906; Oil on canvas; 100 × 200 cm")
    assert result.artist == "Claude Monet"
    assert result.title == "Water Lilies"
    assert result.year == "1906"
    assert result.medium == "Oil on canvas"
    assert result.dimensions == "100 × 200 cm"
    _reset_corpus()


def test_parse_semantic_out_of_order():
    """Out-of-order fields: Title; Year; Artist; Medium."""
    _reset_corpus()
    _load_test_corpus()
    result = parse_semantic("Water Lilies; 1906; Claude Monet; Oil on canvas")
    assert result.title == "Water Lilies"
    assert result.artist == "Claude Monet"
    assert result.year == "1906"
    assert result.medium == "Oil on canvas"
    _reset_corpus()


def test_parse_semantic_multi_comma_title_artist():
    """Multi-comma title with artist: Orchard in Bloom, Louveciennes, Camille Pissarro."""
    _reset_corpus()
    _load_test_corpus()
    result = parse_semantic("Orchard in Bloom, Louveciennes, Camille Pissarro")
    assert result.artist == "Camille Pissarro"
    assert "Orchard in Bloom" in result.title
    assert "Louveciennes" in result.title
    _reset_corpus()


def test_parse_semantic_numbered_prefix():
    """Numbered prefix: No. 32 - Seba, from the series ..."""
    _reset_corpus()
    _load_test_corpus()
    result = parse_semantic("No. 32 - Seba, from the series The Large Landscapes")
    assert result.number == "32"
    _reset_corpus()


def test_parse_semantic_suffix_artist():
    """Suffix artist: The Beach and the Falaise d'Amont Claude Monet."""
    _reset_corpus()
    _load_test_corpus()
    result = parse_semantic("The Beach and the Falaise d'Amont Claude Monet")
    assert result.artist == "Claude Monet"
    assert "The Beach" in result.title
    assert "Falaise d'Amont" in result.title
    _reset_corpus()


def test_parse_semantic_suffix_artist_boudin():
    """Suffix artist: Seated Figures Eugene Boudin."""
    _reset_corpus()
    _load_test_corpus()
    result = parse_semantic("Seated Figures Eugene Boudin")
    assert result.artist == "Eugene Boudin"
    assert result.title == "Seated Figures"
    _reset_corpus()


def test_parse_semantic_single_fragment():
    """Single fragment should be treated as title."""
    _reset_corpus()
    _load_test_corpus()
    result = parse_semantic("Just a title")
    assert result.title == "Just a title"
    assert result.artist == ""
    assert result.year == ""
    _reset_corpus()


def test_parse_semantic_empty_string():
    """Empty string should be handled gracefully."""
    _reset_corpus()
    _load_test_corpus()
    result = parse_semantic("")
    assert result.title == ""
    assert result.raw_stem == ""
    _reset_corpus()


def test_parse_semantic_ensor_case():
    """Ensor case: 'Ensor, Masks Confronting Death'."""
    _reset_corpus()
    _load_test_corpus()
    result = parse_semantic("Ensor, Masks Confronting Death")
    assert result.artist == "Ensor"
    assert "Masks Confronting Death" in result.title
    _reset_corpus()


# ---------------------------------------------------------------------------
# canonical_artist_first() tests
# ---------------------------------------------------------------------------


def test_canonical_artist_first_basic():
    """Basic case with all fields should render artist-first."""
    parsed = ParsedFilename(
        title="Water Lilies",
        artist="Claude Monet",
        year="1906",
        medium="Oil on canvas",
        dimensions="100 × 200 cm"
    )
    result = canonical_artist_first(parsed)
    assert result == "Claude Monet; Water Lilies; 1906; Oil on canvas; 100 × 200 cm"


def test_canonical_artist_first_missing_artist():
    """When artist is missing, should return raw stem."""
    parsed = ParsedFilename(
        title="Water Lilies",
        artist="",
        year="1906",
        medium="Oil on canvas",
        raw_stem="Water Lilies; 1906; Oil on canvas"
    )
    result = canonical_artist_first(parsed)
    assert result == "Water Lilies; 1906; Oil on canvas"


def test_canonical_artist_first_empty_slots_omitted():
    """Empty slots should be omitted (no double semicolons)."""
    parsed = ParsedFilename(
        title="Water Lilies",
        artist="Claude Monet",
        year="",
        medium="Oil on canvas",
        dimensions="100 × 200 cm"
    )
    result = canonical_artist_first(parsed)
    assert result == "Claude Monet; Water Lilies; Oil on canvas; 100 × 200 cm"
    assert ";;" not in result


def test_canonical_artist_first_only_artist_and_title():
    """Only artist and title should render correctly."""
    parsed = ParsedFilename(
        title="Water Lilies",
        artist="Claude Monet",
        year="",
        medium="",
        dimensions=""
    )
    result = canonical_artist_first(parsed)
    assert result == "Claude Monet; Water Lilies"


def test_canonical_artist_first_all_empty():
    """When all slots are empty, should return raw stem."""
    parsed = ParsedFilename(
        title="",
        artist="",
        year="",
        medium="",
        dimensions="",
        raw_stem="Some raw stem"
    )
    result = canonical_artist_first(parsed)
    assert result == "Some raw stem"


def test_canonical_artist_first_series_included():
    """Series should be included in output."""
    parsed = ParsedFilename(
        title="Water Lilies",
        artist="Claude Monet",
        year="1906",
        medium="Oil on canvas",
        dimensions="",
        series="from the series Water Lilies"
    )
    result = canonical_artist_first(parsed)
    assert "from the series Water Lilies" in result


def test_canonical_artist_first_ordering():
    """Order should be Artist; Title; Year; Medium; Dimensions; Series."""
    parsed = ParsedFilename(
        title="Title",
        artist="Artist",
        year="1873",
        medium="Medium",
        dimensions="Dimensions",
        series="Series"
    )
    result = canonical_artist_first(parsed)
    parts = result.split("; ")
    assert parts[0] == "Artist"
    assert parts[1] == "Title"
    assert parts[2] == "1873"
    assert parts[3] == "Medium"
    assert parts[4] == "Dimensions"
    assert parts[5] == "Series"


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


def test_integration_full_pipeline_basic():
    """Test full pipeline from stem to canonical form."""
    _reset_corpus()
    _load_test_corpus()
    stem = "After the Bullfight; Mary Cassatt; 1873; Oil on canvas; 82.5 × 64 cm"
    
    parsed = parse_semantic(stem)
    canonical = canonical_artist_first(parsed)
    
    assert parsed.artist == "Mary Cassatt"
    assert parsed.title == "After the Bullfight"
    assert parsed.year == "1873"
    assert parsed.medium == "Oil on canvas"
    assert parsed.dimensions == "82.5 × 64 cm"
    assert canonical.startswith("Mary Cassatt;")
    _reset_corpus()


def test_integration_full_pipeline_out_of_order():
    """Test full pipeline with out-of-order input."""
    _reset_corpus()
    _load_test_corpus()
    stem = "Water Lilies; 1906; Claude Monet; Oil on canvas"
    
    parsed = parse_semantic(stem)
    canonical = canonical_artist_first(parsed)
    
    assert parsed.artist == "Claude Monet"
    assert parsed.title == "Water Lilies"
    assert parsed.year == "1906"
    assert canonical.startswith("Claude Monet;")
    _reset_corpus()


def test_integration_full_pipeline_multi_comma():
    """Test full pipeline with multi-comma title + artist."""
    _reset_corpus()
    _load_test_corpus()
    stem = "Orchard in Bloom, Louveciennes, Camille Pissarro; 1877; Oil on canvas"
    
    parsed = parse_semantic(stem)
    canonical = canonical_artist_first(parsed)
    
    assert parsed.artist == "Camille Pissarro"
    assert "Orchard in Bloom" in parsed.title
    assert "Louveciennes" in parsed.title
    assert canonical.startswith("Camille Pissarro;")
    _reset_corpus()