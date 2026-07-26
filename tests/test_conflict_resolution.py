"""Tests for deterministic conflict resolution (medium vocab + CLI policy)."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from scripts.resolve_conflicts import resolve_sidecars

from fine_art_archive import provenance, sidecar
from fine_art_archive.enrichment import medium_vocab

BASE_SIDECAR: dict[str, Any] = {
    "work_id": "1111111-example-work",
    "schema_version": "1.0",
    "artist": {"name": "Example Painter"},
    "title": "Example Work",
    "files": {
        "master": {
            "filename": "master.jpeg",
            "sha256": "1111111" + ("0" * 57),
            "size_bytes": 100,
            "ingested_at": "2026-05-16T21:30:00Z",
        }
    },
    "history": [{"ts": "2026-05-16T21:30:00Z", "actor": "codex", "op": "ingested"}],
}


def _conflict_note(original: str) -> str:
    return f'Higher-tier source replaced lower-tier existing value "{original}".'


# --- medium vocabulary -----------------------------------------------------
def test_reconcile_vocabulary_equivalent() -> None:
    assert medium_vocab.reconcile("oil paint, canvas", "oil on canvas") == (
        "agree",
        "Oil on canvas",
    )


def test_reconcile_merges_more_complete_side() -> None:
    # curated "Canvas" (support only) + source "oil paint, canvas" -> merged
    assert medium_vocab.reconcile("oil paint, canvas", "Canvas") == ("agree", "Oil on canvas")
    assert medium_vocab.reconcile("oil", "oil on panel") == ("agree", "Oil on panel")


def test_reconcile_strips_leaked_artist_name() -> None:
    assert medium_vocab.reconcile("oil paint, canvas", "Paul Cezanne; oil on canvas") == (
        "agree",
        "Oil on canvas",
    )


def test_reconcile_reports_genuine_material_conflict() -> None:
    assert medium_vocab.reconcile("oil paint, panel", "oil on canvas")[0] == "conflict"
    assert medium_vocab.reconcile("pastel, paper", "oil on canvas")[0] == "conflict"


def test_reconcile_unparsed_side() -> None:
    assert medium_vocab.reconcile("oil on canvas", "an undated study")[0] == "unparsed"


# --- CLI policy ------------------------------------------------------------
def _write(tmp_path: Path, field: str, current: Any, original: str) -> Path:
    meta = deepcopy(BASE_SIDECAR)
    meta[field] = current
    provenance.set(meta, field, "conflicting", "wikidata", note=_conflict_note(original))
    path = tmp_path / "staging" / str(meta["work_id"]) / "meta.json"
    sidecar.write(path, meta)
    return path


def test_medium_conflict_reconciled_to_canonical(tmp_path: Path) -> None:
    path = _write(tmp_path, "medium", "oil paint, canvas", "oil on canvas")
    stats, review = resolve_sidecars(path.parents[1])
    assert stats.reconciled_medium == 1
    result = sidecar.load_validated(path)
    assert result["medium"] == "Oil on canvas"
    assert result["field_provenance"]["medium"]["status"] == "available"
    assert review == []


def test_material_conflict_keeps_curated_and_is_reported(tmp_path: Path) -> None:
    path = _write(tmp_path, "medium", "oil paint, panel", "oil on canvas")
    stats, review = resolve_sidecars(path.parents[1])
    assert stats.material_conflicts == 1
    result = sidecar.load_validated(path)
    assert result["medium"] == "oil on canvas"  # curated kept
    assert result["field_provenance"]["medium"]["status"] == "unverified"
    assert len(review) == 1


def test_year_conflict_keeps_curated_museum_value(tmp_path: Path) -> None:
    path = _write(tmp_path, "year", "1490", "1495-1498")
    stats, _ = resolve_sidecars(path.parents[1])
    assert stats.curated_kept == 1
    result = sidecar.load_validated(path)
    assert result["year"] == "1495-1498"
    assert result["field_provenance"]["year"]["status"] == "unverified"
    assert "1490" in result["field_provenance"]["year"]["note"]


def test_non_conflicting_fields_untouched(tmp_path: Path) -> None:
    meta = deepcopy(BASE_SIDECAR)
    meta["medium"] = "Oil on canvas"
    provenance.set(meta, "medium", "available", "wikidata")
    path = tmp_path / "staging" / str(meta["work_id"]) / "meta.json"
    sidecar.write(path, meta)
    stats, _ = resolve_sidecars(path.parents[1])
    assert stats.attempted_works == 0
    assert sidecar.load_validated(path)["medium"] == "Oil on canvas"
