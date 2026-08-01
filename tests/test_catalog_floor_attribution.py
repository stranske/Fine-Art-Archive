"""Tests for the Wikidata identity fetch + floor attribution cataloguing."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from scripts.catalog_floor_attribution import ATTRIBUTIONS, catalog

from fine_art_archive import sidecar
from fine_art_archive.enrichment import wikidata_identity as wi


class FakeEntityClient:
    """Serves EntityData with en label + P569/P570 years, keyed by QID."""

    def __init__(self, data: dict[str, dict[str, Any]]) -> None:
        self._data = data

    def get(self, url: str, *, params: Any = None) -> dict[str, Any] | None:
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


# --- identity helper -------------------------------------------------------
def test_fetch_identity() -> None:
    client = FakeEntityClient({"Q5588": {"label": "Frida Kahlo", "birth": "1907", "death": "1954"}})
    assert wi.fetch_identity("Q5588", client=client) == ("Frida Kahlo", "1907–1954")
    assert wi.fetch_identity("Q999", client=client) == (None, None)
    assert wi.fetch_identity("", client=client) == (None, None)


def test_fetch_identity_one_sided_lifespan() -> None:
    client = FakeEntityClient({"Qx": {"label": "Jacopo di Cambio", "death": "1348"}})
    assert wi.fetch_identity("Qx", client=client) == ("Jacopo di Cambio", "–1348")


# --- catalog pass ----------------------------------------------------------
def test_table_wellformed() -> None:
    for attr in ATTRIBUTIONS.values():
        assert attr.qid is None or attr.qid.startswith("Q")
        assert attr.relation in (None, "self", "anonymous", "unknown")
        if attr.relation == "anonymous":
            assert attr.anchor == "Q4233718"


BASE: dict[str, Any] = {
    "work_id": "PLACEHOLDER",
    "schema_version": "1.0",
    "artist": {"name": "junk"},
    "title": "T",
    "year": "1900",
    "category": "painting",
    "files": {
        "master": {
            "filename": "master.jpeg",
            "sha256": "abc" + ("0" * 61),
            "size_bytes": 10,
            "ingested_at": "2026-05-16T21:30:00Z",
        }
    },
    "history": [{"ts": "2026-05-16T21:30:00Z", "actor": "codex", "op": "ingested"}],
}

CLIENT = FakeEntityClient(
    {"Q167132": {"label": "George Bellows", "birth": "1882", "death": "1925"}}
)


def _write(tmp_path: Path, work_id: str, **overrides: Any) -> Path:
    meta = deepcopy(BASE)
    meta["work_id"] = work_id
    meta.update(overrides)
    path = tmp_path / "staging" / work_id / "meta.json"
    sidecar.write(path, meta)
    return path


def test_qid_entry_fills_canonical_and_holder(tmp_path: Path) -> None:
    wid = "b44ff28-pennsylvania-station-excavation-george-wesley-bellows-canvas"
    path = _write(tmp_path, wid, artist={"name": "1907-1908Oil on canvas"})
    stats, _ = catalog(path.parents[1], client=CLIENT, apply=True, now="2026-08-01T00:00:00Z")
    assert stats.changed == 1 and stats.holders_set == 1
    m = sidecar.load_validated(path)
    assert m["artist"]["name"] == "George Bellows"
    assert m["artist"]["wikidata_q"] == "Q167132"
    assert m["artist"]["canonical"]["lifespan"] == "1882–1925"
    assert m["artist"]["lifespan"] == "1882–1925"
    assert m["holder"]["wikidata_q"] == "Q632682"


def test_anonymous_entry_sets_relation_anchor_holder(tmp_path: Path) -> None:
    wid = "f8fc50e-the-mausoleum-of-galla-placidia-ce"
    path = _write(tmp_path, wid, category="mosaic", artist={"name": "425 C.E."})
    catalog(path.parents[1], client=CLIENT, apply=True, now="2026-08-01T00:00:00Z")
    m = sidecar.load_validated(path)
    a = m["artist"]
    assert a["relation"] == "anonymous"
    assert a["attribution_anchor"] == "Q4233718"
    assert a["nationality"] == "Early Christian"
    assert a["name"] == "Unknown (Early Christian)"  # junk sitter/date replaced
    assert a["wikidata_q"] is None
    assert m["holder"]["wikidata_q"] == "Q644288"


def test_unknown_modern_sets_plain_unknown(tmp_path: Path) -> None:
    wid = "bd7244f-30-calvin-coolidge-1919"
    path = _write(tmp_path, wid, category="photograph", artist={"name": "Calvin Coolidge"})
    catalog(path.parents[1], client=CLIENT, apply=True, now="2026-08-01T00:00:00Z")
    a = sidecar.load_validated(path)["artist"]
    assert a["relation"] == "unknown" and a["name"] == "Unknown"


def test_dry_run_does_not_write(tmp_path: Path) -> None:
    wid = "f8fc50e-the-mausoleum-of-galla-placidia-ce"
    path = _write(tmp_path, wid, category="mosaic", artist={"name": "425 C.E."})
    stats, _ = catalog(path.parents[1], client=CLIENT, apply=False)
    assert stats.changed == 1
    assert sidecar.load(path)["artist"].get("relation") is None
