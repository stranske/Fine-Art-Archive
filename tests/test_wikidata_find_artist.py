"""`WikidataProvider.find_artist` — matching a museum record's artist name to a Wikidata QID.

This runs during enrichment, resolving a source's free-text artist field against Wikidata. It
tries an exact identity bridge first (a Getty ULAN number both records carry) and only falls back
to fuzzy name matching when that is absent — the ordering matters, because ULAN is a claim of
identity while fuzzy matching is a guess, and a museum record carrying both must never let the
guess override the claim.

The fuzzy path shares its acceptance threshold with `_verified_artist_qid`, whose own comment says
so explicitly: "one number, so 'close enough to be this artist' cannot mean two different things."
`find_artist` held an independent copy of the same literal instead of referencing it — the two
would still agree today, but the SECOND anyone retuned one of them, "one number" would become
false. Fixed to reference the class constant; the tests below assert the class constant governs
the endpoint precisely, so a future retune of the threshold cannot silently leave this path behind.
"""

from __future__ import annotations

from difflib import SequenceMatcher
from typing import Any

import pytest

from fine_art_archive.enrichment.source_resolver import WikidataProvider, fold_name


class _FakeClient:
    """Scripts responses by the `action` query param; records every call made."""

    def __init__(self, **by_action: object) -> None:
        self._by_action = by_action
        self.calls: list[dict[str, Any]] = []

    def get(self, url: str, *, params=None) -> dict | None:
        params = dict(params or {})
        self.calls.append(params)
        action = params.get("action")
        if action not in self._by_action:
            raise AssertionError(f"unscripted action: {action!r}")
        reply = self._by_action[action]
        if isinstance(reply, Exception):
            raise reply
        return reply


def _provider(**by_action) -> tuple[WikidataProvider, _FakeClient]:
    client = _FakeClient(**by_action)
    return WikidataProvider(client=client), client


def _search(*ids: str) -> dict:
    return {"search": [{"id": qid} for qid in ids]}


def _human(*, name: str, ulan: str | None = None, extra_names: tuple[str, ...] = ()) -> dict:
    claims: dict[str, list] = {
        "P31": [{"mainsnak": {"datavalue": {"value": {"id": "Q5"}}}}],
    }
    if ulan is not None:
        claims["P245"] = [{"mainsnak": {"datavalue": {"value": ulan}}}]
    aliases = {"en": [{"value": alias} for alias in extra_names]} if extra_names else {}
    return {"labels": {"en": {"value": name}}, "aliases": aliases, "claims": claims}


def _non_human(*, name: str = "Not A Person") -> dict:
    return {
        "labels": {"en": {"value": name}},
        "aliases": {},
        "claims": {"P31": [{"mainsnak": {"datavalue": {"value": {"id": "Q3305213"}}}}]},
    }


def _entities(**by_qid: dict) -> dict:
    return {"entities": by_qid}


# ---------------------------------------------------------------------------------------------
# The Getty ULAN bridge — an exact identity claim, checked first.
# ---------------------------------------------------------------------------------------------


def test_a_ulan_match_wins_even_over_a_perfect_name_match(monkeypatch):
    """ULAN is a claim of identity, not a guess. It has to be checked and accepted BEFORE fuzzy
    matching runs at all — otherwise a museum record with both an exact bridge and a merely
    similar name is decided by the weaker signal."""
    provider, _ = _provider(
        wbsearchentities=_search("Q1", "Q2"),
        wbgetentities=_entities(
            Q1=_human(name="Rembrandt van Rijn", ulan="500011051"),
            Q2=_human(name="Rembrandt van Rijn"),  # identical name, no ULAN
        ),
    )

    qid, reason = provider.find_artist("Rembrandt van Rijn", ulan="500011051")

    assert qid == "Q1"
    assert "P245" in reason


def test_no_ulan_supplied_skips_straight_to_fuzzy_matching(monkeypatch):
    provider, _ = _provider(
        wbsearchentities=_search("Q1"),
        wbgetentities=_entities(Q1=_human(name="Rembrandt van Rijn", ulan="500011051")),
    )

    qid, reason = provider.find_artist("Rembrandt van Rijn", ulan=None)

    assert qid == "Q1"
    assert "fuzzy" in reason


