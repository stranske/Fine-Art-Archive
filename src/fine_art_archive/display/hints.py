"""Builder for sidecar `display_hints` defaults.

Given the master's intrinsic properties (dimensions, orientation, tags), produce
sensible per-device rendering parameters. The caller is free to override any
field on a per-work basis — these are the *defaults* the migration planner
should use when no per-piece hints have been authored yet.

Design rule from Phase 2: the dithering algorithm is curatorial, not a global
default. The heuristics here pick something reasonable but the user is expected
to revisit dithering choices for high-value pieces. We err toward Atkinson
because it's the most generally-good choice for the Spectra 6 panel — sharp
contrast preservation, clean blacks/whites — and only diverge when a tag clearly
signals otherwise.

Dithering heuristics keyed off tags:
  graphic, poster, geometric, mondrian, op-art           -> ordered (Bayer)
  impressionism, post-impressionism, monet, pointillism  -> riemersma
  photograph, photography                                -> blue-noise
  default                                                -> atkinson
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal

Orientation = Literal["landscape", "portrait", "square"]
DitherAlg = Literal["ordered", "atkinson", "floyd_steinberg", "riemersma", "blue_noise"]


_DITHER_TAG_RULES: list[tuple[set[str], DitherAlg]] = [
    ({"graphic", "poster", "geometric", "mondrian", "op-art", "minimalism"}, "ordered"),
    ({"impressionism", "post-impressionism", "pointillism"}, "riemersma"),
    ({"photograph", "photography"}, "blue_noise"),
]


def infer_orientation(w_px: int, h_px: int, *, square_tolerance: float = 0.05) -> Orientation:
    """Classify orientation from pixel dimensions.

    A work within `square_tolerance` of 1:1 aspect ratio is "square". Otherwise
    landscape (w > h) or portrait (h > w).
    """
    if w_px <= 0 or h_px <= 0:
        raise ValueError("dimensions must be positive")
    ratio = w_px / h_px
    if abs(ratio - 1.0) <= square_tolerance:
        return "square"
    return "landscape" if ratio > 1.0 else "portrait"


def pick_dither(tags: Iterable[str]) -> DitherAlg:
    """Choose a dithering algorithm by inspecting tags."""
    tag_set = {t.lower() for t in tags}
    for rule_tags, alg in _DITHER_TAG_RULES:
        if tag_set & rule_tags:
            return alg
    return "atkinson"


def build_display_hints(
    *,
    w_px: int,
    h_px: int,
    tags: Iterable[str] | None = None,
) -> dict:
    """Produce a default `display_hints` dict for a master with the given size.

    Returns a dict ready to drop into meta.json's `display_hints` field. The
    caller can mutate/override any value; these are first-pass defaults.
    """
    tags = list(tags or [])
    orientation = infer_orientation(w_px, h_px)
    dither = pick_dither(tags)

    # Most works in the archive are paintings/photos; we allow only the natural
    # orientation by default. The migration step can promote both for works
    # that genuinely look good cropped either way.
    orientations = ["square", "landscape", "portrait"] if orientation == "square" else [orientation]

    # Per-device defaults. The Spectra 6 saturation boost is +30%, contrast
    # +15%; Frame TVs use the master verbatim (no boost). Adjust here, not
    # per-work, when these defaults are wrong.
    return {
        "orientation_natural": orientation,
        "orientation_allowed": orientations,
        # E-Ink targets (Spectra 6)
        "inkposter_tela_28_5": {
            "dither": dither,
            "saturation_boost": 1.30,
            "contrast_boost": 1.15,
            "gamut_target": "spectra6",
        },
        "pimoroni_inky_13_3": {
            "dither": dither,
            "saturation_boost": 1.40,  # smaller panel, push harder
            "contrast_boost": 1.20,
            "gamut_target": "spectra6",
        },
        # Frame TV targets (full sRGB; mat-and-color metadata mirrors the
        # device APIs documented in research_display_landscape_2026-05-16.md)
        "hisense_canvastv": {
            "matte": "modernthin",
            "matte_color": "polar",
        },
        "samsung_frame": {
            "matte": "shadowbox",
            "matte_color": "polar",
        },
        "lg_oled_gallery": {
            "mode": "gallery",
        },
        "tv_4k_generic": {},
        # Meural compatibility (preserved during the transition)
        "meural_landscape": {
            "size_cap_mb": 20,
        },
        "meural_portrait": {
            "size_cap_mb": 20,
        },
    }
