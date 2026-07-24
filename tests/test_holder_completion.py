"""Tests for Wikidata-backed holding-institution completion."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any, NoReturn

import pytest
from scripts.complete_holders import complete_sidecars

from fine_art_archive import sidecar
from fine_art_archive.collect import host_registry
from fine_art_archive.enrichment.holder import HolderLookup, WikidataClient, complete_holder

MINIMAL_SIDECAR: dict[str, Any] = {
    "work_id": "4f3a2b8-after-the-bullfight-cassatt",
    "schema_version": "1.0",
    "artist": {"name": "Mary Cassatt", "wikidata_q": "Q173223"},
    "title": "After the Bullfight",
    "stable_identifiers": {"wikidata_q": "Q98549878"},
    "files": {
        "master": {
            "filename": "master.jpeg",
            "sha256": "4f3a2b8" + ("0" * 57),
            "size_bytes": 12378451,
            "ingested_at": "2026-05-16T21:30:00Z",
        }
    },
    "history": [{"ts": "2026-05-16T21:30:00Z", "actor": "codex", "op": "ingested"}],
}


class FakeClient:
    def __init__(self, lookup: HolderLookup) -> None:
        self.lookup = lookup

    def find_work_qid(
        self, title: str, artist: str, *, creator_qid: str | None = None
    ) -> str | None:
        return self.lookup.work_qid

    def lookup_holder(self, work_qid: str) -> HolderLookup | None:
        assert work_qid == self.lookup.work_qid
        return self.lookup


def _lookup(*, collection_qid: str | None = "Q999001") -> HolderLookup:
    return HolderLookup(
        work_qid="Q98549878",
        collection_qid=collection_qid,
        collection_name="Example Museum" if collection_qid else None,
        ror="01abcde23" if collection_qid else None,
        url="https://museum.example/" if collection_qid else None,
        accession="1969.332",
        iiif_manifest_url="https://iiif.example/manifest.json",
    )


def test_collection_populates_holder_and_provenance() -> None:
    completed = complete_holder(deepcopy(MINIMAL_SIDECAR), client=FakeClient(_lookup()))

    assert completed["holder"] == {
        "name": "Example Museum",
        "wikidata_q": "Q999001",
        "ror": "01abcde23",
        "url": "https://museum.example/",
        "accession": "1969.332",
    }
    assert completed["stable_identifiers"]["wikidata_q"] == "Q98549878"
    assert completed["stable_identifiers"]["museum_accession"] == "1969.332"
    assert (
        completed["stable_identifiers"]["iiif_manifest_url"] == "https://iiif.example/manifest.json"
    )
    provenance = completed["field_provenance"]["holder"]
    assert provenance["status"] == "available"
    assert provenance["source"] == "wikidata"
    assert provenance["source_ref"] == "https://www.wikidata.org/wiki/Q98549878"
    assert provenance["checked_at"].endswith("Z")


def test_no_collection_records_checked_absence() -> None:
    completed = complete_holder(
        deepcopy(MINIMAL_SIDECAR), client=FakeClient(_lookup(collection_qid=None))
    )

    assert completed["holder"] is None
    provenance = completed["field_provenance"]["holder"]
    assert provenance["status"] == "not_available"
    assert provenance["source"] == "wikidata"
    assert provenance["source_ref"] == "https://www.wikidata.org/wiki/Q98549878"
    assert provenance["checked_at"].endswith("Z")


def test_host_registry_match_records_host_key(monkeypatch: pytest.MonkeyPatch) -> None:
    registry_entry = host_registry.HostEntry(
        host_id="example_museum",
        name="Registry Museum",
        wikidata_q="Q999001",
        ror="09registry1",
        homepage="https://registry.example/",
        rights_default=None,
        primary_adapter=None,
    )
    monkeypatch.setattr(
        host_registry, "load_registry", lambda path=None: {"example_museum": registry_entry}
    )
    lookup = HolderLookup(
        work_qid="Q98549878",
        collection_qid="Q999001",
        collection_name=None,
        ror=None,
        url=None,
        accession="A-1",
        iiif_manifest_url=None,
    )

    completed = complete_holder(deepcopy(MINIMAL_SIDECAR), client=FakeClient(lookup))

    assert completed["holder"]["name"] == "Registry Museum"
    assert completed["holder"]["ror"] == "09registry1"
    assert completed["field_provenance"]["holder"]["note"] == ("host_registry_key=example_museum")


def test_available_holder_is_not_overwritten() -> None:
    original = deepcopy(MINIMAL_SIDECAR)
    original["holder"] = {
        "name": "Existing Museum",
        "wikidata_q": "Q123",
        "ror": None,
        "url": None,
        "accession": "OLD-1",
    }
    original["field_provenance"] = {"holder": {"status": "available"}}

    class UnexpectedClient:
        def find_work_qid(
            self, title: str, artist: str, *, creator_qid: str | None = None
        ) -> NoReturn:
            raise AssertionError("available holder should not be researched")

        def lookup_holder(self, work_qid: str) -> NoReturn:
            raise AssertionError("available holder should not be researched")

    completed = complete_holder(deepcopy(original), client=UnexpectedClient())

    assert completed == original


def test_injected_client_timeout_is_a_no_op() -> None:
    original = deepcopy(MINIMAL_SIDECAR)

    class TimeoutClient(FakeClient):
        def lookup_holder(self, work_qid: str) -> HolderLookup | None:
            raise TimeoutError("simulated timeout")

    completed = complete_holder(deepcopy(original), client=TimeoutClient(_lookup()))

    assert completed == original


def test_wikidata_network_timeout_is_caught(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def raise_timeout(request: object, *, timeout: float) -> NoReturn:
        assert request is not None
        assert timeout == 15
        raise TimeoutError("simulated timeout")

    monkeypatch.setattr("urllib.request.urlopen", raise_timeout)

    assert WikidataClient().lookup_holder("Q98549878") is None


def test_cli_worker_validates_writes_mirrors_and_logs(tmp_path: Path) -> None:
    work_id = str(MINIMAL_SIDECAR["work_id"])
    staging_meta = tmp_path / "staging" / work_id / "meta.json"
    mirror_meta = tmp_path / "art" / "works" / work_id / "meta.json"
    operations_log = tmp_path / "operations.log"
    sidecar.write(staging_meta, deepcopy(MINIMAL_SIDECAR))
    sidecar.write(mirror_meta, deepcopy(MINIMAL_SIDECAR))

    stats = complete_sidecars(
        staging_meta.parents[1],
        art_works_root=tmp_path / "art",
        operations_log=operations_log,
        limit=1,
        client=FakeClient(_lookup()),
    )

    assert stats.attempted == 1
    assert stats.updated == 1
    assert stats.mirrored == 1
    staged = sidecar.load_validated(staging_meta)
    mirrored = sidecar.load_validated(mirror_meta)
    assert staged == mirrored
    assert staged["field_provenance"]["holder"]["status"] == "available"
    log_entries = operations_log.read_text(encoding="utf-8").splitlines()
    assert len(log_entries) == 1
    assert json.loads(log_entries[0])["work_id"] == work_id

    rerun = complete_sidecars(
        staging_meta.parents[1],
        art_works_root=tmp_path / "art",
        operations_log=operations_log,
        limit=1,
        client=FakeClient(_lookup()),
    )
    assert rerun.attempted == 0
    assert rerun.updated == 0
    assert rerun.mirrored == 0
    assert operations_log.read_text(encoding="utf-8").splitlines() == log_entries
