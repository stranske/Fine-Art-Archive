"""A master and its display crop must never be classed as duplicates.

This has now gone wrong twice, both times the same way — an analysis compared
megapixels, file size and JPEG quality, never looked at ASPECT, and concluded
that a work held twice was waste:

  * 2026-08-01: 13 of 52 duplicate-resolution decisions would have quarantined
    a file that was in use as a display copy.
  * 2026-08-09: all 44 "duplicate-holding" work-Q-ID groups were presented as
    quarantine candidates. Re-run through this logic, 27 were protected and
    every one of the remaining 17 was itself a display crop.

So the tests here are not abstract. Each one is a shape that has actually been
misread, and the module exists in the canonical library — rather than in a
workspace script someone has to remember — so that it is importable from
wherever the next analysis gets written.
"""

from __future__ import annotations

import pytest

from fine_art_archive.display.crops import (
    ASPECT_TOLERANCE,
    MEURAL_CAP_BYTES,
    ROLE_LANDSCAPE,
    ROLE_PORTRAIT,
    classify_pair,
    crop_role,
    display_aspect_of,
)

MB = 1_000_000


class TestRecognisingADisplayAspect:
    @pytest.mark.parametrize(
        ("w", "h", "expected"),
        [
            (1920, 1080, "16:9"),
            (4000, 2250, "16:9"),
            (29294, 16478, "16:9"),  # a gigapixel crop is still a crop
            (1080, 1920, "9:16"),
            (3375, 6000, "9:16"),
        ],
    )
    def test_files_on_a_display_aspect_are_named(self, w: int, h: int, expected: str) -> None:
        assert display_aspect_of(w / h) == expected

    @pytest.mark.parametrize(("w", "h"), [(1000, 1000), (4000, 3000), (2000, 2600)])
    def test_a_painting_shaped_file_is_not_a_display_aspect(self, w: int, h: int) -> None:
        """Paintings are not 16:9. Squares, 4:3 and portrait canvases are originals."""
        assert display_aspect_of(w / h) is None

    def test_near_miss_is_not_swept_in(self) -> None:
        """The tolerance is tight on purpose — widening it catches originals."""
        assert display_aspect_of(1.70) is None

    @pytest.mark.parametrize("bad", [None, 0, -1])
    def test_unknown_aspect_is_never_guessed(self, bad: float | None) -> None:
        assert display_aspect_of(bad) is None
        assert crop_role(bad) is None

    def test_roles_match_what_the_linker_writes(self) -> None:
        assert crop_role(16 / 9) == ROLE_LANDSCAPE
        assert crop_role(9 / 16) == ROLE_PORTRAIT
        assert crop_role(4 / 3) is None


class TestPairsThatMustBeProtected:
    def test_existing_variant_links_settle_it(self) -> None:
        v = classify_pair(
            16 / 9, 5 * MB, (1920, 1080), 16 / 9, 4 * MB, (1920, 1080), a_has_variant_links=True
        )
        assert v.protected and not v.safe_to_dedupe

    def test_one_side_over_the_meural_cap_is_the_reason_the_other_exists(self) -> None:
        v = classify_pair(4 / 3, 40 * MB, (8000, 6000), 4 / 3, 8 * MB, (2000, 1500))
        assert v.protected
        assert "cannot be shown" in " ".join(v.reasons)

    def test_a_master_and_its_crop_are_not_duplicates(self) -> None:
        """The central case: 4:3 original + 16:9 crop cut from it."""
        v = classify_pair(4 / 3, 12 * MB, (4000, 3000), 16 / 9, 6 * MB, (4000, 2250))
        assert v.protected and not v.safe_to_dedupe

    def test_materially_different_framing_is_protected(self) -> None:
        v = classify_pair(1.9514, 10 * MB, (3900, 2000), 1.7779, 9 * MB, (3556, 2000))
        assert v.protected
        assert "different framing" in " ".join(v.reasons)

    def test_same_display_aspect_but_different_sizes_is_a_decision(self) -> None:
        """One rendition per device is plausible; that is review, not waste.

        Both sides deliberately under Meural's cap, because a pair straddling it
        is settled earlier and more decisively by the cap rule — as the real
        Magnolias cluster (39.0 / 4.6 MB) is.
        """
        v = classify_pair(16 / 9, 12 * MB, (10004, 5627), 16 / 9, 4 * MB, (2560, 1440))
        assert v.verdict == "needs_review"
        assert not v.safe_to_dedupe

    def test_a_pair_straddling_the_meural_cap_is_settled_by_the_cap(self) -> None:
        """The real Magnolias shape — protected for a more specific reason."""
        v = classify_pair(16 / 9, 39 * MB, (10004, 5627), 16 / 9, 4 * MB, (2560, 1440))
        assert v.protected
        assert "cannot be shown" in " ".join(v.reasons)


