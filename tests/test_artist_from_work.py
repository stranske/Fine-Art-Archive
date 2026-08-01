"""Tests for adopting a work's P170 creator as the sidecar artist."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from scripts.backfill_artist_from_work_p170 import backfill

from fine_art_archive.enrichment import artist_from_work as afw


def _entity_data(work_qid: str, *, p170: list[dict[str, Any]]) -> dict[str, Any]:
    return {"entities": {work_qid: {"claims": {"P170": p170}}}}


def _creator_snak(qid: str) -> dict[str, Any]:
    return {"mainsnak": {"snaktype": "value", "datavalue": {"value": {"id": qid}}}}


def _person(qid: str, label: str, *, birth: str | None = None, death: str | None = None):
    claims: dict[str, Any] = {}
    if birth:
        claims["P569"] = [
            {"mainsnak": {"datavalue": {"value": {"time": f"+{birth}-01-01T00:00:00Z"}}}}
        ]
    if death:
        claims["P570"] = [
            {"mainsnak": {"datavalue": {"value": {"time": f"+{death}-01-01T00:00:00Z"}}}}
        ]
    return {"entities": {qid: {"labels": {"en": {"value": label}}, "claims": claims}}}


class FakeClient:
    """Serves EntityData JSON keyed by the QID embedded in the URL."""

    def __init__(self, docs: dict[str, dict[str, Any]]) -> None:
        self._docs = docs

    def get(self, url: str, *, params: dict[str, str] | None = None) -> dict[str, Any] | None:
        qid = url.rsplit("/", 1)[-1].removesuffix(".json")
        return self._docs.get(qid)


def _sidecar(
    work_id: str, *, artist_name: str, work_qid: str | None, artist_qid: str | None = None
):
    artist: dict[str, Any] = {"name": artist_name}
    if artist_qid:
        artist["wikidata_q"] = artist_qid
    meta: dict[str, Any] = {
        "work_id": work_id,
        "schema_version": "1.0",
        "artist": artist,
        "title": "A Work",
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
    if work_qid:
        meta["stable_identifiers"] = {"wikidata_q": work_qid}
    return meta


# --- creator_qid_of + resolve_adoption ----------------------------------------


def test_single_creator_resolves() -> None:
    client = FakeClient({"Q1": _entity_data("Q1", p170=[_creator_snak("Q42207")])})
    qid, reason = afw.creator_qid_of("Q1", client=client)
    assert qid == "Q42207" and reason == "creator"


def test_anonymous_somevalue_declined() -> None:
    anon = {"entities": {"Q1": {"claims": {"P170": [{"mainsnak": {"snaktype": "somevalue"}}]}}}}
    qid, reason = afw.creator_qid_of("Q1", client=FakeClient({"Q1": anon}))
    assert qid is None and reason == "anonymous"


def test_no_p170_declined() -> None:
    qid, reason = afw.creator_qid_of("Q1", client=FakeClient({"Q1": _entity_data("Q1", p170=[])}))
    assert qid is None and reason == "no-p170"


def test_multiple_creators_declined() -> None:
    doc = _entity_data("Q1", p170=[_creator_snak("Q1"), _creator_snak("Q2")])
    qid, reason = afw.creator_qid_of("Q1", client=FakeClient({"Q1": doc}))
    assert qid is None and reason == "multiple"


def test_adoption_replaces_placeholder_name() -> None:
    docs = {
        "Q1": _entity_data("Q1", p170=[_creator_snak("Q42207")]),
        "Q42207": _person("Q42207", "Caravaggio", birth="1571", death="1610")["entities"]["Q42207"],
    }
    # wrap Q42207 as its own EntityData doc
    docs["Q42207"] = _person("Q42207", "Caravaggio", birth="1571", death="1610")
    meta = _sidecar("w1", artist_name="1602", work_qid="Q1")
    adoption, reason = afw.resolve_adoption(meta, client=FakeClient(docs))
    assert reason == "adopt"
    assert adoption.creator_qid == "Q42207" and adoption.display_name == "Caravaggio"
    assert adoption.lifespan == "1571–1610"


def test_resolved_artist_is_never_overwritten() -> None:
    meta = _sidecar("w1", artist_name="Rembrandt", work_qid="Q1", artist_qid="Q5598")
    _a, reason = afw.resolve_adoption(meta, client=FakeClient({}))
    assert reason == "artist-already-resolved"


def test_already_named_creator_is_skipped() -> None:
    docs = {
        "Q1": _entity_data("Q1", p170=[_creator_snak("Q42207")]),
        "Q42207": _person("Q42207", "Caravaggio"),
    }
    meta = _sidecar("w1", artist_name="Caravaggio (Michelangelo Merisi)", work_qid="Q1")
    _a, reason = afw.resolve_adoption(meta, client=FakeClient(docs))
    assert reason == "already-named"


# --- backfill CLI -------------------------------------------------------------


def _docs_caravaggio() -> dict[str, Any]:
    return {
        "Q1": _entity_data("Q1", p170=[_creator_snak("Q42207")]),
        "Q42207": _person("Q42207", "Caravaggio", birth="1571", death="1610"),
    }


def _write(tmp: Path, meta: dict[str, Any]) -> Path:
    p = tmp / meta["work_id"] / "meta.json"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps(meta), encoding="utf-8")
    return p


def test_backfill_apply_sets_artist_and_provenance(tmp_path: Path) -> None:
    path = _write(tmp_path, _sidecar("1111111-x", artist_name="1602", work_qid="Q1"))

    stats, _ = backfill(tmp_path, client=FakeClient(_docs_caravaggio()), apply=True)

    assert stats.attempted == 1 and stats.resolved == 1
    m = json.loads(path.read_text())
    assert m["artist"]["name"] == "Caravaggio"
    assert m["artist"]["wikidata_q"] == "Q42207"
    assert m["artist"]["canonical"]["display_name"] == "Caravaggio"
    assert m["artist"]["canonical"]["method"] == "wikidata-p170"
    prov = m["field_provenance"]["artist_qid"]
    assert prov["status"] == "available" and "1602" in prov["note"]  # original preserved


def test_backfill_dry_run_writes_nothing(tmp_path: Path) -> None:
    path = _write(tmp_path, _sidecar("1111111-x", artist_name="1602", work_qid="Q1"))

    stats, _ = backfill(tmp_path, client=FakeClient(_docs_caravaggio()), apply=False)

    assert len(stats.matches) == 1 and stats.resolved == 0
    assert json.loads(path.read_text())["artist"]["name"] == "1602"


def test_backfill_skips_resolved_and_qidless(tmp_path: Path) -> None:
    _write(tmp_path, _sidecar("1111111-resolved", artist_name="X", work_qid="Q1", artist_qid="Q9"))
    _write(tmp_path, _sidecar("2222222-noworkqid", artist_name="1602", work_qid=None))

    stats, _ = backfill(tmp_path, client=FakeClient(_docs_caravaggio()), apply=True)

    assert stats.attempted == 0 and stats.resolved == 0
