"""Tests for the creator-occupation category prior + its backfill CLI."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from scripts.backfill_category_prior import backfill

from fine_art_archive import sidecar
from fine_art_archive.enrichment import creator_category_prior as cp

PAINTER = "Q1028181"
PRINTMAKER = "Q11569986"
PHOTOGRAPHER = "Q33231"

BASE: dict[str, Any] = {
    "work_id": "6666666-example",
    "schema_version": "1.0",
    "artist": {"name": "Caravaggio", "wikidata_q": "Q42207"},
    "title": "The Doubting Thomas",
    "year": "1602",
    "category": None,
    "files": {
        "master": {
            "filename": "master.jpeg",
            "sha256": "6666666" + ("0" * 57),
            "size_bytes": 10,
            "ingested_at": "2026-05-16T21:30:00Z",
        }
    },
    "history": [{"ts": "2026-05-16T21:30:00Z", "actor": "codex", "op": "ingested"}],
}


# --- pure mappers ----------------------------------------------------------
def test_category_from_occupations() -> None:
    assert cp.category_from_occupations([PAINTER]) == "painting"
    assert cp.category_from_occupations([PHOTOGRAPHER]) == "photograph"
    # multi-medium artist -> abstain
    assert cp.category_from_occupations([PAINTER, PRINTMAKER]) is None
    # unmapped / broad occupation -> abstain
    assert cp.category_from_occupations(["Q483501"]) is None
    assert cp.category_from_occupations([]) is None


def test_infer_prior_title_conflict() -> None:
    # painter + plain title -> painting
    assert cp.infer_prior({"title": "The Doubting Thomas"}, [PAINTER])[0] == "painting"
    # "Drawing" as a verb must NOT block the painting prior
    assert cp.infer_prior({"title": "Fishermen Drawing Nets"}, [PAINTER])[0] == "painting"
    # a title type-noun naming a different category -> abstain
    assert cp.infer_prior({"title": "Mural by Hunto"}, [PAINTER]) is None
    assert cp.infer_prior({"title": "The Isenheim Altarpiece"}, [PAINTER]) is None


def test_fetch_occupations() -> None:
    class FakeClient:
        def get(self, url: str, *, params: Any = None) -> dict[str, Any]:
            return {
                "entities": {
                    "Q42207": {
                        "claims": {
                            "P106": [{"mainsnak": {"datavalue": {"value": {"id": PAINTER}}}}]
                        }
                    }
                }
            }

    assert cp.fetch_occupations("Q42207", client=FakeClient()) == [PAINTER]


# --- backfill CLI ----------------------------------------------------------
class FakeOccClient:
    """Maps artist QID -> occupation QID list, EntityData-shaped."""

    def __init__(self, occ_by_artist: dict[str, list[str]]) -> None:
        self._occ = occ_by_artist

    def get(self, url: str, *, params: Any = None) -> dict[str, Any] | None:
        qid = url.rsplit("/", 1)[-1].removesuffix(".json")
        if qid not in self._occ:
            return None
        claims = [{"mainsnak": {"datavalue": {"value": {"id": o}}}} for o in self._occ[qid]]
        return {"entities": {qid: {"claims": {"P106": claims}}}}


def _write(tmp_path: Path, **overrides: Any) -> Path:
    meta = deepcopy(BASE)
    meta.update(overrides)
    path = tmp_path / "staging" / str(meta["work_id"]) / "meta.json"
    sidecar.write(path, meta)
    return path


def test_backfill_writes_unverified_category(tmp_path: Path) -> None:
    path = _write(tmp_path)
    client = FakeOccClient({"Q42207": [PAINTER]})
    stats, by_cat = backfill(path.parents[1], client=client, apply=True)
    assert stats.resolved == 1 and stats.updated_works == 1
    result = sidecar.load_validated(path)
    assert result["category"] == "painting"
    prov = result["field_provenance"]["category"]
    assert prov["status"] == "unverified"  # hedged, not "available"
    assert by_cat["painting"] == 1


def test_backfill_abstains_on_multi_medium(tmp_path: Path) -> None:
    path = _write(tmp_path, artist={"name": "Rembrandt", "wikidata_q": "Q5598"})
    client = FakeOccClient({"Q5598": [PAINTER, PRINTMAKER]})
    stats, _ = backfill(path.parents[1], client=client, apply=True)
    assert stats.resolved == 0
    assert sidecar.load(path).get("category") is None


def test_backfill_dry_run_and_skips_categorized(tmp_path: Path) -> None:
    p1 = _write(tmp_path, category="painting")  # already categorized -> skipped
    client = FakeOccClient({"Q42207": [PAINTER]})
    stats, _ = backfill(p1.parents[1], client=client, apply=False)
    assert stats.attempted == 0
