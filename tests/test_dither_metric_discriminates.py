"""The dither metric has to be able to tell two dithers apart.

Near-term item N-E3. This is a GATE, not an improvement: N-E4, N-E5, N-E8 and
any optimisation-based halftoning are unverifiable while the ruler reads nearly
the same number for everything.

What it read before: Floyd-Steinberg 25.0, Atkinson 25.4 on the same image — a
1.6% spread between two algorithms with visibly different artifacts. Three
causes, each with a test here:

  * it blurred and differenced 8-bit **gamma-encoded sRGB**, the same space the
    error diffusion runs in, so an error introduced by diffusing in gamma space
    was invisible to the gate meant to catch it;
  * it measured Euclidean distance in **sRGB**, which is not proportional to
    perceived difference;
  * it hardcoded a **1.5 px** blur radius, asserting that every panel at every
    viewing distance is seen identically.

And one thing it could not see at all: worming and banding in a smooth passage
live at 5-20 px — too coarse for per-pixel error, too fine to survive the
acuity blur. `structured_artifact_energy` exists for exactly that band.
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from PIL import Image

from fine_art_archive.eink.palette import (
    ARCMINUTES_PER_RADIAN,
    DEFAULT_BLUR_RADIUS,
    acuity_blur_radius,
    dither_error,
    get_palette,
    linear_to_oklab,
    quantize,
    srgb_to_linear,
)

SPECTRA6 = get_palette("spectra6")


def _plate(w: int = 192, h: int = 192) -> Image.Image:
    """A gradient plus a flat mid-grey band — where worming actually shows."""
    g = np.tile(np.linspace(60, 200, w).astype(np.uint8), (h, 1))
    g[int(h * 0.4) : int(h * 0.7), :] = 128
    return Image.fromarray(np.dstack([g] * 3))


class TestItCanTellTwoDithersApart:
    """The failure that made this a gate."""

    def test_floyd_steinberg_and_atkinson_are_distinguishable(self) -> None:
        src = _plate()
        fs = dither_error(src, quantize(src, SPECTRA6, method="floyd-steinberg"))
        at = dither_error(src, quantize(src, SPECTRA6, method="atkinson"))
        spread = abs(fs["perceived_error"] - at["perceived_error"]) / max(
            fs["perceived_error"], at["perceived_error"]
        )
        assert spread > 0.03, (
            f"only {spread:.1%} apart — the old sRGB metric managed 1.6%, which is "
            "saturation. A metric this blunt cannot validate a dithering change."
        )

    def test_the_artifact_statistic_separates_them_further(self) -> None:
        """Atkinson's coarser texture is real and must be visible as a number."""
        src = _plate()
        fs = dither_error(src, quantize(src, SPECTRA6, method="floyd-steinberg"))
        at = dither_error(src, quantize(src, SPECTRA6, method="atkinson"))
        assert at["structured_artifact_energy"] > fs["structured_artifact_energy"] * 1.5

    def test_dithering_still_beats_nearest_colour(self) -> None:
        """The original insight must survive the rewrite."""
        src = _plate()
        plain = dither_error(src, quantize(src, SPECTRA6, method="none"))
        fs = dither_error(src, quantize(src, SPECTRA6, method="floyd-steinberg"))
        assert fs["perceived_error"] < plain["perceived_error"]
        assert fs["per_pixel_mean"] > plain["per_pixel_mean"], (
            "dithering INCREASES per-pixel error; that is the mechanism, not a regression"
        )

    def test_undithered_flat_quantisation_has_the_most_artifact_energy(self) -> None:
        src = _plate()
        plain = dither_error(src, quantize(src, SPECTRA6, method="none"))
        fs = dither_error(src, quantize(src, SPECTRA6, method="floyd-steinberg"))
        assert plain["structured_artifact_energy"] > fs["structured_artifact_energy"]


