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
from unittest.mock import Mock

import pytest

from fine_art_archive.api import gates, store


# ---------------------------------------------------------------------------
# Helpers shared by the endpoint tests below
# ---------------------------------------------------------------------------
def _app_client(monkeypatch, tmp_path: Path, frontier: Path | None = None):
    from fastapi.testclient import TestClient

    from fine_art_archive.api import main

    if frontier is not None:
        monkeypatch.setattr(
            main,
            "_all_gates",
            lambda: gates.frontier_gates({"QHELD"}, frontier_path=frontier, allowlist=set()),
        )
    return TestClient(main.app)


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


@pytest.mark.parametrize("payload", [[], "not a frontier", 17])
def test_non_object_frontier_is_treated_as_unreadable(tmp_path: Path, payload: object) -> None:
    path = tmp_path / "frontier.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    found = gates.frontier_gates({"Q1"}, frontier_path=path, allowlist=set())
    assert {gate.name for gate in found} == {
        "rights_unclear",
        "new_artist",
        "routed_to_review",
        "deferred_transfer",
    }
    for gate in found:
        assert gate.drainable is gates.UNMEASURED


def test_known_artist_qids_ignores_non_object_sidecars(monkeypatch, tmp_path: Path) -> None:
    works = tmp_path / "works"
    fixtures = {
        "valid": {"artist": {"canonical": {"wikidata_q": "Q123"}}},
        "array": [],
        "artist-list": {"artist": []},
        "canonical-string": {"artist": {"canonical": "QBAD"}},
        "invalid-canonical": {
            "artist": {"wikidata_q": "Q456", "canonical": {"wikidata_q": "not-a-qid"}}
        },
        "non-string-qids": {"artist": {"wikidata_q": ["QBAD"], "canonical": {"wikidata_q": 123}}},
    }
    for name, payload in fixtures.items():
        path = works / name / "meta.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(store, "WORKS", works)
    monkeypatch.setattr(store, "_dossier_signature", lambda: object())
    store.invalidate_artist_qid_cache()
    assert store.known_artist_qids() == frozenset({"Q123", "Q456"})


def test_known_artist_qid_cache_invalidates(monkeypatch, tmp_path: Path) -> None:
    works = tmp_path / "works"
    meta = works / "one" / "meta.json"
    meta.parent.mkdir(parents=True)
    meta.write_text(json.dumps({"artist": {"wikidata_q": "Q100"}}), encoding="utf-8")
    monkeypatch.setattr(store, "WORKS", works)

    stable_sig = object()
    monkeypatch.setattr(store, "_dossier_signature", lambda: stable_sig)

    store.invalidate_artist_qid_cache()
    first = store.known_artist_qids()
    second = store.known_artist_qids()
    assert first == second == frozenset({"Q100"})

    meta.write_text(json.dumps({"artist": {"wikidata_q": "Q200"}}), encoding="utf-8")
    assert store.known_artist_qids() == frozenset({"Q100"})

    store.invalidate_artist_qid_cache()
    assert store.known_artist_qids() == frozenset({"Q200"})


def test_a_deferral_is_a_human_decision_not_a_self_clearing_gate(frontier: Path) -> None:
    """This gate used to claim no human action could clear it. That was wrong.

    Measured on the live frontier: of 20 deferrals, 10 were TRANSFER failures
    on the largest images in the pool (356 MP, 301 MP) and 8 were just under
    the size floor — one by seven pixels, 3053 against 3060. Both are calls a
    person makes in a second given the picture and the numbers, so reporting
    them as "re-proposed automatically; no human action needed" hid a real
    choice behind a reassuring label.
    """
    g = _by_name(gates.frontier_gates({"QHELD"}, frontier_path=frontier, allowlist=set()))
    deferred = g["deferred_transfer"]
    assert deferred.blocking == 1
    assert deferred.auto_clears is False
    assert "size floor" in deferred.label or "download" in deferred.label


