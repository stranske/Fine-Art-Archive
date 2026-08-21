"""Tests for the evidence-pinned #560 data remediation."""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import remediate_variant_identity as remediation  # noqa: E402


def _meta(work_id: str, qid: str, target: str) -> dict:
    return {
        "work_id": work_id,
        "schema_version": "1.0",
        "artist": {"name": "Edvard Munch"},
        "title": "The Scream",
        "files": {
            "master": {
                "filename": "master.jpeg",
                "sha256": "a" * 64,
                "size_bytes": 1,
                "ingested_at": "2026-08-20T00:00:00Z",
            },
            "variants": [{"rel_path": f"works/{target}/master.jpeg", "role": "portrait-crop"}],
        },
        "history": [{"ts": "2026-08-20T00:00:00Z", "actor": "test", "op": "ingested"}],
        "stable_identifiers": {"wikidata_q": qid},
    }


def _write_pair(root: Path) -> tuple[Path, Path]:
    (left, left_qid), (right, right_qid) = remediation.APPROVED_FALSE_VARIANT_PAIR
    left_path, right_path = root / left / "meta.json", root / right / "meta.json"
    left_path.parent.mkdir(parents=True, exist_ok=True)
    right_path.parent.mkdir(parents=True, exist_ok=True)
    left_path.write_text(json.dumps(_meta(left, left_qid, right)), encoding="utf-8")
    right_path.write_text(json.dumps(_meta(right, right_qid, left)), encoding="utf-8")
    return left_path, right_path


def test_dry_run_is_exact_and_non_mutating(tmp_path: Path) -> None:
    left_path, right_path = _write_pair(tmp_path)
    before = (left_path.read_text(), right_path.read_text())

    plan = remediation.remediate(tmp_path, operations_log=tmp_path / "operations.log")

    assert plan is not None
    assert [entry["rel_path"] for entry in plan.removed] == [
        f"works/{remediation.APPROVED_FALSE_VARIANT_PAIR[1][0]}/master.jpeg",
        f"works/{remediation.APPROVED_FALSE_VARIANT_PAIR[0][0]}/master.jpeg",
    ]
    assert (left_path.read_text(), right_path.read_text()) == before


def test_apply_removes_only_reciprocal_links_and_logs_preimage(tmp_path: Path) -> None:
    left_path, right_path = _write_pair(tmp_path)
    log_path = tmp_path / "operations.log"

    remediation.remediate(tmp_path, operations_log=log_path, apply=True)

    left, right = json.loads(left_path.read_text()), json.loads(right_path.read_text())
    assert left["stable_identifiers"]["wikidata_q"] == remediation.APPROVED_FALSE_VARIANT_PAIR[0][1]
    assert right["stable_identifiers"]["wikidata_q"] == remediation.APPROVED_FALSE_VARIANT_PAIR[1][1]
    assert left["files"]["variants"] == []
    assert right["files"]["variants"] == []
    entry = json.loads(log_path.read_text())
    assert entry["issue"] == 560
    assert len(entry["preimage"]) == 2
    assert remediation.remediate(tmp_path, operations_log=log_path, apply=True) is None


def test_refuses_a_partial_or_changed_pair(tmp_path: Path) -> None:
    left_path, right_path = _write_pair(tmp_path)
    partial = json.loads(right_path.read_text())
    partial["files"]["variants"] = []
    right_path.write_text(json.dumps(partial), encoding="utf-8")

    with pytest.raises(ValueError, match="partially present"):
        remediation.build_plan(tmp_path)

    _write_pair(tmp_path)
    changed = copy.deepcopy(json.loads(left_path.read_text()))
    changed["stable_identifiers"]["wikidata_q"] = "Q1"
    left_path.write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(ValueError, match="approved identity evidence"):
        remediation.build_plan(tmp_path)
