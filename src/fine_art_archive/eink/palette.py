"""Palette definitions and dithering for reflective e-paper panels.

Why this lives in our code rather than the device's
---------------------------------------------------
A Spectra 6 panel can show six inks: black, white, red, yellow, blue, green.
A painting has millions of colours. Getting from one to the other is the single
biggest determinant of how the reproduction looks -- far more than panel
resolution -- and every vendor surveyed except BLOOMIN8 performs that conversion
itself, with an undocumented pipeline and no way to influence it. The one
independent hands-on report of a 28.5" colour unit describes photographs as
"dark, desaturated, and low resolution", which is consistent with a conversion
tuned for signage rather than for art.

So we do it here, and hand pre-dithered pixels to any device that accepts them.

Nearest-colour quantisation posterises: a sky becomes bands, a shadow gradient
collapses to two tones. Error diffusion instead carries the quantisation error
of each pixel forward onto its not-yet-decided neighbours, so the fine pattern
integrates back to the intended colour at viewing distance. Floyd-Steinberg is
the standard; Atkinson spreads less error and reads cleaner on low-contrast
reflective media, which is why both are offered.

THE PALETTE VALUES BELOW ARE UNMEASURED
---------------------------------------
No vendor at these sizes publishes a colour profile, a gamut volume, or a
Delta-E figure -- this is the survey's central open gap (docs/EINK_DEVICE_SURVEY.md).
The primaries here are reasonable estimates, NOT measurements, and every profile
carries `measured: False` to say so. They exist to make the pipeline real and
testable now; they must be replaced by measuring an actual panel before any
claim about colour fidelity is credible. `Palette.measured` is what the export
manifest records, so an exported card always states whether its colours were
guessed.

Note in particular that the reviewer above reports the panel cannot render pure
white -- only "a yellowish grey". `Palette.white` therefore is not #FFFFFF for
the colour profiles, because mapping image white onto a white the panel cannot
produce throws away headroom at the top of the range.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

import numpy as np
from PIL import Image

DitherMethod = Literal["none", "floyd-steinberg", "atkinson"]


@dataclass(frozen=True)
class Palette:
    """A device's reproducible colours."""

    name: str
    colours: tuple[tuple[int, int, int], ...]
    measured: bool = False
    note: str = ""
    #: Where these numbers came from. Required reading before trusting any
    #: colour result: nobody outside E Ink has published measured Spectra 6
    #: primaries, so every set in this module is somebody's estimate.
    source: str = ""
    #: How the estimate was produced — "vendor-marketing", "community-photo",
    #: "tool-default", "measured-spectrophotometer".
    generation: str = ""
    #: Illuminant the estimate assumes. Reflective panels have no backlight, so
    #: this is not a formality — the same ink reads differently under D50 and
    #: D65, and an estimate that does not name its illuminant cannot be
    #: reconciled with one that does.
    illuminant: str = ""

    def __post_init__(self) -> None:
        if not self.colours:
            raise ValueError("palette must define at least one colour")

    @property
    def white(self) -> tuple[int, int, int]:
        """The lightest reproducible colour — not necessarily #FFFFFF."""
        return max(self.colours, key=sum)

    @property
    def black(self) -> tuple[int, int, int]:
        return min(self.colours, key=sum)

    def as_pil_palette_image(self) -> Image.Image:
        """A P-mode image carrying this palette, for Image.quantize().

        The 256 entries are filled by CYCLING the real colours rather than
        zero-padding. Zero-padding looks harmless and is not: PIL's quantiser
        may select an index past the real colours, and a zero-padded entry is
        pure #000000 — a colour no reflective panel can produce and one that is
        not this palette's black. It showed up as a single stray (0, 0, 0) pixel
        in 2 of 4 rendered works, which is easy to miss visually and breaks the
        invariant that output contains only reproducible colours. That matters
        downstream, where a pre-dithered upload maps each colour to an ink index.
        """
        flat: list[int] = []
        for rgb in self.colours:
            flat.extend(rgb)
        n = len(self.colours)
        for i in range(n, 256):  # cycle, never pad with black
            flat.extend(self.colours[i % n])
        pal = Image.new("P", (1, 1))
        pal.putpalette(flat)
        return pal

    def contains_only(self, img: Image.Image) -> tuple[bool, set[tuple[int, int, int]]]:
        """Assert the palette invariant. Returns (ok, offending colours)."""
        arr = np.asarray(img.convert("RGB")).reshape(-1, 3)
        present: set[tuple[int, int, int]] = {
            (int(r), int(g), int(b)) for r, g, b in np.unique(arr, axis=0)
        }
        illegal = present - {tuple(c) for c in self.colours}
        return (not illegal, illegal)

    def array(self) -> np.ndarray:
        return np.asarray(self.colours, dtype=np.float64)


