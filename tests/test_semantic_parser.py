"""Unit tests for fine_art_archive.parsers.semantic.

Run with:  pytest -q tests/test_semantic_parser.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import fine_art_archive.parsers.semantic as semantic  # noqa: E402
from fine_art_archive.parsers.semantic import (  # noqa: E402
    ParsedFilename,
    canonical_artist_first,
    classify_fragment,
    load_canonical_corpus,
    parse_semantic,
    split_with_separators,
)

CANONICAL_YAML = """\
artists:
  - name: Claude Monet
    wikidata_qid: Q296
  - name: Mary Cassatt
    wikidata_qid: Q161145
  - name: James Ensor
    wikidata_qid: Q983565
  - name: Camille Pissarro
    wikidata_qid: Q134741
  - name: Eugene Boudin
    wikidata_qid: Q272224
"""


@pytest.fixture
def reset_corpus():
    """Clear module-level artist corpora before and after each test."""
    semantic._KNOWN_ARTISTS_FULL = set()
    semantic._KNOWN_ARTISTS_SURNAMES = set()
    semantic._WIKIDATA_ATTESTED = set()
    yield
    semantic._KNOWN_ARTISTS_FULL = set()
    semantic._KNOWN_ARTISTS_SURNAMES = set()
    semantic._WIKIDATA_ATTESTED = set()


@pytest.fixture
def canonical_corpus(tmp_path, reset_corpus):
    yaml_path = tmp_path / "artists.yaml"
    yaml_path.write_text(CANONICAL_YAML, encoding="utf-8")
    load_canonical_corpus(yaml_path)
    return yaml_path


# --- classify_fragment ------------------------------------------------------


def test_classify_fragment_year(reset_corpus):
    fc = classify_fragment("1873")
    assert fc.type == "year"
    assert fc.confidence >= 0.80


def test_classify_fragment_year_range(reset_corpus):
    fc = classify_fragment("1869-71")
    assert fc.type == "year"
    assert fc.confidence >= 0.90


def test_classify_fragment_dimensions(reset_corpus):
    fc = classify_fragment("82.5 × 64 cm")
    assert fc.type == "dimensions"
    assert fc.confidence >= 0.90


def test_classify_fragment_medium(reset_corpus):
    fc = classify_fragment("Oil on canvas")
    assert fc.type == "medium"
    assert fc.confidence >= 0.85


def test_classify_fragment_known_artist(canonical_corpus):
    fc = classify_fragment("Mary Cassatt")
    assert fc.type == "name"
    assert fc.confidence >= 0.95
    assert "wikidata" in fc.evidence or "known" in fc.evidence


def test_classify_fragment_series(reset_corpus):
    fc = classify_fragment("from the series Natural History")
    assert fc.type == "series"
    assert fc.confidence >= 0.85


def test_classify_fragment_default_title_not_name_like(reset_corpus):
    fc = classify_fragment("masks confronting death")
    assert fc.type == "title"
    assert fc.confidence == 0.40
    assert fc.evidence == "default-residue"


# --- split_with_separators --------------------------------------------------


def test_split_with_separators_prefers_semicolons(reset_corpus):
    stem = "Title; Artist; 1873; Oil on canvas; 82.5 × 64 cm"
    assert split_with_separators(stem) == [
        "Title",
        "Artist",
        "1873",
        "Oil on canvas",
        "82.5 × 64 cm",
    ]


def test_split_with_separators_comma_fallback(reset_corpus):
    stem = "Orchard in Bloom, Louveciennes, Camille Pissarro"
    assert split_with_separators(stem) == [
        "Orchard in Bloom",
        "Louveciennes",
        "Camille Pissarro",
    ]


def test_split_with_separators_short_semicolon_list_keeps_semis(reset_corpus):
    assert split_with_separators("Title; Artist") == ["Title", "Artist"]


# --- parse_semantic ---------------------------------------------------------


def test_parse_semantic_title_first(canonical_corpus):
    result = parse_semantic(
        "After the Bullfight; Mary Cassatt; 1873; Oil on canvas; 82.5 × 64 cm"
    )
    assert result.title == "After the Bullfight"
    assert result.artist == "Mary Cassatt"
    assert result.year == "1873"
    assert result.medium == "Oil on canvas"
    assert result.dimensions == "82.5 × 64 cm"
    assert result.ambiguous is False


def test_parse_semantic_artist_first(canonical_corpus):
    result = parse_semantic(
        "Ensor, Masks Confronting Death; 1888; oil on canvas; 72 × 94 cm"
    )
    assert result.artist == "Ensor"
    assert "Masks Confronting Death" in result.title
    assert result.year == "1888"
    assert result.medium == "oil on canvas"
    assert result.dimensions == "72 × 94 cm"


def test_parse_semantic_out_of_order(canonical_corpus):
    result = parse_semantic(
        "Arrival of the Normandy Train; 1877; Claude Monet; oil on canvas; 60 × 73 cm"
    )
    assert result.title == "Arrival of the Normandy Train"
    assert result.artist == "Claude Monet"
    assert result.year == "1877"
    assert result.medium == "oil on canvas"
    assert result.dimensions == "60 × 73 cm"


def test_parse_semantic_multi_comma_title_plus_artist(canonical_corpus):
    result = parse_semantic(
        "Orchard in Bloom, Louveciennes, Camille Pissarro; 1872; oil on canvas"
    )
    assert result.artist == "Camille Pissarro"
    assert "Orchard in Bloom" in result.title
    assert "Louveciennes" in result.title
    assert result.year == "1872"
    assert result.medium == "oil on canvas"


def test_parse_semantic_numbered_prefix(canonical_corpus):
    result = parse_semantic(
        "No. 32 - Seba, from the series Natural History; 1830; engraving"
    )
    assert result.number == "32"
    assert result.year == "1830"
    assert result.medium == "engraving"
    assert "series" in result.series.lower()


def test_parse_semantic_suffix_artist(canonical_corpus):
    result = parse_semantic("The Beach and the Falaise d'Amont Claude Monet")
    assert result.artist == "Claude Monet"
    assert "Beach" in result.title
    assert result.ambiguous is False


def test_parse_semantic_ambiguous_competing_artists(canonical_corpus):
    result = parse_semantic("Mary Cassatt; Claude Monet; 1880")
    assert result.ambiguous is True
    assert len(result.notes) >= 1
    assert "competing name candidates" in result.notes[0]
    assert "Mary Cassatt" in result.notes[0]
    assert "Claude Monet" in result.notes[0]


# --- canonical_artist_first -------------------------------------------------


def test_canonical_artist_first_omits_empty_slots(reset_corpus):
    parsed = ParsedFilename(
        artist="Mary Cassatt",
        title="After the Bullfight",
        year="1873",
        raw_stem="ignored",
    )
    assert canonical_artist_first(parsed) == "Mary Cassatt; After the Bullfight; 1873"


def test_canonical_artist_first_includes_series(reset_corpus):
    parsed = ParsedFilename(
        artist="Claude Monet",
        title="Water Lilies",
        year="1919",
        series="from the series Zen",
        raw_stem="ignored",
    )
    assert (
        canonical_artist_first(parsed)
        == "Claude Monet; Water Lilies; 1919; from the series Zen"
    )


def test_canonical_artist_first_falls_back_to_raw_stem(reset_corpus):
    parsed = ParsedFilename(raw_stem="unparseable blob")
    assert canonical_artist_first(parsed) == "unparseable blob"
