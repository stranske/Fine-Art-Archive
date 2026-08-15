"""Regression coverage for the local shared-QID migration candidate."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType


def _load_classifier() -> ModuleType:
    script = Path(__file__).resolve().parents[1] / "scripts" / "classify_shared_work_qids.py"
    spec = importlib.util.spec_from_file_location("classify_shared_work_qids", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _meta(work_id: str, qid: str) -> dict[str, object]:
    return {
        "work_id": work_id,
        "schema_version": "1.0",
        "artist": {"name": "Test Artist"},
        "title": work_id,
        "files": {
            "master": {
                "filename": "master.jpeg",
                "sha256": "a" * 64,
                "size_bytes": 1,
                "ingested_at": "2026-08-15T00:00:00Z",
            }
        },
        "history": [{"ts": "2026-08-15T00:00:00Z", "actor": "test", "op": "ingested"}],
        "stable_identifiers": {"wikidata_q": qid},
    }


def _write_meta(root: Path, work_id: str, qid: str) -> Path:
    path = root / work_id / "meta.json"
    path.parent.mkdir()
    path.write_text(json.dumps(_meta(work_id, qid)), encoding="utf-8")
    return path


def test_series_migration_preserves_duplicate_candidates(tmp_path: Path) -> None:
    classifier = _load_classifier()
    root = tmp_path / "works"
    root.mkdir()
    series_paths = [
        _write_meta(root, "aaaaaaa-series-a", "Q2667782"),
        _write_meta(root, "bbbbbbb-series-b", "Q2667782"),
    ]
    duplicate_paths = [
        _write_meta(root, "ccccccc-duplicate-a", "Q900"),
        _write_meta(root, "ddddddd-duplicate-b", "Q900"),
    ]
    report = {
        "shared_qid_count": 2,
        "records": [
            {
                "qid": "Q2667782",
                "n_sidecars": 2,
                "classification": "series-qid",
                "evidence_p31": ["Q15727816"],
                "work_ids": ["aaaaaaa-series-a", "bbbbbbb-series-b"],
            },
            {
                "qid": "Q900",
                "n_sidecars": 2,
                "classification": "duplicate-candidate",
                "evidence_p31": ["Q3305213"],
                "work_ids": ["ccccccc-duplicate-a", "ddddddd-duplicate-b"],
            },
        ],
        "adjudications": [],
    }

    changed = classifier.apply_series_migration(root, report, timestamp="2026-08-15T12:00:00+00:00")
    classifier.check_report(report, root)

    assert changed == 2
    for path in series_paths:
        stable = json.loads(path.read_text(encoding="utf-8"))["stable_identifiers"]
        assert stable == {"part_of_q": "Q2667782"}
    for path in duplicate_paths:
        stable = json.loads(path.read_text(encoding="utf-8"))["stable_identifiers"]
        assert stable == {"wikidata_q": "Q900"}