def test_deferral_reasons_are_classified_not_concatenated() -> None:
    """The three situations need different judgements, so they are separated."""
    floor = gates.classify_deferral("below quality floor: 3053px long edge, need 3060px")
    assert floor["kind"] == gates.DEFER_BELOW_FLOOR
    assert floor["shortfall_px"] == 7
    assert floor["percent_of_floor"] == 100

    # "0px" is the could-not-decode sentinel, NOT a measurement of zero.
    undecoded = gates.classify_deferral("below quality floor: 0px long edge, need 3060px")
    assert undecoded["kind"] == gates.DEFER_UNDECODED

    slow = gates.classify_deferral("throughput 25 KB/s below 50 KB/s floor over 52s")
    assert slow["kind"] == gates.DEFER_TRANSFER
    assert slow["got_px"] is None, "a transfer failure says nothing about pixels"


@pytest.mark.parametrize("bad_dimension", [float("nan"), float("inf"), 3000.5, True])
def test_candidate_row_rejects_non_integer_dimensions(bad_dimension: object) -> None:
    row = gates._cand_row(
        {"screen_scores": {"dimensions_px": [bad_dimension, 3000]}},
        "review",
    )
    assert row["megapixels"] is None
    assert row["long_edge_px"] is None


def test_allowlist_roundtrip_and_rejection(tmp_path: Path) -> None:
    path = tmp_path / "allowlist.jsonl"
    gates.append_allowlist("Q100", decision="approve", ts="2026-08-29T00:00:00Z", path=path)
    gates.append_allowlist("Q200", decision="approve", ts="2026-08-29T00:01:00Z", path=path)
    assert gates.load_allowlisted_artists(path) == {"Q100", "Q200"}
    assert gates.load_refused_artists(path) == set()

    # A later rejection wins over the earlier approval.
    gates.append_allowlist("Q100", decision="reject", ts="2026-08-29T00:02:00Z", path=path)
    assert gates.load_allowlisted_artists(path) == {"Q200"}
    assert gates.load_refused_artists(path) == {"Q100"}

    # A later approval also clears the refusal from the shared parser result.
    gates.append_allowlist("Q100", decision="approve", ts="2026-08-29T00:03:00Z", path=path)
    assert gates.load_allowlisted_artists(path) == {"Q100", "Q200"}
    assert gates.load_refused_artists(path) == set()


def test_missing_allowlist_is_empty_not_an_error(tmp_path: Path) -> None:
    missing = tmp_path / "nope.jsonl"
    assert gates.load_allowlisted_artists(missing) == set()
    assert gates.load_refused_artists(missing) == set()


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


def test_deferrals_report_a_real_drain(monkeypatch, frontier: Path) -> None:
    """Below-floor and transfer failures are both clearable by a person.

    Only the undecodable ones are not: those are a defect to investigate, not
    a judgement anyone can make from the page.
    """
    from fastapi.testclient import TestClient

    from fine_art_archive.api import main

    monkeypatch.setattr(
        main,
        "_all_gates",
        lambda: gates.frontier_gates({"QHELD"}, frontier_path=frontier, allowlist=set()),
    )
    body = TestClient(main.app).get("/review").json()
    row = next(g for g in body["gates"] if g["name"] == "deferred_transfer")
    assert row["auto_clears"] is False


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


def _artist_frontier(tmp_path: Path) -> Path:
    """One artist with works in BOTH artist gates, plus a held-artist control."""
    p = tmp_path / "frontier.json"
    rows = {}
    for i in range(3):
        rows[f"N{i}"] = _cand(f"N{i}", "QNEW", title=f"released {i}")
    for i in range(2):
        rows[f"R{i}"] = _cand(f"R{i}", "QNEW", status="review", title=f"subject-held {i}")
    rows["H1"] = _cand("H1", "QHELD")
    for row in rows.values():
        row["artist_label"] = "Test Painter" if row["artist_qid"] == "QNEW" else "Held Painter"
    p.write_text(json.dumps({"candidates": rows}), encoding="utf-8")
    return p


