from __future__ import annotations

from pathlib import Path

from PIL import Image

from fine_art_archive.display import render


def test_well_served_work_keeps_color_strategy(tmp_path: Path) -> None:
    master = tmp_path / "muted.png"
    out = tmp_path / "rendered.png"
    Image.new("RGB", (4, 4), (120, 110, 95)).save(master)
    hints = {
        "spectra6_test": {
            "gamut_target": "spectra6",
            "dither": "floyd_steinberg",
            "icc_profile": "srgb",
        }
    }
    result = render.render_for_device(master, hints, "spectra6_test", out, native_size=(2, 2))
    assert result.evidence.strategy == "color"
    assert result.evidence.gamut_verdict == "well-served"


def test_compromised_work_uses_duotone_strategy(monkeypatch, tmp_path: Path) -> None:
    from fine_art_archive.eink.gamut import GamutFit

    master = tmp_path / "compromised.png"
    out = tmp_path / "rendered.png"
    Image.new("RGB", (8, 8), (200, 40, 200)).save(master)

    def fake_fit(image, palette):
        return GamutFit(0.05, 0.08, 0.12, 0.08, "spectra6", 64)

    monkeypatch.setattr("fine_art_archive.display.render.gamut_fit", fake_fit)

    hints = {
        "spectra6_test": {
            "gamut_target": "spectra6",
            "dither": "floyd_steinberg",
            "icc_profile": "srgb",
        }
    }
    result = render.render_for_device(master, hints, "spectra6_test", out, native_size=(4, 4))
    assert result.evidence.strategy == "duotone"
    assert result.evidence.gamut_verdict == "compromised"
