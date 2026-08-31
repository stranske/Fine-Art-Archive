"""Parsing museum dimension strings into centimetres.

`parse_dimensions` reads what a museum wrote on a label and produces the height and width the
archive records. Nothing here raises: a misparse stores a painting at the wrong size, and the
number looks exactly as trustworthy as a right one.

The cases below are the ones the module's own comments describe as having bitten it — a shadow
box outranking the work, a run-on full stop becoming a decimal point, a bare letter matching
inside a word — plus the unit conversions, which are the quiet way to be wrong by 2.54x.
"""

from __future__ import annotations

import pytest

from fine_art_archive.enrichment.source_resolver import parse_dimensions

# ---------------------------------------------------------------------------------------------
# Units. Being wrong here scales every dimension in the archive by a constant.
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, h, w",
    [
        ("74.9 x 83.8 cm", 74.9, 83.8),
        ("100 x 200 mm", 10.0, 20.0),
        ("1 x 2 m", 100.0, 200.0),
        ("10 x 20 in.", 25.4, 50.8),
        ("H. 10 in x W. 20 in", 25.4, 50.8),
    ],
)
def test_each_unit_converts_to_centimetres(text, h, w):
    parsed = parse_dimensions(text)
    assert parsed["h_cm"] == pytest.approx(h)
    assert parsed["w_cm"] == pytest.approx(w)


def test_a_bare_pair_with_no_unit_is_read_as_centimetres():
    """The museum default. Guessing inches instead would inflate every unlabelled record by 2.54."""
    assert parse_dimensions("10 x 20") == {"h_cm": 10.0, "w_cm": 20.0, "raw": "10 x 20"}


# ---------------------------------------------------------------------------------------------
# The hazards the module documents.
# ---------------------------------------------------------------------------------------------


def test_the_work_outranks_its_shadow_box():
    """A museum lists the object first and its mount or frame below.

    Taking the largest match, or the last one, records the BOX as the painting — the module's own
    comment cites this exact pairing.
    """
    parsed = parse_dimensions("Image: 74.9 x 83.8 cm\nShadow box: H. 63 in.")
    assert parsed["h_cm"] == pytest.approx(74.9)
    assert parsed["w_cm"] == pytest.approx(83.8)


def test_a_run_on_full_stop_does_not_become_a_decimal_point():
    """ "Oil on canvas.98 x 127 cm" must be 98 cm, not 0.98 cm.

    A bare-decimal pattern would read the sentence-ending period as the start of a number and
    store a 127cm-wide canvas as under a centimetre tall.
    """
    parsed = parse_dimensions("Oil on canvas.98 x 127 cm")
    assert parsed["h_cm"] == pytest.approx(98.0)
    assert parsed["w_cm"] == pytest.approx(127.0)


def test_a_bare_letter_does_not_match_inside_a_word():
    """ "sketch 45" contains an h. Without a word boundary it reads as a height of 45."""
    assert parse_dimensions("sketch 45") is None


def test_markup_and_entities_are_stripped_before_parsing():
    """Museum feeds carry HTML. Left in place, tags and entities break the number match."""
    assert parse_dimensions("<b>30</b> x 40 cm")["h_cm"] == pytest.approx(30.0)
    assert parse_dimensions("30 &times; 40 cm")["w_cm"] == pytest.approx(40.0)


def test_a_height_alone_is_recorded_without_inventing_a_width():
    """Many labels give one dimension. A fabricated width would be indistinguishable from a
    measured one."""
    parsed = parse_dimensions("H. 35 cm")
    assert parsed["h_cm"] == pytest.approx(35.0)
    assert parsed["w_cm"] is None


# ---------------------------------------------------------------------------------------------
# Mapping input, and the `raw` fallback.
# ---------------------------------------------------------------------------------------------


def test_explicit_centimetre_fields_are_used_directly():
    assert parse_dimensions({"h_cm": 30, "w_cm": 20}) == {"h_cm": 30.0, "w_cm": 20.0}


def test_height_and_width_aliases_are_accepted():
    assert parse_dimensions({"height": 5, "width": 6}) == {"h_cm": 5.0, "w_cm": 6.0}


def test_a_mapping_with_no_numbers_falls_back_to_parsing_its_raw_text():
    """The branch that rescues a record whose structured fields are empty but whose label is not.

    Returning None here would discard a dimension the museum did publish.
    """
    parsed = parse_dimensions({"h_cm": None, "w_cm": None, "raw": "30 x 40 cm"})
    assert parsed["h_cm"] == pytest.approx(30.0)
    assert parsed["w_cm"] == pytest.approx(40.0)


def test_a_mapping_whose_raw_is_also_unusable_is_none():
    assert parse_dimensions({"h_cm": None, "w_cm": None, "raw": "no numbers here"}) is None


def test_the_original_text_is_kept_alongside_the_parse():
    """`raw` is what lets a human check a suspicious number against what the museum actually
    wrote."""
    text = "H. 35 x W. 17.2 cm"
    assert parse_dimensions(text)["raw"] == text


# ---------------------------------------------------------------------------------------------
# Nothing to parse.
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("value", [None, "", "   ", "no digits at all", {}])
def test_input_with_no_measurement_is_none_not_zero(value):
    """Zero is a measurement. None is the absence of one, and only the second is true here."""
    assert parse_dimensions(value) is None


def test_a_mixed_fraction_is_not_silently_misread():
    """ "12 1/2 x 9 in." is not parsed, and that is the safe answer.

    Recorded as a limitation rather than a wish: returning None loses the record, but reading
    "12 1/2" as 12 or as 1/2 would store a confidently wrong size. If this ever gains support,
    this test is where the expectation changes deliberately.
    """
    assert parse_dimensions("12 1/2 x 9 in.") is None
