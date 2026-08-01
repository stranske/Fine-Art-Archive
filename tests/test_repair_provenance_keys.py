"""Tests for the field_provenance non-schema-key repair."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from scripts.repair_provenance_keys import repair, strip_nonschema_keys

from fine_art_archive import sidecar

BASE: dict[str, Any] = {
    "work_id": "5555555-example",
    "schema_version": "1.0",
    "artist": {"name": "Renoir", "wikidata_q": "Q39931"},
    "title": "In Summer",
    "year": "1868",
    "files": {
        "master": {
            "filename": "master.jpeg",
            "sha256": "5555555" + ("0" * 57),
            "size_bytes": 10,
            "ingested_at": "2026-05-16T21:30:00Z",
        }
    },
    "history": [{"ts": "2026-05-16T21:30:00Z", "actor": "codex", "op": "ingested"}],
    "field_provenance": {
        "artist_qid_repair": {
            "status": "available",
            "source": "fix_corrupt_artist_qids",
            "source_ref": "https://www.wikidata.org/wiki/Q39931",
            "note": "Replaced with Q39931.",
            "prior_canonical": "Q352",
            "prior_mirror": "Q352",
        }
    },
}


def test_strip_folds_into_note_and_validates() -> None:
    meta = deepcopy(BASE)
    entries, keys = strip_nonschema_keys(meta)
    assert entries == 1 and keys == 2
    entry = meta["field_provenance"]["artist_qid_repair"]
    assert set(entry) == {"status", "source", "source_ref", "note"}
    assert "prior_canonical=Q352" in entry["note"]  # folded, lossless
    sidecar.validate(meta)  # now schema-valid


def test_strip_is_idempotent_on_clean_entry() -> None:
    clean = deepcopy(BASE)
    strip_nonschema_keys(clean)
    entries, keys = strip_nonschema_keys(clean)  # second pass
    assert entries == 0 and keys == 0


def test_repair_apply_writes_valid_sidecar(tmp_path: Path) -> None:
    path = tmp_path / "staging" / str(BASE["work_id"]) / "meta.json"
    # write raw (bypass validation, since the fixture is intentionally invalid)
    path.parent.mkdir(parents=True, exist_ok=True)
    import json

    path.write_text(json.dumps(BASE), encoding="utf-8")

    stats, sources = repair(path.parents[1], apply=True)
    assert stats.repaired == 1 and stats.keys_stripped == 2
    assert sources["fix_corrupt_artist_qids"] == 1
    result = sidecar.load_validated(path)  # validates on load
    assert "prior_canonical" not in result["field_provenance"]["artist_qid_repair"]
