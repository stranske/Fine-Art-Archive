"""Focused, network-free tests for issue #321 metadata completion."""

from __future__ import annotations

import json
import urllib.error
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
from scripts.complete_metadata import complete_sidecars

from fine_art_archive import provenance, sidecar
from fine_art_archive.collect import host_registry
from fine_art_archive.enrichment.source_resolver import (
    ArtistQidResolver,
    Candidate,
    IiifProvider,
    JsonClient,
    MuseumProvider,
    ProviderResult,
    Resolution,
    SourceResolver,
    Tier,
    WikidataProvider,
    apply_resolution,
    parse_dimensions,
)

MINIMAL_SIDECAR: dict[str, Any] = {
    "work_id": "4f3a2b8-after-the-bullfight-cassatt",
    "schema_version": "1.0",
    "artist": {"name": "Mary Cassatt"},
    "title": "After the Bullfight",
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


class StaticProvider:
    def __init__(
        self,
        source_id: str,
        *,
        value: Any = None,
        checked: bool = True,
        tier: Tier = Tier.GENERAL,
    ) -> None:
        self.source_id = source_id
        self.value = value
        self.checked = checked
        self.tier = tier
        self.calls: list[str] = []

    def resolve(self, meta: dict[str, Any], field: str) -> ProviderResult:
        assert meta["work_id"] == MINIMAL_SIDECAR["work_id"]
        self.calls.append(field)
        candidate = (
            Candidate(
                self.value,
                self.source_id,
                f"https://example.test/{self.source_id}",
                self.tier,
            )
            if self.value is not None
            else None
        )
        return ProviderResult(self.checked, self.source_id, candidate)


def _resolver(
    *,
    museum: StaticProvider | None = None,
    wikidata: StaticProvider | None = None,
    iiif: StaticProvider | None = None,
    europeana: StaticProvider | None = None,
    commons: StaticProvider | None = None,
) -> SourceResolver:
    return SourceResolver(
        museum=museum or StaticProvider("museum", checked=False),
        wikidata=wikidata or StaticProvider("wikidata", checked=False),
        iiif=iiif or StaticProvider("iiif", checked=False),
        europeana=europeana or StaticProvider("europeana", checked=False),
        commons=commons or StaticProvider("commons", checked=False),
    )


def _claim(value: Any) -> dict[str, Any]:
    return {"mainsnak": {"datavalue": {"value": value}}}


class FakeJsonClient:
    def __init__(self, responses: list[dict[str, Any]], *, timeout: float = 15) -> None:
        self.responses = responses
        self.timeout = timeout
        self.calls: list[tuple[str, dict[str, str] | None]] = []

    def get(self, url: str, *, params: dict[str, str] | None = None) -> dict[str, Any] | None:
        self.calls.append((url, params))
        return self.responses.pop(0)


def test_tier_a_wins_before_tier_b_when_both_have_values() -> None:
    museum = StaticProvider("met", value="1873", tier=Tier.MUSEUM)
    wikidata = StaticProvider("wikidata", value="1874")
    resolver = _resolver(museum=museum, wikidata=wikidata)

    resolution = resolver.research(deepcopy(MINIMAL_SIDECAR), "year")

    assert resolution.status == "available"
    assert resolution.as_tuple() == ("1873", "met", "https://example.test/met")
    assert museum.calls == ["year"]
    assert wikidata.calls == []


def test_new_registry_host_uses_declarative_api_before_wikidata() -> None:
    museum_client = FakeJsonClient(
        [
            {
                "record": {
                    "objectType": "Oil painting",
                    "productionDates": [{"date": {"text": "1888"}}],
                    "materialsAndTechniques": "oil on canvas",
                }
            }
        ]
    )
    museum = MuseumProvider(client=museum_client)  # type: ignore[arg-type]
    wikidata = StaticProvider("wikidata", value="1889")
    meta = deepcopy(MINIMAL_SIDECAR)
    meta["holder"] = {
        "name": "V&A",
        "wikidata_q": None,
        "ror": None,
        "url": "https://www.vam.ac.uk/",
        "accession": "O1288719",
    }
    resolver = SourceResolver(
        museum=museum,
        wikidata=wikidata,
        iiif=StaticProvider("iiif", checked=False),
        europeana=StaticProvider("europeana", checked=False),
        commons=StaticProvider("commons", checked=False),
    )

    resolution = resolver.research(meta, "year")

    assert resolution.status == "available"
    assert resolution.value == "1888"
    assert resolution.source_id == "museum:victoria_and_albert"
    assert resolution.tier == Tier.MUSEUM
    assert resolution.source_ref == "https://api.vam.ac.uk/v2/museumobject/O1288719"
    assert museum_client.calls == [("https://api.vam.ac.uk/v2/museumobject/O1288719", None)]
    assert wikidata.calls == []


def test_declarative_iiif_pattern_is_tier_a(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry = host_registry.HostEntry(
        host_id="iiif_museum",
        name="IIIF Museum",
        wikidata_q="Q999001",
        ror=None,
        homepage="https://museum.example/",
        rights_default="mixed",
        primary_adapter=None,
        accession_property="P217",
        iiif_pattern="https://iiif.example/manifests/{accession}.json",
    )
    monkeypatch.setattr(
        host_registry,
        "find_by_holder",
        lambda **kwargs: entry if kwargs.get("wikidata_q") == entry.wikidata_q else None,
    )
    museum_client = FakeJsonClient(
        [
            {
                "@context": "http://iiif.io/api/presentation/3/context.json",
                "id": "https://iiif.example/manifests/42.json",
                "type": "Manifest",
                "metadata": [
                    {
                        "label": {"en": ["Dimensions"]},
                        "value": {"en": ["82.5 × 64 cm"]},
                    }
                ],
            }
        ]
    )
    museum = MuseumProvider(client=museum_client)  # type: ignore[arg-type]
    wikidata = StaticProvider("wikidata", value={"h_cm": 1.0, "w_cm": 1.0})
    meta = deepcopy(MINIMAL_SIDECAR)
    meta["holder"] = {
        "name": entry.name,
        "wikidata_q": entry.wikidata_q,
        "accession": "42",
    }
    resolver = SourceResolver(
        museum=museum,
        wikidata=wikidata,
        iiif=StaticProvider("iiif", checked=False),
        europeana=StaticProvider("europeana", checked=False),
        commons=StaticProvider("commons", checked=False),
    )

    resolution = resolver.research(meta, "dimensions_original")

    assert resolution.status == "available"
    assert resolution.value == {
        "h_cm": 82.5,
        "w_cm": 64.0,
        "raw": "82.5 × 64 cm",
    }
    assert resolution.source_id == "museum:iiif_museum"
    assert resolution.tier == Tier.MUSEUM
    assert wikidata.calls == []


def test_registry_accession_property_discovers_declarative_iiif_identifier() -> None:
    museum_client = FakeJsonClient(
        [
            {
                "entities": {
                    "Q106854726": {
                        "claims": {
                            "P10121": [_claim("231347")],
                        }
                    }
                }
            },
            {
                "@context": "http://iiif.io/api/presentation/3/context.json",
                "id": "https://iiif.harvardartmuseums.org/manifests/object/231347",
                "type": "Manifest",
                "metadata": [
                    {
                        "label": {"en": ["Date"]},
                        "value": {"en": ["about 1500"]},
                    }
                ],
            },
        ]
    )
    museum = MuseumProvider(client=museum_client)  # type: ignore[arg-type]
    generic_wikidata = StaticProvider("wikidata", value="1499")
    meta = deepcopy(MINIMAL_SIDECAR)
    meta["holder"] = {
        "name": "Harvard Art Museums",
        "wikidata_q": "Q3783572",
        "accession": None,
    }
    meta["stable_identifiers"] = {"wikidata_q": "Q106854726"}
    resolver = SourceResolver(
        museum=museum,
        wikidata=generic_wikidata,
        iiif=StaticProvider("iiif", checked=False),
        europeana=StaticProvider("europeana", checked=False),
        commons=StaticProvider("commons", checked=False),
    )

    resolution = resolver.research(meta, "year")

    assert resolution.status == "available"
    assert resolution.value == "1500"
    assert resolution.source_id == "museum:harvard_art_museums"
    assert resolution.tier == Tier.MUSEUM
    assert museum_client.calls == [
        (
            WikidataProvider.API_URL,
            {
                "action": "wbgetentities",
                "format": "json",
                "ids": "Q106854726",
                "languages": "en",
                "props": "claims",
            },
        ),
        ("https://iiif.harvardartmuseums.org/manifests/object/231347", None),
    ]
    assert generic_wikidata.calls == []


def test_available_value_is_never_overwritten_or_requeried() -> None:
    meta = deepcopy(MINIMAL_SIDECAR)
    meta["year"] = "1872"
    provenance.set(
        meta,
        "year",
        "available",
        "catalogue",
        checked_at="2026-07-24T00:00:00Z",
    )
    museum = StaticProvider("met", value="1873", tier=Tier.MUSEUM)

    resolution = _resolver(museum=museum).research(meta, "year")

    assert resolution.value == "1872"
    assert resolution.status == "available"
    assert resolution.source_id == "catalogue"
    assert museum.calls == []


def test_all_failed_or_inapplicable_sources_leave_field_researchable() -> None:
    resolution = _resolver().research(deepcopy(MINIMAL_SIDECAR), "medium")

    assert resolution.status == "not_researched"
    assert resolution.value is None
    assert resolution.source_id is None


def test_wikidata_claim_is_available_with_source_identity() -> None:
    client = FakeJsonClient(
        [
            {
                "entities": {
                    "Q98549878": {
                        "claims": {
                            "P571": [
                                _claim(
                                    {
                                        "time": "+1873-00-00T00:00:00Z",
                                        "precision": 9,
                                    }
                                )
                            ]
                        }
                    }
                }
            }
        ]
    )
    wikidata = WikidataProvider(client=client)  # type: ignore[arg-type]
    meta = deepcopy(MINIMAL_SIDECAR)
    meta["stable_identifiers"] = {"wikidata_q": "Q98549878"}
    resolver = SourceResolver(
        museum=StaticProvider("museum", checked=False),
        wikidata=wikidata,
        iiif=StaticProvider("iiif", checked=False),
        europeana=StaticProvider("europeana", checked=False),
        commons=StaticProvider("commons", checked=False),
    )

    resolution = resolver.research(meta, "year")

    assert resolution.status == "available"
    assert resolution.value == "1873"
    assert resolution.source_id == "wikidata"
    assert resolution.source_ref == "https://www.wikidata.org/wiki/Q98549878"


def test_iiif_only_value_is_available_and_dimensions_are_parsed() -> None:
    client = FakeJsonClient(
        [
            {
                "@context": "http://iiif.io/api/presentation/3/context.json",
                "id": "https://iiif.example/manifest",
                "type": "Manifest",
                "metadata": [
                    {
                        "label": {"en": ["Dimensions"]},
                        "value": {"en": ["82.5 × 64 cm"]},
                    }
                ],
            }
        ]
    )
    iiif = IiifProvider(client=client)  # type: ignore[arg-type]
    meta = deepcopy(MINIMAL_SIDECAR)
    meta["stable_identifiers"] = {
        "iiif_manifest_url": "https://iiif.example/manifest",
    }
    resolver = SourceResolver(
        museum=StaticProvider("museum", checked=False),
        wikidata=StaticProvider("wikidata", checked=False),
        iiif=iiif,
        europeana=StaticProvider("europeana", checked=False),
        commons=StaticProvider("commons", checked=False),
    )

    resolution = resolver.research(meta, "dimensions_original")

    assert resolution.status == "available"
    assert resolution.source_id == "iiif"
    assert resolution.source_ref == "https://iiif.example/manifest"
    assert resolution.value == {
        "h_cm": 82.5,
        "w_cm": 64.0,
        "raw": "82.5 × 64 cm",
    }


def test_absent_from_all_successfully_checked_sources_is_not_available() -> None:
    resolver = _resolver(
        museum=StaticProvider("met"),
        wikidata=StaticProvider("wikidata"),
        iiif=StaticProvider("iiif"),
    )

    resolution = resolver.research(deepcopy(MINIMAL_SIDECAR), "medium")

    assert resolution.status == "not_available"
    assert resolution.value is None
    assert resolution.source_id == "source_resolver"
    assert resolution.note is not None
    assert "met, wikidata, iiif" in resolution.note


def test_source_disagreement_replaces_guess_and_records_loser() -> None:
    meta = deepcopy(MINIMAL_SIDECAR)
    meta["year"] = "1872"
    provenance.set(
        meta,
        "year",
        "unverified",
        "filename_parse",
        checked_at="2026-07-24T00:00:00Z",
    )
    resolver = _resolver(
        museum=StaticProvider("met", value="1873", tier=Tier.MUSEUM),
    )

    resolution = resolver.research(meta, "year")
    changed = apply_resolution(
        meta,
        "year",
        resolution,
        checked_at="2026-07-24T01:00:00Z",
    )

    assert changed
    assert meta["year"] == "1873"
    assert meta["field_provenance"]["year"] == {
        "status": "conflicting",
        "source": "met",
        "source_ref": "https://example.test/met",
        "checked_at": "2026-07-24T01:00:00Z",
        "note": 'Higher-tier source replaced lower-tier existing value "1872".',
    }


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Height: 10 in; Width: 5 in", {"h_cm": 25.4, "w_cm": 12.7}),
        ("820 × 640 mm", {"h_cm": 82.0, "w_cm": 64.0}),
    ],
)
def test_dimension_parser_converts_to_centimetres(raw: str, expected: dict[str, float]) -> None:
    parsed = parse_dimensions(raw)

    assert parsed is not None
    assert {key: parsed[key] for key in ("h_cm", "w_cm")} == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # Imperial first, metric in parentheses: reading left to right lands
        # inside the fraction and yields 4 x 9 cm for a 34.9 x 23.8 cm sheet.
        ("13 3/4 x 9 3/8 in. (34.9 x 23.8 cm)", {"h_cm": 34.9, "w_cm": 23.8}),
        ("41 3/8  x 33 1/4 in. (105.1 x 84.5 cm)", {"h_cm": 105.1, "w_cm": 84.5}),
        # "H."/"W." with a trailing period must be recognised as named axes.
        ("H. 35 x W. 17.2 cm (13 3/4 x 6 3/4 in.)", {"h_cm": 35.0, "w_cm": 17.2}),
        # The object comes first; a mount or shadow box on a later line must not
        # outrank it.
        (
            "Image: 29 1/2 x 33 in. (74.9 x 83.8 cm)\r\n"
            "Shadow box, shared with 1977.340: H. 63 in. (160 cm); W. 45 in. (114.3 cm)",
            {"h_cm": 74.9, "w_cm": 83.8},
        ),
        (
            "Image: 23 3/4 x 17 1/2 in. (60.4 x 44.5 cm)\r\n"
            "Overall: 56 1/8 x 24 3/4in. (142.6 x 62.9 cm)",
            {"h_cm": 60.4, "w_cm": 44.5},
        ),
        # Unitless labeled values belong to their own line, not to a later
        # framed-imperial line in the same museum record.
        (
            "Image: H. 34.9 x W. 23.8\n"
            "Frame: H. 63 in. x W. 45 in.",
            {"h_cm": 34.9, "w_cm": 23.8},
        ),
        # When a record has no parenthesized metric pair, preserve mixed
        # imperial fractions instead of falling through to no dimensions.
        ("13 3/4 x 9 3/8 in.", {"h_cm": 34.925, "w_cm": 23.8125}),
        # Depth must not displace height: "A x B x C" is (A, B), never (B, C).
        ("92.7 x 74.3 x 2.5cm", {"h_cm": 92.7, "w_cm": 74.3}),
        ("68 × 54 × 2 cm", {"h_cm": 68.0, "w_cm": 54.0}),
        # A full stop running into the number must not become a decimal point.
        ("Oil on canvas.98 x 127 cm", {"h_cm": 98.0, "w_cm": 127.0}),
        # Metric-first strings already parsed correctly and must not regress.
        ("60.3 × 80.2 cm (23 3/4 × 31 1/2 in.)", {"h_cm": 60.3, "w_cm": 80.2}),
        ("79.4×89.5 cm", {"h_cm": 79.4, "w_cm": 89.5}),
    ],
)
def test_dimension_parser_handles_museum_strings(raw: str, expected: dict[str, float]) -> None:
    parsed = parse_dimensions(raw)

    assert parsed is not None
    assert {key: parsed[key] for key in ("h_cm", "w_cm")} == expected


