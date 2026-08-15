"""Render helpers for E-Ink devices with fixed Spectra-6 gamut."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageCms

from fine_art_archive.eink.gamut import gamut_fit
from fine_art_archive.eink.palette import GRAY16, MONO1BIT, get_palette
from fine_art_archive.eink.render_strategy import (
    RenderStrategyChoice,
    RenderStrategyName,
    choose_render_strategy,
)

_VALID_RENDER_STRATEGIES = frozenset({"color", "grayscale", "duotone"})


def _parse_render_strategy(value: object) -> RenderStrategyName:
    if value not in _VALID_RENDER_STRATEGIES:
        raise ValueError(f"invalid render strategy: {value!r}")
    return value  # type: ignore[return-value]


def _coerce_strategy_policy(
    policy: dict[str, str] | None,
) -> dict[str, RenderStrategyName] | None:
    if policy is None:
        return None
    return {key: _parse_render_strategy(value) for key, value in policy.items()}

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

_ICC_RENDERING_INTENTS = {
    "perceptual": ImageCms.Intent.PERCEPTUAL,
    "relative_colorimetric": ImageCms.Intent.RELATIVE_COLORIMETRIC,
    "saturation": ImageCms.Intent.SATURATION,
    "absolute_colorimetric": ImageCms.Intent.ABSOLUTE_COLORIMETRIC,
}


@dataclass(frozen=True)
class RenderEvidence:
    strategy: str
    reason: str
    gamut_verdict: str


@dataclass(frozen=True)
class RenderResult:
    path: Path
    evidence: RenderEvidence


def _nearest_palette_color(pixel: np.ndarray) -> np.ndarray:
    """Map one RGB pixel to nearest Spectra-6 entry by Euclidean distance."""
    deltas = _PALETTE_ARRAY - pixel
    idx = int(np.argmin(np.sum(deltas * deltas, axis=1)))
    return _PALETTE_ARRAY[idx]


def _nearest_palette_quantize(rgb: np.ndarray, palette: np.ndarray) -> np.ndarray:
    """Vectorized nearest-palette quantization for an RGB array."""
    flat = rgb.reshape(-1, 3).astype(np.float32)
    deltas = flat[:, None, :] - palette[None, :, :]
    distances = np.sum(deltas * deltas, axis=2)
    nearest_idx = np.argmin(distances, axis=1)
    quantized = palette[nearest_idx]
    return quantized.reshape(rgb.shape).astype(np.uint8)


def _nearest_palette_quantize_spectra6(rgb: np.ndarray) -> np.ndarray:
    return _nearest_palette_quantize(rgb, _PALETTE_ARRAY)


def _luminance(rgb: np.ndarray) -> np.ndarray:
    return 0.2126 * rgb[:, :, 0].astype(np.float32) + 0.7152 * rgb[:, :, 1] + 0.0722 * rgb[:, :, 2]


def _apply_grayscale(rgb: np.ndarray) -> np.ndarray:
    gray_palette = np.asarray(GRAY16.colours, dtype=np.float32)
    lum = _luminance(rgb)
    flat_lum = lum.reshape(-1, 1)
    gray_levels = gray_palette[:, 0].reshape(1, -1)
    nearest = np.argmin(np.abs(flat_lum - gray_levels), axis=1)
    out = gray_palette[nearest].reshape(rgb.shape)
    return out.astype(np.uint8)


def _apply_duotone(rgb: np.ndarray) -> np.ndarray:
    duo_palette = np.asarray(MONO1BIT.colours, dtype=np.float32)
    lum = _luminance(rgb)
    threshold = float(np.median(lum))
    dark, light = duo_palette[0], duo_palette[1]
    mask = lum >= threshold
    out = np.empty(rgb.shape, dtype=np.float32)
    out[mask] = light
    out[~mask] = dark
    return out.astype(np.uint8)


def _floyd_steinberg_dither(rgb: np.ndarray, palette: np.ndarray) -> np.ndarray:
    """Apply Floyd-Steinberg error diffusion then quantize to the palette."""
    work = rgb.astype(np.float32).copy()
    h, w, _ = work.shape
    out = np.zeros_like(work)

    for y in range(h):
        for x in range(w):
            original = work[y, x]
            deltas = palette - original
            idx = int(np.argmin(np.sum(deltas * deltas, axis=1)))
            quantized = palette[idx]
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


def _ordered_dither(rgb: np.ndarray, palette: np.ndarray) -> np.ndarray:
    """Apply ordered dithering via 4x4 Bayer thresholding before quantization."""
    work = rgb.astype(np.float32).copy()
    h, w, _ = work.shape

    tiled = np.tile(_BAYER_4X4, (h // 4 + 1, w // 4 + 1))[:h, :w]
    offset = (tiled / 16.0 - 0.5) * (255.0 / 8.0)
    work += offset[:, :, None]
    work = np.clip(work, 0, 255)
    return _nearest_palette_quantize(work, palette)


def _profile_from_hint(profile_hint: Any) -> Any:
    if profile_hint is None:
        return ImageCms.createProfile("sRGB")
    if isinstance(profile_hint, (str, Path)):
        hint_text = str(profile_hint).strip()
        if not hint_text or hint_text.lower() == "srgb":
            return ImageCms.createProfile("sRGB")
        if hint_text.startswith("device:"):
            device_key = hint_text.removeprefix("device:")
            raise ValueError(
                f"missing measured ICC profile for {device_key!r}; "
                "provide display_hints[device]['icc_profile'] as a path or bytes"
            )
        return ImageCms.ImageCmsProfile(str(profile_hint))
    if isinstance(profile_hint, bytes):
        return ImageCms.ImageCmsProfile(BytesIO(profile_hint))
    raise TypeError(f"unsupported ICC profile hint: {type(profile_hint).__name__}")


def _source_profile(src: Image.Image) -> Any:
    icc_profile = src.info.get("icc_profile")
    if icc_profile:
        return ImageCms.ImageCmsProfile(BytesIO(icc_profile))
    return ImageCms.createProfile("sRGB")


def _icc_gamut_map(src: Image.Image, device_hints: dict[str, Any]) -> Image.Image:
    """Map source colors into the configured device profile before dithering."""
    rendering_intent = str(device_hints.get("rendering_intent", "perceptual")).lower()
    intent = _ICC_RENDERING_INTENTS.get(rendering_intent)
    if intent is None:
        raise ValueError(f"unsupported ICC rendering intent: {rendering_intent!r}")

    flags = ImageCms.Flags(0)
    if device_hints.get("black_point_compensation", True):
        flags |= ImageCms.Flags.BLACKPOINTCOMPENSATION

    try:
        source_profile = _source_profile(src)
        source_image = src if src.mode == "RGB" else src.convert("RGB")
        mapped = ImageCms.profileToProfile(
            source_image,
            source_profile,
            _profile_from_hint(device_hints.get("icc_profile")),
            outputMode="RGB",
            renderingIntent=intent,
            flags=flags,
        )
        if mapped is None:
            raise ValueError("ICC transform returned no image")
        return mapped
    except (OSError, TypeError, ImageCms.PyCMSError) as exc:
        raise ValueError("failed to apply ICC gamut mapping") from exc


def _quantize_for_strategy(
    rgb: np.ndarray,
    strategy: RenderStrategyChoice,
    dither_mode: str,
) -> np.ndarray:
    if strategy.strategy == "grayscale":
        gray = _apply_grayscale(rgb)
        gray_palette = np.asarray(GRAY16.colours, dtype=np.float32)
        if dither_mode == "ordered":
            return _ordered_dither(gray, gray_palette)
        return _floyd_steinberg_dither(gray, gray_palette)
    if strategy.strategy == "duotone":
        duo = _apply_duotone(rgb)
        duo_palette = np.asarray(MONO1BIT.colours, dtype=np.float32)
        if dither_mode == "ordered":
            return _ordered_dither(duo, duo_palette)
        return _floyd_steinberg_dither(duo, duo_palette)
    if dither_mode == "ordered":
        return _ordered_dither(rgb, _PALETTE_ARRAY)
    return _floyd_steinberg_dither(rgb, _PALETTE_ARRAY)


def gamut_render_evidence(
    image: Image.Image, policy: dict[str, str] | None = None
) -> RenderEvidence:
    """Compute gamut verdict and chosen render strategy for a master image."""
    fit = gamut_fit(image.convert("RGB"), get_palette("spectra6"))
    choice = choose_render_strategy(fit, policy=_coerce_strategy_policy(policy))
    return RenderEvidence(
        strategy=choice.strategy,
        reason=choice.reason,
        gamut_verdict=fit.verdict,
    )


def render_for_device(
    master_path: Path,
    hints: dict,
    device_key: str,
    out_path: Path,
    *,
    native_size: tuple[int, int],
) -> RenderResult:
    """Render a master image to a device-native file with explicit strategy evidence."""
    device_hints = hints[device_key]
    if device_hints.get("gamut_target") != "spectra6":
        raise ValueError(
            f"unsupported gamut_target for {device_key!r}: {device_hints.get('gamut_target')!r}"
        )

    dither_mode = device_hints.get("dither", "floyd_steinberg")
    policy = device_hints.get("render_strategy_policy")
    forced_strategy = device_hints.get("render_strategy")
    with Image.open(master_path) as src:
        rgb_source = src if src.mode == "RGB" else src.convert("RGB")
        fit = gamut_fit(rgb_source, get_palette("spectra6"))
        if forced_strategy:
            strategy = RenderStrategyChoice(
                _parse_render_strategy(forced_strategy),
                f"forced render_strategy={forced_strategy}",
            )
        else:
            strategy = choose_render_strategy(
                fit, policy=_coerce_strategy_policy(policy)
            )
        gamut_mapped = _icc_gamut_map(src, device_hints)
        resized = gamut_mapped.resize(native_size, Image.Resampling.LANCZOS)
    rgb = np.asarray(resized, dtype=np.uint8)

    rendered = _quantize_for_strategy(rgb, strategy, dither_mode)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(rendered, mode="RGB").save(out_path)
    evidence = RenderEvidence(
        strategy=strategy.strategy,
        reason=strategy.reason,
        gamut_verdict=fit.verdict,
    )
    return RenderResult(path=out_path, evidence=evidence)
