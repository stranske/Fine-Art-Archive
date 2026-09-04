from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from fine_art_archive.display import render
from fine_art_archive.eink.palette import get_palette

# Colour output is quantized to the canonical Spectra-6 estimate, not the
# saturated legacy primaries. Palette order is documented in eink/palette.py:
# black, white, red, yellow, blue, green.
CANONICAL_GREEN = tuple(int(v) for v in get_palette("spectra6").colours[5])


def test_icc_gamut_mapping_runs_before_quantize_and_dither(monkeypatch, tmp_path: Path) -> None:
    master = tmp_path / "wide-gamut-red.png"
    out = tmp_path / "rendered.png"
    Image.new("RGB", (1, 1), (250, 0, 0)).save(master)

    def fake_profile_to_profile(src, *args, **kwargs):
        assert src.size == (1, 1)
        assert args
        assert kwargs["outputMode"] == "RGB"
        assert kwargs["renderingIntent"] == render.ImageCms.Intent.PERCEPTUAL
        assert kwargs["flags"] & render.ImageCms.Flags.BLACKPOINTCOMPENSATION
        return Image.new("RGB", src.size, (0, 250, 0))

    monkeypatch.setattr(render.ImageCms, "profileToProfile", fake_profile_to_profile)

    hints = {
        "spectra6_test": {
            "gamut_target": "spectra6",
            "dither": "floyd_steinberg",
            "icc_profile": "srgb",
            "rendering_intent": "perceptual",
            "black_point_compensation": True,
            "render_strategy": "color",
        }
    }

    result = render.render_for_device(master, hints, "spectra6_test", out, native_size=(2, 1))

    rendered = np.asarray(Image.open(result.path).convert("RGB"), dtype=np.uint8)
    assert rendered.shape[:2] == (1, 2)
    assert {tuple(int(v) for v in pixel) for row in rendered for pixel in row} == {CANONICAL_GREEN}


def test_icc_mapping_normalizes_unprofiled_grayscale_before_transform(
    monkeypatch, tmp_path: Path
) -> None:
    master = tmp_path / "grayscale.png"
    out = tmp_path / "rendered.png"
    Image.new("L", (2, 1), 200).save(master)

    def fake_profile_to_profile(src, *args, **kwargs):
        assert src.mode == "RGB"
        assert src.size == (2, 1)
        return Image.new("RGB", src.size, (0, 250, 0))

    monkeypatch.setattr(render.ImageCms, "profileToProfile", fake_profile_to_profile)

    hints = {
        "spectra6_test": {
            "gamut_target": "spectra6",
            "dither": "floyd_steinberg",
            "icc_profile": "SRGB",
        }
    }

    result = render.render_for_device(master, hints, "spectra6_test", out, native_size=(2, 1))

    rendered = np.asarray(Image.open(result.path).convert("RGB"), dtype=np.uint8)
    assert {tuple(int(v) for v in pixel) for row in rendered for pixel in row} == {CANONICAL_GREEN}


def test_invalid_rendering_intent_is_rejected(tmp_path: Path) -> None:
    master = tmp_path / "master.png"
    out = tmp_path / "rendered.png"
    Image.new("RGB", (1, 1), (250, 0, 0)).save(master)

    hints = {
        "spectra6_test": {
            "gamut_target": "spectra6",
            "rendering_intent": "magic",
        }
    }

    try:
        render.render_for_device(master, hints, "spectra6_test", out, native_size=(1, 1))
    except ValueError as exc:
        assert "unsupported ICC rendering intent" in str(exc)
    else:
        raise AssertionError("expected invalid rendering intent to fail")


def test_missing_measured_device_profile_fails_clearly(tmp_path: Path) -> None:
    master = tmp_path / "master.png"
    out = tmp_path / "rendered.png"
    Image.new("RGB", (1, 1), (250, 0, 0)).save(master)

    hints = {
        "spectra6_test": {
            "gamut_target": "spectra6",
            "icc_profile": "device:inkposter_tela_28_5",
        }
    }

    try:
        render.render_for_device(master, hints, "spectra6_test", out, native_size=(1, 1))
    except ValueError as exc:
        assert "missing measured ICC profile" in str(exc)
        assert "inkposter_tela_28_5" in str(exc)
    else:
        raise AssertionError("expected missing device ICC profile to fail")
