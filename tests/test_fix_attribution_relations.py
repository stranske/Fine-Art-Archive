"""Tests for the attribution-relation + reference-QID fix."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from scripts.fix_attribution_relations import ATTRIBUTIONS, fix

from fine_art_archive import sidecar

_RELATIONS = {"workshop", "circle", "after", "follower", "attributed", "anonymous"}
_CONFIDENCE = {"scholarly_consensus", "attributed", "inferred", "uncertain"}


class FakeEntityClient:
    def __init__(self, data: dict[str, dict[str, Any]]) -> None:
        self._data = data

    def get(self, url: str, *, params: Any = None) -> dict[str, Any] | None:
        qid = url.rsplit("/", 1)[-1].removesuffix(".json")
        info = self._data.get(qid)
        if info is None:
            return None
        claims: dict[str, Any] = {}
        for prop, key in (("P569", "birth"), ("P570", "death")):
            if info.get(key):
                claims[prop] = [
                    {
                        "mainsnak": {
                            "datavalue": {"value": {"time": f"+{info[key]}-00-00T00:00:00Z"}}
                        }
                    }
                ]
        return {"entities": {qid: {"labels": {"en": {"value": info["label"]}}, "claims": claims}}}


CLIENT = FakeEntityClient(
    {"Q68631": {"label": "Rogier van der Weyden", "birth": "1399", "death": "1464"}}
)

BASE: dict[str, Any] = {
    "work_id": "PLACEHOLDER",
    "schema_version": "1.0",
    "artist": {"name": "SRC", "wikidata_q": "Q47551", "canonical": {"display_name": "Titian"}},
    "title": "T",
    "year": "1450",
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


def test_table_is_wellformed() -> None:
    assert len(ATTRIBUTIONS) == 32
    for attr in ATTRIBUTIONS.values():
        assert attr.relation in _RELATIONS
        assert attr.confidence in _CONFIDENCE
        assert (attr.ref_qid is None) == (attr.relation == "anonymous")
        if attr.ref_qid:
            assert attr.ref_qid.startswith("Q")


def _write(tmp_path: Path, work_id: str, **overrides: Any) -> Path:
    meta = deepcopy(BASE)
    meta["work_id"] = work_id
    meta["artist"] = deepcopy(BASE["artist"])
    meta["artist"].update(overrides.pop("artist", {}))
    meta.update(overrides)
    path = tmp_path / "staging" / work_id / "meta.json"
    sidecar.write(path, meta)
    return path


def test_workshop_fixes_reference_and_keeps_name(tmp_path: Path) -> None:
    wid = "07bbd4c-portrait-of-isabella-of-portugal-weyden"  # Workshop of van der Weyden -> Q68631
    path = _write(tmp_path, wid, artist={"name": "Workshop of Rogier van der Weyden"})
    stats, _ = fix(path.parents[1], client=CLIENT, apply=True, now="2026-08-01T00:00:00Z")
    assert stats.changed == 1 and stats.reference_fixed == 1  # was Titian Q47551
    a = sidecar.load_validated(path)["artist"]
    assert a["name"] == "Workshop of Rogier van der Weyden"  # source string untouched
    assert a["relation"] == "workshop"
    assert a["wikidata_q"] == "Q68631"  # corrected reference artist
    assert a["canonical"]["display_name"] == "Rogier van der Weyden"
    assert a["canonical"]["lifespan"] == "1399–1464"
    assert a["attribution_confidence"] == "scholarly_consensus"


def test_anonymous_case(tmp_path: Path) -> None:
    wid = "00edba3-jonah-and-the-whale-folio-probably-iran"
    path = _write(tmp_path, wid, artist={"name": "Unknown artist, Attributed to Iran"})
    fix(path.parents[1], client=CLIENT, apply=True, now="2026-08-01T00:00:00Z")
    a = sidecar.load_validated(path)["artist"]
    assert a["relation"] == "anonymous"
    assert a["attribution_anchor"] == "Q4233718"
    assert a["wikidata_q"] is None
    assert a["canonical"] is None
    assert a["nationality"] == "Persian"


def test_dry_run_does_not_write(tmp_path: Path) -> None:
    wid = "07bbd4c-portrait-of-isabella-of-portugal-weyden"
    path = _write(tmp_path, wid, artist={"name": "Workshop of Rogier van der Weyden"})
    stats, _ = fix(path.parents[1], client=CLIENT, apply=False)
    assert stats.changed == 1
    assert sidecar.load(path)["artist"].get("relation") is None