class TestItMeasuresInTheRightSpace:
    def test_srgb_to_linear_undoes_the_transfer_function(self) -> None:
        assert srgb_to_linear(np.array([[[0, 0, 0]]]))[0, 0, 0] == pytest.approx(0.0)
        assert srgb_to_linear(np.array([[[255, 255, 255]]]))[0, 0, 0] == pytest.approx(1.0)
        # Mid-grey 128 is ~0.216 in linear light, NOT 0.502. Blurring the 0.502
        # version is the error the old metric made.
        assert srgb_to_linear(np.array([[[128, 128, 128]]]))[0, 0, 0] == pytest.approx(
            0.2158, abs=1e-3
        )

    def test_oklab_lightness_is_monotonic_and_anchored(self) -> None:
        black = linear_to_oklab(srgb_to_linear(np.array([[[0, 0, 0]]])))[0, 0, 0]
        grey = linear_to_oklab(srgb_to_linear(np.array([[[128, 128, 128]]])))[0, 0, 0]
        white = linear_to_oklab(srgb_to_linear(np.array([[[255, 255, 255]]])))[0, 0, 0]
        assert black == pytest.approx(0.0, abs=1e-6)
        assert white == pytest.approx(1.0, abs=1e-3)
        assert black < grey < white

    def test_the_metric_itself_linearises_not_just_the_helper(self) -> None:
        """The wire, not just the part.

        Asserting `srgb_to_linear` is correct proves nothing about whether
        `dither_error` calls it — an earlier version of this file tested the
        helper in isolation and a deliberate break that removed linearisation
        from the metric passed all twenty tests.

        Decisive case: a 50/50 black/white checkerboard. In LINEAR light it
        integrates to 0.5, which is sRGB ~188 — markedly lighter than sRGB 128.
        So a correctly-linearising metric scores the checkerboard as closer to
        flat 188 than to flat 128. A metric that blurs gamma-encoded values
        concludes the exact opposite, because 0 and 255 average to 128 there.
        """
        n = 64
        yy, xx = np.mgrid[0:n, 0:n]
        checker = np.where((xx + yy) % 2 == 0, 255, 0).astype(np.uint8)
        checker_img = Image.fromarray(np.dstack([checker] * 3))
        flat_128 = Image.fromarray(np.full((n, n, 3), 128, dtype=np.uint8))
        flat_188 = Image.fromarray(np.full((n, n, 3), 188, dtype=np.uint8))

        to_128 = dither_error(flat_128, checker_img, 6.0)["perceived_error"]
        to_188 = dither_error(flat_188, checker_img, 6.0)["perceived_error"]
        assert to_188 < to_128, (
            f"checkerboard read as closer to mid-grey 128 ({to_128:.4f}) than to "
            f"188 ({to_188:.4f}) — the blur is averaging gamma-encoded values, "
            "which is the defect N-E3 exists to remove"
        )

    def test_identical_images_score_zero(self) -> None:
        src = _plate()
        e = dither_error(src, src)
        assert e["perceived_error"] == pytest.approx(0.0, abs=1e-9)
        assert e["structured_artifact_energy"] == pytest.approx(0.0, abs=1e-9)


class TestTheRadiusComesFromTheViewingGeometry:
    def test_it_follows_the_arcminute_relation(self) -> None:
        # 131 ppi at 150 cm: (131 * 150/2.54) / 3438
        expected = (131 * (150 / 2.54)) / ARCMINUTES_PER_RADIAN
        assert acuity_blur_radius(131, 150) == pytest.approx(expected)

    def test_further_away_means_a_larger_pixel_radius(self) -> None:
        """More pixels fall inside one arcminute the further back you stand."""
        assert acuity_blur_radius(131, 300) > acuity_blur_radius(131, 150)

    def test_a_denser_panel_means_a_larger_pixel_radius(self) -> None:
        assert acuity_blur_radius(262, 150) > acuity_blur_radius(131, 150)

    def test_geometry_actually_reaches_the_metric(self) -> None:
        src = _plate()
        e = dither_error(
            src, quantize(src, SPECTRA6, method="floyd-steinberg"), ppi=131, viewing_distance_cm=150
        )
        assert e["blur_radius"] == pytest.approx(acuity_blur_radius(131, 150))
        assert e["blur_radius"] != DEFAULT_BLUR_RADIUS

    def test_an_explicit_radius_still_wins(self) -> None:
        """Back-compatible: callers that pass a radius keep their numbers."""
        src = _plate()
        e = dither_error(
            src, quantize(src, SPECTRA6, method="none"), 1.5, ppi=131, viewing_distance_cm=150
        )
        assert e["blur_radius"] == pytest.approx(1.5)

    def test_no_geometry_falls_back_to_the_documented_default(self) -> None:
        src = _plate()
        e = dither_error(src, quantize(src, SPECTRA6, method="none"))
        assert e["blur_radius"] == pytest.approx(DEFAULT_BLUR_RADIUS)

    @pytest.mark.parametrize("bad", [0, -1])
    def test_nonsense_geometry_is_refused(self, bad: float) -> None:
        with pytest.raises(ValueError, match="must be positive"):
            acuity_blur_radius(bad, 150)
        with pytest.raises(ValueError, match="must be positive"):
            acuity_blur_radius(131, bad)

    @pytest.mark.parametrize("bad", [-1, float("nan"), float("inf")])
    def test_a_nonsense_radius_is_still_refused(self, bad: float) -> None:
        src = _plate(32, 32)
        with pytest.raises(ValueError, match="finite non-negative"):
            dither_error(src, src, bad)


class TestTheBlurIsWellBehaved:
    def test_a_flat_field_survives_the_blur_unchanged(self) -> None:
        """Reflected edges, not zero-padding — otherwise borders read as error."""
        flat = Image.fromarray(np.full((64, 64, 3), 128, dtype=np.uint8))
        e = dither_error(flat, flat, 8.0)
        assert e["perceived_error"] == pytest.approx(0.0, abs=1e-9)

    def test_zero_radius_is_a_no_op_not_a_crash(self) -> None:
        src = _plate(64, 64)
        e = dither_error(src, quantize(src, SPECTRA6, method="none"), 0)
        assert math.isfinite(e["perceived_error"])
