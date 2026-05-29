"""Tests for fine_art_archive.collect.dedupe.

Covers the scenarios that actually mattered in practice:
  - the Caillebotte "Paris Street; Rainy Day" near-miss
  - exact title+artist match (the trivial path)
  - surname-only match (Vermeer + The Milkmaid)
  - diacritic / case insensitivity (Renoir é vs e, "Pierre-Auguste" vs "pierre auguste")
  - non-duplicate: novel work returns no match
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fine_art_archive.collect.dedupe import (  # noqa: E402
    _dim_compat,
    _normalize,
    _parse_dimensions,
    _surname,
    _title_similarity,
    check_inventory,
)


def _write_inv(path: Path, rows: list[dict]) -> None:
    fields = [
        "rel_path",
        "subfolder",
        "basename",
        "size_bytes",
        "mtime_iso",
        "number",
        "title",
        "artist",
        "year",
        "year_min",
        "year_max",
        "medium",
        "dimensions",
        "raw_stem",
        "parse_strategy",
    ]
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fields})


# --- Helpers -----------------------------------------------------------------


def test_normalize_strips_diacritics_and_punctuation() -> None:
    assert _normalize("Pierre-Auguste Renoir") == "pierre auguste renoir"
    assert _normalize("Café de l'Europe") == "cafe de l europe"
    assert _normalize("  multiple   spaces  ") == "multiple spaces"


def test_surname_takes_last_token() -> None:
    assert _surname("Vincent van Gogh") == "gogh"
    assert _surname("Pierre-Auguste Renoir") == "renoir"
    # Too-short last token gets discarded (false-positive guard)
    assert _surname("Bob de") == ""


def test_title_similarity_handles_subset() -> None:
    """Containment catches the Caillebotte "Paris Street; Rainy Day" case
    where the inventory entry's title is a subset of the candidate."""
    # candidate has the full title; inventory has only "Paris Street"
    sim = _title_similarity("Paris Street; Rainy Day", "Paris Street")
    assert sim >= 0.90, f"expected ≥0.90 (subset containment), got {sim:.2f}"


def test_title_similarity_avoids_single_token_over_match() -> None:
    """Single-word candidate shouldn't get a free pass against a longer title."""
    sim = _title_similarity("Composition", "Composition VIII")
    # Jaccard 0.5, containment requires min_n >= 2 → falls back to Jaccard
    assert sim < 0.90


# --- Match tests --------------------------------------------------------------


def test_caillebotte_paris_street_rainy_day(tmp_path: Path) -> None:
    """The real failure that motivated this module: the inventory entry
    has 'Rainy Day' misplaced into the year slot by the old parser,
    so titles only partially overlap. The dedupe must still flag it."""
    inv = tmp_path / "inv.csv"
    _write_inv(
        inv,
        [
            {
                "rel_path": "Landscape TV/Paris Street; Gustave Caillebotte; "
                "Rainy Day; 1877; Oil on canvas; 212.2 × 276.2 cm.jpeg",
                "title": "Paris Street",
                "artist": "Gustave Caillebotte",
                "size_bytes": "84796647",
            },
        ],
    )
    r = check_inventory("Paris Street; Rainy Day", "Gustave Caillebotte", inv)
    assert r.has_strong_match, f"expected strong match, got {r.matches}"
    assert r.best.confidence >= 0.90
    assert r.best.tier == "exact-artist+near-title"


def test_exact_title_artist_match(tmp_path: Path) -> None:
    inv = tmp_path / "inv.csv"
    _write_inv(
        inv,
        [
            {
                "rel_path": "Portrait/Self-Portrait; ...jpeg",
                "title": "Self-Portrait",
                "artist": "Pierre-Auguste Renoir",
                "size_bytes": "2400000",
            },
        ],
    )
    r = check_inventory("Self-Portrait", "Pierre-Auguste Renoir", inv)
    assert r.has_strong_match
    assert r.best.tier == "exact-title-artist"
    assert r.best.confidence >= 0.98


def test_surname_only_match(tmp_path: Path) -> None:
    inv = tmp_path / "inv.csv"
    _write_inv(
        inv,
        [
            {
                "rel_path": "Portrait/The Milkmaid; Johannes Vermeer; ...jpeg",
                "title": "The Milkmaid",
                "artist": "Johannes Vermeer",
                "size_bytes": "17400000",
            },
        ],
    )
    # candidate uses only the surname
    r = check_inventory("The Milkmaid", "Vermeer", inv)
    assert r.has_strong_match
    # surname match + exact title → exact-artist+near-title via surname
    assert r.best.tier == "exact-artist+near-title"