class TestPairsThatAreGenuinelyRedundant:
    def test_identical_dimensions_at_the_same_display_aspect(self) -> None:
        """Same rendition, two JPEG qualities — the real Third of May case.

        Now requires the content evidence, because the geometry it used to
        decide on is shared with the complementary-crop case below.
        """
        v = classify_pair(
            16 / 9,
            298 * MB,
            (29294, 16478),
            16 / 9,
            297 * MB,
            (29294, 16478),
            content_correlation=0.998,
        )
        assert v.safe_to_dedupe and not v.protected

    def test_identical_display_geometry_alone_is_no_longer_enough(self) -> None:
        """Without the pixels, this shape has two explanations — so it is review.

        The regression this guards: `classify_pair` returned `redundant` for the
        real Van Gogh *Garden of the Asylum* pair (2013x3579 twice, 11.72 vs
        11.75 MB), which are two COMPLEMENTARY crops. The module written to stop
        display crops being deleted would have greenlit deleting one.
        """
        v = classify_pair(9 / 16, 12 * MB, (2013, 3579), 9 / 16, 12 * MB, (2013, 3579))
        assert not v.safe_to_dedupe
        assert v.verdict == "needs_review"
        assert "geometry cannot tell apart" in " ".join(v.reasons)

    def test_low_content_correlation_protects_complementary_crops(self) -> None:
        """The measured Van Gogh pair: identical geometry, different content."""
        v = classify_pair(
            9 / 16,
            12 * MB,
            (2013, 3579),
            9 / 16,
            12 * MB,
            (2013, 3579),
            content_correlation=-0.168,
        )
        assert v.protected and not v.safe_to_dedupe
        assert "complementary crops" in " ".join(v.reasons)

    def test_non_finite_content_correlation_needs_review(self) -> None:
        v = classify_pair(
            16 / 9,
            12 * MB,
            (1600, 900),
            16 / 9,
            12 * MB,
            (1600, 900),
            content_correlation=float("nan"),
        )
        assert v.verdict == "needs_review"

    def test_identical_dimensions_off_any_display_aspect(self) -> None:
        v = classify_pair(4 / 3, 10 * MB, (4000, 3000), 4 / 3, 6 * MB, (4000, 3000))
        assert v.safe_to_dedupe


class TestTheDefaultDirection:
    def test_unknown_geometry_defaults_to_review_not_to_safe(self) -> None:
        """Wrong 'redundant' deletes a file in use; wrong 'review' costs a glance."""
        v = classify_pair(None, None, None, None, None, None)
        assert v.verdict == "needs_review"
        assert not v.safe_to_dedupe

    def test_nothing_is_safe_without_positive_evidence(self) -> None:
        v = classify_pair(4 / 3, 10 * MB, (4000, 3000), 4 / 3, 6 * MB, (2000, 1500))
        assert not v.safe_to_dedupe

    def test_the_constants_are_the_documented_ones(self) -> None:
        assert MEURAL_CAP_BYTES == 20 * 1024 * 1024
        assert ASPECT_TOLERANCE == 0.02
