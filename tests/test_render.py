from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from fine_art_archive.display.hints import build_display_hints
from fine_art_archive.display.render import SPECTRA6_PALETTE, render_for_device


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


def test_output_uses_only_palette(tmp_path: Path):
    master = _write_gradient(tmp_path / "gradient.png")
    out = tmp_path / "rendered.png"

    hints = build_display_hints(w_px=96, h_px=64, tags=["geometric"])
    native_size = (80, 48)
    render_for_device(master, hints, "inkposter_tela_28_5", out, native_size=native_size)

    rendered = np.asarray(Image.open(out).convert("RGB"), dtype=np.uint8)
    assert tuple(rendered.shape[1::-1]) == native_size

    palette = np.asarray(SPECTRA6_PALETTE, dtype=np.uint8)
    flat = rendered.reshape(-1, 3)
    matches = np.all(flat[:, None, :] == palette[None, :, :], axis=2)
    assert bool(np.all(np.any(matches, axis=1)))


def test_render_is_deterministic(tmp_path: Path):
    master = _write_gradient(tmp_path / "gradient.png")
    out1 = tmp_path / "rendered1.png"
    out2 = tmp_path / "rendered2.png"

    hints = build_display_hints(w_px=96, h_px=64, tags=["geometric"])
    native_size = (80, 48)

    render_for_device(master, hints, "inkposter_tela_28_5", out1, native_size=native_size)
    render_for_device(master, hints, "inkposter_tela_28_5", out2, native_size=native_size)

    assert out1.read_bytes() == out2.read_bytes()


def test_unquantized_resize_would_fail_palette_gate(tmp_path: Path):
    """Demonstrate the deliberate-break condition without mutating source code."""
    master = _write_gradient(tmp_path / "gradient.png")
    native_size = (80, 48)

    with Image.open(master) as src:
        unquantized = np.asarray(
            src.convert("RGB").resize(native_size, Image.Resampling.LANCZOS), dtype=np.uint8
        )

    palette = np.asarray(SPECTRA6_PALETTE, dtype=np.uint8)
    flat = unquantized.reshape(-1, 3)
    matches = np.all(flat[:, None, :] == palette[None, :, :], axis=2)
    assert not bool(np.all(np.any(matches, axis=1)))
