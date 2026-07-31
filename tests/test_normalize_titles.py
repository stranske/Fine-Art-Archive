"""Tests for the reviewed-title normalization pass."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from scripts.normalize_titles import (
    TITLE_CORRECTIONS,
    TitleFix,
    normalize_titles,
)

from fine_art_archive import sidecar


def _sidecar(work_id: str, title: str) -> dict[str, Any]:
    return {
        "work_id": work_id,
        "schema_version": "1.0",
        "artist": {"name": "Some Artist"},
        "title": title,
        "files": {
            "master": {
                "filename": "master.jpeg",
                "sha256": "a" * 64,
                "size_bytes": 1,
                "ingested_at": "2026-05-16T21:30:00Z",
            }
        },
        "history": [{"ts": "2026-05-16T21:30:00Z", "actor": "codex", "op": "ingested"}],
    }


def _write_staging(tmp_path: Path, work_id: str, title: str) -> Path:
    path = tmp_path / work_id / "meta.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(_sidecar(work_id, title)), encoding="utf-8")
    return path


# --- data integrity of the reviewed map --------------------------------------


def test_every_correction_is_a_real_change() -> None:
    for work_id, fix in TITLE_CORRECTIONS.items():
        assert fix.title != fix.expected, work_id
        assert fix.title.strip() == fix.title and fix.title, work_id
        assert fix.note, work_id


def test_corrected_titles_pass_schema() -> None:
    for work_id, fix in TITLE_CORRECTIONS.items():
        sidecar.validate(_sidecar(work_id, fix.title))


# --- dry-run --------------------------------------------------------------------


def test_dry_run_reports_but_does_not_write(tmp_path: Path) -> None:
    work_id, fix = next(iter(TITLE_CORRECTIONS.items()))
    path = _write_staging(tmp_path, work_id, fix.expected)

    stats = normalize_titles(tmp_path, corrections={work_id: fix}, apply=False)

    assert stats.attempted == 1
    assert stats.updated == 0
    assert json.loads(path.read_text())["title"] == fix.expected  # untouched on disk


# --- apply ----------------------------------------------------------------------


def test_apply_rewrites_title_and_records_provenance(tmp_path: Path) -> None:
    work_id, fix = next(iter(TITLE_CORRECTIONS.items()))
    path = _write_staging(tmp_path, work_id, fix.expected)

    stats = normalize_titles(tmp_path, corrections={work_id: fix}, apply=True)

    assert stats.updated == 1
    written = json.loads(path.read_text())
    assert written["title"] == fix.title
    entry = written["field_provenance"]["title"]
    assert entry["status"] == "available"
    assert entry["source"] == "curated"
    assert entry["note"] == fix.note
    assert entry["checked_at"]


def test_apply_mirrors_and_logs(tmp_path: Path) -> None:
    work_id = "0a005ef-the-shipbuilder-and-his-wife-jan"
    fix = TITLE_CORRECTIONS[work_id]
    _write_staging(tmp_path, work_id, fix.expected)

    art_root = tmp_path / "art"
    mirror = art_root / work_id / "meta.json"
    mirror.parent.mkdir(parents=True)
    mirror.write_text(json.dumps(_sidecar(work_id, fix.expected)), encoding="utf-8")
    log = tmp_path / "operations.log"

    stats = normalize_titles(
        tmp_path,
        corrections={work_id: fix},
        art_works_root=art_root,
        operations_log=log,
        apply=True,
    )

    assert stats.mirrored == 1
    assert json.loads(mirror.read_text())["title"] == fix.title
    logged = json.loads(log.read_text().strip())
    assert logged["op"] == "title_normalization"
    assert logged["actor"] == "normalize_titles"
    assert logged["old_title"] == fix.expected
    assert logged["new_title"] == fix.title


# --- guards ---------------------------------------------------------------------


def test_drifted_title_is_skipped_not_clobbered(tmp_path: Path) -> None:
    work_id, fix = next(iter(TITLE_CORRECTIONS.items()))
    path = _write_staging(tmp_path, work_id, "A totally different title")

    stats = normalize_titles(tmp_path, corrections={work_id: fix}, apply=True)

    assert stats.updated == 0
    assert stats.skipped_drift == [work_id]
    assert json.loads(path.read_text())["title"] == "A totally different title"


def test_already_normalized_is_idempotent(tmp_path: Path) -> None:
    work_id, fix = next(iter(TITLE_CORRECTIONS.items()))
    path = _write_staging(tmp_path, work_id, fix.title)  # already the corrected value

    stats = normalize_titles(tmp_path, corrections={work_id: fix}, apply=True)

    assert stats.updated == 0
    assert stats.skipped_drift == []  # correct value is not "drift"
    assert json.loads(path.read_text())["title"] == fix.title


def test_missing_work_is_reported(tmp_path: Path) -> None:
    work_id, fix = next(iter(TITLE_CORRECTIONS.items()))

    stats = normalize_titles(tmp_path, corrections={work_id: fix}, apply=True)

    assert stats.updated == 0
    assert stats.missing == [work_id]


def test_empty_result_would_fail_schema(tmp_path: Path) -> None:
    import jsonschema

    work_id = "x-empty"
    fix = TitleFix(expected="junk", title="", note="n")
    _write_staging(tmp_path, work_id, "junk")

    with pytest.raises(jsonschema.ValidationError):
        normalize_titles(tmp_path, corrections={work_id: fix}, apply=True)
