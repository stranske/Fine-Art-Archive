"""Regression coverage for the shared ALLOWED_P31 artwork-class allowlist."""

from __future__ import annotations

import os

import pytest

from fine_art_archive.known_works.artwork_classes import (
    ALLOWED_P31,
    FORBIDDEN_P31,
    USER_AGENT,
    WORK_OF_ART_QID,
    allowed_p31_non_artwork_mismatches,
    allowed_p31_sparql_values,
    audit_allowed_p31_against_wikidata,
    is_subclass_of_work_of_art,
)
from fine_art_archive.known_works.fetchers import _wd_sparql_query


def _entity_with_parents(*parents: str) -> dict:
    claims = []
    for parent in parents:
        claims.append(
            {
                "mainsnak": {
                    "snaktype": "value",
                    "datavalue": {"value": {"id": parent}},
                }
            }
        )
    return {"claims": {"P279": claims}} if claims else {"claims": {}}


def test_allowed_p31_includes_drawing_and_excludes_junk() -> None:
    assert "Q93184" in ALLOWED_P31  # drawing
    assert WORK_OF_ART_QID in ALLOWED_P31
    assert FORBIDDEN_P31.isdisjoint(ALLOWED_P31)
    assert "Q11086742" not in ALLOWED_P31


def test_wikidata_audit_user_agent_includes_contact() -> None:
    assert "tim@stranskemo.com" in USER_AGENT


def test_sparql_values_and_known_works_query_use_shared_allowlist() -> None:
    values = allowed_p31_sparql_values()
    assert "wd:Q93184" in values
    assert "wd:Q11086742" not in values
    query = _wd_sparql_query("Q43270")
    assert values in query
    assert "wd:Q11086742" not in query
    assert "wd:Q93184" in query


def test_is_subclass_of_work_of_art_walks_p279_chain() -> None:
    parent_map = {
        "Q3305213": ["Q4502142"],
        "Q4502142": [WORK_OF_ART_QID],
        "Q11086742": ["Q15416"],  # television program — not work of art
        WORK_OF_ART_QID: [],
    }
    assert is_subclass_of_work_of_art(WORK_OF_ART_QID, parent_map)
    assert is_subclass_of_work_of_art("Q3305213", parent_map)
    assert not is_subclass_of_work_of_art("Q11086742", parent_map)


def test_allowed_p31_audit_accepts_subclass_chain() -> None:
    entities = {
        qid: _entity_with_parents(WORK_OF_ART_QID) for qid in ALLOWED_P31 if qid != WORK_OF_ART_QID
    }
    entities[WORK_OF_ART_QID] = _entity_with_parents()
    assert allowed_p31_non_artwork_mismatches(entities) == []


def test_allowed_p31_audit_reports_non_artwork_and_missing() -> None:
    # Temporarily treat the allowlist as containing a junk id via a local
    # entities payload that only covers a subset — missing members are reported.
    entities = {
        "Q3305213": _entity_with_parents("Q15416"),  # wrong parent
    }
    mismatches = allowed_p31_non_artwork_mismatches(entities)
    joined = "\n".join(mismatches)
    assert "Q3305213: not a subclass of Q838948" in joined
    assert "Q93184: Wikidata returned no entity" in joined


@pytest.mark.skipif(
    os.environ.get("RUN_WIKIDATA_AUDIT") != "1",
    reason="Set RUN_WIKIDATA_AUDIT=1 to run the live Wikidata ALLOWED_P31 audit.",
)
def test_live_allowed_p31_members_are_work_of_art_subclasses() -> None:
    assert audit_allowed_p31_against_wikidata() == []


def test_series_of_prints_is_a_group_class() -> None:
    """Q19960510 is what Hokusai's "Thirty-six Views of Mount Fuji" carries.

    Labels confirmed against live Wikidata 2026-09-02: Q19960510 is "series of
    prints", a subclass of Q15709879 "artwork series". Q227494 declares it
    alongside Q1396354 "colour woodcut" — so an acquisition gate that asks
    whether ANY class is an artwork class sees the woodcut and says yes, and a
    SERIES identity lands on a single print's sidecar. Being a set is not
    cancelled by also being a medium.
    """
    from fine_art_archive.known_works.artwork_classes import (
        GROUP_P31,
        SINGLE_WORK_P31,
        is_group_class,
        is_single_work_class,
    )

    assert "Q19960510" in GROUP_P31
    assert is_group_class("Q19960510")
    assert "Q19960510" not in SINGLE_WORK_P31
    assert not is_single_work_class("Q19960510")


def test_an_entity_that_is_both_a_series_and_a_woodcut_classifies_as_a_series() -> None:
    from fine_art_archive.known_works.artwork_classes import is_series_qid

    def entity(p31=None, p279=None) -> dict:
        def claim(pid, qids):
            return {
                pid: [
                    {"mainsnak": {"snaktype": "value", "datavalue": {"value": {"id": q}}}}
                    for q in qids
                ]
            }

        claims: dict = {}
        if p31:
            claims.update(claim("P31", p31))
        if p279:
            claims.update(claim("P279", p279))
        return {"claims": claims}

    entities = {
        "Q227494": entity(p31=["Q19960510", "Q1396354"]),
        "Q19960510": entity(p279=["Q15709879"]),
        "Q1396354": entity(p279=["Q18219090"]),
    }
    assert is_series_qid("Q227494", entities)
    assert not is_series_qid(
        "Q1", {"Q1": entity(p31=["Q3305213"]), "Q3305213": entity()}
    ), "a plain painting is not a series"
