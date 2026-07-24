"""Tests for the additive field provenance sidecar ledger."""

from __future__ import annotations

from copy import deepcopy

import jsonschema
import pytest

from fine_art_archive import provenance, sidecar

MINIMAL_VALID = {
    "work_id": "4f3a2b8-after-the-bullfight-cassatt",
    "schema_version": "1.0",
    "artist": {"name": "Mary Cassatt"},
    "title": "After the Bullfight",
    "files": {
        "master": {
            "filename": "master.jpeg",
            "sha256": "4f3a2b8" + ("0" * 57),
            "size_bytes": 12378451,
            "ingested_at": "2026-05-16T21:30:00Z",
        }
    },
    "history": [{"ts": "2026-05-16T21:30:00Z", "actor": "codex", "op": "ingested"}],
}


def test_field_provenance_schema_is_additive_and_validates_entries():
    meta = deepcopy(MINIMAL_VALID)
    meta["field_provenance"] = {
        "medium": {
            "status": "available",
            "source": "museum_catalog",
            "source_ref": None,
            "checked_at": "2026-07-24T17:00:00Z",
            "note": None,
        }
    }

    sidecar.validate(meta)
    assert sidecar.is_valid(MINIMAL_VALID)


def test_invalid_field_provenance_status_fails_schema_validation():
    meta = deepcopy(MINIMAL_VALID)
    meta["field_provenance"] = {"medium": {"status": "guessed"}}

    with pytest.raises(jsonschema.ValidationError):
        sidecar.validate(meta)


def test_get_set_and_needs_research_round_trip():
    meta = deepcopy(MINIMAL_VALID)

    assert provenance.get(meta, "medium") is None
    assert provenance.needs_research(meta, "medium")

    entry = provenance.set(
        meta,
        "medium",
        "available",
        "museum_catalog",
        source_ref="https://example.test/work/1",
        checked_at="2026-07-24T17:00:00Z",
        note="Catalogued medium.",
    )

    assert provenance.get(meta, "medium") == entry
    assert not provenance.needs_research(meta, "medium")

    provenance.set(meta, "category", "unverified", "filename_backfill")
    provenance.set(meta, "dimensions_original", "not_researched", "migration")
    provenance.set(meta, "title", "not_available", "museum_catalog")
    assert provenance.needs_research(meta, "category")
    assert provenance.needs_research(meta, "dimensions_original")
    assert not provenance.needs_research(meta, "title")


def test_set_rejects_unknown_status_and_stamps_timestamp():
    meta = deepcopy(MINIMAL_VALID)

    with pytest.raises(ValueError, match="unsupported provenance status"):
        provenance.set(meta, "medium", "guessed", "museum_catalog")

    entry = provenance.set(meta, "medium", "conflicting", "museum_catalog")
    assert entry["checked_at"].endswith("Z")


def test_filename_backfill_migration_marks_present_fields_without_overwriting():
    meta = deepcopy(MINIMAL_VALID)
    meta.update(
        {
            "medium": "Oil on canvas",
            "category": "painting",
            "dimensions_original": {"h_cm": 82.5, "w_cm": 64.0},
        }
    )
    original_dimensions = deepcopy(meta["dimensions_original"])
    provenance.set(meta, "medium", "available", "museum_catalog")

    marked = provenance.mark_filename_backfilled_fields(meta)

    assert marked == ["category", "dimensions_original"]
    assert provenance.get(meta, "medium")["status"] == "available"
    assert provenance.get(meta, "category")["status"] == "unverified"
    assert provenance.get(meta, "dimensions_original")["status"] == "unverified"
    assert meta["dimensions_original"] == original_dimensions
