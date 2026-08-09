"""Tests for the Google Lens image-recovery write-back."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from scripts.apply_lens_recovery import (  # noqa: E402
    REF_IMAGE_CONFIRMED,
    _already_lens,
    apply_finding,
)


class FakeSparql:
    """ASK P31/P279*->Q838948 is true only for QIDs in ``artworks``."""

    def __init__(self, artworks: set[str]) -> None:
        self.artworks = artworks

    def query(self, sparql: str) -> dict[str, Any]:
        for q in self.artworks:
            if q in sparql:
                return {"boolean": True}
        return {"boolean": False}


def test_corrects_title_and_artist() -> None:
    meta = {"work_id": "w", "title": "The harvest of wheat", "artist": {"name": "T H Benton"}}
    changes = apply_finding(
        meta, {"artist_name": "Thomas Hart Benton", "title": "Cradling Wheat", "source": "SLAM"},
        client=FakeSparql(set()),
    )
    assert meta["title"] == "Cradling Wheat"
    assert meta["artist"]["name"] == "Thomas Hart Benton"
    assert any("title" in c for c in changes) and any("artist" in c for c in changes)


def test_title_correction_reopens_work_qid() -> None:
    meta = {"work_id": "w", "title": "wrong", "artist": {"name": "A B"}}
    apply_finding(meta, {"title": "Right Title", "source": "x"}, client=FakeSparql(set()))
    assert meta["field_provenance"]["work_qid"]["status"] == "not_researched"
    assert meta["field_provenance"]["work_qid"]["source_ref"].endswith("title-corrected")


def test_sets_verified_work_qid() -> None:
    meta = {"work_id": "w", "title": "Door", "artist": {"name": "Donatello"}}
    apply_finding(
        meta, {"wikidata_q": "Q3908892", "title": "Door of the Apostles", "source": "Wikidata"},
        client=FakeSparql({"Q3908892"}),
    )
    assert meta["stable_identifiers"]["wikidata_q"] == "Q3908892"
    assert meta["field_provenance"]["work_qid"]["status"] == "available"


def test_rejects_non_artwork_qid() -> None:
    meta = {"work_id": "w", "title": "t", "artist": {"name": "x"}}
    changes = apply_finding(
        meta, {"wikidata_q": "Q5", "source": "x"}, client=FakeSparql(set())
    )
    assert (meta.get("stable_identifiers") or {}).get("wikidata_q") is None
    assert any("REJECTED" in c for c in changes)


def test_clears_stale_relation_on_artist_correction() -> None:
    meta = {"work_id": "w", "title": "t", "artist": {"name": "junk", "relation": "unknown"}}
    apply_finding(meta, {"artist_name": "Real Painter", "source": "x"}, client=FakeSparql(set()))
    assert "relation" not in meta["artist"]


def test_resumable_skip_detection() -> None:
    meta = {"work_id": "w", "field_provenance": {"artist_qid": {"source_ref": "faa:google-lens/text"}}}
    assert _already_lens(meta, "artist_qid") is True
    assert _already_lens({"work_id": "w"}, "artist_qid") is False


def test_confirmed_no_artist_finalizes_null() -> None:
    # Image search confirms it's a place / has no individual artist -> null becomes
    # a searched, terminal outcome (not a silent gap).
    meta = {"work_id": "w", "title": "Castillo_de_Zafra", "artist": {"name": None}}
    changes = apply_finding(
        meta,
        {"verdict": "site", "category": "architecture", "title": "Castle of Zafra",
         "source": "Wikipedia"},
        client=FakeSparql(set()),
    )
    assert meta["field_provenance"]["artist_qid"]["source_ref"] == REF_IMAGE_CONFIRMED
    assert meta["category"] == "architecture"
    assert meta["title"] == "Castle of Zafra"
    assert any("confirmed-no-artist" in c for c in changes)


def test_no_change_when_already_correct() -> None:
    meta = {"work_id": "w", "title": "Cradling Wheat", "artist": {"name": "Thomas Hart Benton"}}
    changes = apply_finding(
        meta, {"artist_name": "Thomas Hart Benton", "title": "Cradling Wheat", "source": "x"},
        client=FakeSparql(set()),
    )
    assert changes == []
