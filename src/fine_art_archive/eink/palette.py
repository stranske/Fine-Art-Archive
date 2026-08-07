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
from PIL import Image, ImageFilter

DitherMethod = Literal["none", "floyd-steinberg", "atkinson"]


@dataclass(frozen=True)
class Palette:
    """A device's reproducible colours."""

    name: str
    colours: tuple[tuple[int, int, int], ...]
    measured: bool = False
    note: str = ""

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

PALETTES: dict[str, Palette] = {p.name: p for p in (SPECTRA6, KALEIDO3, MONO1BIT, GRAY16)}


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


def dither_error(
    original: Image.Image, dithered: Image.Image, blur_radius: float = 1.5
) -> dict[str, float]:
    """Quality of a dither, measured the way an eye actually sees it.

    **Per-pixel error is the wrong metric for dithering, and reporting it alone
    inverts the answer.** Dithering deliberately makes individual pixels *more*
    wrong so that the local average comes out right. Measured on Ruisdael's
    "Dunes by the Sea" against the Spectra 6 palette:

        method             per-pixel    blurred r=1.5
        nearest (none)         59.4            48.0
        floyd-steinberg        85.0            25.0
        atkinson               78.7            25.4

    So per-pixel says nearest-colour is 30% better; perceived error says
    dithering is nearly twice as accurate. The blurred figure is the one to
    trust and the one to regress against, because a low-pass filter is what the
    eye does at viewing distance.

    `perceived_rgb_distance` is the headline. The per-pixel numbers are kept
    because they still catch a genuinely broken palette mapping (both metrics
    move together when the palette itself is wrong), but they must never be
    read as a dither-quality score.
    """
    if (
        not isinstance(blur_radius, (int, float))
        or isinstance(blur_radius, bool)
        or not math.isfinite(blur_radius)
        or blur_radius < 0
    ):
        raise ValueError("blur_radius must be a finite non-negative number")
    a_img = original.convert("RGB")
    b_img = dithered.convert("RGB")
    a = np.asarray(a_img, dtype=np.float64)
    b = np.asarray(b_img, dtype=np.float64)
    if a.shape != b.shape:
        raise ValueError(f"shape mismatch {a.shape} vs {b.shape}")
    d = np.sqrt(((a - b) ** 2).sum(axis=2))

    blurred = np.sqrt(
        (
            (
                np.asarray(a_img.filter(ImageFilter.GaussianBlur(blur_radius)), dtype=np.float64)
                - np.asarray(b_img.filter(ImageFilter.GaussianBlur(blur_radius)), dtype=np.float64)
            )
            ** 2
        ).sum(axis=2)
    )

    return {
        "perceived_rgb_distance": float(blurred.mean()),
        "blur_radius": blur_radius,
        "per_pixel_mean": float(d.mean()),
        "per_pixel_p95": float(np.percentile(d, 95)),
        "per_pixel_max": float(d.max()),
    }