# E Ink Spectra 6 (E6): six inks. Values are ESTIMATES — see module docstring.
# White is deliberately below #FFFFFF and slightly warm, matching the reported
# "yellowish grey" rather than an ideal the panel cannot hit.
SPECTRA6 = Palette(
    name="spectra6",
    colours=(
        (28, 28, 28),  # black  — reflective black is never 0,0,0
        (222, 219, 205),  # white  — warm, well below 255
        (158, 48, 44),  # red
        (198, 168, 60),  # yellow
        (44, 70, 132),  # blue
        (54, 108, 74),  # green
    ),
    source=(
        "project estimate: vendor marketing imagery plus reported panel white "
        "point, reconciled by eye"
    ),
    generation="vendor-marketing",
    illuminant="D65 assumed",
    note="E Ink Spectra 6 / E6. Estimated primaries; replace by measurement.",
)

# Kaleido 3 is a colour-filter array over a monochrome panel: colour resolution
# is a third of the mono resolution and saturation is much lower than Spectra 6.
# Modelled as a desaturated 8-colour cube rather than 4,096 addressable colours,
# because the panel cannot hold saturated primaries at full area coverage.
KALEIDO3 = Palette(
    name="kaleido3",
    colours=(
        (30, 30, 30),
        (232, 230, 226),
        (140, 74, 70),
        (150, 138, 82),
        (72, 88, 124),
        (78, 112, 92),
        (118, 96, 108),
        (168, 160, 148),
    ),
    note="Kaleido 3 CFA. Low saturation by construction; estimated.",
)

MONO1BIT = Palette(
    name="mono1bit",
    colours=((20, 20, 20), (228, 226, 220)),
    note="Carta-class bilevel. Estimated ink/paper values.",
)

GRAY16 = Palette(
    name="gray16",
    colours=tuple((round(20 + i * 208 / 15),) * 3 for i in range(16)),
    note="16-level greyscale, as most mono panels actually address.",
)

# --------------------------------------------------------------------------
# Published Spectra 6 estimates (near-term item N-E2).
#
# NOBODY OUTSIDE E INK HAS PUBLISHED MEASURED PRIMARIES. Every set below is an
# estimate, and they disagree. The honest response is not to pick one and call
# it truth — it is to carry all of them and MEASURE how much the answer moves,
# turning an unquantified risk into a stated interval. `palette_sensitivity`
# does that; until a spectrophotometer exists, its spread IS the error bar on
# every colour claim this project makes.
#
# All are `measured=False`. When a real measurement arrives it should be added
# as a new profile with measured=True rather than overwriting one of these,
# so the estimates remain available for comparison.
# --------------------------------------------------------------------------
SPECTRA6_LEGACY = Palette(
    name="spectra6-legacy",
    colours=(
        (0, 0, 0),
        (255, 255, 255),
        (255, 0, 0),
        (255, 255, 0),
        (0, 0, 255),
        (0, 255, 0),
    ),
    measured=False,
    source="naive saturated primaries, as used by early hobbyist drivers",
    generation="tool-default",
    illuminant="unspecified",
    note=(
        "Included BECAUSE it is wrong in a known direction: pure #000000 and "
        "#FFFFFF are outside any reflective panel's range. It bounds how far a "
        "careless estimate moves the result."
    ),
)

SPECTRA6_COMMUNITY = Palette(
    name="spectra6-community",
    colours=(
        (26, 26, 26),
        (222, 219, 205),
        (168, 46, 41),
        (206, 178, 58),
        (39, 63, 125),
        (49, 100, 68),
    ),
    measured=False,
    source="community photographs of a powered panel, white-balanced by eye",
    generation="community-photo",
    illuminant="D65 assumed",
    note="Close to the project default; differs mainly in the chromatic inks.",
)

SPECTRA6_EPDOPTIMIZE = Palette(
    name="spectra6-epdoptimize",
    colours=(
        (30, 30, 30),
        (218, 215, 202),
        (150, 42, 40),
        (188, 160, 55),
        (48, 74, 138),
        (58, 112, 78),
    ),
    measured=False,
    source="epdoptimize-style tooling defaults",
    generation="tool-default",
    illuminant="unspecified",
    note="Slightly darker chromatics than the project default.",
)

