"""Wikidata enrichment must preserve usable labels and reject unavailable identities."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from fine_art_archive.enrichment.source_resolver import (
    Candidate,
    CommonsSdcProvider,
    ProviderResult,
    SourceResolver,
    Tier,
    WikidataProvider,
)

SIDECAR = {"stable_identifiers": {"wikidata_q": "Q123"}}


def _claim(value):
    return {"mainsnak": {"datavalue": {"value": value}}}


def _provider(values, *label_responses):
    work = {"claims": {"P186": [_claim(value) for value in values]}}
    client = SimpleNamespace(get=Mock(side_effect=[{"entities": {"Q123": work}}, *label_responses]))
    return WikidataProvider(client=client), client


def test_literal_medium_claims_are_trimmed_and_keep_source_order():
    provider, client = _provider([" oil on canvas ", "", 42, " tempera "])

    assert provider.resolve(SIDECAR, "medium") == ProviderResult(
        True,
        "wikidata",
        Candidate(
            "oil on canvas, tempera",
            "wikidata",
            "https://www.wikidata.org/wiki/Q123",
            Tier.GENERAL,
        ),
    )
    assert client.get.call_count == 1


def test_blank_and_nontext_medium_claims_supply_no_candidate():
    provider, client = _provider([" ", "", 42, None])

    assert provider.resolve(SIDECAR, "medium") == ProviderResult(True, "wikidata")
    assert client.get.call_count == 1


def test_medium_labels_skip_unusable_entities_and_deduplicate_in_claim_order():
    provider, client = _provider(
        [{"id": f"Q{number}"} for number in range(1, 7)],
        {
            "entities": {
                "Q6": {"labels": {"en": {"value": "tempera"}}},
                "Q5": {"labels": {"en": {"value": "oil paint"}}},
                "Q4": {"labels": {"fr": {"value": "toile"}}},
                "Q2": None,
                "Q1": {"labels": {"en": {"value": "oil paint"}}},
            }
        },
    )

    assert provider.resolve(SIDECAR, "medium") == ProviderResult(
        True,
        "wikidata",
        Candidate(
            "oil paint, tempera",
            "wikidata",
            "https://www.wikidata.org/wiki/Q123",
            Tier.GENERAL,
        ),
    )
    assert client.get.call_count == 2
    assert client.get.call_args.kwargs["params"]["ids"] == "Q1|Q2|Q3|Q4|Q5|Q6"


def test_entities_without_usable_labels_do_not_invent_a_medium():
    provider, client = _provider([{"id": "Q1"}], {"entities": {"Q1": {}}})

    assert provider.resolve(SIDECAR, "medium") == ProviderResult(True, "wikidata")
    assert client.get.call_count == 2


@pytest.mark.parametrize("provider_kind", ["wikidata", "commons"])
@pytest.mark.parametrize("field,property_id", [("medium", "P186"), ("category", "P136")])
def test_failed_label_lookup_leaves_field_researchable(provider_kind, field, property_id):
    entity = {"claims": {property_id: [_claim({"id": "Q1"})]}}
    entity_id = "Q123" if provider_kind == "wikidata" else "M123"
    client = SimpleNamespace(get=Mock(side_effect=[{"entities": {entity_id: entity}}, None]))
    provider = (
        WikidataProvider(client=client)
        if provider_kind == "wikidata"
        else CommonsSdcProvider(client=client)
    )
    inactive = SimpleNamespace(resolve=Mock(return_value=ProviderResult(False, "inactive")))
    providers = dict.fromkeys(("museum", "wikidata", "iiif", "europeana", "commons"), inactive)
    providers[provider_kind] = provider
    resolver = SourceResolver(**providers)
    sidecar = {"stable_identifiers": {"wikidata_q": "Q123", "commons_file": "Example.jpg"}}

    result = resolver.research(sidecar, field)

    assert result.status == "not_researched"
    assert result.value is None
    assert result.source_id is None
    assert client.get.call_count == 2


def test_missing_work_entity_is_unchecked_even_if_it_contains_claims():
    client = SimpleNamespace(
        get=Mock(
            return_value={
                "entities": {"Q123": {"missing": "", "claims": {"P186": [_claim("oil paint")]}}}
            }
        )
    )

    assert WikidataProvider(client=client).resolve(SIDECAR, "medium") == ProviderResult(
        False, "wikidata"
    )
    client.get.assert_called_once()


def test_failed_work_lookup_is_unchecked():
    client = SimpleNamespace(get=Mock(return_value=None))

    assert WikidataProvider(client=client).resolve(SIDECAR, "medium") == ProviderResult(
        False, "wikidata"
    )
    client.get.assert_called_once()


def test_work_without_a_qid_is_unchecked_without_querying_wikidata():
    client = SimpleNamespace(get=Mock(side_effect=AssertionError("no identity to query")))

    assert WikidataProvider(client=client).resolve({}, "medium") == ProviderResult(
        False, "wikidata"
    )
    client.get.assert_not_called()
