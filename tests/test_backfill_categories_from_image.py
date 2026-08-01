"""Tests for the image-based category backfill."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from scripts.backfill_categories_from_image import IMAGE_CATEGORIES, backfill

from fine_art_archive import sidecar

CATEGORY_ENUM = {
    "painting",
    "drawing",
    "print",
    "sculpture",
    "photograph",
    "illuminated_manuscript",
    "fresco",
    "mural",
    "tapestry",
    "altarpiece",
    "icon",
    "architecture",
    "stained_glass",
    "mosaic",
    "monument",
    "architectural_sculpture",
    "other",
}

BASE: dict[str, Any] = {
    "work_id": "b9703b0-self-portrait-gogh",  # a real key in IMAGE_CATEGORIES
    "schema_version": "1.0",
    "artist": {"name": "Vincent van Gogh"},
    "title": "Self-Portrait",
    "year": "1887",
    "category": None,
    "files": {
        "master": {
            "filename": "master.jpeg",
            "sha256": "b9703b0" + ("0" * 57),
            "size_bytes": 10,
            "ingested_at": "2026-05-16T21:30:00Z",
        }
    },
    "history": [{"ts": "2026-05-16T21:30:00Z", "actor": "codex", "op": "ingested"}],
}


def test_table_values_are_valid_enum_members() -> None:
    assert set(IMAGE_CATEGORIES.values()) <= CATEGORY_ENUM
    assert len(IMAGE_CATEGORIES) == 80


def _write(tmp_path: Path, **overrides: Any) -> Path:
    meta = deepcopy(BASE)
    meta.update(overrides)
    path = tmp_path / "staging" / str(meta["work_id"]) / "meta.json"
    sidecar.write(path, meta)
    return path


def test_apply_writes_unverified_category(tmp_path: Path) -> None:
    path = _write(tmp_path)
    stats, by_cat = backfill(path.parents[1], apply=True)
    assert stats.matched == 1 and stats.updated_works == 1
    result = sidecar.load_validated(path)
    assert result["category"] == "painting"
    prov = result["field_provenance"]["category"]
    assert prov["status"] == "unverified" and prov["source"] == "image"
    assert by_cat["painting"] == 1


def test_dry_run_does_not_write(tmp_path: Path) -> None:
    path = _write(tmp_path)
    stats, _ = backfill(path.parents[1], apply=False)
    assert stats.matched == 1 and stats.updated_works == 0
    assert sidecar.load(path).get("category") is None


def test_guard_skips_already_categorized(tmp_path: Path) -> None:
    path = _write(tmp_path, category="drawing")  # a higher-confidence pass set it
    stats, _ = backfill(path.parents[1], apply=True)
    assert stats.matched == 0 and stats.skipped_categorized == 1
    assert sidecar.load(path)["category"] == "drawing"  # not overridden
