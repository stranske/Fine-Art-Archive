"""Tests for QID-less title/artist swap detection and repair."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scripts.fix_title_artist_swap import backfill

from fine_art_archive.enrichment import title_artist_swap as tas


def _person(qid: str, label: str, *, occupations: list[str], birth: str | None = None):
    claim = lambda q: {"mainsnak": {"datavalue": {"value": {"id": q}}}}  # noqa: E731
    claims: dict[str, Any] = {"P31": [claim("Q5")], "P106": [claim(o) for o in occupations]}
    if birth:
        claims["P569"] = [
            {"mainsnak": {"datavalue": {"value": {"time": f"+{birth}-01-01T00:00:00Z"}}}}
        ]
    return {
        "entities": {
            qid: {"claims": claims, "labels": {"en": {"value": label}}, "aliases": {"en": []}}
        }
    }


class FakeClient:
    """Serves wbsearchentities + wbgetentities + EntityData for one artist."""

    def __init__(self, *, search_qid: str | None, entity: dict[str, Any]) -> None:
        self._search_qid = search_qid
        self._entity = entity

    def get(self, url: str, *, params: dict[str, str] | None = None) -> dict[str, Any] | None:
        if params and params.get("action") == "wbsearchentities":
            return {"search": [{"id": self._search_qid}]} if self._search_qid else {"search": []}
        # wbgetentities (resolve_artist_qid) and Special:EntityData (fetch_identity)
        return self._entity


class FakeOeuvre:
    """SPARQL fake: the resolved artist's works (one row per work label)."""

    def __init__(self, labels: list[str]) -> None:
        self._labels = labels

    def query(self, sparql: str) -> dict[str, Any]:
        rows = [
            {
                "w": {"value": f"http://www.wikidata.org/entity/Q90{i}"},
                "wLabel": {"value": label},
            }
            for i, label in enumerate(self._labels)
        ]
        return {"results": {"bindings": rows}}


ARTIST = _person("Q123", "George Wesley Bellows", occupations=["Q1028181"], birth="1882")
POLITICIAN = _person("Q456", "Rutherford B. Hayes", occupations=["Q82955"])
# oeuvre containing "Love of Winter" (confirms the swap) and one that doesn't
OEUVRE_OK = FakeOeuvre(["Love of Winter", "Cliff Dwellers"])
OEUVRE_MISS = FakeOeuvre(["Cliff Dwellers", "Stag at Sharkey's"])


def _meta(title: str, artist_name: str, **kw) -> dict[str, Any]:
    return {"work_id": "x", "title": title, "artist": {"name": artist_name}, **kw}


# --- detect_swap --------------------------------------------------------------


def test_detects_swap_when_title_is_an_artist() -> None:
    client = FakeClient(search_qid="Q123", entity=ARTIST)
    swap = tas.detect_swap(
        _meta("George Wesley Bellows", "Love of Winter"),
        json_client=client,
        sparql_client=OEUVRE_OK,
    )
    assert swap is not None
    assert swap.artist_name == "George Wesley Bellows" and swap.artist_qid == "Q123"
    assert swap.new_title == "Love of Winter"
    assert swap.work_qid == "Q900"  # captured from the oeuvre confirmation


def test_no_swap_when_title_is_a_sitter() -> None:
    # title is a person but NOT an artist (politician) -> not a swap
    client = FakeClient(search_qid="Q456", entity=POLITICIAN)
    assert (
        tas.detect_swap(
            _meta("Rutherford B. Hayes", "Some Title"), json_client=client, sparql_client=OEUVRE_OK
        )
        is None
    )


def test_no_swap_when_title_is_a_real_title() -> None:
    # a real work title doesn't resolve to any artist
    client = FakeClient(search_qid=None, entity={})
    assert (
        tas.detect_swap(
            _meta("The Great Wave", "Unknown"), json_client=client, sparql_client=OEUVRE_OK
        )
        is None
    )


