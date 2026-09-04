from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from fine_art_archive.display.hints import build_display_hints
from fine_art_archive.display.render import render_for_device
from fine_art_archive.eink.palette import SPECTRA6_LEGACY, get_palette

CANONICAL_SPECTRA6 = np.asarray(get_palette("spectra6").colours, dtype=np.uint8)
LEGACY_SPECTRA6 = np.asarray(SPECTRA6_LEGACY.colours, dtype=np.uint8)


def _write_gradient(path: Path, *, size: tuple[int, int] = (96, 64)) -> Path:
    width, height = size
    x = np.linspace(0, 255, width, dtype=np.float32)
    y = np.linspace(0, 255, height, dtype=np.float32)
    xx, yy = np.meshgrid(x, y)

    r = xx
    g = yy
    b = (xx + yy) / 2.0
    gradient = np.stack([r, g, b], axis=-1).astype(np.uint8)
    Image.fromarray(gradient, mode="RGB").save(path)
    return path


def _drawn_only_from(rendered: np.ndarray, palette: np.ndarray) -> bool:
    flat = rendered.reshape(-1, 3)
    matches = np.all(flat[:, None, :] == palette[None, :, :], axis=2)
    return bool(np.all(np.any(matches, axis=1)))


def test_output_uses_canonical_spectra6_palette(tmp_path: Path) -> None:
    """Device output must use the canonical estimate, not the legacy primaries.

    `render_for_device` computes its gamut evidence against
    `get_palette("spectra6")`, so quantizing to the saturated legacy set would
    make the rendered file and the evidence describe different six inks.
    """
    master = _write_gradient(tmp_path / "gradient.png")
    out = tmp_path / "rendered.png"

    hints = build_display_hints(w_px=96, h_px=64, tags=["geometric"])
    hints["inkposter_tela_28_5"]["icc_profile"] = "srgb"
    hints["inkposter_tela_28_5"]["render_strategy"] = "color"
    native_size = (80, 48)
    result = render_for_device(master, hints, "inkposter_tela_28_5", out, native_size=native_size)

    rendered = np.asarray(Image.open(result.path).convert("RGB"), dtype=np.uint8)
    assert tuple(rendered.shape[1::-1]) == native_size

    assert _drawn_only_from(rendered, CANONICAL_SPECTRA6)

    # The legacy set shares no colour with the canonical estimate, so a render
    # that still quantized through it cannot satisfy the assertion above.
    present = {tuple(int(v) for v in px) for px in rendered.reshape(-1, 3)}
    assert present.isdisjoint({tuple(int(v) for v in c) for c in LEGACY_SPECTRA6})


def test_render_is_deterministic(tmp_path: Path) -> None:
    master = _write_gradient(tmp_path / "gradient.png")
    out1 = tmp_path / "rendered1.png"
    out2 = tmp_path / "rendered2.png"

    hints = build_display_hints(w_px=96, h_px=64, tags=["geometric"])
    hints["inkposter_tela_28_5"]["icc_profile"] = "srgb"
    hints["inkposter_tela_28_5"]["render_strategy"] = "color"
    native_size = (80, 48)

    render_for_device(master, hints, "inkposter_tela_28_5", out1, native_size=native_size)
    render_for_device(master, hints, "inkposter_tela_28_5", out2, native_size=native_size)

    assert out1.read_bytes() == out2.read_bytes()


def test_unquantized_resize_would_fail_palette_gate(tmp_path: Path) -> None:
    """Demonstrate the deliberate-break condition without mutating source code."""
    master = _write_gradient(tmp_path / "gradient.png")
    native_size = (80, 48)

    with Image.open(master) as src:
        unquantized = np.asarray(
            src.convert("RGB").resize(native_size, Image.Resampling.LANCZOS), dtype=np.uint8
        )

    assert not _drawn_only_from(unquantized, CANONICAL_SPECTRA6)
