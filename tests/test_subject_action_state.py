"""The reviewer tagging state machine, and the audit trail beside it.

`/works/{id}/subject_action` is how a human corrects the tagger. Every call writes two things —
the sidecar and an append-only event — and the two must agree, because the event log is the record
of who decided what. If the sidecar is written and the event is lost, a reviewer's decision exists
with no provenance; that is why the handler restores the original sidecar when the append fails,
and that restoration was untested.

The state transitions were untested too. They look repetitive but are not interchangeable:
`confirm`, `reject` and `add` all record a reviewer, while `reset` REMOVES one — returning a tag to
the machine's proposal. Getting that backwards would leave a reviewer's name on a decision they
withdrew.
"""

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
def archive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    works = tmp_path / "works"
    monkeypatch.setattr(api_store, "WORKS", works)
    monkeypatch.setattr(api_main, "ART_WORKS_ROOT", works)
    monkeypatch.setattr(api_main, "SUBJECT_TAG_EVENTS", tmp_path / "subject_tag_events.jsonl")
    return tmp_path


def _sidecar(root: Path, work_id: str = "w1", payload: dict | None = None) -> Path:
    path = root / "works" / work_id / "meta.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload or {"work_id": work_id, "subject": {}}), encoding="utf-8")
    return path


def _tags(path: Path) -> list[dict]:
    return json.loads(path.read_text())["subject"]["content_tags"]


def _post(client: TestClient, work_id: str, **body) -> object:
    payload = {"reviewer": "tim"}
    payload.update(body)
    return client.post(f"/works/{work_id}/subject_action", json=payload)


# ---------------------------------------------------------------------------------------------
# Refusals.
# ---------------------------------------------------------------------------------------------


def test_an_unknown_action_is_refused_and_quoted_back(client, archive: Path):
    """The action set is a closed vocabulary. An unrecognised one falling through would write an
    event for a decision the sidecar never recorded."""
    _sidecar(archive)

    response = _post(client, "w1", action="maybe", tag="people:portrait")

    assert response.status_code == 400
    assert "maybe" in response.json()["detail"]


@pytest.mark.parametrize("action", ["confirm", "reject", "add", "reset"])
@pytest.mark.parametrize("tag", [None, "", "portrait", "nocolon"])
def test_a_tag_action_without_a_qualified_tag_is_refused(client, archive: Path, action, tag):
    """`group:id` is the tag format. An unqualified tag would create an entry no group filter can
    find, which reads as the tag having been dropped."""
    _sidecar(archive)

    response = _post(client, "w1", action=action, **({"tag": tag} if tag is not None else {}))

    assert response.status_code == 400
    assert "group:id" in response.json()["detail"]


def test_a_freetext_review_needs_no_tag(client, archive: Path):
    """The one action that is about the work rather than a tag."""
    path = _sidecar(archive)

    response = _post(client, "w1", action="freetext_review", text="Looks like a later copy.")

    assert response.status_code == 200
    notes = json.loads(path.read_text())["subject"]["reviewer_notes"]
    assert notes[-1]["text"] == "Looks like a later copy."
    assert notes[-1]["reviewer"] == "tim"


def test_an_action_on_a_work_with_no_sidecar_is_a_404(client, archive: Path):
    """Writing one would fabricate a work. The sidecar is the record that the work exists."""
    response = _post(client, "ghost", action="confirm", tag="people:portrait")

    assert response.status_code == 404
    assert "ghost" in response.json()["detail"]


# ---------------------------------------------------------------------------------------------
# The transitions.
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "action,state", [("confirm", "confirmed"), ("reject", "rejected"), ("add", "added")]
)
def test_acting_on_an_untagged_work_records_the_reviewers_decision(
    client, archive: Path, action, state
):
    path = _sidecar(archive)

    assert _post(client, "w1", action=action, tag="people:portrait").status_code == 200

    tag = _tags(path)[0]
    assert tag["id"] == "people:portrait"
    assert tag["state"] == state
    assert tag["source"] == "reviewer"
    assert tag["reviewer"] == "tim"


@pytest.mark.parametrize(
    "action,state", [("confirm", "confirmed"), ("reject", "rejected"), ("add", "added")]
)
def test_acting_on_a_proposed_tag_updates_it_in_place(client, archive: Path, action, state):
    """One entry per tag. Appending a second would leave the machine's proposal and the
    reviewer's verdict both present, and every consumer would have to guess which wins."""
    path = _sidecar(
        archive,
        payload={
            "work_id": "w1",
            "subject": {
                "content_tags": [{"id": "people:portrait", "state": "proposed", "source": "model"}]
            },
        },
    )

    assert _post(client, "w1", action=action, tag="people:portrait").status_code == 200

    tags = _tags(path)
    assert len(tags) == 1
    assert tags[0]["state"] == state
    assert tags[0]["reviewer"] == "tim"