def test_a_ulan_that_matches_nobody_falls_through_to_fuzzy_matching():
    """The source's ULAN may simply be wrong or point at a record Wikidata does not carry P245
    for. Refusing to fall back would throw away a perfectly good name match."""
    provider, _ = _provider(
        wbsearchentities=_search("Q1"),
        wbgetentities=_entities(Q1=_human(name="Rembrandt van Rijn", ulan="500011051")),
    )

    qid, reason = provider.find_artist("Rembrandt van Rijn", ulan="999999999")

    assert qid == "Q1"
    assert "fuzzy" in reason


def test_ulan_values_are_cleaned_before_comparison():
    """Wikidata's raw P245 value and a source's ULAN field are not guaranteed to be formatted
    identically; both go through `_clean_ulan` so a cosmetic difference doesn't hide a real
    match.

    The candidate's NAME deliberately does not resemble the query. A first version of this test
    used a name identical to the query, so when the cleaning step was broken the ULAN check
    simply failed silently and the SAME qid came back anyway via the fuzzy-match fallback — the
    test passed for a reason that had nothing to do with what it claimed to check. Isolating the
    ULAN path means only a match via P245 can produce a result here at all.
    """
    provider, _ = _provider(
        wbsearchentities=_search("Q1"),
        wbgetentities=_entities(Q1=_human(name="An Unrelated Name", ulan="  500011051  ")),
    )

    qid, reason = provider.find_artist("Rembrandt van Rijn", ulan="500011051")

    assert qid == "Q1"
    assert "P245" in reason


# ---------------------------------------------------------------------------------------------
# The fuzzy name match, and its shared threshold.
# ---------------------------------------------------------------------------------------------


def test_the_best_scoring_human_candidate_wins():
    """Multiple search hits can plausibly be humans; the closest name to the query is the
    answer, not the first or the last in the list."""
    provider, _ = _provider(
        wbsearchentities=_search("Q1", "Q2"),
        wbgetentities=_entities(
            Q1=_human(name="Rembrandt Harmenszoon"),
            Q2=_human(name="Rembrandt van Rijn"),
        ),
    )

    qid, _ = provider.find_artist("Rembrandt van Rijn", ulan=None)

    assert qid == "Q2"


# `fold_name("Rembrandt van Rijn" + "x" * n)` against the plain folded query: 4 trailing
# characters lands at 0.90 (above `ARTIST_NAME_MATCH_MIN`), 5 lands at 0.878 (below). Adjacent
# on either side of the real threshold, computed from the exact pipeline `find_artist` uses
# (`fold_name` then `SequenceMatcher.ratio()`) rather than a hand-picked pair — an earlier
# version of this test guessed a pair algebraically and the guess was simply wrong.
_QUERY = "Rembrandt van Rijn"
_JUST_ABOVE = _QUERY + "x" * 4
_JUST_BELOW = _QUERY + "x" * 5


def test_a_match_at_the_shared_threshold_is_accepted():
    """Pinned against the class constant rather than a copied literal — if the constant is ever
    retuned, this test's own oracle computation moves with it instead of silently testing a
    stale number."""
    ratio = SequenceMatcher(None, fold_name(_QUERY), fold_name(_JUST_ABOVE)).ratio()
    assert ratio >= WikidataProvider.ARTIST_NAME_MATCH_MIN  # the fixture actually clears the bar

    provider, _ = _provider(
        wbsearchentities=_search("Q1"), wbgetentities=_entities(Q1=_human(name=_JUST_ABOVE))
    )

    qid, reason = provider.find_artist(_QUERY, ulan=None)

    assert qid == "Q1"
    assert f"{ratio:.2f}" in reason


def test_a_match_just_below_the_shared_threshold_is_rejected():
    ratio = SequenceMatcher(None, fold_name(_QUERY), fold_name(_JUST_BELOW)).ratio()
    assert ratio < WikidataProvider.ARTIST_NAME_MATCH_MIN  # the fixture actually misses the bar

    provider, _ = _provider(
        wbsearchentities=_search("Q1"), wbgetentities=_entities(Q1=_human(name=_JUST_BELOW))
    )

    qid, reason = provider.find_artist(_QUERY, ulan=None)

    assert qid is None
    assert reason is None


