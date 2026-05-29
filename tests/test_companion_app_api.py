"""FastAPI Companion App service smoke tests (issue #5).

Stands the API up in-process via Starlette's TestClient and confirms the core
read endpoints respond on an empty archive: the data/ratings paths return
empty-but-valid shapes, `/` serves the Focus-mode UI, and image/metadata lookups
404 cleanly when a work is absent. Complements tests/test_companion_api.py,
which exercises the data-store layer directly.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from fine_art_archive.api.main import app


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(app)


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
