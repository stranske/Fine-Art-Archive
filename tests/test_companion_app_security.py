"""Security tests for URL-supplied Companion App work IDs."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fine_art_archive.api import main as api_main
from fine_art_archive.api import store as api_store
from fine_art_archive.api.main import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def isolated_archive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    staging = tmp_path / "staging_sidecars"
    art_root = tmp_path / "works"
    monkeypatch.setattr(api_store, "STAGING", staging)
    monkeypatch.setattr(api_main, "ART_WORKS_ROOT", art_root)
    monkeypatch.setattr(api_main, "SUBJECT_TAG_EVENTS", tmp_path / "subject_tag_events.jsonl")
    return tmp_path


def write_sidecar(root: Path, work_id: str, payload: dict | None = None) -> Path:
    sidecar = root / "staging_sidecars" / work_id / "meta.json"
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    sidecar.write_text(json.dumps(payload or {"work_id": work_id, "subject": {}}))
    return sidecar


@pytest.mark.parametrize(
    ("method", "path", "json_body"),
    [
        ("get", "/works/%2E%2E", None),
        ("get", "/works/%2E%2E%5Cmeta", None),
        ("get", "/works/vermeer%00little", None),
        ("get", "/works/%2E%2E/image", None),
        ("get", "/works/%2E%2E/full", None),
        ("get", "/works/%2E%2E/ratings", None),
        ("post", "/works/%2E%2E/rate", {"quality": 5, "surface": "companion-app"}),
        ("post", "/works/%2E%2E/subject_action", {"action": "freetext_review", "text": "x"}),
    ],
)
def test_rejects_traversing_work_ids_with_400(
    client: TestClient,
    isolated_archive: Path,
    method: str,
    path: str,
    json_body: dict | None,
) -> None:
    if json_body is None:
        response = getattr(client, method)(path)
    else:
        response = getattr(client, method)(path, json=json_body)

    assert response.status_code == 400


def test_subject_action_traversal_does_not_write_outside_staging(
    client: TestClient,
    isolated_archive: Path,
) -> None:
    outside_meta = isolated_archive / "meta.json"
    outside_meta.write_text(json.dumps({"work_id": "outside", "subject": {"reviewer_notes": []}}))

    response = client.post(
        "/works/%2E%2E/subject_action",
        json={"action": "freetext_review", "text": "should not write"},
    )

    assert response.status_code == 400
    assert json.loads(outside_meta.read_text()) == {
        "work_id": "outside",
        "subject": {"reviewer_notes": []},
    }


def test_legitimate_work_id_still_resolves(
    client: TestClient,
    isolated_archive: Path,
) -> None:
    write_sidecar(isolated_archive, "vermeer-little-street", {"work_id": "vermeer-little-street"})

    response = client.get("/works/vermeer-little-street")

    assert response.status_code == 200
    assert response.json()["work_id"] == "vermeer-little-street"
