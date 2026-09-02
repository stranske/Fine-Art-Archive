"""The resolution cascade in `resolve_artist`, and the Wikidata fallback beneath it.

Four strategies, tried in order, each less certain than the last: an exact match against the
curated alias table, a family-surname fold (with a veto when the input names two different
painters), an online Wikidata search, and finally "unresolved". Every caller downstream reads
`method` and `confidence` to decide how much to trust the result — a mislabelled method turns a
guess into something the pipeline treats as certain, or vice versa.

None of this cascade, and none of `_wb_search_for_artist`, was under test.
"""

from __future__ import annotations

import json
import urllib.error

import pytest

from fine_art_archive.identity import artist_resolver as artist_resolver


@pytest.fixture(scope="module")
def table() -> dict:
    return artist_resolver.build_alias_table()


def _resolve(raw: str, **kwargs) -> artist_resolver.ResolvedArtist:
    return artist_resolver.resolve_artist(raw, artist_resolver.build_alias_table(), **kwargs)


# ---------------------------------------------------------------------------------------------
# The empty case, and multi-creator strings.
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("raw", ["", "   ", None])
def test_a_blank_or_missing_artist_resolves_to_the_empty_method(raw, table):
    result = artist_resolver.resolve_artist(raw, table)

    assert result.method == "empty"
    assert result.confidence == 0.0
    assert result.q is None


def test_a_multi_creator_string_resolves_on_its_primary(table):
    """ "Rubens and Jan Brueghel the Elder" is catalogued as two hands. The pipeline needs ONE
    resolution to drive the row, and re-running on each piece is left to the caller — dropping
    the co-creators silently would lose the second name from the record entirely."""
    result = artist_resolver.resolve_artist("Rubens and Jan Brueghel the Elder", table)

    assert result.q == artist_resolver.resolve_artist("Rubens", table).q
    assert result.method.startswith("multi-primary(")
    assert "Jan Brueghel the Elder" in result.notes


def test_the_multi_creator_confidence_is_discounted_from_the_primarys(table):
    """A joint attribution is less certain than a solo one, even when the primary name itself
    resolves with full confidence."""
    solo = artist_resolver.resolve_artist("Rembrandt", table)
    joint = artist_resolver.resolve_artist("Rembrandt and an unknown assistant", table)

    assert joint.confidence == pytest.approx(solo.confidence * 0.9)


def test_a_comma_separated_family_given_name_is_not_treated_as_multiple_creators(table):
    """ "Vermeer, Johannes" is one painter in last-name-first form, not two people joined by a
    comma. `split_multi` treats a single comma with no "and"/"&" as that form."""
    result = artist_resolver.resolve_artist("Vermeer, Johannes", table)

    assert not result.method.startswith("multi-primary")


# ---------------------------------------------------------------------------------------------
# Exact alias match.
# ---------------------------------------------------------------------------------------------


def test_a_curated_alias_resolves_exactly(table):
    result = artist_resolver.resolve_artist("Rembrandt van Rijn", table)

    assert result.method == "alias-exact"
    assert result.confidence == 0.99
    assert result.q == "Q5598"


def test_exact_match_beats_every_other_strategy(table):
    """An exact hit must never fall through to a lower-confidence path just because a later
    branch would also match."""
    result = artist_resolver.resolve_artist("Rembrandt van Rijn", table, allow_wikidata=True)

    assert result.method == "alias-exact"


# ---------------------------------------------------------------------------------------------
# Family-surname fold, and its veto.
# ---------------------------------------------------------------------------------------------


def test_a_distinctive_surname_folds_to_its_curated_entry(table):
    """ "Rembrandt" alone, or wrapped in extra words, is not a literal alias-table key — the fold
    is what lets a partial or decorated name still resolve."""
    result = artist_resolver.resolve_artist("Rembrandt studio painting", table)

    assert result.method == "alias-family-fold"
    assert result.confidence == 0.85
    assert result.q == "Q5598"
    assert "rembrandt" in result.notes


def test_two_competing_surnames_veto_the_fold_entirely(table):
    """The property that keeps the fold safe: an input naming two different curated painters
    must resolve to NEITHER, not to whichever happens first in the alias table's iteration
    order. Folding to one would misattribute the other painter's work.
    """
    result = artist_resolver.resolve_artist("Rembrandt Monet", table)

    assert result.q is None
    assert result.method != "alias-family-fold"


