from __future__ import annotations

import json

import pytest
from scripts.migrate_series_positions import build_candidates, main, validate_mapping

from fine_art_archive import sidecar
from tests.test_sidecar import MINIMAL_VALID


def _write_member(root, work_id: str, qid: str) -> None:
    meta = dict(MINIMAL_VALID)
    meta["work_id"] = work_id
    meta["stable_identifiers"] = {"part_of_q": qid}
    sidecar.write(root / work_id / "meta.json", meta)


def _records():
    return [
        {"work_id": "1111111-one", "qid": "Q100", "position": 1, "source": "catalog A"},
        {
            "work_id": "2222222-two",
            "qid": "Q100",
            "position": 2,
            "position_label": "Plate II",
            "source": "catalog B",
        },
    ]


def test_builds_metadata_only_candidates_and_reviewable_report(tmp_path):
    root = tmp_path / "source"
    for record in _records():
        _write_member(root, record["work_id"], record["qid"])

    candidates, report = build_candidates(root, _records())

    assert [work_id for work_id, _meta in candidates] == ["1111111-one", "2222222-two"]
    assert candidates[1][1]["series"] == {
        "position": 2,
        "position_label": "Plate II",
        "source": "catalog B",
    }
    assert report["changes"][0] == {
        "work_id": "1111111-one",
        "qid": "Q100",
        "old_value": None,
        "new_position": 1,
        "evidence_source": "catalog A",
    }
    assert "series" not in sidecar.load(root / "1111111-one" / "meta.json")


@pytest.mark.parametrize(
    "records,match",
    [
        (
            [
                {"work_id": "a", "qid": "Q1", "position": 1, "source": "x"},
                {"work_id": "b", "qid": "Q1", "position": 1, "source": "y"},
            ],
            "duplicate positions",
        ),
        (
            [
                {"work_id": "a", "qid": "Q1", "position": 1, "source": "x"},
                {"work_id": "b", "qid": "Q1", "position": 3, "source": "y"},
            ],
            "missing positions",
        ),
    ],
)
def test_rejects_duplicate_or_missing_positions(records, match):
    with pytest.raises(ValueError, match=match):
        validate_mapping(records)


def test_check_cli_reports_changes_without_writing_candidates(tmp_path, monkeypatch, capsys):
    root = tmp_path / "source"
    for record in _records():
        _write_member(root, record["work_id"], record["qid"])
    mapping = tmp_path / "mapping.json"
    mapping.write_text(json.dumps({"records": _records()}), encoding="utf-8")
    output = tmp_path / "candidates"
    report_path = tmp_path / "report.json"
    monkeypatch.setattr(
        "sys.argv",
        [
            "migrate_series_positions.py",
            "--root",
            str(root),
            "--mapping",
            str(mapping),
            "--output-dir",
            str(output),
            "--report",
            str(report_path),
            "--check",
        ],
    )

    assert main() == 0
    output_json = json.loads(capsys.readouterr().out)
    assert output_json["change_count"] == 2
    assert [row["work_id"] for row in output_json["changes"]] == ["1111111-one", "2222222-two"]
    assert report_path.exists()
    assert not output.exists()
