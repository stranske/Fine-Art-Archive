"""Tests for the corpus-wide artist.canonical identity backfill."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from scripts.backfill_artist_canonical import backfill

from fine_art_archive import sidecar


class FakeEntityClient:
    def __init__(self, data: dict[str, dict[str, Any]]) -> None:
        self._data = data
        self.calls = 0

    def get(self, url: str, *, params: Any = None) -> dict[str, Any] | None:
        self.calls += 1
        qid = url.rsplit("/", 1)[-1].removesuffix(".json")
        info = self._data.get(qid)
        if info is None:
            return None
        claims: dict[str, Any] = {}
        if info.get("birth"):
            claims["P569"] = [
                {
                    "mainsnak": {
                        "datavalue": {"value": {"time": f"+{info['birth']}-00-00T00:00:00Z"}}
                    }
                }
            ]
        if info.get("death"):
            claims["P570"] = [
                {
                    "mainsnak": {
                        "datavalue": {"value": {"time": f"+{info['death']}-00-00T00:00:00Z"}}
                    }
                }
            ]
        return {"entities": {qid: {"labels": {"en": {"value": info["label"]}}, "claims": claims}}}


BASE: dict[str, Any] = {
    "work_id": "PLACEHOLDER",
    "schema_version": "1.0",
    "artist": {"name": "Michelangelo Merisi da Caravaggio", "wikidata_q": "Q42207"},
    "title": "T",
    "year": "1600",
    "category": "painting",
    "files": {
        "master": {
            "filename": "m.jpeg",
            "sha256": "abc" + ("0" * 61),
            "size_bytes": 10,
            "ingested_at": "2026-05-16T21:30:00Z",
        }
    },
    "history": [{"ts": "2026-05-16T21:30:00Z", "actor": "codex", "op": "ingested"}],
}

CLIENT = FakeEntityClient({"Q42207": {"label": "Caravaggio", "birth": "1571", "death": "1610"}})


def _write(tmp_path: Path, work_id: str, **overrides: Any) -> Path:
    meta = deepcopy(BASE)
    meta["work_id"] = work_id
    meta.update(overrides)
    path = tmp_path / "staging" / work_id / "meta.json"
    sidecar.write(path, meta)
    return path


def test_fills_canonical_from_qid(tmp_path: Path) -> None:
    path = _write(tmp_path, "1111111-a")
    stats, _ = backfill(path.parents[1], client=CLIENT, apply=True, now="2026-08-01T00:00:00Z")
    assert stats.resolved == 1 and stats.updated_works == 1
    can = sidecar.load_validated(path)["artist"]["canonical"]
    assert can["display_name"] == "Caravaggio"
    assert can["lifespan"] == "1571–1610"
    assert can["family_key"] == "caravaggio"
    assert can["wikidata_q"] == "Q42207"


def test_name_is_untouched(tmp_path: Path) -> None:
    path = _write(tmp_path, "1111112-b")
    backfill(path.parents[1], client=CLIENT, apply=True)
    assert sidecar.load(path)["artist"]["name"] == "Michelangelo Merisi da Caravaggio"


def test_skips_when_display_name_present(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "1111113-c",
        artist={"name": "x", "wikidata_q": "Q42207", "canonical": {"display_name": "Caravaggio"}},
    )
    stats, _ = backfill(path.parents[1], client=CLIENT, apply=True)
    assert stats.candidates == 0


def test_skips_when_no_qid(tmp_path: Path) -> None:
    path = _write(tmp_path, "1111114-d", artist={"name": "Anonymous"})
    stats, _ = backfill(path.parents[1], client=CLIENT, apply=True)
    assert stats.candidates == 0


def test_caches_per_artist(tmp_path: Path) -> None:
    client = FakeEntityClient({"Q42207": {"label": "Caravaggio", "birth": "1571", "death": "1610"}})
    _write(tmp_path, "1111115-e")
    _write(tmp_path, "1111116-f")  # same artist QID
    stats, _ = backfill(tmp_path / "staging", client=client, apply=True)
    assert stats.resolved == 2 and stats.distinct_artists == 1 and client.calls == 1


def test_unresolved_qid_left_untouched(tmp_path: Path) -> None:
    path = _write(tmp_path, "1111117-g", artist={"name": "x", "wikidata_q": "Q999999999"})
    stats, reasons = backfill(path.parents[1], client=CLIENT, apply=True)
    assert stats.resolved == 0 and reasons["unresolved"] == 1
    assert sidecar.load(path)["artist"].get("canonical") is None
