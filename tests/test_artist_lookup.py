"""Tests for name-based artist_qid resolution + backfill CLI."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from scripts.backfill_artist_qids import backfill

from fine_art_archive import sidecar
from fine_art_archive.identity import artist_lookup

BASE: dict[str, Any] = {
    "work_id": "2222222-example",
    "schema_version": "1.0",
    "artist": {"name": "Example"},
    "title": "Example",
    "files": {
        "master": {
            "filename": "master.jpeg",
            "sha256": "2222222" + ("0" * 57),
            "size_bytes": 10,
            "ingested_at": "2026-05-16T21:30:00Z",
        }
    },
    "history": [{"ts": "2026-05-16T21:30:00Z", "actor": "codex", "op": "ingested"}],
}


class FakeClient:
    """Serves canned wbsearchentities + wbgetentities payloads."""

    def __init__(self, search: list[str], entities: dict[str, dict[str, Any]]) -> None:
        self._search = {"search": [{"id": q} for q in search]}
        self._entities = {"entities": entities}

    def get(self, url: str, *, params: dict[str, str] | None = None) -> dict[str, Any] | None:
        return (
            self._search
            if params and params.get("action") == "wbsearchentities"
            else self._entities
        )


def _person(name: str, *, occupations: list[str]) -> dict[str, Any]:
    def claim(qid: str) -> dict[str, Any]:
        return {"mainsnak": {"datavalue": {"value": {"id": qid}}}}

    return {
        "claims": {"P31": [claim("Q5")], "P106": [claim(o) for o in occupations]},
        "labels": {"en": {"value": name}},
        "aliases": {"en": []},
    }


# --- name cleaning ---------------------------------------------------------
def test_clean_name_variants() -> None:
    assert artist_lookup.clean_name("Titian (Tiziano Vecellio)") == "Titian"
    assert artist_lookup.clean_name("Kandinsky, Vassily") == "Vassily Kandinsky"
    assert (
        artist_lookup.clean_name("Jan Brueghel the Elder & Hans Rottenhammer")
        == "Jan Brueghel the Elder"
    )


# --- resolution + occupation gate -----------------------------------------
def test_resolves_artist_with_occupation() -> None:
    # obscure name (not in the offline alias table) -> exercises the search path
    client = FakeClient(
        ["Q16012501"], {"Q16012501": _person("Edna Reindel", occupations=["Q1028181"])}
    )
    qid, method = artist_lookup.resolve_artist_qid("Edna Reindel", client=client)
    assert qid == "Q16012501"
    assert "wikidata artist match" in method


def test_rejects_non_artist_human() -> None:
    # a president sitter -> human but not an art occupation -> rejected
    client = FakeClient(["Q11812"], {"Q11812": _person("Calvin Coolidge", occupations=["Q82955"])})
    qid, reason = artist_lookup.resolve_artist_qid("Calvin Coolidge", client=client)
    assert qid is None
    assert reason == "no-artist-match"


def test_rejects_attribution_and_junk() -> None:
    client = FakeClient([], {})
    assert artist_lookup.resolve_artist_qid("Circle of Rembrandt", client=client)[0] is None
    assert artist_lookup.resolve_artist_qid("1692", client=client) == (None, "not-a-name")
    assert artist_lookup.resolve_artist_qid("Unknown artist", client=client)[0] is None


# --- backfill CLI ----------------------------------------------------------
def test_backfill_writes_only_missing(tmp_path: Path) -> None:
    meta = deepcopy(BASE)
    meta["artist"] = {"name": "Claude Monet"}
    path = tmp_path / "staging" / str(meta["work_id"]) / "meta.json"
    sidecar.write(path, meta)
    client = FakeClient(["Q296"], {"Q296": _person("Claude Monet", occupations=["Q1028181"])})

    stats, _ = backfill(path.parents[1], client=client)
    assert stats.resolved == 1
    result = sidecar.load_validated(path)
    assert result["artist"]["wikidata_q"] == "Q296"
    assert result["field_provenance"]["artist_qid"]["status"] == "available"

    # second run: already has a QID -> not attempted
    stats2, _ = backfill(path.parents[1], client=client)
    assert stats2.attempted == 0


def test_dry_run_reports_without_writing(tmp_path: Path) -> None:
    meta = deepcopy(BASE)
    meta["artist"] = {"name": "Claude Monet"}
    path = tmp_path / "staging" / str(meta["work_id"]) / "meta.json"
    sidecar.write(path, meta)
    client = FakeClient(["Q296"], {"Q296": _person("Claude Monet", occupations=["Q1028181"])})

    stats, _ = backfill(path.parents[1], client=client, dry_run=True)

    assert stats.attempted == 1
    assert stats.resolved == 0  # nothing written
    assert [m["qid"] for m in stats.matches] == ["Q296"]
    assert "wikidata_q" not in sidecar.load(path)["artist"]  # unchanged on disk


def test_only_uncategorized_scopes_the_pass(tmp_path: Path) -> None:
    client = FakeClient(["Q296"], {"Q296": _person("Claude Monet", occupations=["Q1028181"])})

    # in scope: uncategorized + no work QID
    in_scope = deepcopy(BASE)
    in_scope["work_id"] = "2222221-in-scope"
    in_scope["artist"] = {"name": "Claude Monet"}
    sidecar.write(tmp_path / "staging" / "2222221-in-scope" / "meta.json", in_scope)

    # out of scope: already categorized
    categorized = deepcopy(BASE)
    categorized["work_id"] = "2222223-categorized"
    categorized["artist"] = {"name": "Claude Monet"}
    categorized["category"] = "painting"
    sidecar.write(tmp_path / "staging" / "2222223-categorized" / "meta.json", categorized)

    # out of scope: already has a work QID
    qided = deepcopy(BASE)
    qided["work_id"] = "2222224-has-workqid"
    qided["artist"] = {"name": "Claude Monet"}
    qided["stable_identifiers"] = {"wikidata_q": "Q111"}
    sidecar.write(tmp_path / "staging" / "2222224-has-workqid" / "meta.json", qided)

    stats, _ = backfill(tmp_path / "staging", client=client, only_uncategorized=True)

    assert stats.attempted == 1  # only the in-scope work
    assert [m["work_id"] for m in stats.matches] == ["2222221-in-scope"]