def test_subject_portrait_guard() -> None:
    # artist field (would-be title) names the person -> a portrait OF them, decline
    client = FakeClient(search_qid="Q123", entity=ARTIST)
    assert (
        tas.detect_swap(
            _meta("George Wesley Bellows", "Portrait of Bellows"),
            json_client=client,
            sparql_client=OEUVRE_OK,
        )
        is None
    )


def test_no_swap_when_new_title_is_junk() -> None:
    # artist field is a bare date -> not promotable to a title
    client = FakeClient(search_qid="Q123", entity=ARTIST)
    assert (
        tas.detect_swap(
            _meta("George Wesley Bellows", "1914"), json_client=client, sparql_client=OEUVRE_OK
        )
        is None
    )


def test_resolved_artist_is_never_touched() -> None:
    client = FakeClient(search_qid="Q123", entity=ARTIST)
    meta = _meta(
        "George Wesley Bellows", "Love of Winter", artist={"name": "x", "wikidata_q": "Q9"}
    )
    assert tas.detect_swap(meta, json_client=client, sparql_client=OEUVRE_OK) is None


def test_attribution_qualified_title_declines() -> None:
    # "Parmigianino (after)" is a copy after the artist, not by him -> no swap
    client = FakeClient(search_qid="Q123", entity=ARTIST)
    swap = tas.detect_swap(
        _meta("Parmigianino (after)", "The Circumcision"),
        json_client=client,
        sparql_client=OEUVRE_OK,
    )
    assert swap is None


def test_oeuvre_confirmation_rejects_wrong_same_name_artist() -> None:
    # "Jan Vermeer" resolves to a same-named painter, but "The Glass of Wine" is
    # not in that painter's oeuvre -> self-reject rather than attach the wrong one.
    client = FakeClient(search_qid="Q123", entity=ARTIST)
    swap = tas.detect_swap(
        _meta("George Wesley Bellows", "Love of Winter"),
        json_client=client,
        sparql_client=OEUVRE_MISS,  # oeuvre lacks the recovered title
    )
    assert swap is None


# --- backfill CLI -------------------------------------------------------------


def _write(tmp: Path, work_id: str, title: str, artist_name: str) -> Path:
    meta = {
        "work_id": work_id,
        "schema_version": "1.0",
        "title": title,
        "artist": {"name": artist_name},
        "files": {
            "master": {
                "filename": "m.jpeg",
                "sha256": "a" * 64,
                "size_bytes": 1,
                "ingested_at": "2026-05-16T21:30:00Z",
            }
        },
        "history": [{"ts": "2026-05-16T21:30:00Z", "actor": "codex", "op": "ingested"}],
    }
    p = tmp / work_id / "meta.json"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps(meta), encoding="utf-8")
    return p


def test_backfill_applies_swap_and_provenance(tmp_path: Path) -> None:
    path = _write(tmp_path, "1111111-bellows", "George Wesley Bellows", "Love of Winter")
    stats, _ = backfill(
        tmp_path,
        json_client=FakeClient(search_qid="Q123", entity=ARTIST),
        sparql_client=OEUVRE_OK,
        apply=True,
    )

    assert stats.swapped == 1
    m = json.loads(path.read_text())
    assert m["title"] == "Love of Winter"
    assert m["artist"]["name"] == "George Wesley Bellows"
    assert m["artist"]["wikidata_q"] == "Q123"
    assert m["artist"]["canonical"]["method"] == "title-artist-unswap"
    assert m["field_provenance"]["title"]["status"] == "available"
    assert m["field_provenance"]["artist_qid"]["status"] == "available"
    assert m["stable_identifiers"]["wikidata_q"] == "Q900"  # work QID captured
    assert m["field_provenance"]["work_qid"]["status"] == "available"


def test_backfill_dry_run_writes_nothing(tmp_path: Path) -> None:
    path = _write(tmp_path, "1111111-bellows", "George Wesley Bellows", "Love of Winter")
    stats, _ = backfill(
        tmp_path,
        json_client=FakeClient(search_qid="Q123", entity=ARTIST),
        sparql_client=OEUVRE_OK,
        apply=False,
    )

    assert len(stats.matches) == 1 and stats.swapped == 0
    assert json.loads(path.read_text())["title"] == "George Wesley Bellows"  # untouched
