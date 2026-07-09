from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fine_art_archive.fixity import (
    create_bag,
    record_fixity,
    sha256_file,
    verify_bag,
    verify_fixity,
)


def _sidecar(master_sha: str) -> dict[str, Any]:
    return {
        "work_id": "4f3a2b8-after-the-bullfight-cassatt",
        "schema_version": "1.0",
        "artist": {"name": "Mary Cassatt"},
        "title": "After the Bullfight",
        "files": {
            "master": {
                "filename": "master.jpeg",
                "sha256": master_sha,
                "size_bytes": 11,
                "ingested_at": "2026-05-16T21:30:00Z",
            }
        },
        "history": [{"ts": "2026-05-16T21:30:00Z", "actor": "codex", "op": "ingested"}],
    }


def _work_dir(tmp_path: Path, *, payload: bytes = b"master-data") -> tuple[Path, Path, Path]:
    work_dir = tmp_path / "work"
    work_dir.mkdir()
    master = work_dir / "master.jpeg"
    master.write_bytes(payload)
    meta = work_dir / "meta.json"
    meta.write_text(json.dumps(_sidecar(sha256_file(master))), encoding="utf-8")
    return work_dir, meta, master


def test_record_fixity_appends_verification_event(tmp_path: Path) -> None:
    _, meta_path, master = _work_dir(tmp_path)
    original = json.loads(meta_path.read_text(encoding="utf-8"))
    original["files"]["master"]["sha256"] = "0" * 64
    meta_path.write_text(json.dumps(original), encoding="utf-8")

    result = record_fixity(meta_path, master_path=master, verified_at="2026-07-09T14:00:00Z")

    updated = json.loads(meta_path.read_text(encoding="utf-8"))
    assert result.actual_sha256 == sha256_file(master)
    assert updated["files"]["master"]["sha256"] == result.actual_sha256
    assert updated["verification"]["fixity_events"][-1] == {
        "algorithm": "sha256",
        "sha256": result.actual_sha256,
        "expected_sha256": "0" * 64,
        "verified_at": "2026-07-09T14:00:00Z",
        "master_path": "master.jpeg",
        "status": "recorded",
    }
    assert updated["history"][-1]["op"] == "fixity_verified"


def test_verify_fixity_reports_corrupted_master(tmp_path: Path) -> None:
    _, meta_path, master = _work_dir(tmp_path)

    master.write_bytes(b"master-data!")
    result = verify_fixity(meta_path, master_path=master)

    assert not result.matched
    assert result.expected_sha256 != result.actual_sha256


def test_create_bag_and_verify_manifest(tmp_path: Path) -> None:
    work_dir, _, _ = _work_dir(tmp_path)
    bag_dir = tmp_path / "bag"

    create_bag([work_dir], bag_dir)

    manifest = bag_dir / "manifest-sha256.txt"
    assert manifest.exists()
    manifest_text = manifest.read_text(encoding="utf-8")
    assert "data/works/work/master.jpeg" in manifest_text
    assert "data/works/work/meta.json" in manifest_text
    assert verify_bag(bag_dir).valid


def test_bag_verify_detects_payload_mismatch(tmp_path: Path) -> None:
    work_dir, _, _ = _work_dir(tmp_path)
    bag_dir = tmp_path / "bag"
    create_bag([work_dir], bag_dir)

    (bag_dir / "data" / "works" / "work" / "master.jpeg").write_bytes(b"corrupt")
    result = verify_bag(bag_dir)

    assert not result.valid
    assert result.mismatches == ("data/works/work/master.jpeg",)