def test_artist_view_separates_what_a_decision_releases(monkeypatch, tmp_path: Path) -> None:
    """The count must promise only what approving actually delivers.

    Approving an artist clears the new-artist gate. A work the screener sent to
    review for another reason — a flagged subject — stays held. Reporting one
    combined total would promise a release the decision cannot make.
    """
    from fastapi.testclient import TestClient

    from fine_art_archive.api import main

    frontier = _artist_frontier(tmp_path)
    monkeypatch.setattr(
        main,
        "_all_gates",
        lambda: gates.frontier_gates({"QHELD"}, frontier_path=frontier, allowlist=set()),
    )
    body = TestClient(main.app).get("/review/artists").json()
    row = next(a for a in body["artists"] if a["artist_qid"] == "QNEW")

    assert row["n_released"] == 3, "the three screened works are what approval frees"
    assert row["n_held_elsewhere"] == 2, "the review-status works are not freed by this"
    assert row["n_works"] == 5
    assert row["artist_label"] == "Test Painter"
    # The already-held artist is not a decision at all.
    assert all(a["artist_qid"] != "QHELD" for a in body["artists"])


def test_artist_view_orders_by_what_is_released(monkeypatch, tmp_path: Path) -> None:
    """Biggest unlock first — the same clicks should buy the most."""
    from fastapi.testclient import TestClient

    from fine_art_archive.api import main

    p = tmp_path / "frontier.json"
    rows = {}
    for i in range(4):
        rows[f"BIG{i}"] = _cand(f"BIG{i}", "QBIG")
    rows["SMALL0"] = _cand("SMALL0", "QSMALL")
    p.write_text(json.dumps({"candidates": rows}), encoding="utf-8")
    monkeypatch.setattr(
        main,
        "_all_gates",
        lambda: gates.frontier_gates({"QHELD"}, frontier_path=p, allowlist=set()),
    )
    body = TestClient(main.app).get("/review/artists").json()
    assert [a["artist_qid"] for a in body["artists"]] == ["QBIG", "QSMALL"]


def test_a_decided_work_leaves_every_gate(tmp_path: Path) -> None:
    """Feedback must be honoured by ALL gates, not gate by gate.

    Twenty deferrals were decided — 14 taken, 6 refused — and all twenty kept
    being presented, because the deferral list was built from the frontier and
    never read the decision record. Three gates had the same hole. Filtering
    per-gate is what let them disagree about whether feedback counts, so the
    filter is applied once for every gate and this test pins it.
    """
    frontier = tmp_path / "frontier.json"
    frontier.write_text(
        json.dumps(
            {
                "candidates": {
                    "Q1": _cand("Q1", "QNEW1"),
                    "Q2": _cand("Q2", "QHELD", status="review"),
                    "Q3": _cand("Q3", "QHELD", deferrals=2),
                }
            }
        ),
        encoding="utf-8",
    )
    decisions = tmp_path / "work_decisions.jsonl"

    def gates_now() -> dict[str, gates.Gate]:
        return _by_name(gates.frontier_gates({"QHELD"}, frontier_path=frontier, allowlist=set()))

    import fine_art_archive.api.gates as gates_module

    original = gates_module.WORK_DECISIONS
    gates_module.WORK_DECISIONS = decisions
    try:
        before = gates_now()
        assert before["new_artist"].blocking == 1
        assert before["routed_to_review"].blocking == 1
        assert before["deferred_transfer"].blocking == 1

        for qid, decision in (("Q1", "reject"), ("Q2", "keep"), ("Q3", "force")):
            gates.append_work_decision(
                qid, decision=decision, ts="2026-08-31T00:00:00Z", path=decisions
            )

        after = gates_now()
        assert after["new_artist"].blocking == 0, "a refused work must leave its gate"
        assert after["routed_to_review"].blocking == 0, "a kept work must leave its gate"
        assert after["deferred_transfer"].blocking == 0, "a forced work must leave its gate"
    finally:
        gates_module.WORK_DECISIONS = original


