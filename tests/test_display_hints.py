"""Tests for fine_art_archive.display.hints — the display_hints builder."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fine_art_archive.display.hints import (  # noqa: E402
    build_display_hints,
    infer_orientation,
    pick_dither,
)

# -- orientation -------------------------------------------------------------


def test_orientation_landscape():
    assert infer_orientation(1600, 1000) == "landscape"


def test_orientation_portrait():
    assert infer_orientation(1000, 1600) == "portrait"


def test_orientation_square_within_tolerance():
    assert infer_orientation(1000, 1000) == "square"
    assert infer_orientation(1000, 1030) == "square"  # within 5%


def test_orientation_just_outside_square_tolerance():
    # Ratio 1.10 is well outside the 5% square tolerance.
    assert infer_orientation(1100, 1000) == "landscape"


def test_orientation_rejects_zero_dims():
    with pytest.raises(ValueError):
        infer_orientation(0, 100)


# -- dither selection --------------------------------------------------------


def test_dither_default_atkinson():
    assert pick_dither([]) == "atkinson"
    assert pick_dither(["renaissance", "religious"]) == "atkinson"


def test_dither_impressionism_riemersma():
    assert pick_dither(["impressionism"]) == "riemersma"
    assert pick_dither(["Post-Impressionism"]) == "riemersma"  # case-insensitive
    assert pick_dither(["pointillism", "french"]) == "riemersma"


def test_dither_graphic_ordered():
    assert pick_dither(["geometric"]) == "ordered"
    assert pick_dither(["mondrian", "abstract"]) == "ordered"
    assert pick_dither(["minimalism"]) == "ordered"


def test_dither_photograph_bluenoise():
    assert pick_dither(["photograph"]) == "blue_noise"
    assert pick_dither(["photography"]) == "blue_noise"


# -- full builder ------------------------------------------------------------


def test_build_includes_all_target_devices():
    hints = build_display_hints(w_px=1600, h_px=1000)
    for key in [
        "inkposter_tela_28_5",
        "pimoroni_inky_13_3",
        "hisense_canvastv",
        "samsung_frame",
        "lg_oled_gallery",
        "tv_4k_generic",
        "meural_landscape",
        "meural_portrait",
    ]:
        assert key in hints


def test_build_orientation_landscape():
    hints = build_display_hints(w_px=1600, h_px=1000)
    assert hints["orientation_natural"] == "landscape"
    assert hints["orientation_allowed"] == ["landscape"]


def test_build_orientation_portrait():
    hints = build_display_hints(w_px=1000, h_px=1600)
    assert hints["orientation_natural"] == "portrait"
    assert hints["orientation_allowed"] == ["portrait"]


def test_build_orientation_square_allows_all():
    hints = build_display_hints(w_px=1000, h_px=1000)
    assert hints["orientation_natural"] == "square"
    assert set(hints["orientation_allowed"]) == {"square", "landscape", "portrait"}


def test_build_dither_propagates_to_eink_devices():
    hints = build_display_hints(w_px=1600, h_px=1000, tags=["impressionism"])
    assert hints["inkposter_tela_28_5"]["dither"] == "riemersma"
    assert hints["pimoroni_inky_13_3"]["dither"] == "riemersma"


def test_build_meural_size_caps_present():
    hints = build_display_hints(w_px=1600, h_px=1000)
    assert hints["meural_landscape"]["size_cap_mb"] == 20
    assert hints["meural_portrait"]["size_cap_mb"] == 20
