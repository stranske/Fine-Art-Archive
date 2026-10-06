"""Research-request log recovery must preserve active requests and reject failed writes."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fine_art_archive.api import main as api_main

NOW = datetime(2026, 10, 6, 12, tzinfo=UTC)


@pytest.fixture
def research_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW

    monkeypatch.setattr(api_main, "datetime", FrozenDatetime)
    monkeypatch.setattr(
        api_main, "_get_work_checked", lambda wid: {"work_id": wid, "title": "Étude", "dossier": {}}
    )
    log = tmp_path / "research_requests.jsonl"
    monkeypatch.setattr(api_main, "RESEARCH_REQUESTS", log)
    return log


def _record(work_id: str, when: datetime, note: str) -> dict:
    return {"work_id": work_id, "ts": when.isoformat(), "note": note}


@pytest.mark.parametrize(
    "bad_line",
    ["{", "{}", '{"ts":"bad-date"}', "null", "[]", "[1]", "12", "true", '"text"'],
    ids=[
        "invalid-json",
        "missing-date",
        "invalid-date",
        "null",
        "empty-array",
        "array",
        "number",
        "boolean",
        "string",
    ],
)
def test_malformed_record_does_not_block_read_or_destroy_active_requests(
    research_log: Path, bad_line: str
) -> None:
    keep = _record("w1", NOW - timedelta(days=1), "préserver")
    other = _record("w2", NOW, "another work")
    expired = _record("w1", NOW - timedelta(days=api_main.RESEARCH_REQUEST_TTL_DAYS + 1), "old")
    research_log.write_text(
        json.dumps(keep)
        + "\n"
        + bad_line
        + "\n"
        + json.dumps(expired)
        + "\n"
        + json.dumps(other)
        + "\n",
        encoding="utf-8",
    )

    with TestClient(api_main.app) as client:
        response = client.get("/works/w1/research")
        assert response.status_code == 200
        assert response.json()["requested"] is True
        response = client.post(
            "/works/w1/research_request", json={"note": "étudier", "focus": "colour"}
        )

    assert response.status_code == 200
    records = [json.loads(line) for line in research_log.read_text(encoding="utf-8").splitlines()]
    assert records[:2] == [keep, other]
    assert len(records) == 3
    assert records[-1] == response.json()["request"]
    assert records[-1]["note"] == "étudier"
    assert records[-1]["focus"] == "colour"
    assert records[-1]["title"] == "Étude"
    assert response.json()["expires_days"] == api_main.RESEARCH_REQUEST_TTL_DAYS


def test_cutoff_is_inclusive_and_latest_request_is_specific_to_work(research_log: Path) -> None:
    cutoff = NOW - timedelta(days=api_main.RESEARCH_REQUEST_TTL_DAYS)
    expired = _record("w1", cutoff - timedelta(microseconds=1), "expired")
    boundary = _record("w1", cutoff, "boundary")
    newest = _record("w1", NOW, "latest")
    other = _record("w2", NOW, "other")
    research_log.write_text(
        "".join(json.dumps(record) + "\n" for record in [expired, boundary, newest, other]),
        encoding="utf-8",
    )

    assert api_main._active_research_requests(cutoff.timestamp()) == [boundary, newest, other]
    assert api_main._open_research_request("w1") == newest
    assert api_main._open_research_request("w2") == other
    assert api_main._open_research_request("absent") is None


@pytest.mark.parametrize("operation", ["write_text", "replace"])
def test_failed_compaction_returns_retryable_error_and_preserves_log(
    research_log: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    keep = _record("w1", NOW, "keep this request")
    original = (json.dumps(keep) + "\n").encode("utf-8")
    research_log.write_bytes(original)
    original_operation = getattr(Path, operation)

    def fail_compaction(path: Path, *args, **kwargs):
        if path.parent == research_log.parent and path.suffix == ".tmp":
            raise OSError(5, "Input/output error")
        return original_operation(path, *args, **kwargs)

    monkeypatch.setattr(Path, operation, fail_compaction)
    with TestClient(api_main.app) as client:
        response = client.post("/works/w1/research_request", json={"note": "must not land"})
        assert research_log.read_bytes() == original
        assert response.status_code == 503
        assert response.json()["detail"] == {
            "error": "research_request_storage",
            "message": "Input/output error",
        }
        assert client.get("/works/w1/research").json()["requested"] is True
    assert research_log.read_bytes() == original