# ---------------------------------------------------------------------------
# Endpoint contract tests — Thread 8 (new endpoints need safety/error tests)
# ---------------------------------------------------------------------------


def test_candidate_image_bad_qid_returns_400(monkeypatch, tmp_path: Path) -> None:
    client = _app_client(monkeypatch, tmp_path)
    assert client.get("/review/candidate/not-a-qid/image").status_code == 400


def test_candidate_image_unknown_qid_returns_404(monkeypatch, tmp_path: Path) -> None:

    monkeypatch.setattr(gates, "candidate_image_url", lambda qid, **_: None)
    client = _app_client(monkeypatch, tmp_path)
    assert client.get("/review/candidate/Q99999/image").status_code == 404


def test_candidate_image_disallowed_scheme_does_not_fetch(monkeypatch, tmp_path: Path) -> None:
    from fine_art_archive.api import main

    fetch = Mock()
    monkeypatch.setattr(gates, "candidate_image_url", lambda qid, **_: "file:///tmp/image.jpg")
    monkeypatch.setattr(main, "_fetch_candidate_bytes", fetch)

    client = _app_client(monkeypatch, tmp_path)
    response = client.get("/review/candidate/Q99999/image")

    assert response.status_code == 502
    fetch.assert_not_called()


def test_variant_candidate_image_outside_roots_returns_403(monkeypatch, tmp_path: Path) -> None:
    import csv

    from fine_art_archive.api import main
    from fine_art_archive.api import store as _store

    csv_path = tmp_path / "upgrades.csv"
    with open(csv_path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["existing_wid", "candidate_path"])
        w.writerow(["W00000001", "/etc/passwd"])
    monkeypatch.setattr(main, "VARIANT_UPGRADE_CSV", csv_path)
    monkeypatch.setattr(_store, "validate_work_id", lambda _: None)
    client = _app_client(monkeypatch, tmp_path)
    assert client.get("/variant_upgrades/W00000001/candidate_image").status_code == 403


def test_review_works_invalid_source_returns_400(monkeypatch, tmp_path: Path) -> None:
    client = _app_client(monkeypatch, tmp_path)
    assert client.get("/review/works?source=evil").status_code == 400


def test_work_decision_removes_work_from_next_response(monkeypatch, tmp_path: Path) -> None:
    import fine_art_archive.api.gates as gates_module

    frontier_path = tmp_path / "frontier.json"
    frontier_path.write_text(
        json.dumps(
            {
                "candidates": {
                    "Q10": _cand("Q10", "QAPPROVED", status="screened"),
                    "Q11": _cand("Q11", "QAPPROVED", status="screened"),
                }
            }
        ),
        encoding="utf-8",
    )
    decisions_path = tmp_path / "work_decisions.jsonl"

    orig_frontier = gates_module.FRONTIER_JSON
    orig_decisions = gates_module.WORK_DECISIONS
    orig_allowlist = gates_module.ARTIST_ALLOWLIST
    allowlist_path = tmp_path / "allowlist.jsonl"
    gates.append_allowlist(
        "QAPPROVED", decision="approve", ts="2026-08-31T00:00:00Z", path=allowlist_path
    )
    gates_module.FRONTIER_JSON = frontier_path
    gates_module.WORK_DECISIONS = decisions_path
    gates_module.ARTIST_ALLOWLIST = allowlist_path
    try:
        client = _app_client(monkeypatch, tmp_path)
        before = client.get("/review/works?source=approved").json()
        before_ids = {w["id"] for w in before["works"]}
        assert "Q10" in before_ids

        client.post(
            "/review/works/Q10/decision",
            json={"decision": "reject", "title": ""},
        )
        after = client.get("/review/works?source=approved").json()
        after_ids = {w["id"] for w in after["works"]}
        assert "Q10" not in after_ids
        assert "Q11" in after_ids
    finally:
        gates_module.FRONTIER_JSON = orig_frontier
        gates_module.WORK_DECISIONS = orig_decisions
        gates_module.ARTIST_ALLOWLIST = orig_allowlist



