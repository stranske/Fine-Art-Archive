"""Turning Wikidata claim values into archive fields.

Every function here reads third-party JSON and writes a number or a label into a sidecar, and each
fails by producing a WRONG value rather than by raising. A unit factor off by an order of magnitude
records a 1.5 m altarpiece as 1.5 cm; a deprecated claim treated as current imports data Wikidata
itself has marked wrong; a category match in the wrong order files a stained-glass window as a
painting. None of it was covered.

The unit table is the sharpest of these. `+1.5` metres and `+1.5` centimetres are the same amount
with different meanings, and nothing downstream can tell them apart once the conversion is done.
"""

from __future__ import annotations

import pytest

from fine_art_archive.enrichment.source_resolver import (
    _category_from_text,
    _claim_values,
    _clean_text,
    _dimensions_from_claims,
    _english_label,
    _entity_names,
    _first_text,
    _number,
    _quantity_cm,
    _round_dimension,
)

_CM = "http://www.wikidata.org/entity/Q174728"
_M = "http://www.wikidata.org/entity/Q11573"
_MM = "http://www.wikidata.org/entity/Q828224"
_INCH = "http://www.wikidata.org/entity/Q218593"


def _quantity(amount: str, unit: str) -> dict:
    return {"amount": amount, "unit": unit}


def _entity(**claims) -> dict:
    return {
        "claims": {
            prop: [{"mainsnak": {"datavalue": {"value": value}}}] for prop, value in claims.items()
        }
    }


# ---------------------------------------------------------------------------------------------
# Units.
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "amount,unit,expected",
    [
        ("+50", _CM, 50.0),
        ("+1.5", _M, 150.0),
        ("+500", _MM, 50.0),
        ("+10", _INCH, 25.4),
        ("+7", "1", 7.0),
    ],
)
def test_each_supported_unit_converts_to_centimetres(amount, unit, expected):
    """The archive stores centimetres. A wrong factor is invisible: the number looks plausible and
    only the physical object disagrees."""
    assert _quantity_cm(_quantity(amount, unit)) == pytest.approx(expected)


def test_an_unknown_unit_yields_nothing_rather_than_an_unconverted_number():
    """Feet, points, or a unit added to Wikidata next year. Returning the raw amount would record
    it AS centimetres, which is worse than recording no dimension at all."""
    assert _quantity_cm(_quantity("+7", "http://www.wikidata.org/entity/Q99999")) is None


@pytest.mark.parametrize("value", ["a string", None, 42, [], {"unit": _CM}])
def test_a_malformed_quantity_yields_nothing(value):
    assert _quantity_cm(value) is None


def test_an_uncoercible_amount_yields_nothing():
    assert _quantity_cm(_quantity("about a metre", _M)) is None


def test_the_unit_is_read_from_the_end_of_the_uri():
    """Wikidata writes the unit as a full entity URI, sometimes with a trailing slash."""
    assert _quantity_cm(_quantity("+50", _CM + "/")) == pytest.approx(50.0)
    assert _quantity_cm(_quantity("+50", "Q174728")) == pytest.approx(50.0)


# ---------------------------------------------------------------------------------------------
# Numbers.
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected", [("+50", 50.0), ("-3", -3.0), ("1.5", 1.5), (" 2 ", 2.0), (7, 7.0), (7.5, 7.5)]
)
def test_numbers_are_parsed_including_the_wikidata_plus_prefix(raw, expected):
    """Wikidata writes every quantity with an explicit sign, so `+50` has to parse.

    The implementation's `.lstrip("+")` is redundant — `float("+50")` already works — and removing
    it fails nothing here. That was checked by deliberate break rather than assumed, and it is
    recorded rather than papered over: the test pins the BEHAVIOUR (a signed amount parses), not
    the line that happens to implement it.
    """
    assert _number(raw) == pytest.approx(expected)


def test_a_decimal_comma_is_read_as_a_decimal_point():
    """European-formatted sources write `1,5`. Read as a thousands separator it becomes 15."""
    assert _number("1,5") == pytest.approx(1.5)


