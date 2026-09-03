"""Network-free contracts for the resolver's remote enrichment providers.

These paths turn third-party responses into archive metadata.  A plausible but
wrong value is more dangerous here than an exception, so the tests assert both
the request identity and the candidate that may be written downstream.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any

import pytest

from fine_art_archive.collect import host_registry
from fine_art_archive.enrichment.source_resolver import (
    Candidate,
    CommonsSdcProvider,
    EuropeanaProvider,
    MuseumProvider,
    ProviderResult,
    Tier,
    WikidataProvider,
)

SIDECAR: dict[str, Any] = {
    "work_id": "4f3a2b8-after-the-bullfight-cassatt",
    "artist": {"name": "Mary Cassatt"},
    "title": "After the Bullfight",
}


class ScriptedJsonClient:
    """Return scripted JSON responses and retain the exact request sequence."""

    def __init__(self, responses: list[dict[str, Any]], *, timeout: float = 15) -> None:
        self.responses = responses
        self.timeout = timeout
        self.calls: list[tuple[str, dict[str, str] | None]] = []

    def get(self, url: str, *, params: dict[str, str] | None = None) -> dict[str, Any]:
        self.calls.append((url, params))
        return self.responses.pop(0)


def _claim(value: Any) -> dict[str, Any]:
    return {"mainsnak": {"datavalue": {"value": value}}}


def test_configured_accession_caches_a_negative_wikidata_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A missing custom accession must not spend a second request in the same run.

    ``None`` is a cached answer here, not the cache-miss sentinel.  Membership
    testing is what preserves that distinction.
    """
    entry = host_registry.HostEntry(
        host_id="example_museum",
        name="Example Museum",
        wikidata_q="Q999",
        ror=None,
        homepage="https://museum.example/",
        rights_default="public-domain",
        primary_adapter=None,
        api_base="https://museum.example/api/objects",
        accession_property="P3634",
    )
    monkeypatch.setattr(host_registry, "find_by_holder", lambda **_kwargs: entry)
    client = ScriptedJsonClient([{"entities": {"Q123": {"claims": {}}}}])
    provider = MuseumProvider(client=client)  # type: ignore[arg-type]
    meta = deepcopy(SIDECAR)
    meta["holder"] = {"name": entry.name, "wikidata_q": entry.wikidata_q}
    meta["stable_identifiers"] = {"wikidata_q": "Q123"}

    first = provider.resolve(meta, "year")
    second = provider.resolve(meta, "year")

    expected = ProviderResult(False, "museum:example_museum")
    assert first == second == expected
    assert client.calls == [
        (
            WikidataProvider.API_URL,
            {
                "action": "wbgetentities",
                "format": "json",
                "ids": "Q123",
                "languages": "en",
                "props": "claims",
            },
        )
    ]


def test_europeana_provider_maps_the_record_and_preserves_its_query() -> None:
    client = ScriptedJsonClient(
        [
            {
                "items": [
                    {
                        "guid": "https://www.europeana.eu/item/123/example",
                        "edmConceptLabel": ["Oil", "canvas"],
                    }
                ]
            }
        ]
    )
    provider = EuropeanaProvider(api_key="test-key", client=client)  # type: ignore[arg-type]

    result = provider.resolve(deepcopy(SIDECAR), "medium")

    assert result == ProviderResult(
        True,
        "europeana",
        Candidate(
            "Oil, canvas",
            "europeana",
            "https://www.europeana.eu/item/123/example",
            Tier.GENERAL,
        ),
    )
    assert client.calls == [
        (
            EuropeanaProvider.API_URL,
            {
                "wskey": "test-key",
                "query": "After the Bullfight Mary Cassatt",
                "rows": "5",
                "profile": "rich",
            },
        )
    ]


def test_commons_sdc_provider_resolves_a_claim_label_and_file_source() -> None:
    client = ScriptedJsonClient(
        [
            {
                "entities": {
                    "M123": {
                        "claims": {"P186": [_claim({"id": "Q296955"})]},
                    }
                }
            },
            {
                "entities": {
                    "Q296955": {"labels": {"en": {"value": "Oil paint"}}},
                }
            },
        ]
    )
    provider = CommonsSdcProvider(client=client)  # type: ignore[arg-type]
    meta = deepcopy(SIDECAR)
    meta["stable_identifiers"] = {"commons_file": "Mary Cassatt.jpg"}

    result = provider.resolve(meta, "medium")

    assert result == ProviderResult(
        True,
        "wikimedia_commons_sdc",
        Candidate(
            "Oil paint",
            "wikimedia_commons_sdc",
            "https://commons.wikimedia.org/wiki/File%3AMary_Cassatt.jpg",
            Tier.GENERAL,
        ),
    )
    assert client.calls == [
        (
            CommonsSdcProvider.API_URL,
            {
                "action": "wbgetentities",
                "format": "json",
                "sites": "commonswiki",
                "titles": "File:Mary Cassatt.jpg",
                "languages": "en",
                "props": "claims|labels",
            },
        ),
        (
            WikidataProvider.API_URL,
            {
                "action": "wbgetentities",
                "format": "json",
                "ids": "Q296955",
                "languages": "en",
                "props": "claims|labels|aliases",
            },
        ),
    ]
