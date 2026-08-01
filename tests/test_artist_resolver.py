"""Regression coverage for curated artist identity resolution."""

import os

import pytest

from fine_art_archive.identity.artist_resolver import (
    CURATED_ALIASES,
    audit_curated_aliases_against_wikidata,
    build_alias_table,
    curated_alias_identity_mismatches,
    resolve_artist,
)

# This is deliberately independent of CURATED_ALIASES.  The resolver table is
# hand-maintained, and a plausible-looking but wrong Q-ID silently propagates
# through discovery and sidecar metadata with high confidence.
EXPECTED_CURATED_QIDS = {
    "Pieter Bruegel the Elder": "Q43270",
    "Pieter Brueghel the Younger": "Q255828",
    "Jan Brueghel the Elder": "Q209050",
    "Jan Brueghel the Younger": "Q285933",
    "Claude Monet": "Q296",
    "Pierre-Auguste Renoir": "Q39931",
    "Rembrandt van Rijn": "Q5598",
    "Édouard Manet": "Q40599",
    "Paul Cézanne": "Q35548",
    "Diego Velázquez": "Q297",
    "Albrecht Dürer": "Q5580",
    "Leonardo da Vinci": "Q762",
    "Michelangelo": "Q5592",
    "Raphael": "Q5597",
    "Caravaggio": "Q42207",
    "Titian": "Q47551",
    "Vincent van Gogh": "Q5582",
    "Giotto di Bondone": "Q7814",
    "Katsushika Hokusai": "Q5586",
    "Utagawa Hiroshige": "Q200798",
    "Francisco Goya": "Q5432",
}


def test_curated_aliases_have_the_expected_canonical_qids() -> None:
    assert {entry["display_name"]: entry["q"] for entry in CURATED_ALIASES} == EXPECTED_CURATED_QIDS


def test_corrected_curated_aliases_resolve_exactly() -> None:
    table = build_alias_table()

    for name, qid in {
        "Pierre-Auguste Renoir": "Q39931",
        "Jan Brueghel the Elder": "Q209050",
        "Jan Brueghel the Younger": "Q285933",
        "Pieter Brueghel the Younger": "Q255828",
    }.items():
        resolved = resolve_artist(name, table, allow_wikidata=False)
        assert resolved.q == qid
        assert resolved.method == "alias-exact"
        assert resolved.confidence == 0.99


def test_curated_alias_identity_audit_accepts_english_label_or_alias() -> None:
    entities = {
        "Q43270": {"labels": {"en": {"value": "Pieter Bruegel I"}}},
        "Q255828": {
            "labels": {"en": {"value": "Pieter Brueghel II"}},
            "aliases": {"en": [{"value": "Pieter Brueghel the Younger"}]},
        },
    }

    mismatches = curated_alias_identity_mismatches(entities)

    assert "Q43270" not in "\n".join(mismatches)
    assert "Q255828" not in "\n".join(mismatches)
    assert (
        "Q209050: expected 'Jan Brueghel the Elder', but Wikidata returned no entity" in mismatches
    )


def test_curated_alias_identity_audit_reports_name_mismatch() -> None:
    entities = {
        "Q43270": {"labels": {"en": {"value": "Not Pieter Bruegel"}}},
    }

    mismatches = curated_alias_identity_mismatches(entities)

    assert (
        "Q43270: expected 'Pieter Bruegel the Elder'; Wikidata reports 'Not Pieter Bruegel'"
        in mismatches
    )


@pytest.mark.skipif(
    os.environ.get("RUN_WIKIDATA_AUDIT") != "1",
    reason="Set RUN_WIKIDATA_AUDIT=1 to run the live Wikidata identity audit.",
)
def test_live_curated_aliases_match_wikidata() -> None:
    assert audit_curated_aliases_against_wikidata() == []