def test_a_prefix_phrase_still_attaches_to_the_named_artist_at_lower_confidence(table):
    """ "Workshop of Rembrandt" is provenance the archive wants to keep — it names whose workshop
    — but it is explicitly NOT the same hand as a solo "Rembrandt", so it must resolve to a
    different method and a lower confidence, not be indistinguishable from an autograph work."""
    result = artist_resolver.resolve_artist("Workshop of Rembrandt", table)

    assert result.method == "alias-family-fold-derived"
    assert result.confidence == 0.50
    assert result.q == "Q5598"
    assert "derived attribution" in result.notes


@pytest.mark.parametrize(
    "phrase", ["Studio of", "School of", "Circle of", "Follower of", "Manner of"]
)
def test_every_declared_relation_phrase_is_recognised(table, phrase):
    result = artist_resolver.resolve_artist(f"{phrase} Rembrandt", table)

    assert result.method == "alias-family-fold-derived"


def test_a_plain_family_fold_is_more_confident_than_a_derived_one(table):
    """The two confidences (0.85 vs 0.50) exist to be compared by a caller deciding whether to
    trust an attribution automatically. If they were equal, that decision would have nothing to
    read."""
    plain = artist_resolver.resolve_artist("Rembrandt studio painting", table)
    derived = artist_resolver.resolve_artist("Workshop of Rembrandt", table)

    assert plain.confidence > derived.confidence


def test_an_entry_without_a_primary_surname_does_not_fold_blind(table):
    """`Pieter Brueghel` needs "the Elder"/"the Younger" to disambiguate two real painters, so
    the curated table deliberately leaves its `primary_surname` unset — folding on "Brueghel"
    alone would guess between two different people."""
    result = artist_resolver.resolve_artist("Brueghel", table)

    assert result.method != "alias-family-fold"
    assert result.method != "alias-family-fold-derived"


# ---------------------------------------------------------------------------------------------
# No match, and the Wikidata fallback.
# ---------------------------------------------------------------------------------------------


def test_no_match_and_no_wikidata_permission_is_unresolved_without_any_network_call(
    table, monkeypatch
):
    """`allow_wikidata` defaults to False, and it has to actually gate the network — not merely
    be documented as doing so."""

    def refuse(raw):
        raise AssertionError("Wikidata was queried despite allow_wikidata=False")

    monkeypatch.setattr(artist_resolver, "_wb_search_for_artist", refuse)

    result = artist_resolver.resolve_artist("Someone Uncatalogued Entirely", table)

    assert result.method == "unresolved"
    assert result.confidence == 0.0


def test_a_wikidata_hit_is_used_when_permitted(table, monkeypatch):
    monkeypatch.setattr(
        artist_resolver,
        "_wb_search_for_artist",
        lambda raw: {"q": "Q999", "label": "A Found Painter", "lifespan": "1600–1650"},
    )

    result = artist_resolver.resolve_artist(
        "Someone Uncatalogued Entirely", table, allow_wikidata=True
    )

    assert result.method == "wikidata-search"
    assert result.q == "Q999"
    assert result.display_name == "A Found Painter"
    assert result.lifespan == "1600–1650"
    assert result.confidence == 0.70  # the documented default when the hit carries none


def test_a_wikidata_hits_own_confidence_is_used_when_present(table, monkeypatch):
    monkeypatch.setattr(
        artist_resolver,
        "_wb_search_for_artist",
        lambda raw: {"q": "Q999", "label": "A Found Painter", "confidence": 0.6},
    )

    result = artist_resolver.resolve_artist(
        "Someone Uncatalogued Entirely", table, allow_wikidata=True
    )

    assert result.confidence == 0.6


def test_the_family_key_of_a_wikidata_hit_is_derived_from_its_label(table, monkeypatch):
    monkeypatch.setattr(
        artist_resolver,
        "_wb_search_for_artist",
        lambda raw: {"q": "Q999", "label": "A Found Painter"},
    )

    result = artist_resolver.resolve_artist(
        "Someone Uncatalogued Entirely", table, allow_wikidata=True
    )

    assert result.family_key == "painter"


def test_a_wikidata_miss_falls_through_to_unresolved(table, monkeypatch):
    monkeypatch.setattr(artist_resolver, "_wb_search_for_artist", lambda raw: None)

    result = artist_resolver.resolve_artist(
        "Someone Uncatalogued Entirely", table, allow_wikidata=True
    )

    assert result.method == "unresolved"