PALETTES: dict[str, Palette] = {
    p.name: p
    for p in (
        SPECTRA6,
        SPECTRA6_LEGACY,
        SPECTRA6_COMMUNITY,
        SPECTRA6_EPDOPTIMIZE,
        KALEIDO3,
        MONO1BIT,
        GRAY16,
    )
}

#: The Spectra 6 estimates that disagree with one another. Sweeping these is
#: how a colour claim gets an error bar before any hardware exists.
SPECTRA6_PROFILES: tuple[str, ...] = (
    "spectra6",
    "spectra6-community",
    "spectra6-epdoptimize",
    "spectra6-legacy",
)

#: The subset anyone might actually believe. `spectra6-legacy` is excluded: it
#: uses pure #000000/#FFFFFF, which no reflective panel reaches, and it is ~5x
#: worse than the rest on every work measured. Left in the headline spread it
#: dominates completely (79% vs 15%) and the interval stops describing genuine
#: disagreement between credible estimates. Both numbers are reported, because
#: the wide one bounds carelessness and the narrow one is the real error bar.
SPECTRA6_PLAUSIBLE: tuple[str, ...] = (
    "spectra6",
    "spectra6-community",
    "spectra6-epdoptimize",
)


def get_palette(name: str) -> Palette:
    try:
        return PALETTES[name]
    except KeyError:
        raise KeyError(f"unknown palette {name!r}; have {sorted(PALETTES)}") from None


# --------------------------------------------------------------------------
# Dithering
# --------------------------------------------------------------------------
_FS_KERNEL = (  # (dx, dy, weight/16) — Floyd-Steinberg
    (1, 0, 7 / 16),
    (-1, 1, 3 / 16),
    (0, 1, 5 / 16),
    (1, 1, 1 / 16),
)
_ATKINSON_KERNEL = (  # spreads only 6/8 of the error — less noise, more
    (1, 0, 1 / 8),
    (2, 0, 1 / 8),  # contrast on reflective media
    (-1, 1, 1 / 8),
    (0, 1, 1 / 8),
    (1, 1, 1 / 8),
    (0, 2, 1 / 8),
)


def _diffuse(rgb: np.ndarray, pal: np.ndarray, kernel, serpentine: bool) -> np.ndarray:
    """Error-diffusion dither. Returns an index array into `pal`.

    Kept in NumPy rather than delegating to PIL for the two cases PIL cannot
    do: Atkinson, and serpentine scanning. Serpentine alternates row direction,
    which breaks up the diagonal worming that plain left-to-right Floyd-Steinberg
    produces in large flat areas — and a painting's sky is exactly that.
    """
    h, w, _ = rgb.shape
    work = rgb.astype(np.float64, copy=True)
    out = np.zeros((h, w), dtype=np.uint8)
    for y in range(h):
        xs = range(w) if (not serpentine or y % 2 == 0) else range(w - 1, -1, -1)
        flip = serpentine and y % 2 == 1
        for x in xs:
            old = work[y, x]
            idx = int(np.argmin(((pal - old) ** 2).sum(axis=1)))
            out[y, x] = idx
            err = old - pal[idx]
            for dx, dy, wt in kernel:
                sx = x - dx if flip else x + dx
                sy = y + dy
                if 0 <= sx < w and 0 <= sy < h:
                    work[sy, sx] += err * wt
    return out


def quantize(
    img: Image.Image,
    palette: Palette,
    method: DitherMethod = "floyd-steinberg",
    *,
    serpentine: bool = True,
    fast: bool = True,
) -> Image.Image:
    """Map `img` onto `palette`, returning an RGB image of palette colours.

    `fast=True` (the default) delegates Floyd-Steinberg to PIL's C
    implementation. That default is measured, not assumed: on a 2560x1440 render
    the NumPy serpentine path took 26.6s against PIL's 0.1s — 250x slower — for
    a perceived error of 24.99 vs 24.94, i.e. no difference worth having. The
    theoretical benefit of serpentine scanning is avoiding diagonal "worming" in
    large flat areas, which this metric cannot see; if that artifact ever shows
    up on a real panel, `fast=False` is the lever, and the 26s is then earned.

    Atkinson always uses the NumPy path because PIL cannot do it, and it is
    worth having: it diffuses only 6/8 of the error, which holds more local
    contrast on low-contrast reflective media.
    """
    rgb = img.convert("RGB")
    if method == "none":
        return rgb.quantize(
            palette=palette.as_pil_palette_image(), dither=Image.Dither.NONE
        ).convert("RGB")
    if method == "floyd-steinberg" and fast:
        return rgb.quantize(
            palette=palette.as_pil_palette_image(),
            dither=Image.Dither.FLOYDSTEINBERG,
        ).convert("RGB")
    if method not in ("floyd-steinberg", "atkinson"):
        raise ValueError(f"unknown dither method {method!r}")

    kernel = _FS_KERNEL if method == "floyd-steinberg" else _ATKINSON_KERNEL
    pal = palette.array()
    idx = _diffuse(np.asarray(rgb, dtype=np.float64), pal, kernel, serpentine)
    return Image.fromarray(pal.astype(np.uint8)[idx], mode="RGB")


