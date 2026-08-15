"""Can six inks reproduce this archive? Answered without hardware.

Near-term item N-E1, sequenced before any display purchase because it is the
INPUT to that decision.

The trap this module fell into first, and these tests exist to prevent
returning to: measuring each pixel's distance to the nearest single ink. A
six-ink panel is not limited to six colours — dithering places inks side by
side and the eye integrates them, so the achievable set is their convex hull in
LINEAR light. Measured the wrong way, every test image came back "well-served,
0.0% out of gamut": a metric that cannot fail is not a measurement.

The threshold is calibrated against 40 real works rather than asserted, for the
same reason.
"""

from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from fine_art_archive.eink.gamut import (
    MIXTURE_STEPS,
    OUT_OF_GAMUT_THRESHOLD,
    GamutFit,
    _mixture_set,
    _palette_oklab,
    gamut_fit,
    summarise_corpus,
)
from fine_art_archive.eink.palette import get_palette

SPECTRA6 = get_palette("spectra6")


def _solid(rgb: tuple[int, int, int], n: int = 64) -> Image.Image:
    return Image.fromarray(np.full((n, n, 3), rgb, dtype=np.uint8))


class TestThePanelIsNotSixColours:
    def test_the_achievable_set_is_far_larger_than_the_ink_count(self) -> None:
        """The defect that made the first version useless."""
        inks = _palette_oklab(SPECTRA6)
        mixtures = _mixture_set(SPECTRA6)
        assert len(inks) == 6
        assert len(mixtures) > 400, (
            "dithering mixes inks; treating the panel as six discrete colours "
            "reported every image as perfectly served"
        )

    def test_every_ink_is_itself_reachable(self) -> None:
        inks = _palette_oklab(SPECTRA6)
        mixtures = _mixture_set(SPECTRA6)
        for ink in inks:
            d = np.sqrt(((mixtures - ink) ** 2).sum(axis=1)).min()
            assert d < 1e-9

    def test_a_mid_grey_is_reachable_by_mixing_even_though_no_ink_is_grey(self) -> None:
        """Black + white dithered is grey. That is the whole point."""
        fit = gamut_fit(_solid((128, 128, 128)), SPECTRA6)
        assert fit.out_of_gamut_fraction == 0.0

    def test_mixture_lattice_uses_the_documented_granularity(self) -> None:
        assert MIXTURE_STEPS == 6


class TestItActuallyDiscriminates:
    def test_muted_earth_tones_are_well_served(self) -> None:
        rng = np.random.default_rng(0)
        img = Image.fromarray(rng.integers(90, 150, (128, 128, 3)).astype(np.uint8))
        assert gamut_fit(img, SPECTRA6).verdict == "well-served"

    @pytest.mark.parametrize("rgb", [(255, 0, 255), (0, 255, 255), (255, 128, 0)])
    def test_colours_outside_a_six_ink_hull_are_flagged(self, rgb: tuple[int, int, int]) -> None:
        """Neon magenta is not reachable from black/white/red/yellow/blue/green."""
        fit = gamut_fit(_solid(rgb), SPECTRA6)
        assert fit.verdict == "poorly-served"
        assert fit.out_of_gamut_fraction > 0.5

    def test_the_two_ends_are_not_the_same_number(self) -> None:
        """A metric that ranks a Vermeer and a neon swatch alike is broken."""
        muted = gamut_fit(_solid((120, 110, 95)), SPECTRA6)
        neon = gamut_fit(_solid((255, 0, 255)), SPECTRA6)
        assert neon.mean_distance > muted.mean_distance * 3


class TestTheThresholdIsCalibrated:
    def test_it_is_the_value_the_measurement_supports(self) -> None:
        """0.03/0.05 flag most of the archive; 0.12 flags almost none."""
        assert OUT_OF_GAMUT_THRESHOLD == 0.08

    def test_verdict_bands_are_ordered(self) -> None:
        def fit(frac: float) -> GamutFit:
            return GamutFit(0.0, 0.0, 0.0, frac, "spectra6", 1)

        assert fit(0.0).verdict == "well-served"
        assert fit(0.05).verdict == "compromised"
        assert fit(0.50).verdict == "poorly-served"


class TestTheCorpusSummaryDoesNotHideTheTail:
    def test_it_reports_buckets_not_just_an_average(self) -> None:
        fits = [GamutFit(0.01, 0.02, 0.03, 0.0, "spectra6", 1) for _ in range(9)]
        fits.append(GamutFit(0.2, 0.3, 0.4, 0.9, "spectra6", 1))
        s = summarise_corpus(fits)
        assert s["verdicts"]["well-served"] == 9
        assert s["verdicts"]["poorly-served"] == 1
        assert s["worst_out_of_gamut_fraction"] == pytest.approx(
            0.9
        ), "a corpus mean would say the archive is fine while a tenth is unshowable"

    def test_an_empty_corpus_is_not_reported_as_healthy(self) -> None:
        assert summarise_corpus([])["works"] == 0
