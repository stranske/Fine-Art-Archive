"""Tests for the hand-verified work-QID re-resolution pass."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from scripts.reresolve_work_qids import (
    QID_PROV_FIELD,
    RESOLUTIONS,
    Resolution,
    reresolve,
)

from fine_art_archive import sidecar

BASE: dict[str, Any] = {
    "work_id": "1111111-example",
    "schema_version": "1.0",
    "artist": {"name": "Example"},
    "title": "Example",
    "year": "1889",
    "files": {
        "master": {
            "filename": "master.jpeg",
            "sha256": "1111111" + ("0" * 57),
            "size_bytes": 10,
            "ingested_at": "2026-05-16T21:30:00Z",
        }
    },
    "history": [{"ts": "2026-05-16T21:30:00Z", "actor": "codex", "op": "ingested"}],
}

# Two hand-verified corrections exercised by the tests: one that sets a new QID
# + category, one that clears the QID.
FIX = Resolution(
    old_qid="Q32",
    old_entity="country",
    new_qid="Q3268045",
    new_entity="Luxe, Calme et Volupté",
    category="painting",
    note="verified test fixture",
)
CLEAR = Resolution(
    old_qid="Q18869",
    old_entity="region",
    new_qid=None,
    new_entity=None,
    category=None,
    note="no work entity",
)
TABLE = {"1111aaa-fix": FIX, "2222bbb-clear": CLEAR}


def _write(tmp_path: Path, work_id: str, qid: str, **overrides: Any) -> Path:
    meta = deepcopy(BASE)
    meta["work_id"] = work_id
    meta["stable_identifiers"] = {"wikidata_q": qid}
    meta.update(overrides)
    path = tmp_path / "staging" / work_id / "meta.json"
    sidecar.write(path, meta)
    return path


def test_apply_sets_new_qid_category_and_provenance(tmp_path: Path) -> None:
    path = _write(tmp_path, "1111aaa-fix", "Q32", category=None)
    stats, outcomes = reresolve(path.parents[1], resolutions=TABLE, apply=True)
    assert stats.matched == 1 and stats.changed == 1 and stats.skipped_guard == 0
    result = sidecar.load_validated(path)
    assert result["stable_identifiers"]["wikidata_q"] == "Q3268045"
    assert result["category"] == "painting"
    qid_prov = result["field_provenance"][QID_PROV_FIELD]
    assert qid_prov["status"] == "available"
    assert qid_prov["source"] == "wikidata"
    assert qid_prov["source_ref"] == "https://www.wikidata.org/wiki/Q3268045"
    assert result["field_provenance"]["category"]["status"] == "available"
    assert any(line.startswith("OK    1111aaa-fix") for line in outcomes)


def test_apply_clears_qid_and_records_not_available(tmp_path: Path) -> None:
    path = _write(tmp_path, "2222bbb-clear", "Q18869", category=None)
    reresolve(path.parents[1], resolutions=TABLE, apply=True)
    result = sidecar.load_validated(path)
    assert result["stable_identifiers"]["wikidata_q"] is None
    qid_prov = result["field_provenance"][QID_PROV_FIELD]
    assert qid_prov["status"] == "not_available"
    assert qid_prov["source_ref"] is None
    # clearing must not invent a category
    assert result.get("category") is None
    assert "category" not in result.get("field_provenance", {})


def test_guard_skips_when_current_qid_differs(tmp_path: Path) -> None:
    # sidecar already carries some other QID -> the audit is stale, don't clobber
    path = _write(tmp_path, "1111aaa-fix", "Q999999", category=None)
    stats, outcomes = reresolve(path.parents[1], resolutions=TABLE, apply=True)
    assert stats.matched == 1 and stats.changed == 0 and stats.skipped_guard == 1
    assert sidecar.load(path)["stable_identifiers"]["wikidata_q"] == "Q999999"
    assert any(line.startswith("SKIP  1111aaa-fix") for line in outcomes)


def test_dry_run_does_not_write(tmp_path: Path) -> None:
    path = _write(tmp_path, "1111aaa-fix", "Q32", category=None)
    stats, _ = reresolve(path.parents[1], resolutions=TABLE, apply=False)
    assert stats.changed == 1 and stats.mirrored == 0
    on_disk = sidecar.load(path)
    assert on_disk["stable_identifiers"]["wikidata_q"] == "Q32"  # unchanged
    assert "field_provenance" not in on_disk


def test_mirror_and_log_written_on_apply(tmp_path: Path) -> None:
    path = _write(tmp_path, "1111aaa-fix", "Q32", category=None)
    mirror = tmp_path / "art" / "1111aaa-fix" / "meta.json"
    sidecar.write(mirror, sidecar.load(path))
    log = tmp_path / "operations.log"
    stats, _ = reresolve(
        path.parents[1],
        resolutions=TABLE,
        art_works_root=tmp_path / "art",
        operations_log=log,
        apply=True,
    )
    assert stats.mirrored == 1
    assert sidecar.load(mirror)["stable_identifiers"]["wikidata_q"] == "Q3268045"
    assert log.exists() and '"op": "work_qid_reresolve"' in log.read_text()


def test_untouched_work_is_ignored(tmp_path: Path) -> None:
    path = _write(tmp_path, "3333ccc-other", "Q1", category="drawing")
    stats, _ = reresolve(path.parents[1], resolutions=TABLE, apply=True)
    assert stats.matched == 0 and stats.changed == 0
    assert sidecar.load(path)["category"] == "drawing"  # untouched


def test_real_resolution_table_categories_are_valid_enum() -> None:
    schema = sidecar.load_schema()
    allowed = set(schema["properties"]["category"]["enum"])
    cats = {res.category for res in RESOLUTIONS.values() if res.category is not None}
    assert cats <= allowed, cats - allowed


def test_real_resolution_table_qids_well_formed() -> None:
    for res in RESOLUTIONS.values():
        assert res.new_qid is None or res.new_qid.startswith("Q")
        assert res.old_qid.startswith("Q")
