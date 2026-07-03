"""FastAPI Companion App service smoke tests (issue #5).

Stands the API up in-process via Starlette's TestClient and confirms the core
read endpoints respond on an empty archive: the data/ratings paths return
empty-but-valid shapes, `/` serves the Focus-mode UI, and image/metadata lookups
404 cleanly when a work is absent. Complements tests/test_companion_api.py,
which exercises the data-store layer directly.
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

import pytest
from fastapi.exceptions import RequestValidationError
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
    assert "unpkg.com" not in r.text
    assert 'src="/ui/vendor/htmx-1.9.10.min.js"' in r.text


def test_vendored_htmx_is_served(client: TestClient) -> None:
    r = client.get("/ui/vendor/htmx-1.9.10.min.js")
    assert r.status_code == 200
    assert "javascript" in r.headers["content-type"]
    assert b"htmx" in r.content[:200]


def test_works_list_empty_shape(client: TestClient) -> None:
    r = client.get("/works")
    assert r.status_code == 200
    body = r.json()
    assert {"total", "offset", "limit", "works"}.issubset(body)
    assert body["works"] == []


def test_missing_work_404(client: TestClient) -> None:
    assert client.get("/works/nonexistent-wid").status_code == 404


def test_manifest_work_without_sidecar_returns_handled_placeholder(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_csv = tmp_path / "manifest.csv"
    staging = tmp_path / "staging_sidecars"
    manifest_csv.write_text(
        "work_id,title,artist_name,artist_wikidata_q,year,medium\n"
        "manifest-only,Manifest Work,Known Artist,Q123,1888,oil\n"
    )
    monkeypatch.setattr(api_store, "MANIFEST_CSV", manifest_csv)
    monkeypatch.setattr(api_store, "STAGING", staging)
    api_store.invalidate_manifest_cache()

    response = client.get("/works/manifest-only")

    api_store.invalidate_manifest_cache()
    assert response.status_code == 200
    body = response.json()
    assert body["work_id"] == "manifest-only"
    assert body["title"] == "Manifest Work"
    assert body["_sidecar_status"] == "missing"
    assert "not staged yet" in body["_sidecar_message"]


def test_artists_list(client: TestClient) -> None:
    r = client.get("/artists")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_queues(client: TestClient) -> None:
    r = client.get("/queues")
    assert r.status_code == 200
    assert "queues" in r.json()


@pytest.mark.parametrize(
    ("file_bytes", "expected_error"),
    [
        (b"{bad", "invalid_queue_json"),
        (b"[]", "invalid_queue_shape"),
        (b"\xff", "invalid_queue_file"),
    ],
)
def test_invalid_queue_returns_partial_list_handled_detail_and_health_signal(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    file_bytes: bytes,
    expected_error: str,
) -> None:
    queues_dir = tmp_path / "queues"
    queues_dir.mkdir()
    (queues_dir / "valid.json").write_text(
        json.dumps({"name": "Valid", "description": "ok", "work_ids": ["w1"]})
    )
    (queues_dir / "bad.json").write_bytes(file_bytes)
    monkeypatch.setattr(api_main, "QUEUES_DIR", queues_dir)

    queue_list = client.get("/queues")
    queue_detail = client.get("/queues/bad")
    health = client.get("/healthz")

    assert queue_list.status_code == 200
    assert queue_detail.status_code == 422
    list_body = queue_list.json()
    assert list_body["queues"] == [{"name": "Valid", "description": "ok", "n_works": 1}]
    assert list_body["queues_invalid_count"] == 1
    assert list_body["invalid_queues"][0]["error"] == expected_error
    assert queue_detail.json()["detail"]["error"] == expected_error
    assert queue_detail.json()["detail"]["file"] == "bad.json"
    assert health.status_code == 200
    assert health.json()["ok"] is False
    assert health.json()["queues_invalid_count"] == 1


def test_queue_invalid_count_cache_reloads_when_files_change(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    queues_dir = tmp_path / "queues"
    queues_dir.mkdir()
    (queues_dir / "bad.json").write_bytes(b"\xff")
    monkeypatch.setattr(api_main, "QUEUES_DIR", queues_dir)

    first_health = client.get("/healthz")
    (queues_dir / "bad.json").write_text(
        json.dumps({"name": "Fixed", "description": "", "work_ids": []})
    )
    second_health = client.get("/healthz")

    assert first_health.status_code == 200
    assert first_health.json()["ok"] is False
    assert first_health.json()["queues_invalid_count"] == 1
    assert second_health.status_code == 200
    assert second_health.json()["ok"] is True
    assert second_health.json()["queues_invalid_count"] == 0


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


def test_rating_history_detail_section_is_visible_by_default(client: TestClient) -> None:
    r = client.get("/")
    assert r.status_code == 200
    assert re.search(r'<details\b(?=[^>]*\bid="rs-history")(?=[^>]*\bopen\b)[^>]*>', r.text)
    assert re.search(r'<div\b(?=[^>]*\bid="rating-history")(?=[^>]*\bclass="sub")[^>]*>', r.text)


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
    assert not hasattr(api_main, "RATINGS_LOG")
    persisted = json.loads(isolated_ratings_log.read_text().strip())
    assert persisted["quality"] == 8
    assert persisted["fit"] == 6


def test_append_rating_rejects_non_finite_json(
    isolated_ratings_log,
) -> None:
    with pytest.raises(ValueError):
        api_store.append_rating(
            {
                "work_id": "test-wid",
                "quality": 8,
                "dwell_seconds": float("nan"),
                "surface": "companion-app",
            }
        )

    assert not isolated_ratings_log.exists()


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


@pytest.mark.parametrize(
    "payload",
    [
        {"quality": 5, "surface": "companion-app", "dwell_seconds": -1},
        {"quality": 0, "fit": 5, "surface": "companion-app"},
        {"quality": 11, "fit": 5, "surface": "companion-app"},
        {"quality": 5, "fit": 0, "surface": "companion-app"},
        {"quality": 5, "fit": 11, "surface": "companion-app"},
        {"quality": "5", "fit": 5, "surface": "companion-app"},
        {"quality": 5, "fit": "5", "surface": "companion-app"},
    ],
)
def test_rate_work_rejects_invalid_rating_numbers(
    client: TestClient,
    isolated_ratings_log,
    stub_work: None,
    payload: dict,
) -> None:
    r = client.post("/works/test-wid/rate", json=payload)

    assert r.status_code == 422
    assert not isolated_ratings_log.exists()


@pytest.mark.parametrize("non_finite_literal", ["NaN", "Infinity"])
def test_rate_work_rejects_non_finite_dwell_seconds(
    client: TestClient,
    isolated_ratings_log,
    stub_work: None,
    non_finite_literal: str,
) -> None:
    r = client.post(
        "/works/test-wid/rate",
        content=(
            '{"quality": 5, "surface": "companion-app", ' f'"dwell_seconds": {non_finite_literal}}}'
        ),
        headers={"content-type": "application/json"},
    )

    assert r.status_code == 422
    assert not isolated_ratings_log.exists()


def test_validation_errors_with_validator_context_remain_json_serializable() -> None:
    response = asyncio.run(
        api_main.validation_exception_handler(
            None,
            RequestValidationError(
                [
                    {
                        "type": "value_error",
                        "loc": ("body", "rating"),
                        "msg": "Value error, boom",
                        "input": 5,
                        "ctx": {"error": ValueError("boom")},
                    }
                ]
            ),
        )
    )

    body = json.loads(response.body)
    assert response.status_code == 422
    assert body["detail"][0]["ctx"]["error"] == "boom"


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


def test_debug_log_rejects_oversized_event_without_append(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    debug_log = tmp_path / "ui_debug.log"
    debug_log.write_text("existing\n", encoding="utf-8")
    monkeypatch.setattr(api_main, "DEBUG_LOG", debug_log)
    monkeypatch.setattr(api_main, "DEBUG_LOG_MAX_EVENT_BYTES", 64)

    response = client.post(
        "/debug/log",
        json={"where": "companion", "info": {"message": "x" * 200}},
    )

    assert response.status_code == 413
    assert "bytes > 64 bytes" in response.json()["detail"]
    assert debug_log.read_text(encoding="utf-8") == "existing\n"


def test_debug_log_rejects_oversized_request_before_parsing(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    debug_log = tmp_path / "ui_debug.log"
    debug_log.write_text("existing\n", encoding="utf-8")
    monkeypatch.setattr(api_main, "DEBUG_LOG", debug_log)
    monkeypatch.setattr(api_main, "DEBUG_LOG_MAX_REQUEST_BYTES", 32)

    response = client.post(
        "/debug/log",
        content=b'{"where":"companion","info":{"message":"' + (b"x" * 128) + b'"}}',
        headers={"content-type": "application/json"},
    )

    assert response.status_code == 413
    assert "request exceeds size limit" in response.json()["detail"]
    assert debug_log.read_text(encoding="utf-8") == "existing\n"


def test_debug_log_rotates_before_log_grows_unbounded(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    debug_log = tmp_path / "ui_debug.log"
    debug_log.write_text("old line\n", encoding="utf-8")
    monkeypatch.setattr(api_main, "DEBUG_LOG", debug_log)
    monkeypatch.setattr(api_main, "DEBUG_LOG_MAX_BYTES", debug_log.stat().st_size + 20)
    monkeypatch.setattr(api_main, "DEBUG_LOG_MAX_EVENT_BYTES", 1024)

    response = client.post(
        "/debug/log",
        json={"where": "companion", "info": {"message": "new line"}},
    )

    rotated = debug_log.with_suffix(".log.1")
    assert response.status_code == 200
    assert rotated.read_text(encoding="utf-8") == "old line\n"
    current = debug_log.read_text(encoding="utf-8")
    assert '"where": "companion"' in current
    assert '"message": "new line"' in current


def test_variant_upgrade_decision_rejects_unknown_work_without_append(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidates_csv = tmp_path / "variant_upgrade_candidates.csv"
    decisions_log = tmp_path / "variant_upgrade_decisions.jsonl"
    candidates_csv.write_text(
        "existing_wid,candidate_wid,score\n" "known-work,candidate-work,0.91\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(api_main, "VARIANT_UPGRADE_CSV", candidates_csv)
    monkeypatch.setattr(api_main, "VARIANT_UPGRADE_DECISIONS", decisions_log)

    def missing_work(_work_id: str) -> None:
        api_store.validate_work_id(_work_id)
        return None

    monkeypatch.setattr(api_store, "get_manifest_row", missing_work)
    monkeypatch.setattr(api_store, "get_work", missing_work)

    missing = client.post(
        "/variant_upgrades/not-a-real-work/decision",
        json={"decision": "reject", "note": "typo"},
    )
    malformed = client.post(
        "/variant_upgrades/not a real work/decision",
        json={"decision": "reject", "note": "bad path"},
    )
    valid = client.post(
        "/variant_upgrades/known-work/decision",
        json={"decision": "accept", "note": "promote"},
    )

    assert missing.status_code == 404
    assert malformed.status_code == 400
    assert valid.status_code == 200
    lines = decisions_log.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert '"existing_wid": "known-work"' in lines[0]
    assert "not-a-real-work" not in lines[0]
    assert "not a real work" not in lines[0]