@pytest.mark.parametrize("raw", [True, False])
def test_a_boolean_is_not_a_number(raw):
    """`bool` is a subclass of `int`, so `True` would silently become a dimension of 1 cm."""
    assert _number(raw) is None


@pytest.mark.parametrize("raw", ["", "  ", "many", None, [], {}])
def test_an_uncoercible_value_is_not_a_number(raw):
    assert _number(raw) is None


def test_rounding_keeps_four_places():
    """Inches convert to repeating decimals. Storing the full float makes two runs over the same
    claim produce different sidecars."""
    assert _round_dimension(25.399999999) == 25.4
    assert _round_dimension(1 / 3) == 0.3333


def test_rounding_an_absent_dimension_is_a_programming_error_not_a_zero():
    """A missing dimension stored as 0.0 cm is a claim about the object. Raising forces the caller
    to decide."""
    with pytest.raises(ValueError, match="cannot round an absent dimension"):
        _round_dimension(None)


# ---------------------------------------------------------------------------------------------
# Dimensions.
# ---------------------------------------------------------------------------------------------


def test_both_dimensions_are_read_from_their_own_properties():
    entity = _entity(P2048=_quantity("+120", _CM), P2049=_quantity("+80", _CM))

    assert _dimensions_from_claims(entity) == {"h_cm": 120.0, "w_cm": 80.0}


@pytest.mark.parametrize(
    "present,absent,key", [("P2048", "P2049", "h_cm"), ("P2049", "P2048", "w_cm")]
)
def test_one_dimension_alone_is_still_recorded(present, absent, key):
    """Half a measurement is a fact. Requiring both would discard every source that publishes only
    a height."""
    result = _dimensions_from_claims(_entity(**{present: _quantity("+120", _CM)}))

    assert result == {key: 120.0}


def test_no_dimensions_at_all_yields_nothing_rather_than_an_empty_object():
    """`{}` written to a sidecar reads as "measured, and it has no size"."""
    assert _dimensions_from_claims(_entity()) is None
    assert _dimensions_from_claims({}) is None


def test_a_dimension_in_an_unknown_unit_is_dropped_not_defaulted():
    entity = _entity(P2048=_quantity("+120", "http://www.wikidata.org/entity/Q99999"))

    assert _dimensions_from_claims(entity) is None


# ---------------------------------------------------------------------------------------------
# Claim selection.
# ---------------------------------------------------------------------------------------------


def test_a_deprecated_claim_is_skipped():
    """Wikidata marks a statement deprecated when the community has decided it is WRONG. Importing
    it anyway launders a known error into the archive as fact."""
    entity = {
        "claims": {
            "P2048": [
                {"rank": "deprecated", "mainsnak": {"datavalue": {"value": _quantity("+9", _CM)}}},
                {"rank": "normal", "mainsnak": {"datavalue": {"value": _quantity("+120", _CM)}}},
            ]
        }
    }

    assert _dimensions_from_claims(entity) == {"h_cm": 120.0}


def test_non_deprecated_ranks_are_kept_in_order():
    """Preferred and normal are both usable; the first is taken."""
    entity = {
        "claims": {
            "P2048": [
                {"rank": "preferred", "mainsnak": {"datavalue": {"value": _quantity("+120", _CM)}}},
                {"rank": "normal", "mainsnak": {"datavalue": {"value": _quantity("+9", _CM)}}},
            ]
        }
    }

    assert _dimensions_from_claims(entity) == {"h_cm": 120.0}


@pytest.mark.parametrize(
    "claims",
    [
        {"P2048": "not a list"},
        {"P2048": [{"mainsnak": "not a mapping"}]},
        {"P2048": [{"mainsnak": {"datavalue": {}}}]},
        {"P2048": ["not a mapping"]},
    ],
)
def test_a_malformed_claim_yields_no_values(claims):
    """Third-party JSON. Every shape below has been seen in some dump or other, and none of them
    should raise inside an enrichment run over thousands of works."""
    assert _claim_values({"claims": claims}, "P2048") == []


def test_a_missing_claims_block_yields_no_values():
    assert _claim_values({}, "P2048") == []
    assert _claim_values({"claims": "not a mapping"}, "P2048") == []


