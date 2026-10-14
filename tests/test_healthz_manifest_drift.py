"""`/healthz` must not report ok:true while the operator UI is blind.

Audit finding 37 (2026-08-08). `manifest.csv` is the Companion App's only
navigation path, and until 2026-09-01 nothing regenerated it when a work was
promoted. On 2026-08-05 that left 18 promoted works servable and renderable but
unfindable — browse showed 3393 against 3411 on disk — while `/healthz` reported
`ok: true` throughout, because `ok` only ever considered ratings and queues.

That absence is *why* the gap went unnoticed, so the regression these tests
guard is "health is silent about drift", not "drift exists".
`scripts/build_manifest.py` is now the producer that clears the drift; see
`tests/test_build_manifest.py`.
"""

from __future__ import annotations

import csv
import json
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fine_art_archive.api import main as api_main
from fine_art_archive.api import store as api_store
from fine_art_archive.api.main import app


@pytest.fixture
def archive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Real archive files with independently controlled manifest and directory IDs."""
    works = tmp_path / "works"
    works.mkdir()
    manifest = tmp_path / "manifest.csv"

    def build(sidecars: int, manifest_rows: int, *, manifest_ids: list[str] | None = None) -> None:
        for i in range(sidecars):
            (works / f"wid-{i:03d}").mkdir(exist_ok=True)
        with open(manifest, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=["work_id", "title"])
            writer.writeheader()
            ids = (
                manifest_ids
                if manifest_ids is not None
                else [f"wid-{i:03d}" for i in range(manifest_rows)]
            )
            for i, work_id in enumerate(ids):
                writer.writerow({"work_id": work_id, "title": f"Work {i}"})

    monkeypatch.setattr(api_store, "WORKS", works)
    monkeypatch.setattr(api_store, "MANIFEST_CSV", manifest)
    monkeypatch.setattr(api_main, "ART_WORKS_ROOT", works)
    monkeypatch.setattr(api_store, "RATINGS_LOG", tmp_path / "ratings.jsonl")
    monkeypatch.setattr(api_main, "QUEUES_DIR", tmp_path / "queues")
    api_store.invalidate_manifest_cache()
    api_store.invalidate_ratings_cache()
    yield build
    api_store.invalidate_manifest_cache()
    api_store.invalidate_ratings_cache()


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

    Nothing in this repository wrote ``manifest.csv`` until 2026-09-01, so this
    is the state a fresh deployment against a real works tree started in — not a
    hypothetical. It is still the state a deployment reaches whenever the works
    tree grows and nobody reruns the generator.
    """
    archive(sidecars=3411, manifest_rows=0)
    body = client.get("/healthz").json()
    assert body["manifest_loaded"] == 0
    assert body["sidecar_works"] == 3411
    assert body["manifest_drift"] == -3411
    assert body["ok"] is False, "an empty manifest over a populated tree is total navigation loss"


def test_drift_arrives_with_the_command_that_clears_it(archive, client: TestClient) -> None:
    """A gate that cannot say what would clear it is defective, however accurate.

    ``manifest_drift`` sat at a correct, unexplained negative number for weeks
    while the file had no producer at all. The number alone cannot distinguish
    "behind" from "unfixable", so health names the producer beside it.
    """
    archive(sidecars=11, manifest_rows=8)
    drifted = client.get("/healthz").json()
    assert drifted["ok"] is False
    assert drifted["manifest_remedy"] == api_main.MANIFEST_REBUILD_COMMAND

    # Absolute, and pointing at a generator that exists. More than one checkout
    # of this repo lives on a machine, each with its own manifest.csv beside it,
    # and the app is often served from a different one than the operator has
    # open; a relative command would rebuild a file the running app never reads.
    interpreter, script = drifted["manifest_remedy"].split(" ", 1)
    assert Path(interpreter).is_absolute() and Path(interpreter).exists()
    assert Path(script).is_absolute() and Path(script).is_file()

    archive(sidecars=11, manifest_rows=11)
    healthy = client.get("/healthz").json()
    assert healthy["ok"] is True
    assert healthy["manifest_remedy"] is None, "a healthy manifest needs no remedy"


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


def test_same_count_different_ids_is_unhealthy(archive, client: TestClient) -> None:
    archive(sidecars=3, manifest_rows=3, manifest_ids=["wid-000", "retired-work", "wid-002"])
    response = client.get("/healthz")
    assert response.status_code == 200
    body = response.json()
    assert body["manifest_drift"] == 0
    assert body["ok"] is False
    assert body["manifest_missing"] == ["wid-001"]
    assert body["manifest_extra"] == ["retired-work"]
    assert body["manifest_missing_count"] == body["manifest_extra_count"] == 1
    assert body["manifest_remedy"] == api_main.MANIFEST_REBUILD_COMMAND


def test_manifest_id_differences_are_sorted_and_bounded(archive, client: TestClient) -> None:
    archive(
        sidecars=73, manifest_rows=73, manifest_ids=[f"stale-{i:03d}" for i in reversed(range(73))]
    )
    body = client.get("/healthz").json()
    assert body["ok"] is False
    assert body["manifest_drift"] == 0
    assert body["manifest_missing_count"] == body["manifest_extra_count"] == 73
    assert body["manifest_missing"] == [f"wid-{i:03d}" for i in range(50)]
    assert body["manifest_extra"] == [f"stale-{i:03d}" for i in range(50)]


def test_real_manifest_rebuild_clears_same_count_drift(archive, client: TestClient) -> None:
    archive(sidecars=3, manifest_rows=3, manifest_ids=["wid-000", "retired-work", "wid-002"])
    for work in api_store.WORKS.iterdir():
        (work / "meta.json").write_text(json.dumps({"work_id": work.name, "title": work.name}))
    assert client.get("/healthz").json()["ok"] is False
    result = subprocess.run(
        [
            sys.executable,
            "scripts/build_manifest.py",
            "--works-root",
            str(api_store.WORKS),
            "--out",
            str(api_store.MANIFEST_CSV),
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    # Exercise the real loader's cache invalidation after an atomic same-size rewrite.
    body = client.get("/healthz").json()
    assert body["ok"] is True
    assert body["manifest_drift"] == 0
    assert body["manifest_missing"] == body["manifest_extra"] == []
    assert body["manifest_missing_count"] == body["manifest_extra_count"] == 0
    assert body["manifest_remedy"] is None


def test_missing_tree_keeps_id_comparison_unknown(archive, client: TestClient, monkeypatch) -> None:
    archive(sidecars=0, manifest_rows=2)
    monkeypatch.setattr(api_store, "WORKS", api_store.WORKS / "absent")
    body = client.get("/healthz").json()
    assert body["ok"] is False
    assert body["manifest_missing"] is body["manifest_extra"] is None
    assert body["manifest_missing_count"] is body["manifest_extra_count"] is None
    assert body["sidecar_works"] is body["manifest_drift"] is None


def test_regular_files_do_not_count_as_work_ids(archive, client: TestClient) -> None:
    archive(sidecars=2, manifest_rows=2)
    (api_store.WORKS / "readme.txt").write_text("not a work directory")
    body = client.get("/healthz").json()
    assert body["ok"] is True
    assert body["manifest_missing"] == body["manifest_extra"] == []
