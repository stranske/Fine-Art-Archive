from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from fine_art_archive.api import store


@pytest.fixture
def isolated_store_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[tuple[Path, Path]]:
    manifest_csv = tmp_path / "manifest.csv"
    ratings_log = tmp_path / "ratings_log.jsonl"
    monkeypatch.setattr(store, "MANIFEST_CSV", manifest_csv)
    monkeypatch.setattr(store, "RATINGS_LOG", ratings_log)
    store.invalidate_manifest_cache()
    store.invalidate_ratings_cache()
    yield manifest_csv, ratings_log
    store.invalidate_manifest_cache()
    store.invalidate_ratings_cache()


def test_ratings_cache_reloads_after_out_of_band_append(
    isolated_store_paths: tuple[Path, Path],
) -> None:
    _manifest_csv, ratings_log = isolated_store_paths
    ratings_log.write_text(
        json.dumps({"work_id": "work-1", "rating": 4, "ts": "2026-01-01T00:00:00Z"}) + "\n"
    )

    assert store.count_ratings() == 1

    with ratings_log.open("a") as handle:
        handle.write(
            json.dumps({"work_id": "work-2", "rating": 5, "ts": "2026-01-01T00:01:00Z"}) + "\n"
        )

    assert store.count_ratings() == 2


def test_per_work_rating_cache_reloads_after_out_of_band_append(
    isolated_store_paths: tuple[Path, Path],
) -> None:
    _manifest_csv, ratings_log = isolated_store_paths
    ratings_log.write_text(
        json.dumps({"work_id": "work-1", "rating": 4, "ts": "2026-01-01T00:00:00Z"}) + "\n"
    )

    latest = store.latest_rating("work-1")
    assert latest is not None
    assert latest["rating"] == 4
    assert store.count_ratings_for("work-1") == 1
    assert len(store.list_ratings_for("work-1")) == 1

    with ratings_log.open("a") as handle:
        handle.write(
            json.dumps({"work_id": "work-1", "rating": 5, "ts": "2026-01-01T00:01:00Z"}) + "\n"
        )

    latest = store.latest_rating("work-1")
    assert latest is not None
    assert latest["rating"] == 5
    assert store.count_ratings_for("work-1") == 2
    assert [event["rating"] for event in store.list_ratings_for("work-1")] == [4, 5]


def test_manifest_cache_reloads_after_out_of_band_append(
    isolated_store_paths: tuple[Path, Path],
) -> None:
    manifest_csv, _ratings_log = isolated_store_paths
    manifest_csv.write_text("work_id,title,artist_name\nwork-1,First,Artist One\n")

    assert [row["work_id"] for row in store.load_manifest()] == ["work-1"]

    with manifest_csv.open("a") as handle:
        handle.write("work-2,Second,Artist Two\n")

    assert [row["work_id"] for row in store.load_manifest()] == ["work-1", "work-2"]


def test_manifest_load_handles_file_deleted_after_signature(
    isolated_store_paths: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest_csv, _ratings_log = isolated_store_paths
    manifest_csv.write_text("work_id,title,artist_name\nwork-1,First,Artist One\n")

    monkeypatch.setattr(store, "_file_signature", lambda _path: (1, 1))
    manifest_csv.unlink()

    assert store.load_manifest() == []


def test_ratings_load_handles_file_deleted_after_signature(
    isolated_store_paths: tuple[Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    _manifest_csv, ratings_log = isolated_store_paths
    ratings_log.write_text(
        json.dumps({"work_id": "work-1", "rating": 4, "ts": "2026-01-01T00:00:00Z"}) + "\n"
    )

    monkeypatch.setattr(store, "_file_signature", lambda _path: (1, 1))
    ratings_log.unlink()

    assert store.count_ratings() == 0
    assert store.latest_rating("work-1") is None
