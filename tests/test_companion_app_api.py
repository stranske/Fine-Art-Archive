"""FastAPI Companion App service smoke tests (issue #5).

Stands the API up in-process via Starlette's TestClient and confirms the core
read endpoints respond on an empty archive: the data/ratings paths return
empty-but-valid shapes, `/` serves the Focus-mode UI, and image/metadata lookups
404 cleanly when a work is absent. Complements tests/test_companion_api.py,
which exercises the data-store layer directly.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fine_art_archive.api import main as api_main
from fine_art_archive.api import store as api_store
from fine_art_archive.api.main import app


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def isolated_ratings_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    ratings_log = tmp_path / "ratings_log.jsonl"
    monkeypatch.setattr(api_main, "RATINGS_LOG", ratings_log)
    monkeypatch.setattr(api_store, "RATINGS_LOG", ratings_log)
    api_store.invalidate_ratings_cache()
    yield ratings_log
    api_store.invalidate_ratings_cache()


@pytest.fixture
def stub_work(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api_store, "get_work", lambda work_id: {"work_id": work_id})


def test_healthz(client: TestClient) -> None:
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_root_serves_focus_ui(client: TestClient) -> None:
    r = client.get("/")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]


def test_works_list_empty_shape(client: TestClient) -> None:
    r = client.get("/works")
    assert r.status_code == 200
    body = r.json()
    assert {"total", "offset", "limit", "works"}.issubset(body)
    assert body["works"] == []


def test_missing_work_404(client: TestClient) -> None:
    assert client.get("/works/nonexistent-wid").status_code == 404


def test_artists_list(client: TestClient) -> None:
    r = client.get("/artists")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_queues(client: TestClient) -> None:
    r = client.get("/queues")
    assert r.status_code == 200
    assert "queues" in r.json()


def test_rating_taxonomy(client: TestClient) -> None:
    r = client.get("/rating_taxonomy")
    assert r.status_code == 200
    assert "groups" in r.json()


def test_ratings_summary_empty(client: TestClient) -> None:
    r = client.get("/ratings/summary")
    assert r.status_code == 200
    assert r.json()["n_events"] == 0
    assert r.json()["corrupt_line_count"] == 0


def test_ratings_summary_includes_two_axis_and_legacy_ratings(
    client: TestClient,
    isolated_ratings_log,
    stub_work: None,
) -> None:
    first = client.post(
        "/works/test-wid/rate",
        json={"quality": 7, "fit": 4, "surface": "companion-app"},
    )
    second = client.post(
        "/works/test-wid/rate",
        json={"quality": 9, "fit": 6, "surface": "companion-app"},
    )
    high_quality = client.post(
        "/works/test-wid/rate",
        json={"quality": 10, "fit": 10, "surface": "companion-app"},
    )
    legacy = client.post(
        "/works/legacy-wid/rate",
        json={"rating": 2, "surface": "companion-app"},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert high_quality.status_code == 200
    assert legacy.status_code == 200

    r = client.get("/ratings/summary")
    assert r.status_code == 200
    body = r.json()
    assert body["n_events"] == 4
    assert body["corrupt_line_count"] == 0
    assert list(body["quality_distribution"]) == ["7", "9", "10"]
    assert body["quality_distribution"] == {"7": 1, "9": 1, "10": 1}
    assert list(body["fit_distribution"]) == ["4", "6", "10"]
    assert body["fit_distribution"] == {"4": 1, "6": 1, "10": 1}
    assert body["rating_distribution"] == {"2": 1}

    by_work = {entry["work_id"]: entry for entry in body["most_rated_works"]}
    assert by_work["test-wid"]["n_ratings"] == 3
    assert by_work["test-wid"]["last_quality"] == 10
    assert by_work["test-wid"]["last_fit"] == 10
    assert by_work["test-wid"]["last_rating"] is None
    assert by_work["legacy-wid"]["last_rating"] == 2


def test_corrupt_ratings_are_counted_and_surface_in_health(
    client: TestClient,
    isolated_ratings_log,
) -> None:
    isolated_ratings_log.write_text(
        '{"work_id": "valid", "quality": 8, "surface": "companion-app"}\n' '{"work_id": "broken",\n'
    )
    api_store.invalidate_ratings_cache()

    summary = client.get("/ratings/summary")
    health = client.get("/healthz")

    assert summary.status_code == 200
    assert summary.json()["n_events"] == 1
    assert summary.json()["corrupt_line_count"] == 1
    assert health.status_code == 200
    assert health.json()["ok"] is False
    assert health.json()["ratings_corrupt_line_count"] == 1


def test_work_ratings_shape(client: TestClient) -> None:
    # Per-work rating history endpoint (surfaced in the detail view).
    r = client.get("/works/any-wid/ratings")
    assert r.status_code == 200
    body = r.json()
    assert body["work_id"] == "any-wid"
    assert body["ratings"] == []


def test_rate_work_write_path(
    client: TestClient,
    isolated_ratings_log,
    stub_work: None,
) -> None:
    r = client.post(
        "/works/test-wid/rate",
        json={
            "quality": 8,
            "fit": 6,
            "surface": "companion-app",
            "selected_reasons": ["affect:somber"],
        },
    )

    assert r.status_code == 200
    event = r.json()["event"]
    assert event["event_kind"] == "rating"
    assert event["quality"] == 8
    assert event["fit"] == 6
    assert event["scheme"] == "two-axis-10"
    assert event["work_id"] == "test-wid"
    assert event["selected_reasons"] == ["affect:somber"]
    assert isolated_ratings_log.read_text().strip()


def test_rate_work_unknown_surface(
    client: TestClient,
    isolated_ratings_log,
    stub_work: None,
) -> None:
    r = client.post(
        "/works/test-wid/rate",
        json={"quality": 5, "surface": "not-a-valid-surface-xyz"},
    )

    assert r.status_code == 400


def test_rate_work_unknown_chip_id(
    client: TestClient,
    isolated_ratings_log,
    stub_work: None,
) -> None:
    r = client.post(
        "/works/test-wid/rate",
        json={
            "quality": 5,
            "surface": "companion-app",
            "selected_reasons": ["not-a-real:chip"],
        },
    )

    assert r.status_code == 400


def test_rate_work_all_none_payload(
    client: TestClient,
    isolated_ratings_log,
    stub_work: None,
) -> None:
    r = client.post(
        "/works/test-wid/rate",
        json={
            "quality": None,
            "fit": None,
            "rating": None,
            "surface": "companion-app",
        },
    )

    assert r.status_code == 400


def test_rate_work_unknown_rating(
    client: TestClient,
    isolated_ratings_log,
    stub_work: None,
) -> None:
    r = client.post(
        "/works/test-wid/rate",
        json={"rating": 99, "surface": "companion-app"},
    )

    assert r.status_code == 400


def test_rate_missing_work_404(
    client: TestClient,
    isolated_ratings_log,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(api_store, "get_work", lambda _work_id: None)
    r = client.post(
        "/works/no-such-wid/rate",
        json={"quality": 5, "fit": 4, "surface": "companion-app"},
    )

    assert r.status_code == 404
