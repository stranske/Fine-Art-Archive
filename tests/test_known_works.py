"""Series-QID classification and identity-field regressions for issue #542."""

from __future__ import annotations

import json
from pathlib import Path

from scripts.classify_shared_work_qids import apply_series_migration, check_report

from fine_art_archive.known_works.artwork_classes import (
    KNOWN_SERIES_QIDS,
    is_series_qid,
    series_qid_evidence,
)


def _claim(property_id: str, target: str) -> dict[str, object]:
    return {
        "claims": {
            property_id: [
                {
                    "mainsnak": {
                        "snaktype": "value",
                        "datavalue": {"value": {"id": target}},
                    }
                }
            ]
        }
    }


def test_series_qid_detected_for_group_entity() -> None:
    """Q2667782 is a triptych whose direct P31 includes painting series."""
    entities = {
        "Q2667782": _claim("P31", "Q15727816"),
        "Q15727816": _claim("P279", "Q18573970"),
        "Q18573970": {"claims": {}},
    }

    evidence = series_qid_evidence("Q2667782", entities)

    assert is_series_qid("Q2667782", entities) is True
    assert evidence["p31"] == ["Q15727816"]
    assert evidence["matched_group_classes"] == ["Q15727816", "Q18573970"]


def test_scrovegni_fresco_qid_is_not_the_cycle() -> None:
    """Q547923 identifies one fresco; Q29353420 is its larger cycle."""
    entities = {
        "Q547923": _claim("P31", "Q22669139"),
        "Q22669139": _claim("P279", "Q3305213"),
        "Q3305213": {"claims": {}},
    }

    assert is_series_qid("Q547923", entities) is False


def test_series_detection_follows_p279_to_group_class() -> None:
    entities = {
        "Q999": _claim("P31", "Q998"),
        "Q998": _claim("P279", "Q15709879"),
        "Q15709879": {"claims": {}},
    }

    assert is_series_qid("Q999", entities) is True


def test_shared_qid_report_is_fully_adjudicated() -> None:
    report_path = Path(__file__).resolve().parents[1] / "docs/reports/shared_work_qids.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))

    assert report["shared_qid_count"] == len(report["records"])
    assert {record["classification"] for record in report["records"]} <= {
        "series-qid",
        "duplicate-candidate",
    }
    series = {
        record["qid"] for record in report["records"] if record["classification"] == "series-qid"
    }
    assert series == KNOWN_SERIES_QIDS == {"Q2667782"}


def test_report_preserves_the_single_work_scrovegni_qid() -> None:
    report_path = Path(__file__).resolve().parents[1] / "docs/reports/shared_work_qids.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    decision = next(item for item in report["adjudications"] if item["qid"] == "Q547923")

    assert decision["classification"] == "single-work"
    assert decision["part_of_q"] == "Q29353420"
    assert decision["evidence"]["matched_group_classes"] == []


def test_series_migration_moves_identity_without_touching_other_fields(tmp_path: Path) -> None:
    work_ids = ("1234567-rubens-master", "7654321-rubens-display")
    for work_id in work_ids:
        work_dir = tmp_path / work_id
        work_dir.mkdir()
        meta = {
            "work_id": work_id,
            "schema_version": "1.0",
            "artist": {"name": "Peter Paul Rubens"},
            "title": "The Descent from the Cross",
            "files": {
                "master": {
                    "filename": "master.jpg",
                    "sha256": "a" * 64,
                    "size_bytes": 1,
                    "ingested_at": "2026-08-15T00:00:00Z",
                }
            },
            "history": [{"ts": "2026-08-15T00:00:00Z", "actor": "test", "op": "seed"}],
            "stable_identifiers": {"wikidata_q": "Q2667782", "part_of_q": "Q2667782"},
        }
        (work_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    report = {
        "shared_qid_count": 1,
        "records": [
            {
                "qid": "Q2667782",
                "classification": "series-qid",
                "work_ids": list(work_ids),
                "evidence": {"p31": ["Q15727816"]},
            }
        ],
        "adjudications": [],
    }

    changed = apply_series_migration(tmp_path, report, timestamp="2026-08-15T12:15:00Z")

    assert changed == 2
    check_report(report, tmp_path)
    for work_id in work_ids:
        meta = json.loads((tmp_path / work_id / "meta.json").read_text(encoding="utf-8"))
        assert "wikidata_q" not in meta["stable_identifiers"]
        assert meta["stable_identifiers"]["part_of_q"] == "Q2667782"
        assert meta["history"][-1]["op"] == "migrate-series-qid"
