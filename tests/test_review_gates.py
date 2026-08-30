"""The consolidated review surface: every gate, with its drain beside it.

Two properties are what make this surface worth having, and both are pinned here:

  * **A gate always reports what would clear it.** Blocking count and drainable
    count come back in the same response. A gate that reports only what it is
    holding reads as "be patient" indefinitely; one that also reports zero
    drainable is instantly recognisable as stuck.

  * **"Could not measure" is never rendered as zero.** An unreadable frontier
    must produce `drainable: null`, not `drainable: 0` — the first says look
    into it, the second says all clear. Conflating them is exactly how a broken
    check gets mistaken for a healthy one.

Nothing here is a queue. No test asserts that a list is short, or that anyone
has drained it, because nothing in the archive waits on that happening.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fine_art_archive.api import gates


def _cand(
    qid: str,
    artist: str,
    *,
    status: str = "screened",
    gates_pass: bool = True,
    deferrals: int = 0,
    title: str = "Untitled",
) -> dict:
    verdicts = {"fit_for_targets": "pass", "require_public_domain_evidence": "pass"}
    if not gates_pass:
        verdicts["fit_for_targets"] = "unevaluated"
    return {
        "qid": qid,
        "title": title,
        "artist_qid": artist,
        "status": status,
        "transfer_deferrals": deferrals,
        "screen_scores": {"gates": verdicts, "dimensions_px": [4000, 3000]},
    }


@pytest.fixture
def frontier(tmp_path: Path) -> Path:
    p = tmp_path / "frontier.json"
    p.write_text(
        json.dumps(
            {
                "candidates": {
                    # held artist -> not blocked at all
                    "Q1": _cand("Q1", "QHELD"),
                    # new artists, one acquirable the moment it is approved
                    "Q2": _cand("Q2", "QNEW1"),
                    "Q3": _cand("Q3", "QNEW2", gates_pass=False),
                    # already resolved, must not appear
                    "Q4": _cand("Q4", "QNEW3", status="acquired"),
                    "Q5": _cand("Q5", "QNEW4", status="rejected"),
                    # routed to review, and a deferral
                    "Q6": _cand("Q6", "QHELD", status="review"),
                    "Q7": _cand("Q7", "QHELD", deferrals=2),
                }
            }
        ),
        encoding="utf-8",
    )
    return p


def _by_name(found: list[gates.Gate]) -> dict[str, gates.Gate]:
    return {g.name: g for g in found}


def test_new_artist_gate_counts_blocking_and_drainable(frontier: Path) -> None:
    g = _by_name(gates.frontier_gates({"QHELD"}, frontier_path=frontier, allowlist=set()))

    new = g["new_artist"]
    # QNEW1 and QNEW2 are blocked; the acquired and rejected ones are not.
    assert new.blocking == 2
    # Only QNEW1 clears every screening gate, so only it is drainable today.
    assert new.drainable == 1
    assert new.summary()["deadlocked"] is False


def test_unevaluated_gate_is_not_counted_as_drainable(frontier: Path) -> None:
    """A candidate with an `unevaluated` screening gate is not ready to go.

    "We did not check" must never be reported as "it cleared" — least of all on
    the surface a person uses to decide what to let through.
    """
    g = _by_name(gates.frontier_gates({"QHELD"}, frontier_path=frontier, allowlist=set()))
    rows = {r["id"]: r for r in g["new_artist"].items}
    assert rows["Q2"]["would_pass_now"] is True
    assert rows["Q3"]["would_pass_now"] is False


def test_approving_an_artist_removes_them_from_the_gate(frontier: Path) -> None:
    """The allowlist is the drain. Using it must actually shrink the gate."""
    before = _by_name(gates.frontier_gates({"QHELD"}, frontier_path=frontier, allowlist=set()))
    after = _by_name(gates.frontier_gates({"QHELD"}, frontier_path=frontier, allowlist={"QNEW1"}))
    assert before["new_artist"].blocking == 2
    assert after["new_artist"].blocking == 1
    assert after["new_artist"].drainable == 0


def test_unreadable_frontier_reports_unmeasured_not_zero(tmp_path: Path) -> None:
    """The failure that this whole surface exists to make impossible.

    A frontier we cannot read must not produce a clean bill of health. Every
    frontier gate reports `drainable = None`, and the summary flags it, so the
    run that could not look is distinguishable from the run that found nothing.
    """
    missing = tmp_path / "does-not-exist.json"
    found = gates.frontier_gates({"QHELD"}, frontier_path=missing, allowlist=set())

    assert found, "an unreadable frontier must still report its gates"
    for g in found:
        assert g.drainable is gates.UNMEASURED
        summary = g.summary()
        assert summary["drainable_measured"] is False
        # The critical assertion: unmeasured must not read as a drained gate.
        assert summary["deadlocked"] is False
        assert summary["drainable"] is None


def test_corrupt_frontier_is_treated_as_unreadable(tmp_path: Path) -> None:
    bad = tmp_path / "frontier.json"
    bad.write_text("{not json", encoding="utf-8")
    for g in gates.frontier_gates({"Q1"}, frontier_path=bad, allowlist=set()):
        assert g.drainable is gates.UNMEASURED


def test_auto_clearing_gate_is_not_reported_as_deadlocked(frontier: Path) -> None:
    """Deferrals drain on their own, so a zero human-drain is not an alarm."""
    g = _by_name(gates.frontier_gates({"QHELD"}, frontier_path=frontier, allowlist=set()))
    deferred = g["deferred_transfer"]
    assert deferred.blocking == 1
    assert deferred.drainable == 0
    assert deferred.auto_clears is True
    assert deferred.summary()["deadlocked"] is False


def test_allowlist_roundtrip_and_rejection(tmp_path: Path) -> None:
    path = tmp_path / "allowlist.jsonl"
    gates.append_allowlist("Q100", decision="approve", ts="2026-08-29T00:00:00Z", path=path)
    gates.append_allowlist("Q200", decision="approve", ts="2026-08-29T00:01:00Z", path=path)
    assert gates.load_allowlisted_artists(path) == {"Q100", "Q200"}

    # A later rejection wins over the earlier approval.
    gates.append_allowlist("Q100", decision="reject", ts="2026-08-29T00:02:00Z", path=path)
    assert gates.load_allowlisted_artists(path) == {"Q200"}


def test_missing_allowlist_is_empty_not_an_error(tmp_path: Path) -> None:
    assert gates.load_allowlisted_artists(tmp_path / "nope.jsonl") == set()


def test_summary_endpoint_agrees_with_each_gate(monkeypatch, frontier: Path) -> None:
    """The roll-up must be derived from the per-gate verdicts, not recomputed.

    A second copy of the "is this deadlocked" rule inside the endpoint would
    drift from `Gate.summary()` silently, because both copies would go on
    returning plausible numbers. This pins them to one definition.
    """
    from fastapi.testclient import TestClient

    from fine_art_archive.api import main

    monkeypatch.setattr(
        main,
        "_all_gates",
        lambda: gates.frontier_gates({"QHELD"}, frontier_path=frontier, allowlist=set()),
    )
    body = TestClient(main.app).get("/review").json()

    for row in body["gates"]:
        assert (row["name"] in body["deadlocked_gates"]) is row["deadlocked"]
        assert (row["name"] in body["unmeasured_gates"]) is (not row["drainable_measured"])
    assert body["total_blocking"] == sum(r["blocking"] for r in body["gates"])
    assert body["total_drainable"] == sum(
        r["drainable"] for r in body["gates"] if r["drainable_measured"]
    )


def test_self_clearing_gate_never_lands_in_deadlocked_list(monkeypatch, frontier: Path) -> None:
    """A gate that drains on its own must not raise the one real alarm."""
    from fastapi.testclient import TestClient

    from fine_art_archive.api import main

    monkeypatch.setattr(
        main,
        "_all_gates",
        lambda: gates.frontier_gates({"QHELD"}, frontier_path=frontier, allowlist=set()),
    )
    body = TestClient(main.app).get("/review").json()
    assert "deferred_transfer" not in body["deadlocked_gates"]


def test_rights_gate_is_unmeasured_before_the_screener_has_run(frontier: Path) -> None:
    """No candidate carries a rights determination yet — that is not "zero".

    Reporting "0 unclear" from a frontier nobody asked would say all-clear about
    a question never put. The gate must say it could not measure.
    """
    g = _by_name(gates.frontier_gates({"QHELD"}, frontier_path=frontier, allowlist=set()))
    rights = g["rights_unclear"]
    assert rights.blocking == 0
    assert rights.drainable is gates.UNMEASURED
    assert rights.summary()["drainable_measured"] is False
    assert rights.summary()["deadlocked"] is False


def test_rights_gate_counts_only_undetermined_candidates(tmp_path: Path) -> None:
    """Once assessed, in-copyright is a decision; only `unclear` is a gap.

    Tim's 2026-08-29 exception permits acquiring rights-reserved work for
    private display, so `rights-reserved` must NOT appear here. `unclear` is
    the one outcome nobody decided.
    """
    p = tmp_path / "frontier.json"

    def with_rights(qid: str, rights: str, **kw) -> dict:
        row = _cand(qid, "QHELD", **kw)
        row["screen_scores"]["rights_status"] = rights
        return row

    p.write_text(
        json.dumps(
            {
                "candidates": {
                    "Q1": with_rights("Q1", "public-domain"),
                    "Q2": with_rights("Q2", "rights-reserved"),
                    "Q3": with_rights("Q3", "unclear"),
                    "Q4": with_rights("Q4", "unclear", status="acquired"),
                }
            }
        ),
        encoding="utf-8",
    )
    rights = _by_name(gates.frontier_gates({"QHELD"}, frontier_path=p, allowlist=set()))[
        "rights_unclear"
    ]
    assert rights.blocking == 1, "only the un-acquired `unclear` candidate counts"
    assert rights.drainable == 1
    assert [i["id"] for i in rights.items] == ["Q3"]
