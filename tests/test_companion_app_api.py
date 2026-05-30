"""Companion API smoke tests (issue #5).

These tests call the FastAPI route handlers directly instead of going through
an HTTP transport. This keeps them deterministic in CI while still asserting
the endpoint contracts on an empty archive.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from fastapi.responses import FileResponse

from fine_art_archive.api import main


def test_healthz() -> None:
    body = main.healthz()
    assert body["ok"] is True


def test_root_serves_focus_ui() -> None:
    response = main.root()
    assert isinstance(response, FileResponse)
    assert str(response.path).endswith("src/fine_art_archive/ui/index.html")


def test_works_list_empty_shape() -> None:
    body = main.list_works(limit=50, offset=0)
    assert {"total", "offset", "limit", "works"}.issubset(body)
    assert body["works"] == []


def test_missing_work_404() -> None:
    with pytest.raises(HTTPException, match="no sidecar for nonexistent-wid"):
        main.get_work("nonexistent-wid")


def test_artists_list() -> None:
    assert isinstance(main.list_artists(limit=100), list)


def test_queues() -> None:
    assert "queues" in main.list_queues()


def test_rating_taxonomy() -> None:
    assert "groups" in main.rating_taxonomy()


def test_ratings_summary_empty() -> None:
    assert main.ratings_summary()["n_events"] == 0