def test_dimension_parser_does_not_read_a_word_as_a_named_axis() -> None:
    """A bare ``h``/``w`` inside a word is not a height or width marker."""
    assert parse_dimensions("sketch 45 x 30 cm") == {
        "h_cm": 45.0,
        "w_cm": 30.0,
        "raw": "sketch 45 x 30 cm",
    }


def test_artist_resolves_from_museum_record_and_getty_ulan(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry = host_registry.HostEntry(
        host_id="met",
        name="The Metropolitan Museum of Art",
        wikidata_q="Q160236",
        ror="01xtbq813",
        homepage="https://www.metmuseum.org/",
        rights_default="public-domain",
        primary_adapter="met",
    )
    monkeypatch.setattr(
        host_registry,
        "find_by_holder",
        lambda **kwargs: entry if kwargs.get("wikidata_q") == "Q160236" else None,
    )
    museum_client = FakeJsonClient(
        [
            {
                "objectID": 42,
                "title": "Test Work",
                "artistDisplayName": "Aurelia Test",
                "artistULAN_URL": "http://vocab.getty.edu/ulan/500123456",
                "objectURL": "https://www.metmuseum.org/art/collection/search/42",
            }
        ]
    )
    wikidata_client = FakeJsonClient(
        [
            {"search": [{"id": "Q1234", "label": "Aurelia Test"}]},
            {
                "entities": {
                    "Q1234": {
                        "claims": {
                            "P31": [_claim({"id": "Q5"})],
                            "P245": [_claim("500123456")],
                        },
                        "labels": {"en": {"value": "Aurelia Test"}},
                        "aliases": {"en": [{"value": "A. Test"}]},
                    }
                }
            },
        ]
    )
    wikidata = WikidataProvider(client=wikidata_client)  # type: ignore[arg-type]
    identity = ArtistQidResolver(wikidata=wikidata)
    museum = MuseumProvider(
        client=museum_client,  # type: ignore[arg-type]
        artist_resolver=identity,
    )
    meta = deepcopy(MINIMAL_SIDECAR)
    meta["artist"] = {"name": "Unknown museum transcription"}
    meta["holder"] = {
        "name": entry.name,
        "wikidata_q": entry.wikidata_q,
        "ror": entry.ror,
        "url": entry.homepage,
        "accession": "42",
    }
    resolver = SourceResolver(
        museum=museum,
        wikidata=StaticProvider("wikidata", checked=False),
        iiif=StaticProvider("iiif", checked=False),
        europeana=StaticProvider("europeana", checked=False),
        commons=StaticProvider("commons", checked=False),
    )

    resolution = resolver.research(meta, "artist_qid")

    assert resolution.status == "available"
    assert resolution.value == "Q1234"
    assert resolution.source_id == "met"
    assert resolution.note == "Wikidata P245 match via Getty ULAN 500123456"


@pytest.mark.parametrize(
    "error",
    [
        urllib.error.URLError("offline"),
        TimeoutError("timeout"),
        OSError("socket failed"),
    ],
)
def test_json_transport_is_timeout_bounded_and_skips_network_failures(
    monkeypatch: pytest.MonkeyPatch, error: OSError
) -> None:
    seen_timeouts: list[float] = []

    def fail(request: object, *, timeout: float) -> None:
        assert request is not None
        seen_timeouts.append(timeout)
        raise error

    monkeypatch.setattr("urllib.request.urlopen", fail)

    assert JsonClient(timeout=7.5).get("https://example.test/data.json") is None
    assert seen_timeouts == [7.5]


def test_completion_writes_staging_existing_work_mirror_and_log_idempotently(
    tmp_path: Path,
) -> None:
    work_id = str(MINIMAL_SIDECAR["work_id"])
    meta = deepcopy(MINIMAL_SIDECAR)
    provenance.set(
        meta,
        "year",
        "not_researched",
        checked_at="2026-07-24T00:00:00Z",
    )
    for field in ("medium", "category", "dimensions_original", "artist_qid"):
        provenance.set(
            meta,
            field,
            "not_available",
            "fixture",
            checked_at="2026-07-24T00:00:00Z",
        )
    staging_path = tmp_path / "staging" / work_id / "meta.json"
    mirror_path = tmp_path / "art" / "works" / work_id / "meta.json"
    log_path = tmp_path / "operations.log"
    sidecar.write(staging_path, meta)
    sidecar.write(mirror_path, meta)

    class YearResolver:
        def research(self, meta: dict[str, Any], field: str) -> Resolution:
            assert field == "year"
            return Resolution(
                "1873",
                "wikidata",
                "https://www.wikidata.org/wiki/Q1",
                "available",
                Tier.GENERAL,
            )

    first = complete_sidecars(
        staging_path.parents[1],
        art_works_root=tmp_path / "art",
        operations_log=log_path,
        resolver=YearResolver(),  # type: ignore[arg-type]
        limit=1,
    )

    assert first.updated_works == 1
    assert first.updated_fields == 1
    assert first.mirrored == 1
    assert sidecar.load_validated(staging_path) == sidecar.load_validated(mirror_path)
    assert sidecar.load(staging_path)["year"] == "1873"
    log_lines = log_path.read_text(encoding="utf-8").splitlines()
    assert len(log_lines) == 1
    assert json.loads(log_lines[0])["fields"]["year"]["source"] == "wikidata"

    second = complete_sidecars(
        staging_path.parents[1],
        art_works_root=tmp_path / "art",
        operations_log=log_path,
        resolver=YearResolver(),  # type: ignore[arg-type]
        limit=1,
    )

    assert second.attempted_works == 0
    assert second.updated_works == 0
    assert log_path.read_text(encoding="utf-8").splitlines() == log_lines


def test_invalid_sidecar_is_skipped_not_fatal(tmp_path: Path) -> None:
    staging_dir = tmp_path / "staging"
    log_path = tmp_path / "operations.log"

    def write_valid(directory: str) -> Path:
        meta = deepcopy(MINIMAL_SIDECAR)
        provenance.set(meta, "year", "not_researched", checked_at="2026-07-24T00:00:00Z")
        for field in ("medium", "category", "dimensions_original", "artist_qid"):
            provenance.set(
                meta, field, "not_available", "fixture", checked_at="2026-07-24T00:00:00Z"
            )
        path = staging_dir / directory / "meta.json"
        sidecar.write(path, meta)
        return path

    first = write_valid("01-valid")
    invalid = deepcopy(MINIMAL_SIDECAR)
    invalid["rights"] = {"status": "CC0"}
    invalid_path = staging_dir / "02-invalid" / "meta.json"
    invalid_path.parent.mkdir(parents=True)
    invalid_path.write_text(json.dumps(invalid), encoding="utf-8")
    last = write_valid("03-valid")

    class YearResolver:
        def research(self, meta: dict[str, Any], field: str) -> Resolution:
            assert field == "year"
            return Resolution(
                "1873", "wikidata", "https://www.wikidata.org/wiki/Q1", "available", Tier.GENERAL
            )

    stats = complete_sidecars(
        staging_dir,
        operations_log=log_path,
        resolver=YearResolver(),  # type: ignore[arg-type]
        limit=2,
    )

    assert stats.attempted_works == 2
    assert stats.updated_works == 2
    assert stats.skipped_invalid == 1
    assert sidecar.load(first)["year"] == "1873"
    assert sidecar.load(last)["year"] == "1873"
    entries = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
    skipped = [entry for entry in entries if entry["op"] == "invalid_sidecar_skipped"]
    assert len(skipped) == 1
    assert skipped[0]["actor"] == "complete_metadata"
    assert skipped[0]["work_id"] == str(MINIMAL_SIDECAR["work_id"])
    assert skipped[0]["staging_path"] == str(invalid_path)
    assert "'CC0' is not one of" in skipped[0]["validation_error"]
