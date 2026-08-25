"""`/healthz` must not report ok:true while the operator UI is blind.

Audit finding 37 (2026-08-08). `manifest.csv` is the Companion App's only
navigation path, and nothing regenerates it when a work is promoted. On
2026-08-05 that left 18 promoted works servable and renderable but unfindable —
browse showed 3393 against 3411 on disk — while `/healthz` reported `ok: true`
throughout, because `ok` only ever considered ratings and queues.

That absence is *why* the gap went unnoticed, so the regression these tests
guard is "health is silent about drift", not "drift exists".
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fine_art_archive.api import main as api_main
from fine_art_archive.api import store as api_store
from fine_art_archive.api.main import app


@pytest.fixture
def archive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A works tree and manifest whose row count the test controls."""
    works = tmp_path / "works"
    works.mkdir()
    manifest = tmp_path / "manifest.csv"

    def build(sidecars: int, manifest_rows: int) -> None:
        for i in range(sidecars):
            (works / f"wid-{i:03d}").mkdir(exist_ok=True)
        with open(manifest, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=["work_id", "title"])
            writer.writeheader()
            for i in range(manifest_rows):
                writer.writerow({"work_id": f"wid-{i:03d}", "title": f"Work {i}"})

    monkeypatch.setattr(api_store, "WORKS", works)
    monkeypatch.setattr(api_store, "MANIFEST_CSV", manifest)
    monkeypatch.setattr(api_main, "ART_WORKS_ROOT", works)
    yield build


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_healthz_reports_manifest_drift(archive, client: TestClient) -> None:
    """The 2026-08-05 shape: manifest one batch behind the sidecar tree."""
    archive(sidecars=11, manifest_rows=8)
    body = client.get("/healthz").json()
    assert body["manifest_loaded"] == 8
    assert body["sidecar_works"] == 11
    assert body["manifest_drift"] == -3
    assert body["ok"] is False, "drift must not report healthy"


def test_healthz_ok_when_manifest_matches(archive, client: TestClient) -> None:
    archive(sidecars=11, manifest_rows=11)
    body = client.get("/healthz").json()
    assert body["manifest_drift"] == 0
    assert body["ok"] is True


def test_healthz_reports_archive_works(archive, client: TestClient) -> None:
    """`archive_works` exposes the on-disk count the UI never showed."""
    archive(sidecars=5, manifest_rows=5)
    assert client.get("/healthz").json()["archive_works"] == 5


def test_absent_manifest_is_not_configured_not_drifted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, client: TestClient
) -> None:
    """A fresh checkout ships a fixture sidecar and no manifest.

    Failing health there would be a false alarm on every dev machine, so an
    empty manifest must not be read as drift.
    """
    works = tmp_path / "works"
    works.mkdir()
    (works / "test-wid").mkdir()
    monkeypatch.setattr(api_store, "WORKS", works)
    monkeypatch.setattr(api_store, "MANIFEST_CSV", tmp_path / "absent.csv")
    monkeypatch.setattr(api_main, "ART_WORKS_ROOT", tmp_path / "works")

    body = client.get("/healthz").json()
    assert body["manifest_loaded"] == 0
    assert body["ok"] is True


def test_empty_manifest_over_populated_archive_is_not_healthy(archive, client: TestClient) -> None:
    """Total navigation loss must not be quieter than partial drift.

    The empty-manifest allowance exists for the fresh checkout above. Applied
    to a populated tree it admitted the *worst* state: 0 manifest rows over
    3411 sidecars reported ``ok: true``, while 1 row over 3411 reported
    ``ok: false``. Health was non-monotonic in the severity of the condition
    it exists to detect, and the total-loss case was the silent one.

    Nothing in this repository writes ``manifest.csv``, so this is the state a
    fresh deployment against a real works tree starts in — not a hypothetical.
    """
    archive(sidecars=3411, manifest_rows=0)
    body = client.get("/healthz").json()
    assert body["manifest_loaded"] == 0
    assert body["sidecar_works"] == 3411
    assert body["manifest_drift"] == -3411
    assert body["ok"] is False, "an empty manifest over a populated tree is total navigation loss"


def test_unreadable_tree_is_unknown_not_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, client: TestClient
) -> None:
    """A missing works tree is 'we do not know', never 'the archive is empty'.

    Reporting 0 there would make drift arithmetic read healthy in exactly the
    case health should fire.
    """
    monkeypatch.setattr(api_store, "WORKS", tmp_path / "does-not-exist")
    monkeypatch.setattr(api_main, "ART_WORKS_ROOT", tmp_path / "also-absent")
    monkeypatch.setattr(api_store, "MANIFEST_CSV", tmp_path / "absent.csv")

    body = client.get("/healthz").json()
    assert body["sidecar_works"] is None
    assert body["archive_works"] is None
    assert body["manifest_drift"] is None
