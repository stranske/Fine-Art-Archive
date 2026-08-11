"""A work QID denotes one work, so the resolver must never assign one twice.

Regression: on 2026-08-09 ``resolve_work_qids`` bound Q17277950 (Cezanne's
*Card Players*, a Wikidata **group of paintings**) to two sidecars 15 minutes
apart, and Q2667782 (Rubens' *Descent from the Cross* triptych) to two more.
Both collisions were introduced inside a single run: the resolver searched each
sidecar independently and never asked whether the QID it was about to write was
already held. The archive audit caught them only after the fact, as a ratchet
regression above the 31-collision baseline.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scripts.resolve_work_qids import backfill

from tests.test_work_qid_search import FakeJson, FakeSparqlDetails, _detail_row, _write

# One title, one creator, two holdings -> the search returns the same QID twice.
SERIES_QID = "Q17277950"


def _clients() -> tuple[FakeJson, FakeSparqlDetails]:
    json_c = FakeJson([SERIES_QID])
    sparql = FakeSparqlDetails(
        [_detail_row(SERIES_QID, "The Card Players", artwork=True, creators=[], inception="1892")]
    )
    return json_c, sparql


def _two_sidecars(tmp_path: Path) -> None:
    for work_id, title in (
        ("481c9c3-the-card-player", "The Card Players"),
        ("c38cde9-the-card-players", "The Card Players"),
    ):
        _write(tmp_path, {"work_id": work_id, "artist": {"name": "Cezanne"}, "title": title})


def _qids(tmp_path: Path) -> list[str]:
    out = []
    for path in sorted(tmp_path.glob("*/meta.json")):
        meta: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        qid = (meta.get("stable_identifiers") or {}).get("wikidata_q")
        if qid:
            out.append(qid)
    return out


def test_resolver_never_assigns_one_work_qid_to_two_sidecars(tmp_path: Path) -> None:
    """The second claimant must be declined, not silently given the same QID."""
    _two_sidecars(tmp_path)
    json_c, sparql = _clients()

    stats, outcomes = backfill(tmp_path, sparql=sparql, json_client=json_c, apply=True, retire=True)

    assert _qids(tmp_path) == [SERIES_QID], (
        f"resolver assigned one work QID to more than one sidecar: {_qids(tmp_path)}"
    )
    assert stats.resolved == 1
    assert outcomes["declined:collision"] == 1


def test_collision_is_recorded_as_retired_not_silently_dropped(tmp_path: Path) -> None:
    """The declined sidecar keeps a diagnosable trail naming the holder."""
    _two_sidecars(tmp_path)
    json_c, sparql = _clients()

    backfill(tmp_path, sparql=sparql, json_client=json_c, apply=True, retire=True)

    declined = [
        json.loads(p.read_text(encoding="utf-8"))
        for p in sorted(tmp_path.glob("*/meta.json"))
        if not (json.loads(p.read_text(encoding="utf-8")).get("stable_identifiers") or {}).get(
            "wikidata_q"
        )
    ]
    assert len(declined) == 1
    note = declined[0]["field_provenance"]["work_qid"]["note"]
    assert SERIES_QID in note and "collision" in note


def test_by_creator_backfill_declines_a_qid_another_work_holds(tmp_path: Path) -> None:
    """The dominant collision source obeys the same invariant.

    Replaying operations.log, ``backfill_work_qids_by_creator`` accounted for 58
    of the 60 historical collisions — three *Field with Poppies* sidecars all
    took Q24046967. A guard living only in ``resolve_work_qids`` would have
    caught 2 of 60.
    """
    from scripts.backfill_work_qids_by_creator import backfill as creator_backfill

    from tests.test_work_qid_by_creator import FakeSparql, _binding, _uncat_sidecar
    from tests.test_work_qid_by_creator import _write as _write_uncat

    for work_id in ("0fc5922-field-with-poppies", "3de5029-field-with-poppies"):
        _write_uncat(tmp_path, _uncat_sidecar(work_id, "Field with Poppies"))
    client = FakeSparql([_binding("Q24046967", "Field with Poppies", inception="1890")])

    stats, reasons = creator_backfill(tmp_path, client=client, apply=True)

    assert stats.resolved == 1
    assert reasons["declined:collision"] == 1
    assert _qids(tmp_path) == ["Q24046967"]


def test_by_creator_collision_mirrors_and_logs_the_decline(tmp_path: Path) -> None:
    """A declined collision must preserve the same audit/mirror contract as a match."""
    from scripts.backfill_work_qids_by_creator import backfill as creator_backfill

    from tests.test_work_qid_by_creator import FakeSparql, _binding, _uncat_sidecar
    from tests.test_work_qid_by_creator import _write as _write_uncat

    staging_dir = tmp_path / "staging"
    work_ids = ("0fc5922-field-with-poppies", "3de5029-field-with-poppies")
    for work_id in work_ids:
        _write_uncat(staging_dir, _uncat_sidecar(work_id, "Field with Poppies"))
    mirror_path = tmp_path / "art" / "works" / work_ids[1] / "meta.json"
    mirror_path.parent.mkdir(parents=True)
    mirror_path.write_text(
        (staging_dir / work_ids[1] / "meta.json").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    log_path = tmp_path / "operations.log"
    client = FakeSparql([_binding("Q24046967", "Field with Poppies", inception="1890")])

    stats, reasons = creator_backfill(
        staging_dir,
        client=client,
        art_works_root=tmp_path / "art",
        operations_log=log_path,
        apply=True,
    )

    assert reasons["declined:collision"] == 1
    assert stats.mirrored == 1
    declined = json.loads((staging_dir / work_ids[1] / "meta.json").read_text(encoding="utf-8"))
    assert json.loads(mirror_path.read_text(encoding="utf-8")) == declined
    entries = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    collision = next(entry for entry in entries if entry["op"] == "work_qid_by_creator_collision")
    assert collision["work_id"] == work_ids[1]
    assert collision["proposed_work_qid"] == "Q24046967"


def test_collision_against_a_qid_already_in_the_archive_is_declined(tmp_path: Path) -> None:
    """A pre-existing holder outside this run's resolutions also blocks the write."""
    _write(
        tmp_path,
        {
            "work_id": "0000000-incumbent",
            "artist": {"name": "Cezanne"},
            "title": "The Card Players",
            "stable_identifiers": {"wikidata_q": SERIES_QID},
        },
    )
    _write(
        tmp_path,
        {
            "work_id": "c38cde9-the-card-players",
            "artist": {"name": "Cezanne"},
            "title": "The Card Players",
        },
    )
    json_c, sparql = _clients()

    stats, outcomes = backfill(tmp_path, sparql=sparql, json_client=json_c, apply=True, retire=True)

    assert _qids(tmp_path) == [SERIES_QID]  # only the incumbent
    assert stats.resolved == 0
    assert outcomes["declined:collision"] == 1
