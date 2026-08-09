"""How much of a painting a six-ink panel can actually reproduce.

Near-term item N-E1. This answers "is Spectra 6 good enough for THIS archive"
with **no hardware**, which is why the audit sequenced it before any display
purchase: it is the input to that decision, not a consequence of it.

The question is not "how many colours does the panel have" — six, and everyone
knows that. It is how far a given painting's colours sit from the nearest
colour the panel can make, measured where distance means something. A Vermeer
of muted earths and a Matisse of saturated flat colour are not equally served
by the same six inks, and a corpus average hides exactly that.

So this reports a DISTRIBUTION, never a single number:

  * `mean_distance` — average Oklab distance from each pixel to the nearest
    colour the panel can MIX. Across 40 real works this sits at a median of
    0.022, against 0.097 for the sRGB cube as a whole: paintings live well
    inside what six inks can reach, which is most of the N-E1 answer.
  * `p95_distance` — the tail. A work can have a low mean and still have a
    passage the panel cannot touch, and that passage is what you notice.
  * `out_of_gamut_fraction` — pixels beyond `OUT_OF_GAMUT_THRESHOLD`, where no
    amount of dithering will help because there is nothing near enough to mix.

Measured in **Oklab**, for the same reason the dither metric is (N-E3): sRGB
distance is not perceived distance, so a gamut score computed in sRGB would
rank works by something nobody sees.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PIL import Image

from .palette import Palette, linear_to_oklab, srgb_to_linear

#: Per-pixel Oklab distance from the panel's ACHIEVABLE set beyond which the
#: shift is visible. CALIBRATED against 40 real works from the archive, not
#: guessed — and the calibration is the point, because a threshold that never
#: fires makes the metric decorative:
#:
#:     threshold   median out-of-gamut   p90      works over 2%
#:     0.03              25.7%          54.3%        38/40
#:     0.05               3.5%          20.0%        27/40
#:     0.08               0.08%          4.6%         6/40   <- chosen
#:     0.12               0.00%          0.1%         1/40
#:
#: 0.03 and 0.05 flag most of the archive, which tells you nothing; 0.12 flags
#: almost nothing. 0.08 leaves the bulk clean and isolates a real tail.
#:
#: A first draft used 0.25 against the nearest SINGLE ink and reported every
#: image as 0.0% out of gamut. The fix was not a smaller number but the right
#: model — see `_mixture_set`.
OUT_OF_GAMUT_THRESHOLD = 0.08

#: Granularity of the ink-mixture lattice. 6 inks in steps of 1/6 gives 462
#: reachable colours, which is dense enough that the residual distance is
#: dominated by real gamut limits rather than lattice spacing.
MIXTURE_STEPS = 6

#: Long edge for the analysis downscale. Gamut fit is a property of a work's
#: COLOURS, not its resolution, and decoding gigapixel masters at full size to
#: answer a colour question costs minutes per work for no added accuracy.
ANALYSIS_LONG_EDGE = 512


@dataclass(frozen=True)
class GamutFit:
    """How well one work suits one palette."""

    mean_distance: float
    p95_distance: float
    max_distance: float
    out_of_gamut_fraction: float
    palette: str
    pixels_measured: int

    @property
    def verdict(self) -> str:
        """A label, kept coarse on purpose.

        Three buckets, because the underlying measurement does not support
        finer discrimination and a 1-100 score would imply precision this does
        not have.
        """
        if self.out_of_gamut_fraction < 0.02:
            return "well-served"
        if self.out_of_gamut_fraction < 0.15:
            return "compromised"
        return "poorly-served"


def _palette_oklab(palette: Palette) -> np.ndarray:
    """The inks themselves, in Oklab. Rarely what you want — see `_mixture_set`."""
    rgb = np.array(palette.colours, dtype=np.float64).reshape(1, -1, 3)
    return linear_to_oklab(srgb_to_linear(rgb)).reshape(-1, 3)


def _mixture_set(palette: Palette, steps: int = MIXTURE_STEPS) -> np.ndarray:
    """Colours the panel can actually produce, in Oklab.

    A six-ink panel is not limited to six colours. Dithering places inks side by
    side and the eye integrates them, so the achievable set is the convex hull
    of the inks — and crucially the mixing happens in LINEAR LIGHT, because that
    is what adds when photons arrive together. Averaging the gamma-encoded
    values would model a mixture nobody can make.

    Measuring distance to the nearest single ink instead of to this set is what
    made the first version of this module report every image as well-served: it
    was asking "is this colour one of the six" when the real question is "can
    the six be arranged to look like this".
    """
    inks_linear = srgb_to_linear(
        np.array(palette.colours, dtype=np.float64).reshape(1, -1, 3)
    ).reshape(-1, 3)
    n = inks_linear.shape[0]

    weights: list[tuple[int, ...]] = []

    def walk(prefix: tuple[int, ...], remaining: int, slots: int) -> None:
        if slots == 1:
            weights.append((*prefix, remaining))
            return
        for k in range(remaining + 1):
            walk((*prefix, k), remaining - k, slots - 1)

    walk((), steps, n)
    w = np.array(weights, dtype=np.float64) / steps
    mixed_linear = w @ inks_linear
    return linear_to_oklab(mixed_linear.reshape(1, -1, 3)).reshape(-1, 3)


def gamut_fit(image: Image.Image, palette: Palette) -> GamutFit:
    """Distance from each pixel to the nearest colour the panel can make.

    Distance is to the panel's ACHIEVABLE set — every mixture the inks can be
    dithered into — not to the nearest single ink. Measured before any actual
    dithering, so the answer is a property of the ink set rather than of one
    ditherer's cleverness.
    """
    img = image.convert("RGB")
    if max(img.size) > ANALYSIS_LONG_EDGE:
        img = img.copy()
        img.thumbnail((ANALYSIS_LONG_EDGE, ANALYSIS_LONG_EDGE))

    px = linear_to_oklab(srgb_to_linear(np.asarray(img, dtype=np.float64)))
    flat = px.reshape(-1, 3)
    pal = _mixture_set(palette)

    # (pixels, palette, 3) would be the obvious form and is a memory trap at
    # 512x512x6x3; chunking keeps it bounded without changing the answer.
    nearest = np.empty(flat.shape[0], dtype=np.float64)
    step = 65536
    for i in range(0, flat.shape[0], step):
        chunk = flat[i : i + step]
        d = np.sqrt(((chunk[:, None, :] - pal[None, :, :]) ** 2).sum(axis=2))
        nearest[i : i + step] = d.min(axis=1)

    return GamutFit(
        mean_distance=float(nearest.mean()),
        p95_distance=float(np.percentile(nearest, 95)),
        max_distance=float(nearest.max()),
        out_of_gamut_fraction=float((nearest > OUT_OF_GAMUT_THRESHOLD).mean()),
        palette=palette.name,
        pixels_measured=int(nearest.size),
    )


def summarise_corpus(fits: list[GamutFit]) -> dict[str, float | int | dict[str, int]]:
    """Aggregate per-work fits WITHOUT collapsing them to one number.

    A mean over the corpus would say "the archive is fine" while a tenth of it
    is unshowable. The buckets are the answer; the averages are context.
    """
    if not fits:
        return {"works": 0, "verdicts": {}}
    oog = np.array([f.out_of_gamut_fraction for f in fits])
    mean = np.array([f.mean_distance for f in fits])
    verdicts: dict[str, int] = {}
    for f in fits:
        verdicts[f.verdict] = verdicts.get(f.verdict, 0) + 1
    return {
        "works": len(fits),
        "verdicts": verdicts,
        "median_out_of_gamut_fraction": float(np.median(oog)),
        "p90_out_of_gamut_fraction": float(np.percentile(oog, 90)),
        "worst_out_of_gamut_fraction": float(oog.max()),
        "median_mean_distance": float(np.median(mean)),
    }
