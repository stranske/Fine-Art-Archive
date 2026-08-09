"""Finalisation must survive a work whose physical dimensions are unknown.

Audit finding 07 (2026-08-08). `QualityReport.px_per_cm_long` is `float | None`
— None whenever the work's physical size is absent, which is routine for
prints, drawings and Commons-sourced works. The history note formatted it
unconditionally with `:.1f`, so finalisation aborted with:

    TypeError: unsupported format string passed to NoneType.__format__

The note text already read "px/cm=… if known"; only the formatting did not
allow for it.

Severity was raised on verification for *reach*: the same line ran in the
workspace copy that the ops pipeline actually executed, so this aborted real
acquisitions rather than being latent.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest
from PIL import Image

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "scripts"))
sys.path.insert(0, str(_REPO / "src"))

import finalize_acquisition as fa  # noqa: E402

from fine_art_archive.collect.quality import (  # noqa: E402
    _is_positive_finite,
    measure_resolution,
)


class TestFormatMeasure:
    def test_none_renders_as_unknown_not_a_crash(self) -> None:
        """The regression: this raised TypeError and aborted finalisation."""
        assert fa._fmt_measure(None) == "unknown"

    @pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
    def test_non_finite_renders_by_name(self, bad: float) -> None:
        """`nan`/`inf` digits would read like a measurement someone took."""
        assert fa._fmt_measure(bad) == "invalid"

    def test_real_values_keep_their_precision(self) -> None:
        assert fa._fmt_measure(46.34) == "46.3"
        assert fa._fmt_measure(0.004612, places=5) == "0.00461"

    def test_history_note_builds_with_unknown_density(self) -> None:
        """The exact f-string shape that aborted, now exercised end to end."""
        note = (
            f"verify=PASS; "
            f"px/cm={fa._fmt_measure(None)}; "
            f"jpeg_q={None}; "
            f"fft_hf={fa._fmt_measure(0.0046, places=5)}; "
            f"fit_for=none"
        )
        assert "px/cm=unknown" in note
        assert "fft_hf=0.00460" in note


class TestPositiveFiniteGuard:
    @pytest.mark.parametrize("value", [None, float("nan"), float("inf"), float("-inf"), 0.0, -1.0])
    def test_rejects_unusable_dimensions(self, value: float | None) -> None:
        assert _is_positive_finite(value) is False

    def test_accepts_a_real_measurement(self) -> None:
        assert _is_positive_finite(46.3) is True


class TestMeasureResolution:
    @staticmethod
    def _img() -> Image.Image:
        return Image.new("RGB", (400, 300), (10, 20, 30))

    def test_unknown_dimensions_yield_no_density(self) -> None:
        long_edge, short_edge, px_per_cm = measure_resolution(self._img(), None, None)
        assert (long_edge, short_edge) == (400, 300)
        assert px_per_cm is None

    @pytest.mark.parametrize("bad", [float("nan"), float("inf")])
    def test_non_finite_dimensions_yield_no_density(self, bad: float) -> None:
        """`inf` used to pass `> 0` and produce a silent 0.0 px/cm."""
        _, _, px_per_cm = measure_resolution(self._img(), bad, 30.0)
        assert px_per_cm is None, "a non-finite dimension is not a measurement"

    def test_real_dimensions_still_measure(self) -> None:
        _, _, px_per_cm = measure_resolution(self._img(), 40.0, 30.0)
        assert px_per_cm is not None
        assert math.isclose(px_per_cm, 10.0)