def test_reset_returns_a_tag_to_the_machines_proposal(client, archive: Path):
    """And REMOVES the reviewer. A withdrawn decision that keeps its reviewer's name attributes
    an opinion to someone who no longer holds it."""
    path = _sidecar(archive)
    _post(client, "w1", action="confirm", tag="people:portrait")

    assert _post(client, "w1", action="reset", tag="people:portrait").status_code == 200

    tag = _tags(path)[0]
    assert tag["state"] == "proposed"
    assert "reviewer" not in tag


def test_resetting_a_tag_that_was_never_recorded_changes_nothing(client, archive: Path):
    """There is nothing to return to a proposal. Creating one would invent a machine proposal that
    the tagger never made."""
    path = _sidecar(archive)

    response = _post(client, "w1", action="reset", tag="people:portrait")

    assert response.status_code == 200
    assert _tags(path) == []


def test_needs_review_tracks_whether_any_proposal_is_outstanding(client, archive: Path):
    """The flag the review queue reads. Left stale, a work either hides from the queue with work
    outstanding or sits in it forever with none."""
    path = _sidecar(
        archive,
        payload={
            "work_id": "w1",
            "subject": {
                "content_tags": [
                    {"id": "people:portrait", "state": "proposed", "source": "model"},
                    {"id": "scene:interior", "state": "proposed", "source": "model"},
                ]
            },
        },
    )

    _post(client, "w1", action="confirm", tag="people:portrait")
    assert json.loads(path.read_text())["subject"]["needs_review"] is True

    _post(client, "w1", action="reject", tag="scene:interior")
    assert json.loads(path.read_text())["subject"]["needs_review"] is False

    _post(client, "w1", action="reset", tag="people:portrait")
    assert json.loads(path.read_text())["subject"]["needs_review"] is True


def test_a_first_decision_creates_the_subject_block_with_a_reviewer_method(client, archive: Path):
    """A work the tagger never saw still has to record HOW it was tagged, or the provenance reads
    as a model output."""
    path = _sidecar(archive, payload={"work_id": "w1"})

    assert _post(client, "w1", action="add", tag="people:portrait").status_code == 200

    subject = json.loads(path.read_text())["subject"]
    assert subject["tag_method_version"] == "reviewer"
    assert subject["genre"] == "unknown"


# ---------------------------------------------------------------------------------------------
# The audit trail, and what happens when it cannot be written.
# ---------------------------------------------------------------------------------------------


def test_every_decision_appends_one_event(client, archive: Path):
    _sidecar(archive)
    _post(client, "w1", action="confirm", tag="people:portrait")
    _post(client, "w1", action="reject", tag="scene:interior")

    lines = [
        json.loads(line)
        for line in api_main.SUBJECT_TAG_EVENTS.read_text().splitlines()
        if line.strip()
    ]

    assert [event["action"] for event in lines] == ["confirm", "reject"]
    assert [event["tag"] for event in lines] == ["people:portrait", "scene:interior"]
    assert {event["reviewer"] for event in lines} == {"tim"}


def test_the_response_echoes_the_recorded_event(client, archive: Path):
    """The caller's confirmation that the decision landed, and with what timestamp."""
    _sidecar(archive)

    body = _post(client, "w1", action="confirm", tag="people:portrait").json()

    assert body["ok"] is True
    assert body["event"]["action"] == "confirm"
    assert body["event"]["tag"] == "people:portrait"
    assert body["event"]["work_id"] == "w1"
    assert body["event"]["ts"]


def test_a_failed_event_append_rolls_the_sidecar_back(client, archive: Path, monkeypatch):
    """The property the two writes exist to keep together.

    The sidecar is written first and the event appended second. If the append fails and the
    sidecar is left changed, a reviewer's decision exists with no record of who made it — the
    audit trail silently under-reports, which is worse than losing the decision outright because
    nothing signals the loss.
    """
    path = _sidecar(
        archive,
        payload={
            "work_id": "w1",
            "subject": {
                "content_tags": [{"id": "people:portrait", "state": "proposed", "source": "model"}]
            },
        },
    )
    before = json.loads(path.read_text())

    def refuse(event):
        raise OSError("event log is read-only")

    monkeypatch.setattr(api_main, "_append_subject_tag_event", refuse)

    with pytest.raises(OSError):
        _post(client, "w1", action="confirm", tag="people:portrait")

    # Compared as DATA, not bytes: the restore round-trips through the atomic writer, which
    # re-serialises with indentation. Content is the property; formatting is not.
    assert json.loads(path.read_text()) == before


def test_a_failed_freetext_append_rolls_back_too(client, archive: Path, monkeypatch):
    """The other write path through the same handler — reviewer notes rather than tags."""
    path = _sidecar(archive)
    before = json.loads(path.read_text())

    monkeypatch.setattr(
        api_main,
        "_append_subject_tag_event",
        lambda event: (_ for _ in ()).throw(OSError("event log is read-only")),
    )

    with pytest.raises(OSError):
        _post(client, "w1", action="freetext_review", text="a note")

    assert json.loads(path.read_text()) == before
    assert "reviewer_notes" not in json.loads(path.read_text()).get("subject", {})