def map_to_panel_range(img: Image.Image, palette: Palette) -> Image.Image:
    """Compress the image's tonal range into what the panel can actually show.

    A reflective panel's white is dimmer than #FFFFFF and its black lighter
    than #000000. Handing it full-range pixels wastes headroom at both ends:
    everything above the panel's white clips to the same ink, so highlight
    separation is lost — which is one plausible reason reproductions on these
    panels get described as "dark and desaturated".

    This is a linear remap per channel, applied BEFORE dithering so the
    diffusion works within the achievable range.
    """
    lo = np.asarray(palette.black, dtype=np.float64)
    hi = np.asarray(palette.white, dtype=np.float64)
    a = np.asarray(img.convert("RGB"), dtype=np.float64) / 255.0
    out = lo + a * (hi - lo)
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8), mode="RGB")


# --------------------------------------------------------------------------
# Perceptual machinery for the dither metric (near-term item N-E3).
#
# The metric this replaces blurred and differenced 8-bit gamma-encoded sRGB —
# the SAME space the error diffusion runs in. So a colour error introduced by
# diffusing in gamma space was invisible to the gate meant to catch it, and the
# gate reported the pipeline as correct. It also scored Floyd-Steinberg 25.0
# against Atkinson 25.4: a 1.6% spread between two genuinely different
# algorithms, which is saturation, not agreement. Nothing downstream (N-E4,
# N-E5, N-E8, or any optimisation-based halftoning) can be validated until the
# ruler stops reading the same number for everything.
# --------------------------------------------------------------------------

#: Arcminutes per radian. The eye resolves ~1 arcminute, so this converts a
#: (ppi, viewing distance) pair into "how many pixels fall inside one just-
#: resolvable angle" — which is the only defensible blur radius. A hardcoded
#: 1.5 px says a 131-ppi panel at arm's length and a phone at 20 cm are seen
#: identically, which they are not.
ARCMINUTES_PER_RADIAN = 3438.0

#: Fallback used only when a caller supplies no viewing geometry. Preserved
#: from the original implementation so existing callers keep their numbers.
DEFAULT_BLUR_RADIUS = 1.5

#: Band-pass window, in pixels, for the structured-artifact statistic. Dither
#: worming and banding in a smooth passage (a sky) live at this scale: coarser
#: than a pixel, finer than composition. Per-pixel error cannot see it and the
#: acuity blur averages it away, which is why it needs its own number.
ARTIFACT_BAND_PX = (5.0, 20.0)


def acuity_blur_radius(ppi: float, viewing_distance_cm: float) -> float:
    """Gaussian radius, in pixels, matching one arcminute of visual angle.

    `ppi * distance_inches / 3438` — the pixel count subtended by the eye's
    resolution limit at that distance. Below this the eye integrates; above it
    the eye resolves. That is exactly the boundary a dither metric must model.
    """
    if ppi <= 0 or viewing_distance_cm <= 0:
        raise ValueError("ppi and viewing_distance_cm must be positive")
    distance_inches = viewing_distance_cm / 2.54
    return (ppi * distance_inches) / ARCMINUTES_PER_RADIAN


def srgb_to_linear(a: np.ndarray) -> np.ndarray:
    """8-bit sRGB -> linear light. Blurring must happen HERE, not in sRGB.

    A blur is an average, and averaging gamma-encoded values does not model
    what light does when it reaches the eye. This is the step whose absence let
    a gamma-space diffusion error pass the gate unseen.
    """
    x = a.astype(np.float64) / 255.0
    return np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4)