# --------------------------------------------------------------------------
# The routed queue asks about PICTURES, and must say so
# --------------------------------------------------------------------------
def _routed(qid: str, artist: str, **scores: object) -> dict:
    row = _cand(qid, artist, status="review")
    row["screen_scores"].update(scores)
    return row


def test_routed_row_states_the_screener_flagged_the_picture(tmp_path: Path) -> None:
    p = tmp_path / "frontier.json"
    p.write_text(
        json.dumps(
            {
                "candidates": {
                    "Q1": _routed(
                        "Q1",
                        "QA",
                        held_titles_for_artist=19,
                        candidate_variants=8,
                        depicts_flagged=["Q10791"],
                    )
                }
            }
        ),
        encoding="utf-8",
    )
    rows = gates.works_awaiting_look(set(), frontier_path=p, decided={}, source="routed")
    assert len(rows) == 1
    row = rows[0]
    assert "artist" not in row["why"], row["why"]
    flags = row["routing_flags"]
    assert flags["held_by_artist"] == 19
    assert flags["variants"] == 8
    assert flags["depicts"] == [{"qid": "Q10791", "label": "nudity"}]
    # Position in the artist's set, so the card can say "1 of 12" instead of
    # showing a silent grid that reads as a group approval.
    assert row["artist_work_index"] == 1
    assert row["artist_work_count"] == 1


def test_routed_gate_says_works_are_decided_one_at_a_time(tmp_path: Path) -> None:
    p = tmp_path / "frontier.json"
    p.write_text(json.dumps({"candidates": {"Q1": _routed("Q1", "QA")}}), encoding="utf-8")
    gate = next(
        g
        for g in gates.frontier_gates({"QA"}, allowlist=set(), frontier_path=p)
        if g.name == "routed_to_review"
    )
    assert "artist" not in gate.clears_by, gate.clears_by
    assert "work" in gate.clears_by


def test_an_unnamed_depicts_flag_is_still_reported() -> None:
    """A flag we cannot name is still a flag. Dropping it would render as
    "nothing flagged", which is the opposite of what an unknown code means."""
    flags = gates.routing_flags({"screen_scores": {"depicts_flagged": ["Q99999999"]}})
    assert flags["depicts"] == [{"qid": "Q99999999", "label": None}]


def test_unreadable_archive_is_reported_not_shown_as_nothing_similar() -> None:
    """"Could not look it up" and "nothing similar is held" are opposite
    answers to "is this the painting you already have"."""
    assert gates.held_lookalikes("QA", "a title", None) == {"lookup": "unavailable"}
    ok = gates.held_lookalikes(
        "QA",
        "virgin and child with the young saint john",
        {"QA": [{"id": "w1", "title": "Virgin and Child with the Young Saint John", "norm": "virgin and child with the young saint john"}]},
    )
    assert ok["lookup"] == "ok"
    assert ok["matches"][0]["work_id"] == "w1"


def test_a_candidate_that_was_never_probed_says_so() -> None:
    """An absent megapixel count must not read as a small picture."""
    unprobed = gates._cand_row({"qid": "Q1", "screen_scores": {}}, "why")
    assert unprobed["probed"] is False
    assert unprobed["megapixels"] is None
    probed = gates._cand_row({"qid": "Q2", "screen_scores": {"dimensions_px": [4000, 3000]}}, "why")
    assert probed["probed"] is True
    assert probed["megapixels"] == 12.0