def test_diacritic_insensitivity(tmp_path: Path) -> None:
    inv = tmp_path / "inv.csv"
    _write_inv(
        inv,
        [
            {
                "rel_path": "x.jpeg",
                "title": "Le Café",
                "artist": "Édouard Manet",
                "size_bytes": "100",
            },
        ],
    )
    r = check_inventory("Le Cafe", "Edouard Manet", inv)
    assert r.has_strong_match
    assert r.best.tier == "exact-title-artist"


def test_novel_work_returns_no_match(tmp_path: Path) -> None:
    inv = tmp_path / "inv.csv"
    _write_inv(
        inv,
        [
            {
                "rel_path": "x.jpeg",
                "title": "Some Other Work",
                "artist": "Some Other Artist",
                "size_bytes": "100",
            },
        ],
    )
    r = check_inventory("Brand New Title", "Brand New Artist", inv)
    assert not r.matches


def test_empty_candidate_returns_empty(tmp_path: Path) -> None:
    inv = tmp_path / "inv.csv"
    _write_inv(inv, [{"rel_path": "x.jpeg", "title": "T", "artist": "A", "size_bytes": "100"}])
    r = check_inventory("", "", inv)
    assert not r.matches


# --- Dimensions parsing & comparison ----------------------------------------


def test_parse_dimensions_canonical_forms() -> None:
    # The two dominant forms in the inventory
    assert _parse_dimensions("53.5 x 46.3 cm") == (46.3, 53.5)
    assert _parse_dimensions("53.5 × 46.3 cm") == (46.3, 53.5)
    # Units on both numbers
    assert _parse_dimensions("40.5 cm x 32.5 cm") == (32.5, 40.5)
    # European comma decimal
    assert _parse_dimensions("73,5 x 92,3 cm") == (73.5, 92.3)
    # Inches → cm
    h, w = _parse_dimensions("10 x 20 inches")
    assert abs(h - 25.4) < 0.001 and abs(w - 50.8) < 0.001
    # Leading "medium," prefix
    assert _parse_dimensions("oil on canvas, 40.5 cm x 32.5 cm") == (32.5, 40.5)
    # Trailing parenthetical
    assert _parse_dimensions("55.5 cm x 47 cm (1)") == (47.0, 55.5)
    # Unparseable
    assert _parse_dimensions("") is None
    assert _parse_dimensions("oil on canvas") is None
    # Returns sorted ascending so 53x46 == 46x53
    assert _parse_dimensions("46.3 x 53.5 cm") == _parse_dimensions("53.5 x 46.3 cm")


def test_dim_compat_match_within_tolerance() -> None:
    # Identical
    status, _ = _dim_compat("53.5 x 46.3 cm", "53.5 x 46.3 cm")
    assert status == "match"
    # Catalog rounding within 5%
    status, _ = _dim_compat("53.5 x 46.3 cm", "53 x 46 cm")
    assert status == "match"
    # Order-swapped
    status, _ = _dim_compat("53.5 x 46.3 cm", "46.3 x 53.5 cm")
    assert status == "match"


def test_dim_compat_mismatch_outside_tolerance() -> None:
    # Two different Van Gogh self-portraits 1887: 42×34 cardboard vs 19×14 cardboard
    status, diff = _dim_compat("42 x 34 cm", "19 cm x 14.1 cm")
    assert status == "mismatch"
    assert diff is not None and diff > 0.5
    # 60×85 vs 80×100 — different work in a series
    status, _ = _dim_compat("60 x 85 cm", "80 x 100 cm")
    assert status == "mismatch"


def test_dim_compat_absent_when_unparseable() -> None:
    status, _ = _dim_compat("", "53 x 46 cm")
    assert status == "absent"
    status, _ = _dim_compat("oil on canvas", "53 x 46 cm")
    assert status == "absent"
    status, _ = _dim_compat("", "")
    assert status == "absent"


def test_dim_compat_inches_vs_cm_match() -> None:
    """An inches catalog entry should match its cm equivalent."""
    # 21 x 17 inches ≈ 53.34 x 43.18 cm — within 5% of 53 x 46 cm? height yes (1%),
    # width 6.5% off → mismatch by tight tolerance. Confirms the threshold bites.
    status, _ = _dim_compat("21 x 17 inches", "53 x 46 cm")
    assert status == "mismatch"
    # A tighter equivalent should match
    status, _ = _dim_compat("21 x 18 inches", "53.5 x 45.5 cm")
    assert status == "match"
