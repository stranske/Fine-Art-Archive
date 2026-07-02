"""Security tests for URL-supplied Companion App work IDs."""

from __future__ import annotations

import json
import stat
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
        ("get", "/works/..%2Fmeta", None),
        ("get", "/works/%2E%2E%5Cmeta", None),
        ("get", "/works/vermeer%00little", None),
        ("get", "/works/%2E%2E/image", None),
        ("get", "/works/..%2Fimage", None),
        ("get", "/works/%2E%2E/full", None),
        ("get", "/works/..%2Ffull", None),
        ("get", "/works/%2E%2E/ratings", None),
        ("get", "/works/..%2Fratings", None),
        ("post", "/works/%2E%2E/rate", {"quality": 5, "surface": "companion-app"}),
        ("post", "/works/..%2Frate", {"quality": 5, "surface": "companion-app"}),
        ("post", "/works/%2E%2E/subject_action", {"action": "freetext_review", "text": "x"}),
        ("post", "/works/..%2Fsubject_action", {"action": "freetext_review", "text": "x"}),
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


def test_invalid_subject_action_does_not_append_success_audit(
    client: TestClient,
    isolated_archive: Path,
) -> None:
    write_sidecar(isolated_archive, "vermeer-little-street", {"work_id": "vermeer-little-street"})

    response = client.post(
        "/works/vermeer-little-street/subject_action",
        json={"action": "confirm", "tag": "invalid-tag"},
    )

    assert response.status_code == 400
    assert not (isolated_archive / "subject_tag_events.jsonl").exists()


def test_subject_action_preserves_sidecar_when_atomic_replace_fails(
    isolated_archive: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = TestClient(app, raise_server_exceptions=False)
    original = {"work_id": "vermeer-little-street", "subject": {"content_tags": []}}
    sidecar = write_sidecar(isolated_archive, "vermeer-little-street", original)

    def fail_replace(_src: Path, _dst: Path) -> None:
        raise OSError("simulated replace failure")

    monkeypatch.setattr(api_main.os, "replace", fail_replace)
    response = client.post(
        "/works/vermeer-little-street/subject_action",
        json={"action": "add", "tag": "genre:landscape"},
    )

    assert response.status_code == 500
    assert json.loads(sidecar.read_text()) == original
    assert not (isolated_archive / "subject_tag_events.jsonl").exists()


def test_subject_action_preserves_existing_sidecar_mode(
    client: TestClient,
    isolated_archive: Path,
) -> None:
    sidecar = write_sidecar(
        isolated_archive,
        "vermeer-little-street",
        {"work_id": "vermeer-little-street", "subject": {"content_tags": []}},
    )
    sidecar.chmod(0o640)

    response = client.post(
        "/works/vermeer-little-street/subject_action",
        json={"action": "add", "tag": "genre:landscape"},
    )

    assert response.status_code == 200
    assert stat.S_IMODE(sidecar.stat().st_mode) == 0o640


def test_subject_action_rolls_back_sidecar_when_audit_append_fails(
    isolated_archive: Path,
) -> None:
    client = TestClient(app, raise_server_exceptions=False)
    original = {"work_id": "vermeer-little-street", "subject": {"content_tags": []}}
    sidecar = write_sidecar(isolated_archive, "vermeer-little-street", original)
    (isolated_archive / "subject_tag_events.jsonl").mkdir()

    response = client.post(
        "/works/vermeer-little-street/subject_action",
        json={"action": "add", "tag": "genre:landscape"},
    )

    assert response.status_code == 500
    assert json.loads(sidecar.read_text()) == original


def test_master_filename_cannot_escape_work_directory(
    client: TestClient,
    isolated_archive: Path,
) -> None:
    outside_dir = isolated_archive / "works" / "other"
    outside_dir.mkdir(parents=True)
    outside_master = outside_dir / "master.jpg"
    outside_master.write_bytes(b"not really an image")
    write_sidecar(
        isolated_archive,
        "vermeer-little-street",
        {
            "work_id": "vermeer-little-street",
            "files": {"master": {"filename": "../other/master.jpg"}},
        },
    )

    response = client.get("/works/vermeer-little-street/full")

    assert response.status_code == 400


def test_symlinked_master_cannot_escape_work_directory(
    client: TestClient,
    isolated_archive: Path,
) -> None:
    outside_dir = isolated_archive / "works" / "other"
    outside_dir.mkdir(parents=True)
    outside_master = outside_dir / "master.jpg"
    outside_master.write_bytes(b"not really an image")

    work_dir = isolated_archive / "works" / "vermeer-little-street"
    work_dir.mkdir(parents=True)
    (work_dir / "master.jpg").symlink_to(outside_master)
    write_sidecar(
        isolated_archive,
        "vermeer-little-street",
        {"work_id": "vermeer-little-street"},
    )

    response = client.get("/works/vermeer-little-street/full")

    assert response.status_code == 400


def test_unknown_nested_work_path_returns_404(
    client: TestClient,
    isolated_archive: Path,
) -> None:
    response = client.get("/works/vermeer-little-street/typo")

    assert response.status_code == 404


def test_legitimate_work_id_still_resolves(
    client: TestClient,
    isolated_archive: Path,
) -> None:
    write_sidecar(isolated_archive, "vermeer-little-street", {"work_id": "vermeer-little-street"})

    response = client.get("/works/vermeer-little-street")

    assert response.status_code == 200
    assert response.json()["work_id"] == "vermeer-little-street"