# ---------------------------------------------------------------------------------------------
# Categories.
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Painting", "painting"),
        ("oil painting on canvas", "painting"),
        ("photography", "photograph"),
        ("a photograph", "photograph"),
        ("etching", "print"),
        ("LITHOGRAPH", "print"),
        ("stained glass window", "stained_glass"),
        ("illuminated manuscript", "illuminated_manuscript"),
        ("architectural sculpture", "architectural_sculpture"),
        ("sculpture, marble", "sculpture"),
        ("fresco", "fresco"),
        ("tapestry", "tapestry"),
        ("altarpiece", "altarpiece"),
        ("mosaic", "mosaic"),
    ],
)
def test_a_medium_description_maps_to_a_category(text, expected):
    assert _category_from_text(text) == expected


def test_the_more_specific_token_is_matched_first():
    """`architectural sculpture` contains `sculpture`, and `stained glass` would otherwise never
    be reached at all. Order in the mapping table is the whole mechanism."""
    assert _category_from_text("architectural sculpture") == "architectural_sculpture"
    assert _category_from_text("stained glass") == "stained_glass"
    assert _category_from_text("illuminated manuscript, tempera") == "illuminated_manuscript"


def test_an_unrecognised_medium_yields_nothing_rather_than_a_default():
    """Guessing `painting` for an unknown medium would file it silently under the commonest
    category, where nobody would look for it again."""
    assert _category_from_text("performance") is None
    assert _category_from_text("") is None
    assert _category_from_text(None) is None


def test_a_list_of_descriptions_is_joined_before_matching():
    """Sources publish medium as a list of terms as often as a string."""
    assert _category_from_text(["oil", "painting"]) == "painting"


# ---------------------------------------------------------------------------------------------
# Text.
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("raw,expected", [("  Vermeer  ", "Vermeer"), (42, "42"), (1.5, "1.5")])
def test_text_is_stripped_and_numbers_are_accepted(raw, expected):
    assert _clean_text(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", None, True, False, [], {}])
def test_blank_and_non_scalar_values_are_not_text(raw):
    """`True` would otherwise become the string "True" in a title field."""
    assert _clean_text(raw) is None


def test_the_first_usable_value_wins():
    assert _first_text(None, "", "  ", "Vermeer", "ignored") == "Vermeer"


def test_a_list_value_is_joined_rather_than_taken_apart():
    assert _first_text(["Oil", "canvas"]) == "Oil, canvas"


def test_a_list_of_blanks_falls_through_to_the_next_value():
    """An empty list is not an answer. Returning "" from it would stop the search early."""
    assert _first_text(["", "  "], "Vermeer") == "Vermeer"


def test_an_english_label_is_read_from_the_labels_block():
    assert _english_label({"labels": {"en": {"value": " Girl with a Pearl Earring "}}}) == (
        "Girl with a Pearl Earring"
    )


@pytest.mark.parametrize(
    "entity",
    [
        {},
        {"labels": "not a mapping"},
        {"labels": {}},
        {"labels": {"en": "not a mapping"}},
        {"labels": {"nl": {"value": "Meisje"}}},
    ],
)
def test_a_missing_english_label_yields_nothing(entity):
    """Only English is used for matching, so a Dutch-only entity has no usable name here."""
    assert _english_label(entity) is None


def test_entity_names_are_the_label_followed_by_its_aliases():
    """Aliases are how a source's spelling is matched to Wikidata's. Dropping them loses every
    work catalogued under a variant name."""
    entity = {
        "labels": {"en": {"value": "Rembrandt"}},
        "aliases": {"en": [{"value": "Rembrandt van Rijn"}, {"value": "  "}, "not a mapping"]},
    }

    assert _entity_names(entity) == ["Rembrandt", "Rembrandt van Rijn"]


def test_an_entity_with_no_label_still_yields_its_aliases():
    entity = {"aliases": {"en": [{"value": "Rembrandt van Rijn"}]}}

    assert _entity_names(entity) == ["Rembrandt van Rijn"]


def test_an_entity_with_neither_yields_nothing():
    assert _entity_names({}) == []
    assert _entity_names({"aliases": {"en": "not a list"}}) == []
