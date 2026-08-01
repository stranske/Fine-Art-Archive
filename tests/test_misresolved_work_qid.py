"""Tests for mis-resolved work-QID detection and repair."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scripts.fix_misresolved_work_qids import backfill

from fine_art_archive.enrichment import misresolved_work_qid as mrw


def _row(
    qid: str, *, label: str | None, is_art: bool, is_human: bool, occs: list[str]
) -> dict[str, Any]:
    """A SPARQL-JSON binding row matching classify_query / classify_batch_query."""
    row: dict[str, Any] = {
        "w": {"value": f"http://www.wikidata.org/entity/{qid}"},
        "nart": {"value": "1" if is_art else "0"},
        "nhum": {"value": "1" if is_human else "0"},
        "occs": {"value": " ".join(f"http://www.wikidata.org/entity/{o}" for o in occs)},
    }
    if label is not None:
        row["label"] = {"value": label}
    return row


def _entity(qid: str, *, p31: list[str], label: str | None = None, p106: list[str] | None = None):
    """Bridge helper: derive the SPARQL classification from a P31/P106 description."""
    is_art = any(c in {"Q838948", "Q4502142", "Q3305213"} for c in p31)
    return _row(qid, label=label, is_art=is_art, is_human="Q5" in p31, occs=p106 or [])


class FakeClient:
    """Serves canned SPARQL rows for every work QID named in the query."""

    def __init__(self, docs: dict[str, dict[str, Any]]) -> None:
        self._docs = docs

    def query(self, sparql: str) -> dict[str, Any] | None:
        rows = [row for qid, row in self._docs.items() if f"wd:{qid} " in sparql]
        return {"results": {"bindings": rows}}


# --- classify_qid -------------------------------------------------------------


def test_classifies_artwork() -> None:
    c = FakeClient({"Q1": _entity("Q1", p31=["Q3305213"], label="The Starry Night")})
    t = mrw.classify_qid("Q1", client=c)
    assert t.is_artwork and not t.is_human


def test_classifies_artist_human() -> None:
    c = FakeClient(
        {"Q5586": _entity("Q5586", p31=["Q5"], label="Katsushika Hokusai", p106=["Q1028181"])}
    )
    t = mrw.classify_qid("Q5586", client=c)
    assert t.is_human and t.is_artist and not t.is_artwork


def test_classifies_non_artist_human() -> None:
    c = FakeClient(
        {"Q33866": _entity("Q33866", p31=["Q5"], label="Theodore Roosevelt", p106=["Q82955"])}
    )
    t = mrw.classify_qid("Q33866", client=c)
    assert t.is_human and not t.is_artist


# --- decide_repair ------------------------------------------------------------


def _meta(title: str, artist_name: str, work_qid: str) -> dict[str, Any]:
    return {
        "title": title,
        "artist": {"name": artist_name},
        "stable_identifiers": {"wikidata_q": work_qid},
    }


def test_unswap_when_qid_is_artist_matching_title() -> None:
    qtype = mrw.QidType("Katsushika Hokusai", is_artwork=False, is_human=True, is_artist=True)
    meta = _meta("Katsushika Hokusai", "Under the Wave off Kanagawa", "Q5586")
    r = mrw.decide_repair(meta, qtype)
    assert r.action == "unswap"
    assert r.artist_name == "Katsushika Hokusai" and r.artist_qid == "Q5586"
    assert r.new_title == "Under the Wave off Kanagawa"


def test_clear_when_qid_is_sitter_not_artist() -> None:
    qtype = mrw.QidType("Theodore Roosevelt", is_artwork=False, is_human=True, is_artist=False)
    meta = _meta("Theodore Roosevelt", "John Singer Sargent", "Q33866")
    r = mrw.decide_repair(meta, qtype)
    assert r.action == "clear"


def test_clear_when_qid_is_place() -> None:
    qtype = mrw.QidType("New York", is_artwork=False, is_human=False, is_artist=False)
    meta = _meta("New York", "1911", "Q1384")
    r = mrw.decide_repair(meta, qtype)
    assert r.action == "clear"


def test_artwork_qid_is_never_repaired() -> None:
    qtype = mrw.QidType("The Starry Night", is_artwork=True, is_human=False, is_artist=False)
    assert mrw.decide_repair(_meta("x", "y", "Q1"), qtype) is None


def test_no_unswap_when_title_does_not_match_person() -> None:
    # QID is an artist, but the title is NOT that artist's name -> not a swap
    qtype = mrw.QidType("Claude Monet", is_artwork=False, is_human=True, is_artist=True)
    meta = _meta("Water Lilies", "Some Text", "Q296")
    r = mrw.decide_repair(meta, qtype)
    assert r.action == "clear"


def test_no_unswap_when_recovered_title_is_junk() -> None:
    # Juan de Pareja: title is the person's name, but the artist field is a bare
    # date ("1599-60") -- promoting it to the title would be junk, so clear only.
    qtype = mrw.QidType("Juan de Pareja", is_artwork=False, is_human=True, is_artist=True)
    meta = _meta("Juan de Pareja", "1599–60", "Q1352058")
    r = mrw.decide_repair(meta, qtype)
    assert r.action == "clear"


# --- backfill CLI -------------------------------------------------------------


def _write(tmp: Path, work_id: str, meta: dict[str, Any]) -> Path:
    meta = {
        "work_id": work_id,
        "schema_version": "1.0",
        "files": {
            "master": {
                "filename": "m.jpeg",
                "sha256": "a" * 64,
                "size_bytes": 1,
                "ingested_at": "2026-05-16T21:30:00Z",
            }
        },
        "history": [{"ts": "2026-05-16T21:30:00Z", "actor": "codex", "op": "ingested"}],
        **meta,
    }
    p = tmp / work_id / "meta.json"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps(meta), encoding="utf-8")
    return p


def test_backfill_unswaps_and_clears(tmp_path: Path) -> None:
    swap = _write(
        tmp_path, "1111111-hokusai", _meta("Katsushika Hokusai", "The Great Wave", "Q5586")
    )
    place = _write(tmp_path, "2222222-newyork", _meta("New York", "1911", "Q1384"))
    art = _write(tmp_path, "3333330-real", _meta("The Starry Night", "Van Gogh", "Q45585"))
    docs = {
        "Q5586": _entity("Q5586", p31=["Q5"], label="Katsushika Hokusai", p106=["Q1028181"]),
        "Q1384": _entity("Q1384", p31=["Q1093829"], label="New York City"),
        "Q45585": _entity("Q45585", p31=["Q3305213"], label="The Starry Night"),
    }

    stats, reasons = backfill(tmp_path, client=FakeClient(docs), apply=True)

    assert stats.unswapped == 1 and stats.cleared == 1
    assert reasons["artwork-ok"] == 1

    m = json.loads(swap.read_text())
    assert m["title"] == "The Great Wave"
    assert m["artist"]["name"] == "Katsushika Hokusai"
    assert m["artist"]["wikidata_q"] == "Q5586"
    assert "wikidata_q" not in m["stable_identifiers"]  # person QID removed

    p = json.loads(place.read_text())
    assert "wikidata_q" not in p["stable_identifiers"]
    assert p["artist"]["name"] == "1911"  # clear leaves title/artist untouched

    a = json.loads(art.read_text())
    assert a["stable_identifiers"]["wikidata_q"] == "Q45585"  # real artwork untouched


def test_backfill_dry_run_writes_nothing(tmp_path: Path) -> None:
    place = _write(tmp_path, "2222222-newyork", _meta("New York", "1911", "Q1384"))
    docs = {"Q1384": _entity("Q1384", p31=["Q1093829"], label="New York City")}

    stats, _ = backfill(tmp_path, client=FakeClient(docs), apply=False)

    assert len(stats.matches) == 1 and stats.cleared == 0
    assert json.loads(place.read_text())["stable_identifiers"]["wikidata_q"] == "Q1384"
