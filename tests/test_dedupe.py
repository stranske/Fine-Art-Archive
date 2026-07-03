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
    _normalize,
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
