"""Tests for owner-approved false variant unlink remediation."""

from __future__ import annotations

import json
from pathlib import Path

from fine_art_archive import sidecar
from fine_art_archive.identity.variant_identity import classify_variant_links
from fine_art_archive.identity.variant_remediation import remediate_reciprocal_false_variants


def _meta(work_id: str, qid: str, *, variants: list[dict[str, object]] | None = None) -> dict:
    prefix = work_id.split("-", 1)[0]
    files: dict[str, object] = {
        "master": {
            "filename": "master.jpeg",
            "sha256": prefix + ("0" * (64 - len(prefix))),
            "size_bytes": 10777685,
            "ingested_at": "2026-05-24T05:15:38+00:00",
        }
    }
    if variants is not None:
        files["variants"] = variants
    return {
        "work_id": work_id,
        "schema_version": "1.0",
        "artist": {"name": "Edvard Munch"},
        "title": "The Scream",
        "stable_identifiers": {"wikidata_q": qid},
        "files": files,
        "history": [{"ts": "2026-05-24T05:15:38+00:00", "actor": "test", "op": "seed"}],
    }


def _write_pair(root: Path, work_id_a: str, qid_a: str, work_id_b: str, qid_b: str) -> None:
    rel_a = f"works/{work_id_a}/master.jpeg"
    rel_b = f"works/{work_id_b}/master.jpeg"
    sidecar.write(
        root / work_id_a / "meta.json",
        _meta(
            work_id_a,
            qid_a,
            variants=[{"rel_path": rel_b, "role": "portrait-crop", "filename": "master.jpeg"}],
        ),
    )
    sidecar.write(
        root / work_id_b / "meta.json",
        _meta(
            work_id_b,
            qid_b,
            variants=[{"rel_path": rel_a, "role": "meural-framed", "filename": "master.jpeg"}],
        ),
    )


def test_remediate_reciprocal_false_variants_preserves_qids(tmp_path: Path) -> None:
    work_id_a = "0ba0ac6-the-scream-munch"
    work_id_b = "94de558-the-scream-munch"
    _write_pair(tmp_path, work_id_a, "Q18891156", work_id_b, "Q18891158")
    operations_log = tmp_path / "operations.log"

    stats, results = remediate_reciprocal_false_variants(
        tmp_path,
        work_id_a,
        work_id_b,
        grant="grant=test",
        actor="test",
        apply=True,
        operations_log=operations_log,
    )

    assert stats.planned == 2
    assert stats.removed == 2
    assert stats.wrote == 2
    assert all(item.qid_after is not None for item in results)
    assert all(item.variant_count_after == 0 for item in results)

    metas = [
        sidecar.load(tmp_path / work_id_a / "meta.json"),
        sidecar.load(tmp_path / work_id_b / "meta.json"),
    ]
    assert classify_variant_links(metas) == []
    assert metas[0]["stable_identifiers"]["wikidata_q"] == "Q18891156"
    assert metas[1]["stable_identifiers"]["wikidata_q"] == "Q18891158"
    assert any(
        event["op"] == "remove-false-variant-link" for meta in metas for event in meta["history"]
    )

    log_entries = [
        json.loads(line) for line in operations_log.read_text(encoding="utf-8").splitlines()
    ]
    assert len(log_entries) == 2
    assert {entry["work_id"] for entry in log_entries} == {work_id_a, work_id_b}


def test_dry_run_does_not_write_or_log(tmp_path: Path) -> None:
    work_id_a = "0ba0ac6-the-scream-munch"
    work_id_b = "94de558-the-scream-munch"
    _write_pair(tmp_path, work_id_a, "Q1", work_id_b, "Q2")
    path_a = tmp_path / work_id_a / "meta.json"
    path_b = tmp_path / work_id_b / "meta.json"
    before_a = path_a.read_text(encoding="utf-8")
    before_b = path_b.read_text(encoding="utf-8")
    operations_log = tmp_path / "operations.log"

    stats, _ = remediate_reciprocal_false_variants(
        tmp_path,
        work_id_a,
        work_id_b,
        grant="grant=test",
        actor="test",
        apply=False,
        operations_log=operations_log,
    )

    assert stats.removed == 2
    assert stats.wrote == 0
    assert path_a.read_text(encoding="utf-8") == before_a
    assert path_b.read_text(encoding="utf-8") == before_b
    assert not operations_log.exists()