def linear_to_oklab(rgb: np.ndarray) -> np.ndarray:
    """Linear sRGB -> Oklab, so a distance is a PERCEIVED distance.

    Euclidean distance in sRGB is not proportional to perceived difference; in
    Oklab it approximately is. Differencing in sRGB is what made two dithers
    with visibly different artifacts score within 1.6% of each other.
    """
    r, g, b = rgb[..., 0], rgb[..., 1], rgb[..., 2]
    lms_l = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b
    lms_m = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b
    lms_s = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b
    l_, m_, s_ = np.cbrt(lms_l), np.cbrt(lms_m), np.cbrt(lms_s)
    return np.stack(
        [
            0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_,
            1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_,
            0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_,
        ],
        axis=-1,
    )


def _gaussian_blur_linear(a: np.ndarray, radius: float) -> np.ndarray:
    """Separable Gaussian over float channels, numpy only.

    PIL's `GaussianBlur` refuses mode "F", and `scipy.ndimage` is installed in
    this environment but is NOT a declared dependency — using it would pass
    locally and fail CI. A separable convolution is a dozen lines and keeps the
    dependency set honest.

    Edges are reflected rather than zero-padded: zero-padding would darken the
    border in linear light and show up as a fake error along every edge.
    """
    if radius <= 0:
        return a
    sigma = float(radius)
    half = max(1, int(math.ceil(3.0 * sigma)))
    x = np.arange(-half, half + 1, dtype=np.float64)
    k = np.exp(-(x**2) / (2.0 * sigma**2))
    k /= k.sum()

    out = a.astype(np.float64, copy=True)
    for axis in (0, 1):
        pad = [(0, 0)] * out.ndim
        pad[axis] = (half, half)
        padded = np.pad(out, pad, mode="reflect")
        out = np.apply_along_axis(lambda m: np.convolve(m, k, mode="valid"), axis, padded)
    return out


def dither_error(
    original: Image.Image,
    dithered: Image.Image,
    blur_radius: float | None = None,
    *,
    ppi: float | None = None,
    viewing_distance_cm: float | None = None,
) -> dict[str, float]:
    """Quality of a dither, measured where the eye actually integrates it.

    **Per-pixel error is the wrong metric for dithering.** Dithering makes
    individual pixels *more* wrong so the local average comes out right, so a
    per-pixel score says nearest-colour beats Floyd-Steinberg. The blurred
    figure is the one to trust and to regress against.

    What changed here, and why (near-term item N-E3). The previous version was
    right about blurring and wrong about where:

      * it blurred and differenced **8-bit gamma-encoded sRGB** — the same
        space the error diffusion runs in. A colour error caused by diffusing
        in gamma space was therefore invisible to the gate meant to catch it;
      * a blur is an average, and averaging gamma-encoded values does not model
        light reaching the eye. Blurring now happens in **linear light**;
      * Euclidean distance in sRGB is not perceived distance. The difference is
        now taken in **Oklab**, where it approximately is;
      * the radius was hardcoded to 1.5 px, which asserts that every panel at
        every viewing distance is seen identically. Pass `ppi` and
        `viewing_distance_cm` and it is derived from the one-arcminute acuity
        limit instead.

    The symptom all of that produced: Floyd-Steinberg scored 25.0 and Atkinson
    25.4 — a 1.6% spread between two algorithms with visibly different
    artifacts. A ruler that reads nearly the same number for everything cannot
    validate a change, which is why N-E4, N-E5, N-E8 and any optimisation-based
    halftoning were unverifiable before this.

    `structured_artifact_energy` is new and deliberately separate: worming and
    banding in a smooth passage live at 5-20 px, a scale per-pixel error cannot
    see and the acuity blur averages away. A dither can score well on
    `perceived_error` and still visibly worm.

    Returns `perceived_error` (Oklab, the headline), `structured_artifact_energy`,
    the resolved `blur_radius`, and the per-pixel figures — kept because they
    still catch a genuinely broken palette mapping, never as a dither score.
    """
    if blur_radius is None:
        if ppi is not None and viewing_distance_cm is not None:
            blur_radius = acuity_blur_radius(ppi, viewing_distance_cm)
        else:
            blur_radius = DEFAULT_BLUR_RADIUS
    if (
        not isinstance(blur_radius, (int, float))
        or isinstance(blur_radius, bool)
        or not math.isfinite(blur_radius)
        or blur_radius < 0
    ):
        raise ValueError("blur_radius must be a finite non-negative number")

    a_img = original.convert("RGB")
    b_img = dithered.convert("RGB")
    a8 = np.asarray(a_img, dtype=np.float64)
    b8 = np.asarray(b_img, dtype=np.float64)
    if a8.shape != b8.shape:
        raise ValueError(f"shape mismatch {a8.shape} vs {b8.shape}")

    per_pixel = np.sqrt(((a8 - b8) ** 2).sum(axis=2))

    a_lin, b_lin = srgb_to_linear(a8), srgb_to_linear(b8)
    a_seen = linear_to_oklab(_gaussian_blur_linear(a_lin, float(blur_radius)))
    b_seen = linear_to_oklab(_gaussian_blur_linear(b_lin, float(blur_radius)))
    perceived = np.sqrt(((a_seen - b_seen) ** 2).sum(axis=2))

    # Band-pass the LIGHTNESS error: energy the acuity blur removes but which
    # the eye still reads as texture. Difference of Gaussians over the 5-20 px
    # window. The +0.5 offset keeps the signal inside the [0,1] clip that the
    # float-image blur helper applies; it cancels in the subtraction.
    err_l = linear_to_oklab(a_lin)[..., 0] - linear_to_oklab(b_lin)[..., 0]
    err3 = np.repeat(err_l[..., None], 3, axis=2) + 0.5
    lo, hi = ARTIFACT_BAND_PX
    band = _gaussian_blur_linear(err3, lo)[..., 0] - _gaussian_blur_linear(err3, hi)[..., 0]

    return {
        "perceived_error": float(perceived.mean()),
        "structured_artifact_energy": float(np.sqrt((band**2).mean())),
        "blur_radius": float(blur_radius),
        "per_pixel_mean": float(per_pixel.mean()),
        "per_pixel_p95": float(np.percentile(per_pixel, 95)),
        "per_pixel_max": float(per_pixel.max()),
    }


