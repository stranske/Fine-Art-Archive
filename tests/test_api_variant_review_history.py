"""The upgrade listing must attach the latest decision to the correct picture."""

from __future__ import annotations

import csv
import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from fine_art_archive.api import main as api_main
from fine_art_archive.api import store


@pytest.fixture
def review_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[dict[str, Path]]:
    works = tmp_path / "works"
    staging = tmp_path / "staging"
    works.mkdir()
    staging.mkdir()
    detector = tmp_path / "candidates.csv"
    decisions = tmp_path / "decisions.jsonl"
    monkeypatch.setattr(api_main, "ART_WORKS_ROOT", works)
    monkeypatch.setattr(api_main, "VARIANT_CANDIDATE_ROOTS", (staging,))
    monkeypatch.setattr(api_main, "VARIANT_UPGRADE_CSV", detector)
    monkeypatch.setattr(api_main, "VARIANT_UPGRADE_DECISIONS", decisions)
    monkeypatch.setattr(store, "WORKS", works)
    monkeypatch.setattr(store, "MANIFEST_CSV", tmp_path / "manifest.csv")
    with detector.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=["existing_wid", "title", "artist", "candidate_path"]
        )
        writer.writeheader()
        for wid, size in [("first-work", (30, 20)), ("second-work", (40, 25))]:
            work = works / wid
            work.mkdir()
            Image.new("RGB", size).save(work / "master.png")
            candidate = staging / f"{wid}.png"
            Image.new("RGB", (size[0] * 2, size[1] * 2)).save(candidate)
            writer.writerow(
                {
                    "existing_wid": wid,
                    "title": wid,
                    "artist": "CSV artist",
                    "candidate_path": candidate,
                }
            )
    yield {"works": works, "staging": staging, "detector": detector, "decisions": decisions}
    api_main._image_dims.cache_clear()


def test_absent_detector_does_not_surface_unmatched_decisions(
    review_files: dict[str, Path],
) -> None:
    review_files["detector"].unlink()
    log = review_files["decisions"]
    log.write_text(json.dumps({"existing_wid": "first-work", "decision": "accept"}) + "\n")
    original = log.read_bytes()

    with TestClient(api_main.app) as client:
        response = client.get("/variant_upgrades")

    assert response.status_code == 200
    assert response.json() == {"candidates": [], "decisions": []}
    assert log.read_bytes() == original
    assert not review_files["detector"].exists()


def test_unreviewed_candidates_have_no_decision_and_real_dimensions(
    review_files: dict[str, Path],
) -> None:
    with TestClient(api_main.app) as client:
        response = client.get("/variant_upgrades")

    assert response.status_code == 200
    payload = response.json()
    assert payload["stale_command"] == api_main.VARIANT_DETECT_COMMAND
    assert [row["existing_wid"] for row in payload["candidates"]] == ["first-work", "second-work"]
    for row, existing, candidate in zip(
        payload["candidates"], ["30x20", "40x25"], ["60x40", "80x50"], strict=True
    ):
        assert row["decision"] is None
        assert row["decision_ts"] is None
        assert row["candidate_present"] is True
        assert row["existing_px"] == existing
        assert row["candidate_px"] == candidate
    assert not review_files["decisions"].exists(), "a GET must not create review history"


@pytest.mark.parametrize("interruption", ["", " \n\t\n", "{broken json}\n"])
def test_latest_decisions_are_keyed_by_work_and_ignore_log_noise(
    review_files: dict[str, Path], interruption: str
) -> None:
    records = [
        {"existing_wid": "first-work", "decision": "accept", "ts": "2026-10-01T12:00:00Z"},
        {"existing_wid": "second-work", "decision": "defer", "ts": "2026-10-02T12:00:00Z"},
        {"existing_wid": "first-work", "decision": "reject", "ts": "2026-10-03T12:00:00Z"},
        {"existing_wid": "not-in-detector", "decision": "accept", "ts": "2026-10-04T12:00:00Z"},
    ]
    log = review_files["decisions"]
    log.write_text(
        json.dumps(records[0])
        + "\n"
        + interruption
        + "".join(json.dumps(r) + "\n" for r in records[1:]),
        encoding="utf-8",
    )
    original_log = log.read_bytes()
    original_detector = review_files["detector"].read_bytes()

    with TestClient(api_main.app) as client:
        response = client.get("/variant_upgrades")

    assert response.status_code == 200
    rows = response.json()["candidates"]
    assert [(r["existing_wid"], r["decision"], r["decision_ts"]) for r in rows] == [
        ("first-work", "reject", "2026-10-03T12:00:00Z"),
        ("second-work", "defer", "2026-10-02T12:00:00Z"),
    ]
    assert log.read_bytes() == original_log
    assert review_files["detector"].read_bytes() == original_detector


def test_invalid_detector_identity_is_unavailable_without_hiding_valid_rows(
    review_files: dict[str, Path],
) -> None:
    detector = review_files["detector"]
    with detector.open("a", encoding="utf-8", newline="") as handle:
        csv.writer(handle).writerow(["../outside", "Malformed identity", "CSV artist", ""])

    with TestClient(api_main.app) as client:
        response = client.get("/variant_upgrades")

    assert response.status_code == 200
    valid, second, invalid = response.json()["candidates"]
    assert valid["candidate_present"] is True
    assert second["candidate_present"] is True
    assert invalid["existing_wid"] == "../outside"
    assert invalid["existing_px"] is None
    assert invalid["candidate_px"] is None
    assert invalid["candidate_present"] is False
    assert invalid["title"] == "Malformed identity"
    assert invalid["artist"] == invalid["artist_name"] == "CSV artist"
