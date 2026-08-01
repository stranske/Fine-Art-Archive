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


def _binding(
    w: str,
    label: str,
    coll: str | None = None,
    coll_label: str | None = None,
    inception: str | None = None,
    loc: str | None = None,
    loc_label: str | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "w": {"value": f"http://www.wikidata.org/entity/{w}"},
        "wLabel": {"value": label},
    }
    if coll:
        row["coll"] = {"value": f"http://www.wikidata.org/entity/{coll}"}
        row["collLabel"] = {"value": coll_label or coll}
    if inception:
        row["inception"] = {"value": inception}
    if loc:
        row["loc"] = {"value": f"http://www.wikidata.org/entity/{loc}"}
        row["locLabel"] = {"value": loc_label or loc}
    return row


class FakeSparql:
    def __init__(self, bindings: list[dict[str, Any]]) -> None:
        self._payload = {"results": {"bindings": bindings}}

    def query(self, sparql: str) -> dict[str, Any]:
        return self._payload


# --- matching guards -------------------------------------------------------
def test_matches_and_returns_collection() -> None:
    client = FakeSparql(
        [
            _binding("Q1", "The Starry Night", "Q123", "MoMA", inception="1889"),
            _binding("Q2", "Irises", "Q456", "Getty", inception="1889"),
        ]
    )
    match, reason = hbc.resolve_holder("The Starry Night", 1889, "Q296", client=client)
    assert reason == "match"
    assert match is not None
    assert match.work.work_qid == "Q1"
    assert match.holder_qid == "Q123"
    assert match.kind == "collection"


def test_immovable_uses_location_when_no_collection() -> None:
    # a fresco has no P195 collection but a P276 location (the church)
    client = FakeSparql(
        [_binding("Q1", "The Last Judgment", loc="Q47476", loc_label="Sistine Chapel")]
    )
    # default (movable): no collection -> rejected
    assert (
        hbc.resolve_holder("The Last Judgment", None, "Q5592", client=client)[1] == "no-collection"
    )
    # immovable: location becomes the holder
    match, reason = hbc.resolve_holder(
        "The Last Judgment", None, "Q5592", client=client, allow_location=True
    )
    assert reason == "match"
    assert match is not None
    assert match.holder_qid == "Q47476"
    assert match.holder_label == "Sistine Chapel"
    assert match.kind == "location"


def test_location_from_title_when_work_titles_do_not_match() -> None:
    # fresco scan-naming: per-work titles don't match, but the location name is
    # in the title and the creator's works share that P276 location.
    client = FakeSparql(
        [
            _binding("Q1", "No. 20 Flight into Egypt", loc="Q47476", loc_label="Scrovegni Chapel"),
            _binding("Q2", "No. 17 Nativity", loc="Q47476", loc_label="Scrovegni Chapel"),
        ]
    )
    match, reason = hbc.resolve_holder(
        "Capella dei Scrovegni - 20. Flight", None, "Q7814", client=client, allow_location=True
    )
    assert reason == "match"
    assert match is not None
    assert match.holder_qid == "Q47476"
    assert match.kind == "location"


def test_location_from_title_ambiguous_two_sites() -> None:
    client = FakeSparql(
        [
            _binding("Q1", "Fresco A", loc="Q1", loc_label="Assisi Basilica"),
            _binding("Q2", "Fresco B", loc="Q2", loc_label="Scrovegni Chapel"),
        ]
    )
    # title mentions neither distinctively -> no location-in-title
    match, reason = hbc.resolve_holder(
        "Untitled fresco", None, "Q7814", client=client, allow_location=True
    )
    assert match is None


def test_qid_shaped_label_is_dropped() -> None:
    # Wikidata's label service returns the bare QID when an entity has no English
    # label; that must not be stored as the holder name (registry fills it in).
    client = FakeSparql([_binding("Q1", "The Starry Night", "Q214867", "Q214867")])
    match, reason = hbc.resolve_holder("The Starry Night", None, "Q296", client=client)
    assert reason == "match"
    assert match is not None
    assert match.holder_qid == "Q214867"
    assert match.holder_label is None


def test_collection_preferred_over_location() -> None:
    client = FakeSparql([_binding("Q1", "The Starry Night", "Q123", "MoMA", loc="Q999")])
    match, _ = hbc.resolve_holder(
        "The Starry Night", None, "Q296", client=client, allow_location=True
    )
    assert match is not None
    assert match.holder_qid == "Q123"
    assert match.kind == "collection"


def test_ambiguous_same_title_is_rejected() -> None:
    # two works with the same title (Caravaggio's two St Jeromes) -> no guess
    client = FakeSparql(
        [
            _binding("Q1", "St Jerome Writing", "Q123", "Borghese"),
            _binding("Q2", "St Jerome Writing", "Q456", "Valletta"),
        ]
    )
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


def test_query_groups_by_work_and_is_untruncated() -> None:
    # one row per distinct work (not per collection row) so LIMIT can't truncate
    # a prolific artist's oeuvre; a high, non-binding bound; aliases concatenated.
    q = hbc.creator_works_query("Q5598")
    assert "GROUP BY ?w" in q
    assert "GROUP_CONCAT(DISTINCT ?alt" in q
    assert "LIMIT 4000" in q
    assert "?w wdt:P170 wd:Q5598" in q


def test_works_by_creator_parses_aliases() -> None:
    binding = {
        "w": {"value": "http://www.wikidata.org/entity/Q1"},
        "wLabel": {"value": "Woman with a Parasol"},
        "alts": {"value": "Madame Monet and Her Son||La Promenade"},
    }

    works = hbc.works_by_creator("Q296", client=FakeSparql([binding]))

    assert works[0].aliases == ("Madame Monet and Her Son", "La Promenade")


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
    meta["holder"] = {
        "name": "Existing Museum",
        "wikidata_q": "Q999",
        "ror": None,
        "url": None,
        "accession": None,
    }
    path = tmp_path / "staging" / str(meta["work_id"]) / "meta.json"
    sidecar.write(path, meta)
    client = FakeSparql([_binding("Q1", "The Starry Night", "Q123", "MoMA")])

    stats, _ = backfill(path.parents[1], client=client)
    assert stats.attempted == 0
    assert sidecar.load_validated(path)["holder"]["wikidata_q"] == "Q999"
