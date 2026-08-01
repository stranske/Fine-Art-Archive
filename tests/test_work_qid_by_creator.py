"""Tests for SPARQL by-creator work-QID resolution + backfill CLI."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scripts.backfill_work_qids_by_creator import backfill

from fine_art_archive.enrichment import holder_by_creator as hbc
from fine_art_archive.enrichment import work_qid_by_creator as wqc

# Reuse the holder test's binding + fake-client shape.
from tests.test_holder_by_creator import BASE, FakeSparql, _binding


def _uncat_sidecar(
    work_id: str, title: str, *, artist_qid: str | None = "Q296", year: str | None = "1889"
) -> dict[str, Any]:
    meta = json.loads(json.dumps(BASE))
    meta["work_id"] = work_id
    meta["title"] = title
    meta["artist"] = {"name": "Example"}
    if artist_qid:
        meta["artist"]["wikidata_q"] = artist_qid
    if year is None:
        meta.pop("year", None)
    else:
        meta["year"] = year
    return meta


def _write(tmp_path: Path, meta: dict[str, Any]) -> Path:
    path = tmp_path / meta["work_id"] / "meta.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(meta), encoding="utf-8")
    return path


# --- match_work_entity (the extracted, holder-independent core) ---------------


def test_entity_match_returns_work_without_requiring_holder() -> None:
    # A confident title match whose work has NO collection/location: match_work
    # rejects it as "no-collection", but match_work_entity still identifies it.
    works = hbc.works_by_creator(
        "Q296",
        client=FakeSparql(
            [
                _binding("Q1", "The Starry Night", inception="1889"),  # no coll, no loc
                _binding("Q2", "Irises", inception="1889"),
            ]
        ),
    )
    assert hbc.match_work("The Starry Night", 1889, works)[1] == "no-collection"
    best, score, reason = hbc.match_work_entity("The Starry Night", 1889, works)
    assert reason == "match"
    assert best is not None and best.work_qid == "Q1"
    assert score >= 0.93


def test_entity_match_preserves_guards() -> None:
    works = hbc.works_by_creator(
        "Q296",
        client=FakeSparql(
            [
                # same-title-different-work: two works both score 1.0 -> ambiguous
                _binding("Q1", "Saint Jerome", inception="1605"),
                _binding("Q2", "Saint Jerome", inception="1607"),
            ]
        ),
    )
    assert hbc.match_work_entity("Saint Jerome", None, works)[2] == "ambiguous"

    # Same work held in several collections -> several identical-score rows for
    # one work_qid. Those are the same answer, not a competitor: still a match.
    dup = hbc.works_by_creator(
        "Q297",
        client=FakeSparql(
            [
                _binding("Q1", "Old Woman Cooking Eggs", coll="Q100", inception="1618"),
                _binding("Q1", "Old Woman Cooking Eggs", coll="Q200", inception="1618"),
            ]
        ),
    )
    best, _score, reason = hbc.match_work_entity("Old Woman Cooking Eggs", None, dup)
    assert reason == "match"
    assert best is not None and best.work_qid == "Q1"
    assert hbc.match_work_entity("Completely Different", None, works)[2] == "below-threshold"
    # year disagreement beyond tolerance
    yr = hbc.works_by_creator(
        "Q296", client=FakeSparql([_binding("Q1", "Irises", inception="1600")])
    )
    assert hbc.match_work_entity("Irises", 1889, yr)[2] == "year-mismatch"


# --- resolve_work_qid ---------------------------------------------------------


def test_resolve_work_qid_match() -> None:
    client = FakeSparql(
        [
            _binding("Q1", "The Starry Night", inception="1889"),
            _binding("Q2", "Irises", inception="1889"),
        ]
    )
    match, reason = wqc.resolve_work_qid("The Starry Night", 1889, "Q296", client=client)
    assert reason == "match"
    assert match is not None and match.work_qid == "Q1"


def test_resolve_work_qid_no_creator() -> None:
    match, reason = wqc.resolve_work_qid("x", None, "", client=FakeSparql([]))
    assert match is None and reason == "no-creator"


def test_wrong_creator_declines_rather_than_mismatches() -> None:
    # creator's works never title-match -> no write (self-defending guard)
    client = FakeSparql([_binding("Q9", "Some Unrelated Work", inception="1700")])
    match, reason = wqc.resolve_work_qid("The Starry Night", 1889, "Q999", client=client)
    assert match is None and reason == "below-threshold"


# --- backfill CLI -------------------------------------------------------------


def test_backfill_writes_qid_and_provenance(tmp_path: Path) -> None:
    path = _write(tmp_path, _uncat_sidecar("1111111-starry-night", "The Starry Night"))
    client = FakeSparql([_binding("Q1", "The Starry Night", inception="1889")])

    stats, reasons = backfill(tmp_path, client=client, apply=True)

    assert stats.attempted == 1 and stats.resolved == 1
    written = json.loads(path.read_text())
    assert written["stable_identifiers"]["wikidata_q"] == "Q1"
    entry = written["field_provenance"]["work_qid"]
    assert entry["status"] == "available" and entry["source"] == "wikidata"
    assert entry["source_ref"] == "https://www.wikidata.org/wiki/Q1"


def test_dry_run_reports_without_writing(tmp_path: Path) -> None:
    path = _write(tmp_path, _uncat_sidecar("1111111-starry-night", "The Starry Night"))
    client = FakeSparql([_binding("Q1", "The Starry Night", inception="1889")])

    stats, _ = backfill(tmp_path, client=client, apply=False)

    assert len(stats.matches) == 1 and stats.resolved == 0
    assert "stable_identifiers" not in json.loads(path.read_text())


def test_skips_categorized_and_already_qided(tmp_path: Path) -> None:
    # categorized -> ineligible
    cat = _uncat_sidecar("2222222-categorized", "The Starry Night")
    cat["category"] = "painting"
    _write(tmp_path, cat)
    # already has a work QID -> ineligible
    qided = _uncat_sidecar("3333330-already-qided", "The Starry Night")
    qided["stable_identifiers"] = {"wikidata_q": "Q1"}
    _write(tmp_path, qided)
    client = FakeSparql([_binding("Q1", "The Starry Night", inception="1889")])

    stats, _ = backfill(tmp_path, client=client, apply=True)

    assert stats.attempted == 0 and stats.resolved == 0


def test_no_creator_qid_is_reported_not_guessed(tmp_path: Path) -> None:
    _write(tmp_path, _uncat_sidecar("4444444-no-artist", "The Starry Night", artist_qid=None))
    client = FakeSparql([_binding("Q1", "The Starry Night", inception="1889")])

    stats, reasons = backfill(tmp_path, client=client, apply=True)

    assert stats.attempted == 0 and stats.resolved == 0
    assert stats.needs_artist == 1
    assert reasons["no-creator-qid"] == 1


def test_mirror_and_log(tmp_path: Path) -> None:
    _write(tmp_path, _uncat_sidecar("1111111-starry-night", "The Starry Night"))
    art_root = tmp_path / "art"
    mirror = art_root / "1111111-starry-night" / "meta.json"
    mirror.parent.mkdir(parents=True)
    mirror.write_text(
        json.dumps(_uncat_sidecar("1111111-starry-night", "The Starry Night")), encoding="utf-8"
    )
    log = tmp_path / "operations.log"
    client = FakeSparql([_binding("Q1", "The Starry Night", inception="1889")])

    stats, _ = backfill(
        tmp_path, client=client, art_works_root=art_root, operations_log=log, apply=True
    )

    assert stats.mirrored == 1
    assert json.loads(mirror.read_text())["stable_identifiers"]["wikidata_q"] == "Q1"
    logged = json.loads(log.read_text().strip())
    assert logged["op"] == "work_qid_by_creator_backfill"
    assert logged["matched_work_qid"] == "Q1"
