"""Render helpers for E-Ink devices with fixed Spectra-6 gamut."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

SPECTRA6_PALETTE: tuple[tuple[int, int, int], ...] = (
    (0, 0, 0),
    (255, 255, 255),
    (255, 0, 0),
    (0, 255, 0),
    (0, 0, 255),
    (255, 255, 0),
)

_PALETTE_ARRAY = np.asarray(SPECTRA6_PALETTE, dtype=np.float32)
_BAYER_4X4 = np.asarray(
    [
        [0, 8, 2, 10],
        [12, 4, 14, 6],
        [3, 11, 1, 9],
        [15, 7, 13, 5],
    ],
    dtype=np.float32,
)


def _nearest_palette_color(pixel: np.ndarray) -> np.ndarray:
    """Map one RGB pixel to nearest Spectra-6 entry by Euclidean distance."""
    deltas = _PALETTE_ARRAY - pixel
    idx = int(np.argmin(np.sum(deltas * deltas, axis=1)))
    return _PALETTE_ARRAY[idx]


def _nearest_palette_quantize(rgb: np.ndarray) -> np.ndarray:
    """Vectorized nearest-palette quantization for an RGB array."""
    flat = rgb.reshape(-1, 3).astype(np.float32)
    deltas = flat[:, None, :] - _PALETTE_ARRAY[None, :, :]
    distances = np.sum(deltas * deltas, axis=2)
    nearest_idx = np.argmin(distances, axis=1)
    quantized = _PALETTE_ARRAY[nearest_idx]
    return quantized.reshape(rgb.shape).astype(np.uint8)


def _floyd_steinberg_dither(rgb: np.ndarray) -> np.ndarray:
    """Apply Floyd-Steinberg error diffusion then quantize to Spectra-6."""
    work = rgb.astype(np.float32).copy()
    h, w, _ = work.shape
    out = np.zeros_like(work)

    for y in range(h):
        for x in range(w):
            original = work[y, x]
            quantized = _nearest_palette_color(original)
            out[y, x] = quantized
            error = original - quantized

            if x + 1 < w:
                work[y, x + 1] += error * (7.0 / 16.0)
            if y + 1 < h:
                if x > 0:
                    work[y + 1, x - 1] += error * (3.0 / 16.0)
                work[y + 1, x] += error * (5.0 / 16.0)
                if x + 1 < w:
                    work[y + 1, x + 1] += error * (1.0 / 16.0)

    return np.clip(out, 0, 255).astype(np.uint8)


def _ordered_dither(rgb: np.ndarray) -> np.ndarray:
    """Apply ordered dithering via 4x4 Bayer thresholding before quantization."""
    work = rgb.astype(np.float32).copy()
    h, w, _ = work.shape

    tiled = np.tile(_BAYER_4X4, (h // 4 + 1, w // 4 + 1))[:h, :w]
    offset = (tiled / 16.0 - 0.5) * (255.0 / 8.0)
    work += offset[:, :, None]
    work = np.clip(work, 0, 255)
    return _nearest_palette_quantize(work)


def render_for_device(
    master_path: Path,
    hints: dict,
    device_key: str,
    out_path: Path,
    *,
    native_size: tuple[int, int],
) -> Path:
    """Render a master image to a device-native Spectra-6 file."""
    device_hints = hints[device_key]
    if device_hints.get("gamut_target") != "spectra6":
        raise ValueError(
            f"unsupported gamut_target for {device_key!r}: {device_hints.get('gamut_target')!r}"
        )

    dither_mode = device_hints.get("dither", "floyd_steinberg")
    with Image.open(master_path) as src:
        resized = src.convert("RGB").resize(native_size, Image.Resampling.LANCZOS)
    rgb = np.asarray(resized, dtype=np.uint8)

    rendered = _ordered_dither(rgb) if dither_mode == "ordered" else _floyd_steinberg_dither(rgb)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(rendered, mode="RGB").save(out_path)
    return out_path
