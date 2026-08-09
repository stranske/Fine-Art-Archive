"""Every colour claim here rests on somebody's guess. This measures the guess.

Near-term item N-E2, and it only became meaningful once N-E3 gave the metric
enough resolution to tell two renderings apart.

Nobody outside E Ink has published measured Spectra 6 primaries. The project
default is an estimate, and so is every alternative. Picking one silently and
reporting results to four decimal places states a confidence nobody has earned.

So all the published estimates ship as named profiles, and `palette_sensitivity`
renders the same work under each and reports the SPREAD. That spread is the
error bar on every colour result this project produces.

The measured answer, across 12 real works:

  * across the three PLAUSIBLE estimates: **16.6% median** relative spread
  * including `spectra6-legacy`, which is known-wrong: 79%

Both are reported and the tests keep them separate, because the wide number
bounds carelessness while the narrow one is the actual uncertainty. Reporting
only the wide one would make the palette look hopeless; only the narrow one
would hide how far a bad estimate moves things.

The consequence is worth stating plainly: N-E3 measured Floyd-Steinberg against
Atkinson at **6.5%** apart. That is INSIDE the 16.6% palette interval, so on
today's evidence the choice between them is not decidable — which is exactly
what an error bar is for.
"""

from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from fine_art_archive.eink.palette import (
    PALETTES,
    SPECTRA6_PLAUSIBLE,
    SPECTRA6_PROFILES,
    get_palette,
    palette_sensitivity,
)


def _plate(w: int = 160, h: int = 160) -> Image.Image:
    g = np.tile(np.linspace(50, 210, w).astype(np.uint8), (h, 1))
    rgb = np.dstack([g, np.roll(g, 20, axis=1), np.roll(g, 40, axis=1)])
    return Image.fromarray(rgb.astype(np.uint8))


class TestTheProfilesAreHonestAboutThemselves:
    @pytest.mark.parametrize("name", SPECTRA6_PROFILES)
    def test_every_spectra6_profile_is_registered(self, name: str) -> None:
        assert name in PALETTES

    @pytest.mark.parametrize("name", SPECTRA6_PROFILES)
    def test_none_of_them_claims_to_be_measured(self, name: str) -> None:
        """The day one is, it should be ADDED, not substituted for an estimate."""
        assert get_palette(name).measured is False

    @pytest.mark.parametrize("name", SPECTRA6_PROFILES)
    def test_each_records_where_it_came_from(self, name: str) -> None:
        p = get_palette(name)
        assert p.source, f"{name} does not say where its numbers came from"
        assert p.generation, f"{name} does not say how it was produced"

    def test_the_illuminant_is_recorded(self) -> None:
        """Reflective panels have no backlight — the illuminant is not a formality."""
        assert get_palette("spectra6-community").illuminant

    @pytest.mark.parametrize("name", SPECTRA6_PROFILES)
    def test_every_profile_has_six_inks(self, name: str) -> None:
        assert len(get_palette(name).colours) == 6


class TestLegacyIsIncludedPreciselyBecauseItIsWrong:
    def test_it_uses_colours_no_reflective_panel_reaches(self) -> None:
        cols = set(get_palette("spectra6-legacy").colours)
        assert (0, 0, 0) in cols and (255, 255, 255) in cols

    def test_it_is_excluded_from_the_plausible_set(self) -> None:
        assert "spectra6-legacy" in SPECTRA6_PROFILES
        assert "spectra6-legacy" not in SPECTRA6_PLAUSIBLE

    def test_it_really_does_score_worse(self) -> None:
        """If it did not, keeping a known-wrong profile would be pointless."""
        r = palette_sensitivity(_plate())
        per = {k: v["perceived_error"] for k, v in r["per_profile"].items()}
        assert per["spectra6-legacy"] > max(per[k] for k in SPECTRA6_PLAUSIBLE)


class TestTheSweepProducesAnErrorBar:
    def test_it_reports_both_intervals_separately(self) -> None:
        r = palette_sensitivity(_plate())
        assert r["perceived_error_spread"] > 0
        assert r["plausible_spread"]["absolute"] > 0

    def test_the_plausible_interval_is_tighter_than_the_full_one(self) -> None:
        """The whole reason for separating them."""
        r = palette_sensitivity(_plate())
        assert r["plausible_spread"]["relative"] < r["relative_spread"]

    def test_it_says_out_loud_that_nothing_is_measured(self) -> None:
        r = palette_sensitivity(_plate())
        assert r["all_estimates"] is True
        assert r["profiles_measured"] == []

    def test_best_and_worst_are_named_not_just_numbered(self) -> None:
        r = palette_sensitivity(_plate())
        assert r["best_profile"] in SPECTRA6_PROFILES
        assert r["worst_profile"] == "spectra6-legacy"

    def test_a_single_profile_has_no_spread(self) -> None:
        r = palette_sensitivity(_plate(), ("spectra6",))
        assert r["perceived_error_spread"] == pytest.approx(0.0)
