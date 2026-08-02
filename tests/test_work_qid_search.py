"""Tests for creator-independent title->artwork search + the exhaustion ledger."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scripts.resolve_work_qids import SEARCH_PLAN_VERSION, _eligible, backfill

from fine_art_archive.enrichment import work_qid_search as wqs

# --- search-result fakes ------------------------------------------------------


class FakeJson:
    """wbsearchentities: returns the configured QID list for any title."""

    def __init__(self, hits: list[str]) -> None:
        self._hits = hits

    def get(self, url: str, *, params: dict[str, str] | None = None) -> dict[str, Any]:
        return {"search": [{"id": q} for q in self._hits]}


def _detail_row(qid: str, label: str, *, artwork: bool, creators: list[str], inception: str | None):
    row: dict[str, Any] = {
        "w": {"value": f"http://www.wikidata.org/entity/{qid}"},
        "wLabel": {"value": label},
        "nart": {"value": "1" if artwork else "0"},
        "creators": {"value": " ".join(f"http://www.wikidata.org/entity/{c}" for c in creators)},
    }
    if inception:
        row["inception"] = {"value": inception}
    return row


class FakeSparqlDetails:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def query(self, sparql: str) -> dict[str, Any]:
        return {"results": {"bindings": self._rows}}


def test_global_unique_artwork_matches_without_creator() -> None:
    json_c = FakeJson(["Q1", "Q2"])
    sparql = FakeSparqlDetails(
        [
            _detail_row(
                "Q1", "The Great Wave off Kanagawa", artwork=True, creators=[], inception="1831"
            ),
            _detail_row(
                "Q2", "Kanagawa Prefecture", artwork=False, creators=[], inception=None
            ),  # place
        ]
    )
    qid, reason = wqs.resolve_by_title_search(
        "The Great Wave off Kanagawa", None, None, json_client=json_c, sparql_client=sparql
    )
    assert qid == "Q1" and reason == "match-global-unique"


def test_non_artwork_namesake_never_resolves() -> None:
    # title "New York" -> the city is a hit but filtered out; no artwork -> decline
    json_c = FakeJson(["Q60"])
    sparql = FakeSparqlDetails(
        [_detail_row("Q60", "New York City", artwork=False, creators=[], inception=None)]
    )
    qid, reason = wqs.resolve_by_title_search(
        "New York", None, None, json_client=json_c, sparql_client=sparql
    )
    assert qid is None and reason == "no-artwork-hit"


def test_multiple_artwork_hits_is_ambiguous() -> None:
    json_c = FakeJson(["Q1", "Q2"])
    sparql = FakeSparqlDetails(
        [
            _detail_row("Q1", "River Landscape", artwork=True, creators=["Q10"], inception=None),
            _detail_row("Q2", "River Landscape", artwork=True, creators=["Q11"], inception=None),
        ]
    )
    qid, reason = wqs.resolve_by_title_search(
        "River Landscape", None, None, json_client=json_c, sparql_client=sparql
    )
    assert qid is None and reason == "ambiguous"


def test_known_creator_defers_to_stage1() -> None:
    # when the creator is known, Stage 1 (oeuvre enumeration) is authoritative;
    # this creator-independent search must not second-guess it.
    json_c = FakeJson(["Q1"])
    sparql = FakeSparqlDetails(
        [_detail_row("Q1", "Portrait of a Man", artwork=True, creators=["Q297"], inception="1650")]
    )
    qid, reason = wqs.resolve_by_title_search(
        "Portrait of a Man", None, "Q297", json_client=json_c, sparql_client=sparql
    )
    assert qid is None and reason == "has-creator"


def test_common_title_not_narrowed_to_false_single_by_year() -> None:
    # "Self-Portrait" has several artwork hits; the year must NOT narrow it to one
    json_c = FakeJson(["Q1", "Q2"])
    sparql = FakeSparqlDetails(
        [
            _detail_row("Q1", "Self-Portrait", artwork=True, creators=[], inception="1861"),
            _detail_row("Q2", "Self-Portrait", artwork=True, creators=[], inception="1901"),
        ]
    )
    qid, reason = wqs.resolve_by_title_search(
        "Self-Portrait", 1861, None, json_client=json_c, sparql_client=sparql
    )
    assert qid is None and reason == "ambiguous"


def test_non_distinctive_title_declines_without_creator() -> None:
    # a bare number / single word must not resolve globally
    for title in ("22", "Caucasus", "Roses"):
        qid, reason = wqs.resolve_by_title_search(
            title,
            None,
            None,
            json_client=FakeJson(["Q1"]),
            sparql_client=FakeSparqlDetails(
                [_detail_row("Q1", title, artwork=True, creators=[], inception=None)]
            ),
        )
        assert qid is None and reason == "title-not-distinctive", title


def test_year_disagreement_rejects_sole_candidate() -> None:
    json_c = FakeJson(["Q1"])
    sparql = FakeSparqlDetails(
        [_detail_row("Q1", "Vase of Irises", artwork=True, creators=[], inception="1600")]
    )
    qid, reason = wqs.resolve_by_title_search(
        "Vase of Irises", 1889, None, json_client=json_c, sparql_client=sparql
    )
    assert qid is None and reason == "year-mismatch"


# --- exhaustion ledger (state machine) ----------------------------------------


def _prov(status: str, version: int) -> dict[str, Any]:
    return {
        "work_qid": {
            "status": status,
            "source": "wikidata",
            "source_ref": f"faa:work-qid-search/v{version}",
            "checked_at": "2026-08-01T00:00:00Z",
            "note": "x",
        }
    }


def _meta(work_id: str, **kw) -> dict[str, Any]:
    return {"work_id": work_id, "artist": {"name": "X"}, "title": "T", **kw}


def test_eligible_when_never_researched() -> None:
    assert _eligible(_meta("w")) is True


def test_not_eligible_when_has_work_qid() -> None:
    assert _eligible(_meta("w", stable_identifiers={"wikidata_q": "Q1"})) is False


def test_not_eligible_when_retired_at_current_plan() -> None:
    m = _meta("w", field_provenance=_prov("not_available", SEARCH_PLAN_VERSION))
    assert _eligible(m) is False


def test_reopens_when_plan_version_rises() -> None:
    m = _meta("w", field_provenance=_prov("not_available", SEARCH_PLAN_VERSION - 1))
    assert _eligible(m) is True


def test_blocked_reopens_when_creator_appears() -> None:
    # unverified (no creator) at current version, but a creator QID now exists
    m = _meta(
        "w",
        artist={"name": "Monet", "wikidata_q": "Q296"},
        field_provenance=_prov("unverified", SEARCH_PLAN_VERSION),
    )
    assert _eligible(m) is True


def test_blocked_stays_retired_without_creator() -> None:
    m = _meta("w", field_provenance=_prov("unverified", SEARCH_PLAN_VERSION))
    assert _eligible(m) is False


# --- CLI: resolve vs retire ---------------------------------------------------


def _write(tmp: Path, meta: dict[str, Any]) -> Path:
    meta = {
        "work_id": meta["work_id"],
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
    p = tmp / meta["work_id"] / "meta.json"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps(meta), encoding="utf-8")
    return p


def test_retire_labels_blocked_when_no_creator(tmp_path: Path) -> None:
    _write(tmp_path, {"work_id": "1111111-x", "artist": {"name": "Unknown"}, "title": "Obscure"})
    json_c = FakeJson([])  # no search hits -> unresolved
    sparql = FakeSparqlDetails([])

    # resolve-only: nothing retired, stays not_researched
    s1, _ = backfill(tmp_path, sparql=sparql, json_client=json_c, apply=True, retire=False)
    assert s1.resolved == 0 and s1.retired_blocked == 0
    assert "field_provenance" not in json.loads((tmp_path / "1111111-x" / "meta.json").read_text())

    # retire: no creator -> unverified (blocked), not terminal not_available
    s2, _ = backfill(tmp_path, sparql=sparql, json_client=json_c, apply=True, retire=True)
    assert s2.retired_blocked == 1 and s2.retired_not_available == 0
    entry = json.loads((tmp_path / "1111111-x" / "meta.json").read_text())["field_provenance"][
        "work_qid"
    ]
    assert entry["status"] == "unverified"
    assert f"v{SEARCH_PLAN_VERSION}" in entry["source_ref"]


def test_retire_labels_not_available_with_creator(tmp_path: Path) -> None:
    _write(
        tmp_path,
        {
            "work_id": "2222222-y",
            "artist": {"name": "Monet", "wikidata_q": "Q296"},
            "title": "Obscure",
        },
    )
    # creator present but no oeuvre match + no search hit -> exhausted
    sparql = FakeSparqlDetails([])
    json_c = FakeJson([])

    stats, _ = backfill(tmp_path, sparql=sparql, json_client=json_c, apply=True, retire=True)
    assert stats.retired_not_available == 1
    entry = json.loads((tmp_path / "2222222-y" / "meta.json").read_text())["field_provenance"][
        "work_qid"
    ]
    assert entry["status"] == "not_available"