# ---------------------------------------------------------------------------------------------
# The cache — including the bug this PR fixes.
# ---------------------------------------------------------------------------------------------


def test_a_positive_wikidata_result_is_served_from_cache_on_a_second_call(table, monkeypatch):
    calls = []
    monkeypatch.setattr(
        artist_resolver,
        "_wb_search_for_artist",
        lambda raw: (calls.append(raw), {"q": "Q999", "label": "A Found Painter"})[1],
    )
    cache: dict = {}

    artist_resolver.resolve_artist(
        "Someone Uncatalogued Entirely", table, allow_wikidata=True, wb_cache=cache
    )
    artist_resolver.resolve_artist(
        "Someone Uncatalogued Entirely", table, allow_wikidata=True, wb_cache=cache
    )

    assert len(calls) == 1


def test_a_negative_wikidata_result_is_also_served_from_cache_on_a_second_call(table, monkeypatch):
    """The bug this PR fixes: `cache.get(folded) is None` cannot distinguish "never queried"
    from "queried, found nothing", so a shared cache re-issued the same two network calls for
    every occurrence of an artist Wikidata simply does not have — defeating the entire reason a
    caller passes a cache across a batch run in the first place.
    """
    calls = []
    monkeypatch.setattr(
        artist_resolver, "_wb_search_for_artist", lambda raw: (calls.append(raw), None)[1]
    )
    cache: dict = {}

    for _ in range(3):
        artist_resolver.resolve_artist(
            "Someone Uncatalogued Entirely", table, allow_wikidata=True, wb_cache=cache
        )

    assert len(calls) == 1


def test_the_cache_is_keyed_by_folded_name_so_spelling_variants_share_one_lookup(
    table, monkeypatch
):
    calls = []
    monkeypatch.setattr(
        artist_resolver, "_wb_search_for_artist", lambda raw: (calls.append(raw), None)[1]
    )
    cache: dict = {}

    artist_resolver.resolve_artist(
        "Someone Uncatalogued", table, allow_wikidata=True, wb_cache=cache
    )
    artist_resolver.resolve_artist(
        "SOMEONE   Uncatalogued", table, allow_wikidata=True, wb_cache=cache
    )

    assert len(calls) == 1


def test_without_a_cache_every_call_queries_independently(table, monkeypatch):
    """No cache passed means no cross-call memory — each call gets its own throwaway dict, which
    is the documented default (`wb_cache: ... | None = None`)."""
    calls = []
    monkeypatch.setattr(
        artist_resolver, "_wb_search_for_artist", lambda raw: (calls.append(raw), None)[1]
    )

    artist_resolver.resolve_artist("Someone Uncatalogued Entirely", table, allow_wikidata=True)
    artist_resolver.resolve_artist("Someone Uncatalogued Entirely", table, allow_wikidata=True)

    assert len(calls) == 2


# ---------------------------------------------------------------------------------------------
# `_wb_search_for_artist` itself, offline.
# ---------------------------------------------------------------------------------------------


def _wbsearch_response(*hits: dict) -> bytes:
    return json.dumps({"search": list(hits)}).encode()


def _wbget_response(**entities: dict) -> bytes:
    return json.dumps({"entities": entities}).encode()


def _human_entity(*, birth: str | None = None, death: str | None = None) -> dict:
    claims: dict[str, list] = {
        "P31": [{"mainsnak": {"datavalue": {"value": {"id": "Q5"}}}}],
    }
    if birth is not None:
        claims["P569"] = [{"mainsnak": {"datavalue": {"value": {"time": birth}}}}]
    if death is not None:
        claims["P570"] = [{"mainsnak": {"datavalue": {"value": {"time": death}}}}]
    return {"claims": claims, "labels": {"en": {"value": "A Found Painter"}}}


def _non_human_entity() -> dict:
    return {"claims": {"P31": [{"mainsnak": {"datavalue": {"value": {"id": "Q3305213"}}}}]}}


class _Response:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *exc_info: object) -> bool:
        return False


@pytest.fixture
def transport(monkeypatch):
    """Script a sequence of urlopen replies; records every request made."""

    def install(*replies: object):
        calls = []

        def fake_urlopen(request, timeout=None):
            calls.append({"url": request.full_url, "headers": dict(request.headers)})
            reply = replies[len(calls) - 1] if len(calls) <= len(replies) else replies[-1]
            if isinstance(reply, Exception):
                raise reply
            return _Response(reply)

        monkeypatch.setattr(artist_resolver.urllib.request, "urlopen", fake_urlopen)
        return calls

    return install


