"""Artist review choices must reach the append log before approval counts change."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fine_art_archive.api import gates
from fine_art_archive.api import main as api_main

NOW = datetime(2026, 10, 6, 12, tzinfo=UTC)


@pytest.fixture
def decision_log(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    class FrozenDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW

    monkeypatch.setattr(api_main, "datetime", FrozenDatetime)
    log = tmp_path / "decisions" / "artist_allowlist.jsonl"
    monkeypatch.setattr(gates, "ARTIST_ALLOWLIST", log)
    log.parent.mkdir()
    log.write_text(
        "".join(
            json.dumps({"artist_qid": qid, "decision": decision, "ts": "2026-10-05T12:00:00+00:00"})
            + "\n"
            for qid, decision in [("Q7", "approve"), ("Q99", "reject")]
        ),
        encoding="utf-8",
    )
    return log


@pytest.mark.parametrize("decision", ["approve", "reject"])
def test_artist_decision_persists_choice_and_reports_current_approvals(
    decision_log: Path, decision: str
) -> None:
    original = decision_log.read_bytes()
    body = {"decision": decision, "artist_name": "Dürer", "note": "étude", "reviewer": "Zoë"}

    with TestClient(api_main.app) as client:
        response = client.post("/review/artists/Q42/decision", json=body)

    assert response.status_code == 200
    assert response.json() == {
        "artist_qid": "Q42",
        "decision": decision,
        "approved_artists": 2 if decision == "approve" else 1,
    }
    updated = decision_log.read_bytes()
    assert updated.startswith(original)
    appended = updated[len(original) :].decode("utf-8").splitlines()
    assert len(appended) == 1
    assert json.loads(appended[0]) == {"artist_qid": "Q42", "ts": NOW.isoformat(), **body}
    assert gates.load_allowlisted_artists() == ({"Q7", "Q42"} if decision == "approve" else {"Q7"})
    assert gates.load_refused_artists() == ({"Q99"} if decision == "approve" else {"Q99", "Q42"})


def test_later_artist_decision_reverses_choice_without_erasing_history(decision_log: Path) -> None:
    original = decision_log.read_bytes()
    with TestClient(api_main.app) as client:
        for decision, approved in [("approve", 2), ("reject", 1), ("approve", 2)]:
            response = client.post("/review/artists/Q42/decision", json={"decision": decision})
            assert response.status_code == 200
            assert response.json()["decision"] == decision
            assert response.json()["approved_artists"] == approved
            assert gates.load_allowlisted_artists() == ({"Q7", "Q42"} if approved == 2 else {"Q7"})
            assert gates.load_refused_artists() == ({"Q99"} if approved == 2 else {"Q99", "Q42"})

    updated = decision_log.read_bytes()
    assert updated.startswith(original)
    records = [json.loads(line) for line in updated[len(original) :].splitlines()]
    assert [record["decision"] for record in records] == ["approve", "reject", "approve"]
    assert all(
        record
        == {
            "artist_qid": "Q42",
            "decision": decision,
            "artist_name": "",
            "note": "",
            "reviewer": "tim",
            "ts": NOW.isoformat(),
        }
        for record, decision in zip(records, ["approve", "reject", "approve"], strict=True)
    )


@pytest.mark.parametrize("qid", ["Q0", "Q01", "q42", "Q1000000000000"])
def test_invalid_artist_qid_is_rejected_before_log_append(decision_log: Path, qid: str) -> None:
    original = decision_log.read_bytes()
    with TestClient(api_main.app) as client:
        response = client.post(f"/review/artists/{qid}/decision", json={"decision": "approve"})

    assert response.status_code == 400
    assert response.json() == {"detail": "artist_qid must look like Q12345"}
    assert decision_log.read_bytes() == original


def test_unsupported_artist_decision_is_rejected_before_log_append(decision_log: Path) -> None:
    original = decision_log.read_bytes()
    with TestClient(api_main.app) as client:
        response = client.post("/review/artists/Q42/decision", json={"decision": "defer"})

    assert response.status_code == 422
    assert any(error["loc"] == ["body", "decision"] for error in response.json()["detail"])
    assert decision_log.read_bytes() == original
