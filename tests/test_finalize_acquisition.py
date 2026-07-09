"""Tests for the post-acquisition finalizer script (scripts/finalize_acquisition.py).

Covers the repo-specific helper that recomputes a master's sha256/size/dims and
re-derives the work_id, using a synthetic JPEG (no real archive data, no torch).
The full run_finalize integration (verify + quality + sidecar write) is exercised
operationally against real masters.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from PIL import Image

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "scripts"))
sys.path.insert(0, str(_REPO / "src"))

import finalize_acquisition as fa  # noqa: E402


def _make_jpeg(path: Path, w: int = 320, h: int = 200) -> Path:
    Image.new("RGB", (w, h), (123, 200, 80)).save(path, "JPEG", quality=90)
    return path


def test_module_imports_pipeline_symbols() -> None:
    # Confirms the script wires to the in-repo library (sidecar/verify/quality).
    assert callable(fa.run_finalize)
    assert callable(fa.update_files_master_from_bytes)


def test_update_files_master_from_bytes(tmp_path: Path) -> None:
    master = _make_jpeg(tmp_path / "master.jpg")
    meta = {"work_id": "placeholder-the-little-street-vermeer", "files": {"master": {}}}

    fa.update_files_master_from_bytes(meta, master)

    m = meta["files"]["master"]
    assert len(m["sha256"]) == 64 and all(c in "0123456789abcdef" for c in m["sha256"])
    assert m["size_bytes"] == master.stat().st_size
    assert m["dimensions_px"] == [320, 200]
    assert m["filename"] == "master.jpg"
    assert "ICC" in m["color_profile"] or "sRGB" in m["color_profile"]
    # work_id re-derived: 7-hex sha prefix + preserved slug (schema: ^[0-9a-f]{7}-...)
    assert meta["work_id"].startswith(m["sha256"][:7])
    assert meta["work_id"].endswith("the-little-street-vermeer")


def test_work_id_slug_fallback(tmp_path: Path) -> None:
    master = _make_jpeg(tmp_path / "master.jpg")
    meta = {"work_id": "untitledplaceholder", "files": {"master": {}}}  # no hyphen
    fa.update_files_master_from_bytes(meta, master)
    assert meta["work_id"].endswith("untitled")


def test_run_finalize_writes_source_quality_inputs(tmp_path: Path) -> None:
    _make_jpeg(tmp_path / "master.jpg", w=400, h=300)
    meta = {
        "work_id": "0000000-landscape-fixture",
        "schema_version": "1.0",
        "artist": {"name": "Fixture Artist"},
        "title": "Landscape Fixture",
        "dimensions_original": {"h_cm": 30.0, "w_cm": 40.0},
        "stable_identifiers": {"wikidata_q": None},
        "files": {
            "master": {
                "filename": "master.jpg",
                "sha256": "0" * 64,
                "size_bytes": 0,
                "ingested_at": "2026-06-19T00:00:00+00:00",
            }
        },
        "history": [
            {
                "ts": "2026-06-19T00:00:00+00:00",
                "actor": "test",
                "op": "create",
            }
        ],
    }
    (tmp_path / "meta.json").write_text(json.dumps(meta), encoding="utf-8")

    finalized = fa.run_finalize(tmp_path, refetch_master_hash=True, enrich_getty=False)

    inputs = finalized["verification"]["source_quality_inputs"]
    assert set(inputs) == {"verify_match", "phash_match", "aspect_match", "dim_match"}
    assert inputs["verify_match"] is True
    assert inputs["aspect_match"] is True
    assert inputs["phash_match"] is None
    assert inputs["dim_match"] is None


def test_run_finalize_can_apply_getty_enrichment(tmp_path: Path, monkeypatch) -> None:
    _make_jpeg(tmp_path / "master.jpg", w=400, h=300)
    meta = {
        "work_id": "0000000-landscape-fixture",
        "schema_version": "1.0",
        "artist": {"name": "Fixture Artist"},
        "title": "Landscape Fixture",
        "dimensions_original": {"h_cm": 30.0, "w_cm": 40.0},
        "stable_identifiers": {"wikidata_q": None},
        "files": {
            "master": {
                "filename": "master.jpg",
                "sha256": "0" * 64,
                "size_bytes": 0,
                "ingested_at": "2026-06-19T00:00:00+00:00",
            }
        },
        "history": [
            {
                "ts": "2026-06-19T00:00:00+00:00",
                "actor": "test",
                "op": "create",
            }
        ],
    }
    (tmp_path / "meta.json").write_text(json.dumps(meta), encoding="utf-8")

    def fake_enrich(meta: dict, *, timeout: int) -> dict:
        enriched = json.loads(json.dumps(meta))
        enriched.setdefault("stable_identifiers", {})["ulan"] = "http://vocab.getty.edu/ulan/1"
        return enriched

    monkeypatch.setattr(fa, "enrich_sidecar_getty", fake_enrich)

    finalized = fa.run_finalize(tmp_path, refetch_master_hash=True, enrich_getty=True)

    assert finalized["stable_identifiers"]["ulan"] == "http://vocab.getty.edu/ulan/1"
    written = json.loads((tmp_path / "meta.json").read_text(encoding="utf-8"))
    assert written["stable_identifiers"]["ulan"] == "http://vocab.getty.edu/ulan/1"