def test_no_search_hits_returns_none_without_a_second_request(transport):
    calls = transport(_wbsearch_response())

    assert artist_resolver._wb_search_for_artist("Nobody At All") is None
    assert len(calls) == 1


def test_a_human_top_hit_is_returned_at_top_hit_confidence(transport):
    transport(
        _wbsearch_response({"id": "Q1"}),
        _wbget_response(
            Q1=_human_entity(birth="+1606-00-00T00:00:00Z", death="+1669-00-00T00:00:00Z")
        ),
    )

    result = artist_resolver._wb_search_for_artist("Rembrandt van Rijn")

    assert result["q"] == "Q1"
    assert result["label"] == "A Found Painter"
    assert result["lifespan"] == "1606–1669"
    assert result["confidence"] == 0.75


def test_a_non_human_top_hit_is_skipped_in_favour_of_a_human_one_further_down(transport):
    """A painting, a place, an award can all show up in a name search. The FIRST human is the
    answer; a non-human top hit must not simply fail the whole lookup."""
    transport(
        _wbsearch_response({"id": "Q1"}, {"id": "Q2"}),
        _wbget_response(Q1=_non_human_entity(), Q2=_human_entity()),
    )

    result = artist_resolver._wb_search_for_artist("Someone")

    assert result["q"] == "Q2"
    assert result["confidence"] == 0.60  # not the top hit


def test_no_human_among_the_candidates_returns_none(transport):
    transport(
        _wbsearch_response({"id": "Q1"}, {"id": "Q2"}),
        _wbget_response(Q1=_non_human_entity(), Q2=_non_human_entity()),
    )

    assert artist_resolver._wb_search_for_artist("Someone") is None


def test_only_the_first_five_hits_are_checked(transport):
    """`wbgetentities` is one request for up to five ids — checking every hit an unbounded
    search returns would make one artist lookup scale with how common the name is."""
    hits = [{"id": f"Q{i}"} for i in range(8)]
    entities = {f"Q{i}": _non_human_entity() for i in range(5)}
    # The only human is 6th — outside the checked window.
    entities["Q5"] = _human_entity()
    for i in range(6, 8):
        entities[f"Q{i}"] = _human_entity()
    transport(_wbsearch_response(*hits), _wbget_response(**entities))

    assert artist_resolver._wb_search_for_artist("Common Name") is None


@pytest.mark.parametrize(
    "birth,death,expected",
    [
        ("+1606-00-00T00:00:00Z", "+1669-00-00T00:00:00Z", "1606–1669"),
        ("+1606-00-00T00:00:00Z", None, "1606–?"),
        (None, "+1669-00-00T00:00:00Z", "?–1669"),
        (None, None, ""),
    ],
)
def test_lifespan_formatting_covers_partial_dates(transport, birth, death, expected):
    """No date at all is a plain empty string — not "?–?", which would read as "checked, and
    both dates are genuinely unknown" rather than "no date claim was present"."""
    transport(
        _wbsearch_response({"id": "Q1"}),
        _wbget_response(Q1=_human_entity(birth=birth, death=death)),
    )

    assert artist_resolver._wb_search_for_artist("Someone")["lifespan"] == expected


def test_a_search_transport_failure_returns_none_rather_than_raising(transport):
    """A lookup embedded in a batch enrichment run must not take the whole run down because
    Wikidata timed out on one name."""
    transport(urllib.error.URLError("timed out"))

    assert artist_resolver._wb_search_for_artist("Someone") is None


def test_a_getentities_transport_failure_returns_none_rather_than_raising(transport):
    transport(_wbsearch_response({"id": "Q1"}), urllib.error.URLError("timed out"))

    assert artist_resolver._wb_search_for_artist("Someone") is None


def test_a_malformed_json_body_returns_none_rather_than_raising(transport):
    transport(b"not json at all")

    assert artist_resolver._wb_search_for_artist("Someone") is None


def test_the_request_identifies_itself(transport):
    calls = transport(_wbsearch_response())

    artist_resolver._wb_search_for_artist("Someone")

    assert "FAA" in calls[0]["headers"].get("User-agent", "")
