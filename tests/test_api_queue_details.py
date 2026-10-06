"""Queue detail HTTP contracts: ordering, readable works, and current rating badges."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fine_art_archive.api import main as api_main
from fine_art_archive.api import store


@pytest.fixture
def queue_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    works = tmp_path / "works"
    queues = tmp_path / "queues"
    works.mkdir()
    queues.mkdir()
    monkeypatch.setattr(store, "WORKS", works)
    monkeypatch.setattr(store, "RATINGS_LOG", tmp_path / "ratings.jsonl")
    monkeypatch.setattr(api_main, "QUEUES_DIR", queues)
    store.invalidate_ratings_cache()
    try:
        with TestClient(api_main.app) as client:
            yield client, works, queues
    finally:
        store.invalidate_ratings_cache()


def _write_work(works: Path, wid: str, **fields) -> None:
    directory = works / wid
    directory.mkdir()
    (directory / "meta.json").write_text(json.dumps(fields), encoding="utf-8")


def test_file_queue_preserves_work_order_and_skips_missing(queue_env) -> None:
    client, works, queues = queue_env
    _write_work(
        works,
        "z-first",
        title="First work",
        artist={"name": "Known artist", "wikidata_q": "Q123"},
        year=1643,
        files={"variants": [{"role": "detail"}, {"role": "crop"}]},
    )
    _write_work(works, "a-last", title="Last work", artist=None, files=None)
    (queues / "curated.json").write_text(
        json.dumps(
            {
                "name": "Curated display name",
                "description": "Deliberate viewing order",
                "work_ids": ["z-first", "missing-work", "a-last"],
            }
        ),
        encoding="utf-8",
    )

    response = client.get("/queues/curated")

    assert response.status_code == 200
    assert response.json() == {
        "name": "Curated display name",
        "key": "curated",
        "description": "Deliberate viewing order",
        "total": 2,
        "works": [
            {
                "work_id": "z-first",
                "title": "First work",
                "artist_name": "Known artist",
                "artist_wikidata_q": "Q123",
                "year": 1643,
                "n_variants": 2,
                "_last_rating": None,
                "_last_quality": None,
                "_last_fit": None,
                "_n_ratings": 0,
            },
            {
                "work_id": "a-last",
                "title": "Last work",
                "artist_name": "",
                "artist_wikidata_q": "",
                "year": "",
                "n_variants": 0,
                "_last_rating": None,
                "_last_quality": None,
                "_last_fit": None,
                "_n_ratings": 0,
            },
        ],
    }


@pytest.mark.parametrize(
    ("latest", "expected"),
    [
        ({"rating": 4}, {"_last_rating": 4, "_last_quality": None, "_last_fit": None}),
        ({"quality": 5, "fit": 2}, {"_last_rating": None, "_last_quality": 5, "_last_fit": 2}),
    ],
    ids=["legacy", "two-axis"],
)
def test_queue_badges_use_latest_event_and_count_all_ratings(queue_env, latest, expected) -> None:
    client, works, queues = queue_env
    _write_work(works, "rated", title="Rated work")
    (queues / "rated.json").write_text('{"work_ids": ["rated"]}', encoding="utf-8")
    # File order differs from timestamp order; the API must expose the latest event.
    store.append_rating({"work_id": "rated", "ts": "2026-10-02", **latest})
    store.append_rating({"work_id": "rated", "ts": "2026-10-01", "rating": 1})
    store.append_rating({"work_id": "other", "ts": "2026-10-03", "rating": 3})

    response = client.get("/queues/rated")

    assert response.status_code == 200
    row = response.json()["works"][0]
    assert {key: row[key] for key in expected} == expected
    assert row["_n_ratings"] == 2


def test_dynamic_queue_uses_current_acquisitions_instead_of_same_named_file(
    queue_env, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, works, queues = queue_env
    for wid in ("rated-old", "unrated", "new-arrival"):
        _write_work(works, wid, title=wid)
    (queues / "autonomous-acquisitions.json").write_text(
        '{"name": "Stale file", "work_ids": ["rated-old"]}', encoding="utf-8"
    )
    rows = [
        {"work_id": "rated-old", "acquired_at": "2026-10-01"},
        {"work_id": "unrated", "acquired_at": "2026-10-02"},
    ]
    monkeypatch.setattr(store, "acquisitions_since_epoch", lambda: rows)
    store.append_rating({"work_id": "rated-old", "ts": "2026-10-02", "rating": 4})

    first = client.get("/queues/autonomous-acquisitions")
    rows.append({"work_id": "new-arrival", "acquired_at": "2026-10-03"})
    second = client.get("/queues/autonomous-acquisitions")

    assert first.status_code == second.status_code == 200
    assert [row["work_id"] for row in first.json()["works"]] == ["unrated", "rated-old"]
    body = second.json()
    assert body["key"] == "autonomous-acquisitions"
    assert body["name"] == "Everything the growth automation acquired on its own"
    assert body["total"] == 3
    assert [row["work_id"] for row in body["works"]] == ["new-arrival", "unrated", "rated-old"]


def test_empty_queue_uses_filename_and_default_description(queue_env) -> None:
    client, _, queues = queue_env
    (queues / "empty.json").write_text("{}", encoding="utf-8")

    response = client.get("/queues/empty")

    assert response.status_code == 200
    assert response.json() == {
        "name": "empty",
        "key": "empty",
        "description": "",
        "total": 0,
        "works": [],
    }


def test_unknown_queue_returns_not_found(queue_env) -> None:
    client, _, _ = queue_env

    response = client.get("/queues/unknown")

    assert response.status_code == 404
    assert response.json() == {"detail": "no queue named 'unknown'"}
