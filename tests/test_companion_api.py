"""Smoke tests for the Companion API."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def test_store_loads_without_crashing():
    # Importable even when fastapi isn't installed locally yet.
    from fine_art_archive.api import store

    rows = store.load_manifest()
    assert isinstance(rows, list)


def test_store_list_works_pagination():
    from fine_art_archive.api import store

    r = store.list_works(limit=5, offset=0)
    assert r["limit"] == 5
    assert r["offset"] == 0
    assert "works" in r and "total" in r
    assert len(r["works"]) <= 5


def test_store_search_filters_results():
    from fine_art_archive.api import store

    all_r = store.list_works(limit=1000)
    if all_r["total"] == 0:
        return
    # Pick a real artist from the manifest and verify the filter shrinks it
    sample = all_r["works"][0]
    a_name = sample.get("artist_name")
    if not a_name:
        return
    r = store.list_works(artist=a_name, limit=1000)
    assert r["total"] >= 1
    assert r["total"] <= all_r["total"]
