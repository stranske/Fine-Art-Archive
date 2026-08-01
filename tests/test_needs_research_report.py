"""Tests for the needs-research report (Stage 3 FYI surface)."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from scripts.needs_research_report import classify_blocker, collect, is_junk_title, write_report

from fine_art_archive import sidecar

BASE: dict[str, Any] = {
    "work_id": "7777777-example",
    "schema_version": "1.0",
    "artist": {"name": "Vincent van Gogh", "wikidata_q": "Q296"},
    "title": "The Potato Eaters",
    "year": "1885",
    "category": None,
    "files": {
        "master": {
            "filename": "master.jpeg",
            "sha256": "7777777" + ("0" * 57),
            "size_bytes": 10,
            "ingested_at": "2026-05-16T21:30:00Z",
        }
    },
    "history": [{"ts": "2026-05-16T21:30:00Z", "actor": "codex", "op": "ingested"}],
}


def _write(tmp_path: Path, work_id: str, **overrides: Any) -> None:
    meta = deepcopy(BASE)
    meta["work_id"] = work_id
    meta.update(overrides)
    sidecar.write(tmp_path / "staging" / work_id / "meta.json", meta)


def test_is_junk_title() -> None:
    assert is_junk_title("34. Dwight Eisenhower, June 1956")
    assert is_junk_title("Castillo_de_Zafra")
    assert is_junk_title("")
    assert is_junk_title("Vincent van Gogh", "Vincent van Gogh")  # title == artist
    assert not is_junk_title("The Potato Eaters", "Vincent van Gogh")


def test_classify_blocker() -> None:
    assert classify_blocker(BASE) == "needs_work_qid"  # creator + real title, no work QID
    assert classify_blocker({**BASE, "artist": {"name": "Anonymous"}}) == "needs_artist_qid"
    assert classify_blocker({**BASE, "title": "37. Richard Nixon, 1973"}) == "needs_title_fix"


def test_collect_skips_categorized_and_sorts(tmp_path: Path) -> None:
    _write(tmp_path, "7777771-workqid", title="The Potato Eaters")  # needs_work_qid
    _write(tmp_path, "7777772-artist", artist={"name": "Unknown"})  # needs_artist_qid
    _write(tmp_path, "7777773-done", category="painting")  # excluded
    rows = collect(tmp_path / "staging")
    assert len(rows) == 2
    assert rows[0]["blocker"] == "needs_artist_qid"  # sorted most-actionable first
    assert rows[1]["blocker"] == "needs_work_qid"


def test_write_report_emits_files(tmp_path: Path) -> None:
    _write(tmp_path, "7777774-work", title="The Potato Eaters")
    csv_path, md_path, rows = write_report(tmp_path / "staging", tmp_path / "out")
    assert csv_path.is_file() and md_path.is_file()
    assert "needs_work_qid" in md_path.read_text()
    assert "The Potato Eaters" in csv_path.read_text()
    assert len(rows) == 1
