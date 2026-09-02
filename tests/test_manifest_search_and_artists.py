"""Searching the manifest, and folding artist spellings onto one painter.

This is the archive's only navigation surface: `list_works` is what the browse UI calls, and
`list_artists` is the sidebar. A search that silently misses is the worst outcome available here —
the operator concludes the archive does not hold the painting, and there is nothing to distinguish
that from the truth.

The alias fold is the interesting part. `CURATED_ALIASES` is a hand-written table asserting which
spellings are one person, and both the rows and the query go through it: `Pieter Brueghel` and
`Pieter Bruegel the Elder` are Q43270, so searching either finds both. A bare surname resolves to
nothing and still matches nothing, which is what keeps the fold from becoming a fuzzy search.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from fine_art_archive.api import store as api_store


@pytest.fixture
def manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Write a manifest and point the store at it, cache invalidated."""

    def write(*rows: dict) -> Path:
        path = tmp_path / "manifest.csv"
        with open(path, "w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=["work_id", "title", "artist_name"])
            writer.writeheader()
            for row in rows:
                writer.writerow(row)
        monkeypatch.setattr(api_store, "MANIFEST_CSV", path)
        api_store.invalidate_manifest_cache()
        return path

    monkeypatch.setattr(api_store, "RATINGS_LOG", tmp_path / "ratings.jsonl")
    api_store.invalidate_ratings_cache()
    return write


def _row(work_id: str, title: str, artist: str) -> dict:
    return {"work_id": work_id, "title": title, "artist_name": artist}


def _ids(result: dict) -> list[str]:
    return [work["work_id"] for work in result["works"]]


# ---------------------------------------------------------------------------------------------
# Loading.
# ---------------------------------------------------------------------------------------------


def test_an_absent_manifest_reads_as_an_empty_archive(tmp_path, monkeypatch):
    """A fresh checkout has no manifest. That has to be "nothing to browse", not a crash on the
    first page load."""
    monkeypatch.setattr(api_store, "MANIFEST_CSV", tmp_path / "absent.csv")
    api_store.invalidate_manifest_cache()

    assert api_store.load_manifest() == []


def test_the_manifest_is_reread_when_it_changes(manifest):
    """The generator rewrites it whenever a work is promoted. A cache that never notices means a
    newly promoted work stays invisible until the server restarts."""
    path = manifest(_row("w1", "First", "Rembrandt"))
    assert len(api_store.load_manifest()) == 1

    with open(path, "a", encoding="utf-8", newline="") as handle:
        csv.writer(handle).writerow(["w2", "Second", "Rembrandt"])

    assert len(api_store.load_manifest()) == 2


# ---------------------------------------------------------------------------------------------
# Search.
# ---------------------------------------------------------------------------------------------


def test_a_title_substring_matches(manifest):
    manifest(_row("w1", "The Hunters in the Snow", "Pieter Bruegel the Elder"))

    assert _ids(api_store.list_works(q="hunters")) == ["w1"]


def test_search_is_case_insensitive(manifest):
    manifest(_row("w1", "The Hunters in the Snow", "Pieter Bruegel the Elder"))

    assert _ids(api_store.list_works(q="HUNTERS")) == ["w1"]
    assert _ids(api_store.list_works(q="bruegel")) == ["w1"]


def test_an_artist_substring_matches(manifest):
    """Deliberately an artist the curated table does NOT know.

    Every pass in the matcher can match a curated painter, so a test using one proves only that
    *something* matched. `Émile Bernard` resolves to no Q-ID, which leaves the raw-name pass as
    the only thing that can find him.
    """
    manifest(_row("w1", "Breton Women", "Émile Bernard"))

    assert _ids(api_store.list_works(q="bernard")) == ["w1"]


def test_a_curated_artist_is_also_found_by_substring(manifest):
    manifest(_row("w1", "Night Watch", "Rembrandt"))

    assert _ids(api_store.list_works(q="rembrandt")) == ["w1"]


def test_the_canonical_name_matches_even_when_the_row_spells_it_shorter(manifest):
    """The row says `Rembrandt`; the canonical name is `Rembrandt van Rijn`. Searching the full
    name has to find the work, or the sidebar's own label fails as a search term."""
    manifest(_row("w1", "Night Watch", "Rembrandt"))

    assert _ids(api_store.list_works(q="van rijn")) == ["w1"]


def test_an_accented_name_is_found_without_the_accent(manifest):
    """Nobody types `Émile` into a search box.

    Uncurated on purpose: `Dürer` resolves to Q5580, so a search for `durer` would be found by
    the alias fold even with accent folding removed — the test would pass against the defect.
    """
    manifest(_row("w1", "Breton Women", "Émile Bernard"))

    assert _ids(api_store.list_works(q="emile")) == ["w1"]


def test_an_accented_canonical_name_is_findable_when_the_row_lacks_the_accent(manifest):
    """The row is catalogued `Durer`; the canonical name is `Albrecht Dürer`. Typing the accent
    still finds it.

    Two passes can satisfy this — `ql in cname.lower()` and the alias fold — and after the fold
    was added the canonical-name pass became unreachable as a SOLE matcher: removing it fails
    nothing, confirmed by deliberate break. That is recorded rather than worked around, and this
    test pins the BEHAVIOUR (the work is findable) instead of asserting which pass found it.
    """
    manifest(_row("w1", "Self Portrait", "Durer"))

    assert _ids(api_store.list_works(q="dürer")) == ["w1"]


def test_a_curated_accented_name_is_found_either_way(manifest):
    manifest(_row("w1", "Self Portrait", "Albrecht Dürer"))

    assert _ids(api_store.list_works(q="durer")) == ["w1"]


def test_an_accented_query_still_finds_the_work(manifest):
    """The reverse direction: the accent is typed and the stored name has it too."""
    manifest(_row("w1", "Breton Women", "Émile Bernard"))

    assert _ids(api_store.list_works(q="émile")) == ["w1"]


def test_an_accented_query_finds_an_uncurated_unaccented_name(manifest):
    """Fold the query too; this painter has no curated alias to hide a one-sided fold."""
    manifest(_row("w1", "Breton Women", "Emile Bernard"))

    assert _ids(api_store.list_works(q="émile")) == ["w1"]


def test_a_curated_alias_finds_the_works_catalogued_under_another_spelling(manifest):
    """The defect this fold exists for.

    `CURATED_ALIASES` lists `Pieter Brueghel` and `Pieter Bruegel the Elder` under Q43270. The
    works are catalogued under the second; searching the first returned an EMPTY ARCHIVE, because
    no substring of one appears in the other and nothing resolved the query.
    """
    manifest(_row("w1", "The Hunters in the Snow", "Pieter Bruegel the Elder"))

    assert _ids(api_store.list_works(q="pieter brueghel")) == ["w1"]


def test_another_curated_alias_of_the_same_painter_also_finds_it(manifest):
    """`Pieter Bruegel I` shares no useful substring with `the Elder` either."""
    manifest(_row("w1", "The Hunters in the Snow", "Pieter Bruegel the Elder"))

    assert _ids(api_store.list_works(q="pieter bruegel i")) == ["w1"]


def test_the_fold_does_not_merge_two_different_painters(manifest):
    """Pieter the Elder and Pieter the Younger are separate Q-IDs and separate painters. A fold
    that collapsed them would attribute the son's copies to the father."""
    manifest(
        _row("w1", "The Hunters in the Snow", "Pieter Bruegel the Elder"),
        _row("w2", "Winter Landscape", "Jan Brueghel the Elder"),
    )

    assert _ids(api_store.list_works(q="jan brueghel")) == ["w2"]


def test_an_unresolvable_query_still_matches_nothing(manifest):
    """A bare surname resolves to no Q-ID, so the fold contributes nothing and the search stays a
    substring search. This is what keeps it from becoming a fuzzy match."""
    manifest(_row("w1", "Night Watch", "Rembrandt"))

    assert _ids(api_store.list_works(q="vermeer")) == []


def test_a_query_matching_nothing_returns_an_empty_page_not_an_error(manifest):
    manifest(_row("w1", "Night Watch", "Rembrandt"))

    result = api_store.list_works(q="zzzz")

    assert result["total"] == 0
    assert result["works"] == []


def test_surrounding_whitespace_in_a_query_is_ignored(manifest):
    """Uncurated again: a curated name is resolved by the alias fold, which strips internally, so
    a curated painter would be found even if the query were never stripped."""
    manifest(_row("w1", "Breton Women", "Émile Bernard"))

    assert _ids(api_store.list_works(q="  bernard  ")) == ["w1"]


# ---------------------------------------------------------------------------------------------
# The artist filter.
# ---------------------------------------------------------------------------------------------


def test_the_artist_filter_matches_a_raw_spelling(manifest):
    manifest(
        _row("w1", "Night Watch", "Rembrandt"),
        _row("w2", "The Hunters", "Pieter Bruegel the Elder"),
    )

    assert _ids(api_store.list_works(artist="rembrandt")) == ["w1"]


def test_the_artist_filter_accepts_a_wikidata_qid(manifest):
    """The sidebar keys its entries by Q-ID, so clicking one has to filter by it."""
    manifest(
        _row("w1", "Night Watch", "Rembrandt"),
        _row("w2", "The Hunters", "Pieter Bruegel the Elder"),
    )

    assert _ids(api_store.list_works(artist="Q5598")) == ["w1"]


def test_the_artist_filter_accepts_the_canonical_display_name(manifest):
    manifest(_row("w1", "Night Watch", "Rembrandt"))

    assert _ids(api_store.list_works(artist="rembrandt van rijn")) == ["w1"]


def test_an_artist_filter_matching_nobody_returns_nothing(manifest):
    manifest(_row("w1", "Night Watch", "Rembrandt"))

    assert api_store.list_works(artist="Q99999999")["total"] == 0


# ---------------------------------------------------------------------------------------------
# Pagination and the attached rating.
# ---------------------------------------------------------------------------------------------


def test_total_counts_the_matches_not_the_page(manifest):
    """The UI renders "showing 50 of N" from these two. Returning the page length as the total
    tells the operator the archive is 50 works."""
    manifest(*[_row(f"w{i}", f"Work {i}", "Rembrandt") for i in range(10)])

    result = api_store.list_works(limit=3)

    assert result["total"] == 10
    assert len(result["works"]) == 3


def test_the_offset_walks_the_result_set(manifest):
    manifest(*[_row(f"w{i}", f"Work {i}", "Rembrandt") for i in range(5)])

    first = _ids(api_store.list_works(limit=2, offset=0))
    second = _ids(api_store.list_works(limit=2, offset=2))

    assert first == ["w0", "w1"]
    assert second == ["w2", "w3"]
    assert not set(first) & set(second)


def test_an_offset_past_the_end_is_an_empty_page_with_a_real_total(manifest):
    """Scrolling past the last page must not read as an empty archive."""
    manifest(*[_row(f"w{i}", f"Work {i}", "Rembrandt") for i in range(3)])

    result = api_store.list_works(limit=10, offset=99)

    assert result["works"] == []
    assert result["total"] == 3


def test_the_filter_is_applied_before_the_page_is_cut(manifest):
    """Paginating first and filtering after would show a half-empty page and a wrong total."""
    manifest(
        _row("w2", "The Hunters", "Pieter Bruegel the Elder"),
        _row("w1", "Night Watch", "Rembrandt"),
        _row("w3", "Self Portrait", "Rembrandt"),
    )

    result = api_store.list_works(q="rembrandt", limit=1)

    assert result["total"] == 2
    assert _ids(result) == ["w1"]
    assert _ids(api_store.list_works(q="rembrandt", limit=1, offset=1)) == ["w3"]


def test_each_row_carries_its_canonical_identity(manifest):
    """The browse card shows the canonical name; without it every spelling variant looks like a
    different painter."""
    manifest(_row("w1", "Night Watch", "Rembrandt"))

    work = api_store.list_works()["works"][0]

    assert work["_canonical_q"] == "Q5598"
    assert work["_canonical_name"] == "Rembrandt van Rijn"


def test_an_unresolvable_artist_carries_no_canonical_identity(manifest):
    """Most of the archive is not in the curated table. Those rows must still render."""
    manifest(_row("w1", "A Painting", "Someone Uncatalogued"))

    work = api_store.list_works()["works"][0]

    assert work["_canonical_q"] is None
    assert work["_canonical_name"] is None
    assert work["_n_ratings"] == 0


# ---------------------------------------------------------------------------------------------
# The artist sidebar.
# ---------------------------------------------------------------------------------------------


def test_artists_are_grouped_by_canonical_identity(manifest):
    """Three spellings, one painter, one sidebar entry. Listing them separately is the
    duplication this grouping exists to remove."""
    manifest(
        _row("w1", "Night Watch", "Rembrandt"),
        _row("w2", "Self Portrait", "Rembrandt van Rijn"),
        _row("w3", "The Mill", "Rembrandt Harmenszoon van Rijn"),
    )

    artists = api_store.list_artists()

    assert len(artists) == 1
    assert artists[0]["canonical_q"] == "Q5598"
    assert artists[0]["n_works"] == 3


def test_the_merge_count_shows_how_many_spellings_folded(manifest):
    """Stated in the docstring as the point: "so Tim can see the deduplication at a glance".

    Three works under two spellings, so the merge count (2) and the work count (3) cannot be
    confused for one another — with two of each, a test cannot tell which number it is reading.
    """
    manifest(
        _row("w1", "Night Watch", "Rembrandt"),
        _row("w2", "Self Portrait", "Rembrandt van Rijn"),
        _row("w3", "The Mill", "Rembrandt"),
    )

    artists = api_store.list_artists()

    assert artists[0]["n_works"] == 3
    assert artists[0]["n_raw_strings_merged"] == 2
    assert set(artists[0]["raw_examples"]) == {"Rembrandt", "Rembrandt van Rijn"}


def test_an_unresolvable_artist_groups_on_itself(manifest):
    """Not being in the curated table is the common case, and those painters still need a
    sidebar entry."""
    manifest(
        _row("w1", "A Painting", "Someone Uncatalogued"),
        _row("w2", "Another", "Someone Uncatalogued"),
    )

    artists = api_store.list_artists()

    assert len(artists) == 1
    assert artists[0]["canonical_q"] is None
    assert artists[0]["name"] == "Someone Uncatalogued"
    assert artists[0]["n_works"] == 2


def test_two_unresolvable_artists_do_not_merge_with_each_other(manifest):
    """Grouping every unresolved name under one key would collapse the whole uncatalogued tail
    into a single sidebar row."""
    manifest(
        _row("w1", "A Painting", "Painter One"),
        _row("w2", "Another", "Painter Two"),
    )

    assert len(api_store.list_artists()) == 2


def test_artists_are_ordered_by_work_count(manifest):
    """The sidebar is a way in. Ordering by anything else buries the painters the archive
    actually holds."""
    manifest(
        _row("w1", "A", "Rembrandt"),
        _row("w2", "B", "Rembrandt"),
        _row("w3", "C", "Pieter Bruegel the Elder"),
    )

    artists = api_store.list_artists()
    counts = [artist["n_works"] for artist in artists]

    assert counts == [2, 1]
    assert artists[0]["canonical_q"] == "Q5598"


def test_a_blank_artist_is_skipped_rather_than_listed(manifest):
    """An empty cell would otherwise become a nameless sidebar entry nobody can click."""
    manifest(_row("w1", "A Painting", ""), _row("w2", "Another", "Rembrandt"))

    artists = api_store.list_artists()

    assert [artist["name"] for artist in artists] == ["Rembrandt van Rijn"]


def test_the_artist_limit_is_honoured(manifest):
    manifest(*[_row(f"w{i}", f"Work {i}", f"Painter {i}") for i in range(6)])

    assert len(api_store.list_artists(limit=3)) == 3


def test_the_internal_counter_is_not_leaked_to_the_caller(manifest):
    """`_raw_strings` is a `Counter` used to build the summary. Leaving it on the entry puts a
    non-JSON-serialisable object in an API response."""
    manifest(_row("w1", "Night Watch", "Rembrandt"))

    assert "_raw_strings" not in api_store.list_artists()[0]