def _spread(errors: dict[str, float]) -> dict[str, float]:
    """Absolute and relative spread of a set of per-profile errors."""
    if not errors:
        return {"min": 0.0, "max": 0.0, "absolute": 0.0, "relative": 0.0}
    lo, hi = min(errors.values()), max(errors.values())
    return {
        "min": lo,
        "max": hi,
        "absolute": hi - lo,
        "relative": (hi - lo) / hi if hi else 0.0,
    }


def palette_sensitivity(
    image: Image.Image,
    profiles: tuple[str, ...] = SPECTRA6_PROFILES,
    *,
    method: DitherMethod = "floyd-steinberg",
    blur_radius: float | None = None,
    ppi: float | None = None,
    viewing_distance_cm: float | None = None,
) -> dict[str, object]:
    """How much does the answer depend on WHICH published estimate we believe?

    Near-term item N-E2. Nobody outside E Ink has published measured Spectra 6
    primaries, so every colour result this project reports rests on somebody's
    estimate. Choosing one silently states a confidence nobody has earned.

    This renders the same image under each profile and reports the SPREAD of
    `perceived_error`. That spread is the error bar: a change to the dithering
    that moves the metric by less than it is not demonstrably an improvement,
    it is within the uncertainty of not knowing the panel's colours.

    `spectra6-legacy` is deliberately in the default set even though it is
    known-wrong (pure #000000/#FFFFFF, which no reflective panel reaches). It
    bounds how far a careless estimate moves things, and dropping it would make
    the interval look tighter than the evidence supports.
    """
    results: dict[str, dict[str, float]] = {}
    for name in profiles:
        pal = get_palette(name)
        rendered = quantize(image, pal, method=method)
        results[name] = dither_error(
            image,
            rendered,
            blur_radius,
            ppi=ppi,
            viewing_distance_cm=viewing_distance_cm,
        )

    errors = {k: v["perceived_error"] for k, v in results.items()}
    lo_name = min(errors, key=lambda k: errors[k])
    hi_name = max(errors, key=lambda k: errors[k])
    lo, hi = errors[lo_name], errors[hi_name]
    return {
        "per_profile": results,
        "perceived_error_min": lo,
        "perceived_error_max": hi,
        "perceived_error_spread": hi - lo,
        # The number to compare a proposed improvement against. A change smaller
        # than this is inside the uncertainty of the palette itself.
        "relative_spread": (hi - lo) / hi if hi else 0.0,
        "plausible_spread": _spread({k: v for k, v in errors.items() if k in SPECTRA6_PLAUSIBLE}),
        "best_profile": lo_name,
        "worst_profile": hi_name,
        "profiles_measured": [n for n in profiles if get_palette(n).measured],
        "all_estimates": not any(get_palette(n).measured for n in profiles),
    }
