"""`holder.py`'s defensive readers — the ones that decide what a Wikidata record means.

At 66.2% this is the third-largest gap in the repository, and the unexercised statements are the
guards: every branch that decides an upstream field is the wrong shape and should be ignored
rather than trusted.

Wikidata is user-edited. Any of these fields can be absent, null, a list where a dict belongs, or
a string where an object belongs — and none of that raises here. It produces a holder record with
a wrong museum, a wrong ROR, or a blank artist, which the archive then stores as fact.
"""

from __future__ import annotations

import urllib.error
from email.message import Message

import pytest

from fine_art_archive.enrichment.holder import (
    _artist_name,
    _english_label,
    _entity_ror,
    _retry_delay,
)


def _headers(**fields: str) -> Message:
    msg = Message()
    for key, value in fields.items():
        msg[key.replace("_", "-")] = value
    return msg


def _http_error(**fields: str) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("http://x", 429, "Too Many Requests", _headers(**fields), None)


def _claim(property_id: str, value: str) -> dict:
    return {"claims": {property_id: [{"mainsnak": {"datavalue": {"value": value}}}]}}


# ---------------------------------------------------------------------------------------------
# Backoff. Too short hammers a rate-limited API; too long stalls the enrichment pass.
# ---------------------------------------------------------------------------------------------


def test_retry_after_is_honoured_when_the_server_gives_one():
    """The server knows better than our exponent. Ignoring it is how a 429 becomes a ban."""
    assert _retry_delay(_http_error(Retry_After="7"), attempt=1) == 7.0


def test_retry_after_is_capped_so_one_header_cannot_stall_the_pass():
    assert _retry_delay(_http_error(Retry_After="9999"), attempt=1) == 30.0


@pytest.mark.parametrize("bad", ["soon", "", "7.5", "-3", "Wed, 21 Oct 2015 07:28:00 GMT"])
def test_a_non_integer_retry_after_falls_back_to_the_exponent(bad):
    """A date-form Retry-After is legal HTTP and unparseable here; falling back beats `float()`
    raising inside a retry handler, which would turn a throttle into a crash."""
    assert _retry_delay(_http_error(Retry_After=bad), attempt=3) == 8.0


def test_without_the_header_the_backoff_is_exponential():
    assert _retry_delay(_http_error(), attempt=0) == 1.0
    assert _retry_delay(_http_error(), attempt=2) == 4.0


def test_the_exponent_is_capped_too():
    """Without the cap, attempt 10 waits seventeen minutes."""
    assert _retry_delay(_http_error(), attempt=10) == 30.0


# ---------------------------------------------------------------------------------------------
# English labels out of a user-edited entity.
# ---------------------------------------------------------------------------------------------


def test_an_english_label_is_read_and_stripped():
    entity = {"labels": {"en": {"value": "  Rijksmuseum  "}}}
    assert _english_label(entity) == "Rijksmuseum"


@pytest.mark.parametrize(
    "entity",
    [
        {},
        {"labels": None},
        {"labels": []},
        {"labels": {"nl": {"value": "Rijksmuseum"}}},
        {"labels": {"en": None}},
        {"labels": {"en": "Rijksmuseum"}},
        {"labels": {"en": {}}},
        {"labels": {"en": {"value": None}}},
        {"labels": {"en": {"value": 42}}},
        {"labels": {"en": {"value": "   "}}},
    ],
)
def test_every_wrong_shape_yields_none_rather_than_a_partial_name(entity):
    """Each of these is a real Wikidata shape, and each must be ignored rather than coerced.

    A blank or partial collection name is worse than no name: it is stored as the holder and
    silently replaces the museum this work actually sits in.
    """
    assert _english_label(entity) is None


# ---------------------------------------------------------------------------------------------
# ROR identifiers, tried in property order.
# ---------------------------------------------------------------------------------------------


def test_the_current_property_is_read():
    assert _entity_ror(_claim("P6782", "03vek6s52")) == "03vek6s52"


def test_a_ror_url_is_normalised_to_its_identifier():
    assert _entity_ror(_claim("P6782", "https://ror.org/03vek6s52")) == "03vek6s52"


def test_the_current_property_wins_over_a_legacy_one():
    """P6782 is the real ROR property; P3500 and P8250 are guarded legacy inputs.

    Order matters because a legacy field can hold a value that happens to pass the pattern, and
    taking it over the current one records the wrong institution.
    """
    entity = {
        "claims": {
            "P6782": [{"mainsnak": {"datavalue": {"value": "03vek6s52"}}}],
            "P3500": [{"mainsnak": {"datavalue": {"value": "05dxps055"}}}],
        }
    }
    assert _entity_ror(entity) == "03vek6s52"


@pytest.mark.parametrize(
    "value",
    ["nonsense", "12345", "", "ror.org", "13vek6s52"],
)
def test_a_value_that_is_not_a_ror_is_refused(value):
    """The pattern is the whole guard: a Ringgold number in P3500 must not become a ROR."""
    assert _entity_ror(_claim("P6782", value)) is None


def test_an_entity_with_no_claims_has_no_ror():
    assert _entity_ror({}) is None


# ---------------------------------------------------------------------------------------------
# Artist name, from either sidecar shape.
# ---------------------------------------------------------------------------------------------


def test_the_nested_artist_object_is_read():
    assert _artist_name({"artist": {"name": "Rembrandt"}}) == "Rembrandt"


def test_the_flat_field_is_read_when_there_is_no_object():
    assert _artist_name({"artist_name": "Rembrandt"}) == "Rembrandt"


def test_the_nested_object_wins_when_both_are_present():
    """One sidecar shape supersedes the other; reading the stale flat field would resurrect an
    older name after the object was corrected."""
    sidecar = {"artist": {"name": "Rembrandt"}, "artist_name": "Rembrant"}
    assert _artist_name(sidecar) == "Rembrandt"


@pytest.mark.parametrize(
    "sidecar",
    [
        {},
        {"artist": {}},
        {"artist": {"name": None}},
        {"artist": {"name": 42}},
        {"artist_name": None},
        {"artist_name": ["Rembrandt"]},
    ],
)
def test_a_missing_or_wrongly_typed_artist_is_the_empty_string(sidecar):
    """Empty string, not None: callers concatenate this, and None would raise deep inside a
    formatting path rather than at the read."""
    assert _artist_name(sidecar) == ""
