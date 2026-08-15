from __future__ import annotations

import numpy as np
from PIL import Image

from fine_art_archive.eink.gamut import GamutFit
from fine_art_archive.eink.render_strategy import choose_render_strategy


def _fit(verdict_fraction: float) -> GamutFit:
    return GamutFit(0.01, 0.02, 0.03, verdict_fraction, "spectra6", 100)


def test_well_served_work_uses_color() -> None:
    choice = choose_render_strategy(_fit(0.0))
    assert choice.strategy == "color"
    assert "well-served" in choice.reason


def test_compromised_work_uses_duotone() -> None:
    choice = choose_render_strategy(_fit(0.05))
    assert choice.strategy == "duotone"
    assert "compromised" in choice.reason


def test_poorly_served_work_uses_deliberate_monochrome() -> None:
    choice = choose_render_strategy(_fit(0.9))
    assert choice.strategy == "grayscale"
    assert "poorly-served" in choice.reason


def test_poorly_served_work_uses_deliberate_monochrome_pixels(tmp_path) -> None:
    from pathlib import Path

    from fine_art_archive.display.render import render_for_device

    master = tmp_path / "neon.png"
    out = tmp_path / "rendered.png"
    # saturated magenta is poorly served on Spectra-6 estimates
    Image.new("RGB", (8, 8), (255, 0, 255)).save(master)
    hints = {
        "spectra6_test": {
            "gamut_target": "spectra6",
            "dither": "floyd_steinberg",
            "icc_profile": "srgb",
        }
    }
    result = render_for_device(master, hints, "spectra6_test", out, native_size=(4, 4))
    assert result.evidence.strategy == "grayscale"
    assert "poorly-served" in result.evidence.reason
    rendered = np.asarray(Image.open(out).convert("RGB"), dtype=np.uint8)
    # grayscale output should not contain saturated primaries
    assert not np.any((rendered[:, :, 0] > 240) & (rendered[:, :, 2] > 240))
