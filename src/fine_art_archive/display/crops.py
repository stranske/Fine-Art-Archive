"""Display crops: what they are, and why a "duplicate" claim is invalid without them.

Tim crops high-resolution originals to display dimensions for his frames. The
crop and the original are BOTH real files, both wanted, and they are not
duplicates of one another — the schema says so directly of `files.variants[]`:
*"These are NOT duplicates: each is fit for a specific device."*

This module exists because that fact keeps getting lost, with consequences:

  * 2026-08-01, `audit_duplicate_decisions.py`: **13 of 52** duplicate-resolution
    decisions would have quarantined a file that was IN USE as a display copy.
  * 2026-08-09: a review of 44 "duplicate-holding" work-Q-ID groups presented
    all 44 as candidates for quarantine. Re-run through the crop test, **27
    were protected** and every one of the remaining 17 was itself a display
    crop. There were no duplicate paintings in the set at all.

Both times the analysis compared megapixels, file size and JPEG quality and
never looked at **aspect ratio**, so the explanation was invisible. That is the
failure this module is designed to make structurally impossible: the logic now
lives in the canonical library where any analysis in either tree can import it,
rather than in one workspace script that has to be remembered.

**The rule: nothing may be called a duplicate until `classify_pair` has been
run on it.** A high visual-similarity score is not sufficient — a master and
its 16:9 crop are *supposed* to look alike.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

#: The display aspects Tim actually targets. A file sitting exactly on one of
#: these was almost certainly cut for a frame, not scanned that way — paintings
#: are not 16:9.
DISPLAY_ASPECTS: dict[str, float] = {"16:9": 16 / 9, "9:16": 9 / 16}

#: Tight, because the point is to catch files sitting EXACTLY on a display
#: aspect. A painting that happens to be near 16:9 is not a crop, and widening
#: this would start sweeping real originals in.
DISPLAY_ASPECT_TOLERANCE = 0.005

#: Two renditions whose aspects differ by more than this are framed
#: differently — they are not the same image at another size.
ASPECT_TOLERANCE = 0.02

#: Meural refuses to display a file over 20 MB. When one side is over and the
#: other under, the small file exists BECAUSE the large one cannot be shown.
MEURAL_CAP_BYTES = 20 * 1024 * 1024

#: Aligned image correlation at or above which two files of identical geometry
#: are the same framing at two qualities. Below it they show different parts of
#: the work. Kept in step with
#: ``fine_art_archive.identity.crop_siblings.SAME_CONTENT_MIN_CORRELATION``.
SAME_CONTENT_MIN_CORRELATION = 0.98

#: Roles as written into `files.variants[].role` by `link_display_crops.py`.
ROLE_LANDSCAPE = "landscape-crop"
ROLE_PORTRAIT = "portrait-crop"
ROLE_FRAMED = "meural-framed"


def display_aspect_of(aspect: float | None) -> str | None:
    """Name the display aspect this ratio sits on, or None."""
    if not aspect or aspect <= 0:
        return None
    for name, target in DISPLAY_ASPECTS.items():
        if abs(aspect - target) / target <= DISPLAY_ASPECT_TOLERANCE:
            return name
    return None


def crop_role(aspect: float | None) -> str | None:
    """The `files.variants[].role` a file with this aspect would carry.

    Mirrors `link_display_crops.py`: ~16:9 is a landscape crop, ~9:16 a portrait
    crop, and anything else that is nonetheless a crop is `meural-framed`.
    Returns None when the aspect is unknown — never a role, because guessing a
    role is how a crop gets mistaken for an original.
    """
    da = display_aspect_of(aspect)
    if da == "16:9":
        return ROLE_LANDSCAPE
    if da == "9:16":
        return ROLE_PORTRAIT
    return None


@dataclass(frozen=True)
class CropVerdict:
    """Why a pair may or may not be treated as redundant."""

    #: True when the pair must NOT be deduped — they serve different purposes.
    protected: bool
    #: "protected" | "redundant" | "needs_review"
    verdict: str
    reasons: list[str] = field(default_factory=list)

    @property
    def safe_to_dedupe(self) -> bool:
        return self.verdict == "redundant"


def classify_pair(
    a_aspect: float | None,
    a_bytes: int | None,
    a_pixels: tuple[int, int] | None,
    b_aspect: float | None,
    b_bytes: int | None,
    b_pixels: tuple[int, int] | None,
    *,
    a_has_variant_links: bool = False,
    b_has_variant_links: bool = False,
    content_correlation: float | None = None,
) -> CropVerdict:
    """Decide whether two renditions of one work may be treated as redundant.

    Ordered most-decisive first. Anything that cannot be positively shown to be
    redundant comes back as `needs_review`, never as safe: the cost of a wrong
    "redundant" is deleting a file in use on a frame, and the cost of a wrong
    "needs review" is one glance.

    `content_correlation`, when supplied, is the aligned correlation of the two
    images -- see
    :func:`~fine_art_archive.identity.crop_siblings.measure_lateral_overlap`.
    It is required before any `redundant` verdict on two files that both sit on
    a display aspect, because geometry alone cannot tell one rendition at two
    JPEG qualities from two COMPLEMENTARY crops cut for the same panel. Those
    two cases look identical on every input this function used to take: the same
    display aspect, the same pixel dimensions, near-equal byte sizes. The real
    Third of May pair (29294x16478, 298 vs 297 MB) and the real Van Gogh
    *Garden of the Asylum* pair (2013x3579, 11.72 vs 11.75 MB) differ only in
    what the pixels show, and this function called both redundant -- so the
    module written to stop display crops being deleted would itself have
    greenlit deleting one of a complementary pair.
    """
    reasons: list[str] = []

    if a_has_variant_links or b_has_variant_links:
        reasons.append(
            "already carries variants[] links — the relationship is recorded, "
            "so these are a master and its display copies"
        )
        return CropVerdict(True, "protected", reasons)

    big_b, small_b = sorted([a_bytes or 0, b_bytes or 0], reverse=True)
    if big_b > MEURAL_CAP_BYTES >= small_b > 0:
        reasons.append(
            f"{big_b / 1e6:.1f} MB is over Meural's 20 MB cap and cannot be "
            f"displayed, while {small_b / 1e6:.1f} MB can — the small file "
            "exists BECAUSE the large one cannot be shown"
        )
        return CropVerdict(True, "protected", reasons)

    da_a, da_b = display_aspect_of(a_aspect), display_aspect_of(b_aspect)

    if a_aspect and b_aspect:
        delta = abs(a_aspect - b_aspect) / max(a_aspect, b_aspect)
        if delta > ASPECT_TOLERANCE:
            reasons.append(
                f"aspects differ {a_aspect:.4f} vs {b_aspect:.4f} "
                f"({delta * 100:.1f}%) — different framing, not the same image "
                "at another size"
            )
            return CropVerdict(True, "protected", reasons)

    if bool(da_a) != bool(da_b):
        crop_side = "A" if da_a else "B"
        reasons.append(
            f"side {crop_side} sits exactly on {da_a or da_b} — it is a crop cut "
            "for a frame, and the other side is its original"
        )
        return CropVerdict(True, "protected", reasons)

    if da_a and da_b and da_a == da_b:
        # Both are crops at the same display aspect. Tim targets SEVERAL devices
        # with different resolutions (Meural, Inky 13.3", InkPoster 28.5", Frame
        # TV), so two 16:9 files may be one per device rather than waste.
        if a_pixels and b_pixels and a_pixels == b_pixels:
            # Identical geometry has TWO explanations and this function cannot
            # see the difference: one rendition at two JPEG qualities, or two
            # complementary crops cut to the same panel — which have identical
            # dimensions by construction, since they target the same device.
            # Only the pixels separate them, so only the pixels may decide.
            if content_correlation is None:
                reasons.append(
                    f"both sit on {da_a} at identical {a_pixels[0]}x{a_pixels[1]} — "
                    "that is one rendition at two qualities OR two complementary "
                    "crops for the same panel, which geometry cannot tell apart; "
                    "measure content correlation before calling either redundant"
                )
                return CropVerdict(True, "needs_review", reasons)
            if not math.isfinite(content_correlation):
                reasons.append(
                    "content correlation is not finite — measure again before " "deduplication"
                )
                return CropVerdict(True, "needs_review", reasons)
            if content_correlation < SAME_CONTENT_MIN_CORRELATION:
                reasons.append(
                    f"both sit on {da_a} at identical {a_pixels[0]}x{a_pixels[1]} "
                    f"but content correlation is {content_correlation:.3f} — they "
                    "show DIFFERENT parts of the work, so they are complementary "
                    "crops and neither is redundant"
                )
                return CropVerdict(True, "protected", reasons)
            reasons.append(
                f"both sit on {da_a} at identical {a_pixels[0]}x{a_pixels[1]} and "
                f"content correlation is {content_correlation:.3f} — the same "
                "rendition at two JPEG qualities, so one is redundant"
            )
            return CropVerdict(False, "redundant", reasons)
        reasons.append(
            f"both sit on {da_a} but at different pixel dimensions — plausibly "
            "one rendition per device, which is a decision, not waste"
        )
        return CropVerdict(True, "needs_review", reasons)

    if a_pixels and b_pixels and a_pixels == b_pixels:
        reasons.append(
            f"identical {a_pixels[0]}x{a_pixels[1]} at the same aspect — "
            "one rendition at two JPEG qualities"
        )
        return CropVerdict(False, "redundant", reasons)

    reasons.append("no positive evidence of redundancy — defaulting to review")
    return CropVerdict(True, "needs_review", reasons)
