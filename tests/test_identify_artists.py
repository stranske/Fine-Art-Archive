"""Tests for the hand-verified artist identification pass."""

from __future__ import annotations

import re
from copy import deepcopy
from pathlib import Path
from typing import Any

from scripts.identify_artists import ARTIST_IDS, identify

from fine_art_archive import sidecar

BASE: dict[str, Any] = {
    "work_id": "3e0f4cf-marxism-will-give-health-to-the-masonite",  # a real table key
    "schema_version": "1.0",
    "artist": {"name": "Oil on masonite"},  # junk artist (medium leaked in)
    "title": "Marxism Will Give Health to the Ill",
    "year": "1954",
    "category": "painting",
    "files": {
        "master": {
            "filename": "master.jpeg",
            "sha256": "3e0f4cf" + ("0" * 57),
            "size_bytes": 10,
            "ingested_at": "2026-05-16T21:30:00Z",
        }
    },
    "history": [{"ts": "2026-05-16T21:30:00Z", "actor": "codex", "op": "ingested"}],
}


def test_table_qids_wellformed() -> None:
    assert ARTIST_IDS
    for ident in ARTIST_IDS.values():
        assert re.fullmatch(r"Q\d+", ident.qid)


def _write(tmp_path: Path, **overrides: Any) -> Path:
    meta = deepcopy(BASE)
    meta.update(overrides)
    path = tmp_path / "staging" / str(meta["work_id"]) / "meta.json"
    sidecar.write(path, meta)
    return path


def test_apply_sets_qid_and_fixes_name(tmp_path: Path) -> None:
    path = _write(tmp_path)
    stats, _ = identify(path.parents[1], apply=True)
    assert stats.changed == 1 and stats.mirrored == 0
    result = sidecar.load_validated(path)
    assert result["artist"]["wikidata_q"] == "Q5588"  # Frida Kahlo
    assert result["artist"]["name"] == "Frida Kahlo"  # junk name corrected
    assert result["field_provenance"]["artist_qid"]["status"] == "available"


def test_dry_run_does_not_write(tmp_path: Path) -> None:
    path = _write(tmp_path)
    stats, _ = identify(path.parents[1], apply=False)
    assert stats.changed == 1
    assert sidecar.load(path)["artist"].get("wikidata_q") is None


def test_guard_skips_existing_qid(tmp_path: Path) -> None:
    path = _write(tmp_path, artist={"name": "Frida Kahlo", "wikidata_q": "Q5588"})
    stats, _ = identify(path.parents[1], apply=True)
    assert stats.changed == 0 and stats.skipped_existing == 1


def test_keeps_existing_name_when_not_corrected(tmp_path: Path) -> None:
    # a table entry with name=None keeps the sidecar's (already-correct) name
    path = _write(
        tmp_path,
        work_id="6aacb85-calvin-coolidge-hopkinson",
        artist={"name": "Charles S. Hopkinson"},
        title="Calvin Coolidge",
    )
    identify(path.parents[1], apply=True)
    result = sidecar.load_validated(path)
    assert result["artist"]["wikidata_q"] == "Q5079125"
    assert result["artist"]["name"] == "Charles S. Hopkinson"  # unchanged