def test_the_endpoints_threshold_is_governed_by_the_shared_constant_not_a_private_copy():
    """The regression this fix targets: retuning the class constant must retune what this
    endpoint accepts too. A private copy of the literal held the same value today and would
    have gone on doing so right up until someone tuned the constant and reasonably expected
    both callers to move — which is exactly the drift this test exists to make impossible."""
    provider, _ = _provider(
        wbsearchentities=_search("Q1"), wbgetentities=_entities(Q1=_human(name=_JUST_ABOVE))
    )
    ratio = SequenceMatcher(None, fold_name(_QUERY), fold_name(_JUST_ABOVE)).ratio()

    original = WikidataProvider.ARTIST_NAME_MATCH_MIN
    try:
        WikidataProvider.ARTIST_NAME_MATCH_MIN = ratio + 0.01
        qid, _ = provider.find_artist(_QUERY, ulan=None)
        assert qid is None, "raising the constant should have raised the endpoint's own bar"

        WikidataProvider.ARTIST_NAME_MATCH_MIN = ratio - 0.01
        qid, _ = provider.find_artist(_QUERY, ulan=None)
        assert qid == "Q1", "lowering the constant should have lowered the endpoint's own bar"
    finally:
        WikidataProvider.ARTIST_NAME_MATCH_MIN = original


def test_aliases_are_matched_too_not_only_the_primary_label():
    """A search hit's Wikidata LABEL may be formal ("Rembrandt Harmenszoon van Rijn") while a
    museum record uses a common form ("Rembrandt"). Aliases are what bridge the two without
    dragging the acceptance threshold down for everyone."""
    provider, _ = _provider(
        wbsearchentities=_search("Q1"),
        wbgetentities=_entities(
            Q1=_human(name="Rembrandt Harmenszoon van Rijn", extra_names=("Rembrandt",))
        ),
    )

    qid, _ = provider.find_artist("Rembrandt", ulan=None)

    assert qid == "Q1"


def test_a_non_human_candidate_is_excluded_from_fuzzy_matching_even_with_a_perfect_name():
    """A painting or an award can share a name with its subject. Only P31=Q5 candidates may be
    matched, however close the name."""
    provider, _ = _provider(
        wbsearchentities=_search("Q1"),
        wbgetentities=_entities(Q1=_non_human(name="Rembrandt van Rijn")),
    )

    qid, reason = provider.find_artist("Rembrandt van Rijn", ulan=None)

    assert qid is None
    assert reason is None


def test_a_non_human_candidate_does_not_block_a_human_one_further_down(monkeypatch):
    provider, _ = _provider(
        wbsearchentities=_search("Q1", "Q2"),
        wbgetentities=_entities(
            Q1=_non_human(name="Rembrandt van Rijn"),
            Q2=_human(name="Rembrandt van Rijn"),
        ),
    )

    qid, _ = provider.find_artist("Rembrandt van Rijn", ulan=None)

    assert qid == "Q2"


# ---------------------------------------------------------------------------------------------
# Failure paths — a batch enrichment run must not die on one bad lookup.
# ---------------------------------------------------------------------------------------------


def test_a_failed_search_request_yields_no_match_not_an_exception():
    provider, client = _provider(wbsearchentities=None)

    assert provider.find_artist("Someone", ulan=None) == (None, None)
    assert len(client.calls) == 1  # no second request attempted


@pytest.mark.parametrize("hits", [{}, {"search": "not a list"}, {"search": None}])
def test_a_malformed_search_response_yields_no_match(hits):
    provider, _ = _provider(wbsearchentities=hits)

    assert provider.find_artist("Someone", ulan=None) == (None, None)


def test_an_empty_search_result_set_yields_no_match_without_a_second_request():
    provider, client = _provider(wbsearchentities=_search())

    assert provider.find_artist("Someone", ulan=None) == (None, None)

    assert len(client.calls) == 1


def test_search_hits_with_unusable_ids_are_dropped_not_fatal():
    """A hit missing an `id`, or one that isn't a clean QID, must not crash the batch — it is
    simply not a candidate."""
    provider, _ = _provider(
        wbsearchentities={"search": [{"id": "not-a-qid"}, {}, {"id": "Q1"}]},
        wbgetentities=_entities(Q1=_human(name="Someone")),
    )

    qid, _ = provider.find_artist("Someone", ulan=None)

    assert qid == "Q1"


def test_a_failed_entities_lookup_yields_no_match():
    provider, _ = _provider(wbsearchentities=_search("Q1"), wbgetentities=None)

    assert provider.find_artist("Someone", ulan=None) == (None, None)


def test_an_entity_missing_from_the_response_is_skipped_not_fatal():
    """`wbgetentities` can omit an id it was asked for (a redirect, a deleted item). The
    remaining candidates must still be considered."""
    provider, _ = _provider(
        wbsearchentities=_search("Q1", "Q2"),
        wbgetentities=_entities(Q2=_human(name="Someone")),  # Q1 absent
    )

    qid, _ = provider.find_artist("Someone", ulan=None)

    assert qid == "Q2"
