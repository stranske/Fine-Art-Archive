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


def test_rate_missing_work_404(client: TestClient, isolated_ratings_log) -> None:
    r = client.post(
        "/works/no-such-wid/rate",
        json={"quality": 5, "fit": 4, "surface": "companion-app"},
    )

    assert r.status_code == 404
