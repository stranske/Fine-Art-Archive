"""The review surface that grant G55's standing authority is conditional on.

G55 (2026-08-09) lets Track A promote up to 200 works a month with nobody in
the loop. Tim approved that on one condition: he must be able to see what was
acquired and record that he has looked at it.

Two properties are what make the standing grant safe, and both are tested here:

  * **It cannot silently omit a work.** Membership is decided by the first
    history event's timestamp, never by matching acquisition `op` names. `op`
    is free-form and has already drifted in this archive, so an op-name filter
    would quietly skip anything a future writer spelled differently — and a
    review surface that reads "nothing to see" when it means "we did not look"
    is worse than none at all.

  * **It is a view, not a queue.** Nothing about being unreviewed blocks,
    expires, or accumulates, so an unread list has no consequence.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fine_art_archive.api import main, store

EPOCH = "2026-08-09"


def _sidecar(work_id: str, *, title: str, artist: str, history: list[dict]) -> dict:
    return {
        "work_id": work_id,
        "schema_version": "1.0",
        "artist": {"name": artist},
        "title": title,
        "files": {
            "master": {
                "filename": "master.jpg",
                "sha256": "a" * 64,
                "size_bytes": 1234,
                "ingested_at": "2026-08-09T00:00:00+00:00",
            }
        },
        "history": history,
    }


@pytest.fixture
def staged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    staging = tmp_path / "staging_sidecars"
    staging.mkdir()

    works = {
        # Hand-driven era: before the epoch, must never appear.
        "aaa1111-an-old-hand-driven-work": [
            {"ts": "2026-05-01T00:00:00+00:00", "actor": "claude", "op": "phase3-bulk-move"}
        ],
        # Autonomous era, not yet reviewed.
        "bbb2222-a-new-automated-work": [
            {"ts": "2026-08-09T05:21:01+00:00", "actor": "claude", "op": "batch-acquire-v3"}
        ],
        # Autonomous era, acquired by a writer using an op nobody has seen.
        # This is the drift case; it must still appear.
        "ccc3333-acquired-by-a-future-writer": [
            {"ts": "2026-08-10T09:00:00+00:00", "actor": "claude", "op": "some-future-op-v9"}
        ],
        # Autonomous era, already reviewed.
        "ddd4444-already-reviewed": [
            {"ts": "2026-08-09T06:00:00+00:00", "actor": "claude", "op": "batch-acquire-v3"},
            {
                "ts": "2026-08-09T07:00:00+00:00",
                "actor": "tim",
                "op": store.OWNER_REVIEW_OP,
                "notes": "looks right",
            },
        ],
    }
    for wid, history in works.items():
        d = staging / wid
        d.mkdir()
        (d / "meta.json").write_text(
            json.dumps(
                _sidecar(wid, title=wid.split("-", 1)[1], artist="A Painter", history=history)
            ),
            encoding="utf-8",
        )

    monkeypatch.setattr(store, "STAGING", staging)
    monkeypatch.setattr(store, "AUTOMATION_EPOCH", EPOCH)
    monkeypatch.setattr(main, "ACQUISITION_REVIEW_EVENTS", tmp_path / "events.jsonl")
    store.invalidate_acquisitions_cache()
    yield TestClient(main.app)
    store.invalidate_acquisitions_cache()


class TestTheListCannotSilentlyOmitAWork:
    def test_a_novel_acquisition_op_still_appears(self, staged: TestClient) -> None:
        """The property the whole design turns on.

        `ccc3333` was acquired with `some-future-op-v9`, an op string no code
        in this repo knows about. An op-name filter would drop it silently.
        """
        ids = {w["work_id"] for w in staged.get("/acquisitions").json()["works"]}
        assert "ccc3333-acquired-by-a-future-writer" in ids

    def test_pre_epoch_work_is_excluded(self, staged: TestClient) -> None:
        ids = {w["work_id"] for w in staged.get("/acquisitions").json()["works"]}
        assert "aaa1111-an-old-hand-driven-work" not in ids

    def test_counts_are_reported_before_filtering(self, staged: TestClient) -> None:
        body = staged.get("/acquisitions?reviewed=yes").json()
        assert body["total"] == 3
        assert body["unreviewed"] == 2
        assert body["returned"] == 1

    def test_newest_first(self, staged: TestClient) -> None:
        got = [w["acquired_at"] for w in staged.get("/acquisitions").json()["works"]]
        assert got == sorted(got, reverse=True)


class TestFiltering:
    def test_unreviewed_only(self, staged: TestClient) -> None:
        ids = {w["work_id"] for w in staged.get("/acquisitions?reviewed=no").json()["works"]}
        assert ids == {
            "bbb2222-a-new-automated-work",
            "ccc3333-acquired-by-a-future-writer",
        }

    def test_reviewed_only_carries_who_and_when(self, staged: TestClient) -> None:
        (row,) = staged.get("/acquisitions?reviewed=yes").json()["works"]
        assert row["work_id"] == "ddd4444-already-reviewed"
        assert row["reviewed_by"] == "tim"
        assert row["review_note"] == "looks right"

    @pytest.mark.parametrize("bad", ["maybe", "true", ""])
    def test_unknown_filter_is_refused(self, staged: TestClient, bad: str) -> None:
        assert staged.get(f"/acquisitions?reviewed={bad}").status_code == 400


class TestRecordingAReview:
    def test_marking_reviewed_moves_it_out_of_the_unreviewed_list(self, staged: TestClient) -> None:
        wid = "bbb2222-a-new-automated-work"
        assert staged.post(f"/works/{wid}/acquisition_review", json={}).status_code == 200
        ids = {w["work_id"] for w in staged.get("/acquisitions?reviewed=no").json()["works"]}
        assert wid not in ids

    def test_the_review_is_written_into_history(self, staged: TestClient) -> None:
        wid = "bbb2222-a-new-automated-work"
        staged.post(f"/works/{wid}/acquisition_review", json={"note": "nice impression"})
        row = next(w for w in staged.get("/acquisitions").json()["works"] if w["work_id"] == wid)
        assert row["reviewed"] is True
        assert row["review_note"] == "nice impression"

    def test_the_acquisition_event_survives_the_review(self, staged: TestClient) -> None:
        """Review appends; it must never overwrite how the work got here."""
        wid = "bbb2222-a-new-automated-work"
        staged.post(f"/works/{wid}/acquisition_review", json={})
        row = next(w for w in staged.get("/acquisitions").json()["works"] if w["work_id"] == wid)
        assert row["acquired_at"] == "2026-08-09T05:21:01+00:00"

    def test_reviewing_twice_is_refused_rather_than_duplicated(self, staged: TestClient) -> None:
        wid = "bbb2222-a-new-automated-work"
        staged.post(f"/works/{wid}/acquisition_review", json={})
        assert staged.post(f"/works/{wid}/acquisition_review", json={}).status_code == 409

    def test_undo_returns_it_to_the_unreviewed_list(self, staged: TestClient) -> None:
        wid = "ddd4444-already-reviewed"
        assert (
            staged.post(f"/works/{wid}/acquisition_review", json={"undo": True}).status_code == 200
        )
        ids = {w["work_id"] for w in staged.get("/acquisitions?reviewed=no").json()["works"]}
        assert wid in ids

    def test_undo_on_an_unreviewed_work_is_refused(self, staged: TestClient) -> None:
        assert (
            staged.post(
                "/works/bbb2222-a-new-automated-work/acquisition_review",
                json={"undo": True},
            ).status_code
            == 409
        )

    def test_unknown_work_is_404_not_a_silent_success(self, staged: TestClient) -> None:
        assert (
            staged.post("/works/eee5555-does-not-exist/acquisition_review", json={}).status_code
            == 404
        )

    def test_an_audit_event_is_appended(self, staged: TestClient, tmp_path: Path) -> None:
        staged.post("/works/bbb2222-a-new-automated-work/acquisition_review", json={})
        lines = (tmp_path / "events.jsonl").read_text(encoding="utf-8").strip().splitlines()
        assert json.loads(lines[-1])["action"] == "reviewed"
