"""Tests for SPARQL by-creator holder resolution + backfill CLI."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from scripts.backfill_holders_by_creator import backfill

from fine_art_archive import sidecar
from fine_art_archive.enrichment import holder_by_creator as hbc

BASE: dict[str, Any] = {
    "work_id": "3333333-example",
    "schema_version": "1.0",
    "artist": {"name": "Example", "wikidata_q": "Q296"},
    "title": "Example",
    "year": "1889",
    "files": {
        "master": {
            "filename": "master.jpeg",
            "sha256": "3333333" + ("0" * 57),
            "size_bytes": 10,
            "ingested_at": "2026-05-16T21:30:00Z",
        }
    },
    "history": [{"ts": "2026-05-16T21:30:00Z", "actor": "codex", "op": "ingested"}],
}


def _binding(w: str, label: str, coll: str | None = None, coll_label: str | None = None,
             inception: str | None = None) -> dict[str, Any]:
    row: dict[str, Any] = {
        "w": {"value": f"http://www.wikidata.org/entity/{w}"},
        "wLabel": {"value": label},
    }
    if coll:
        row["coll"] = {"value": f"http://www.wikidata.org/entity/{coll}"}
        row["collLabel"] = {"value": coll_label or coll}
    if inception:
        row["inception"] = {"value": inception}
    return row


class FakeSparql:
    def __init__(self, bindings: list[dict[str, Any]]) -> None:
        self._payload = {"results": {"bindings": bindings}}

    def query(self, sparql: str) -> dict[str, Any]:
        return self._payload


# --- matching guards -------------------------------------------------------
def test_matches_and_returns_collection() -> None:
    client = FakeSparql([
        _binding("Q1", "The Starry Night", "Q123", "MoMA", inception="1889"),
        _binding("Q2", "Irises", "Q456", "Getty", inception="1889"),
    ])
    match, reason = hbc.resolve_holder("The Starry Night", 1889, "Q296", client=client)
    assert reason == "match"
    assert match is not None
    assert match.work.work_qid == "Q1"
    assert match.work.collection_qid == "Q123"


def test_ambiguous_same_title_is_rejected() -> None:
    # two works with the same title (Caravaggio's two St Jeromes) -> no guess
    client = FakeSparql([
        _binding("Q1", "St Jerome Writing", "Q123", "Borghese"),
        _binding("Q2", "St Jerome Writing", "Q456", "Valletta"),
    ])
    match, reason = hbc.resolve_holder("St Jerome Writing", None, "Q42207", client=client)
    assert match is None
    assert reason == "ambiguous"


def test_year_mismatch_rejected() -> None:
    client = FakeSparql([_binding("Q1", "Landscape", "Q123", "Prado", inception="1650")])
    match, reason = hbc.resolve_holder("Landscape", 1889, "Q296", client=client)
    assert match is None
    assert reason == "year-mismatch"


def test_below_threshold_rejected() -> None:
    client = FakeSparql([_binding("Q1", "A Completely Different Title", "Q123", "Prado")])
    match, reason = hbc.resolve_holder("The Starry Night", None, "Q296", client=client)
    assert match is None
    assert reason == "below-threshold"


def test_statement_hash_collection_rejected() -> None:
    # SPARQL sometimes yields a statement hash for P195 -> must be rejected
    client = FakeSparql([_binding("Q1", "The Starry Night", "24399b6cce569e36df7e74f9bd782f77")])
    match, reason = hbc.resolve_holder("The Starry Night", None, "Q296", client=client)
    assert match is None
    assert reason == "no-collection"


# --- backfill CLI ----------------------------------------------------------
def test_backfill_writes_holder(tmp_path: Path) -> None:
    meta = deepcopy(BASE)
    meta["title"] = "The Starry Night"
    path = tmp_path / "staging" / str(meta["work_id"]) / "meta.json"
    sidecar.write(path, meta)
    client = FakeSparql([_binding("Q1", "The Starry Night", "Q123", "MoMA", inception="1889")])

    stats, _ = backfill(path.parents[1], client=client)
    assert stats.resolved == 1
    result = sidecar.load_validated(path)
    assert result["holder"]["wikidata_q"] == "Q123"
    assert result["holder"]["name"] == "MoMA"
    assert result["field_provenance"]["holder"]["status"] == "available"


def test_backfill_skips_existing_holder(tmp_path: Path) -> None:
    meta = deepcopy(BASE)
    meta["title"] = "The Starry Night"
    meta["holder"] = {"name": "Existing Museum", "wikidata_q": "Q999", "ror": None, "url": None, "accession": None}
    path = tmp_path / "staging" / str(meta["work_id"]) / "meta.json"
    sidecar.write(path, meta)
    client = FakeSparql([_binding("Q1", "The Starry Night", "Q123", "MoMA")])

    stats, _ = backfill(path.parents[1], client=client)
    assert stats.attempted == 0
    assert sidecar.load_validated(path)["holder"]["wikidata_q"] == "Q999"
