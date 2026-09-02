"""The fourth reason a work Q-ID sits on two sidecars, and why it is not a defect.

The collision taxonomy had three branches -- duplicate, series, subject -- and
the commonest case in this archive fits none of them. Two complementary crops of
one painting BOTH depict that painting, so both correctly carry its Q-ID. Every
pass that re-derived the three-way split put the same two pairs back in front of
the owner; this is the test that stops it.
"""

from __future__ import annotations

import pytest

from fine_art_archive.identity.crop_siblings import (
    CropSiblingGroup,
    crop_sibling_groups,
    crop_sibling_work_ids,
)

TINTORETTO = "Q19904859"
VAN_GOGH = "Q24020196"


def _meta(work_id: str, qid: str | None, variants: list[dict] | None = None) -> dict:
    files: dict[str, object] = {
        "master": {
            "filename": "master.jpeg",
            "sha256": "a" * 64,
            "size_bytes": 1,
            "ingested_at": "2026-09-01T00:00:00Z",
        }
    }
    if variants is not None:
        files["variants"] = variants
    return {
        "work_id": work_id,
        "schema_version": "1.0",
        "artist": {"name": "Test Artist"},
        "title": work_id,
        "files": files,
        "history": [{"ts": "2026-09-01T00:00:00Z", "actor": "test", "op": "ingested"}],
        "stable_identifiers": {"wikidata_q": qid} if qid else {},
    }


def _crop(target: str, position: str | None = None) -> dict:
    return {
        "filename": "master.jpeg",
        "rel_path": f"works/{target}/master.jpeg",
        "role": "partial-crop",
        "crop_position": position,
    }


class TestRecognisingTheGroup:
    def test_a_mutually_declared_pair_is_a_crop_sibling_group(self) -> None:
        """The real Tintoretto shape: each side names the other as partial-crop."""
        metas = [
            _meta("0777183-loaves", TINTORETTO, [_crop("7c89c9a-loaves", "right")]),
            _meta("7c89c9a-loaves", TINTORETTO, [_crop("0777183-loaves", "left")]),
        ]
        groups = crop_sibling_groups(metas)
        assert len(groups) == 1
        assert groups[0].work_qid == TINTORETTO
        assert groups[0].work_ids == ("0777183-loaves", "7c89c9a-loaves")

    def test_positions_are_read_from_the_entry_that_describes_each_side(self) -> None:
        """`crop_position` describes the VARIANT, per the schema — not the owner."""
        metas = [
            _meta("0777183-loaves", TINTORETTO, [_crop("7c89c9a-loaves", "right")]),
            _meta("7c89c9a-loaves", TINTORETTO, [_crop("0777183-loaves", "left")]),
        ]
        positions = crop_sibling_groups(metas)[0].positions
        assert positions["7c89c9a-loaves"] == "right"
        assert positions["0777183-loaves"] == "left"

    def test_a_three_crop_work_does_not_need_a_complete_graph(self) -> None:
        """A 3-panel work links as a chain; requiring every pair would miss it."""
        metas = [
            _meta("aaa-wide", "Q1", [_crop("bbb-wide", "centre")]),
            _meta("bbb-wide", "Q1", [_crop("aaa-wide", "left"), _crop("ccc-wide", "right")]),
            _meta("ccc-wide", "Q1", [_crop("bbb-wide", "centre")]),
        ]
        groups = crop_sibling_groups(metas)
        assert len(groups) == 1
        assert groups[0].work_ids == ("aaa-wide", "bbb-wide", "ccc-wide")

    def test_work_ids_are_exposed_flat_for_callers_that_filter(self) -> None:
        metas = [
            _meta("0777183-loaves", TINTORETTO, [_crop("7c89c9a-loaves", "right")]),
            _meta("7c89c9a-loaves", TINTORETTO, [_crop("0777183-loaves", "left")]),
        ]
        assert crop_sibling_work_ids(metas) == frozenset({"0777183-loaves", "7c89c9a-loaves"})


class TestWhatMustNotBeExcused:
    """A real duplicate must never slip through as a crop sibling."""

    def test_an_unlinked_pair_sharing_a_qid_is_not_excused(self) -> None:
        """The Van Gogh shape BEFORE its links were written — still a collision."""
        metas = [_meta("569ac23-garden", VAN_GOGH), _meta("8716d0e-garden", VAN_GOGH)]
        assert crop_sibling_groups(metas) == []

    def test_a_one_sided_declaration_is_not_enough(self) -> None:
        """One entry cannot distinguish 'complementary' from a stray link."""
        metas = [
            _meta("aaa-work", "Q1", [_crop("bbb-work", "left")]),
            _meta("bbb-work", "Q1"),
        ]
        assert crop_sibling_groups(metas) == []

    def test_a_directed_cycle_is_not_a_crop_sibling_group(self) -> None:
        """A cycle lacks the reciprocal pair evidence needed to excuse a Q-ID."""
        metas = [
            _meta("aaa-work", "Q1", [_crop("bbb-work", "left")]),
            _meta("bbb-work", "Q1", [_crop("ccc-work", "centre")]),
            _meta("ccc-work", "Q1", [_crop("aaa-work", "right")]),
        ]
        assert crop_sibling_groups(metas) == []

    def test_a_different_role_is_not_a_partial_crop(self) -> None:
        """`duplicate-copy` means the opposite thing and must not be excused."""
        metas = [
            _meta(
                "aaa-work",
                "Q1",
                [{"rel_path": "works/bbb-work/master.jpeg", "role": "duplicate-copy"}],
            ),
            _meta(
                "bbb-work",
                "Q1",
                [{"rel_path": "works/aaa-work/master.jpeg", "role": "duplicate-copy"}],
            ),
        ]
        assert crop_sibling_groups(metas) == []

    def test_a_link_pointing_outside_the_group_does_not_excuse_the_group(self) -> None:
        metas = [
            _meta("aaa-work", "Q1", [_crop("zzz-elsewhere", "left")]),
            _meta("bbb-work", "Q1", [_crop("zzz-elsewhere", "right")]),
        ]
        assert crop_sibling_groups(metas) == []

    def test_a_sidecar_without_a_qid_forms_no_group(self) -> None:
        metas = [
            _meta("aaa-work", None, [_crop("bbb-work", "left")]),
            _meta("bbb-work", None, [_crop("aaa-work", "right")]),
        ]
        assert crop_sibling_groups(metas) == []


class TestCompleteness:
    def test_a_group_missing_a_position_is_not_complete(self) -> None:
        """Incomplete is still a group — it just has a position left to measure."""
        group = CropSiblingGroup(TINTORETTO, ("a", "b"), {"a": "left", "b": None})
        assert not group.complete

    def test_a_group_with_every_position_is_complete(self) -> None:
        group = CropSiblingGroup(TINTORETTO, ("a", "b"), {"a": "left", "b": "right"})
        assert group.complete


class TestTheMeasurement:
    """`measure_lateral_overlap` needs real pixels; these cover its contract."""

    def test_missing_imaging_libraries_raise_rather_than_verdict(self) -> None:
        """Could not measure must never be readable as measured and different."""
        pytest.importorskip("numpy")
        pytest.importorskip("PIL")
        from fine_art_archive.identity.crop_siblings import measure_lateral_overlap

        with pytest.raises((OSError, FileNotFoundError)):
            measure_lateral_overlap("/nonexistent/a.jpg", "/nonexistent/b.jpg")

    def test_complementary_requires_all_three_conditions(self) -> None:
        """A high best-match alone is not enough — a re-encode also matches high."""
        from fine_art_archive.identity.crop_siblings import LateralOverlap

        reencode = LateralOverlap(
            aligned_ncc=0.995, best_ncc=0.995, shift_fraction=0.0, ordering=None
        )
        assert reencode.same_content
        assert not reencode.complementary

        crops = LateralOverlap(
            aligned_ncc=-0.17, best_ncc=0.982, shift_fraction=0.33, ordering="a-left"
        )
        assert crops.complementary
        assert not crops.same_content

    def test_measurement_returns_numeric_scores_for_real_images(self, tmp_path) -> None:
        """Valid images exercise the locate path rather than only its error path."""
        pytest.importorskip("numpy")
        pillow = pytest.importorskip("PIL.Image")
        import numpy as np

        from fine_art_archive.identity.crop_siblings import measure_lateral_overlap

        panorama = np.tile(np.arange(120, dtype=np.uint8), (40, 1))
        left_path = tmp_path / "left.png"
        right_path = tmp_path / "right.png"
        pillow.fromarray(panorama[:, :80]).save(left_path)
        pillow.fromarray(panorama[:, 40:]).save(right_path)

        result = measure_lateral_overlap(left_path, right_path, height=40)
        assert isinstance(result.best_ncc, float)
        assert result.best_ncc <= 1.0


class TestTheCalibration:
    """The threshold is measured, not chosen — so it must not drift silently."""

    def test_it_separates_the_measured_populations(self) -> None:
        """Both real pairs pass; the strongest unrelated pair observed does not."""
        from fine_art_archive.identity.crop_siblings import OVERLAP_MIN_NCC

        weakest_true_pair = 0.926  # Tintoretto, measured 2026-09-01
        strongest_unrelated = 0.559  # max of 11 random archive pairs
        assert strongest_unrelated < OVERLAP_MIN_NCC < weakest_true_pair

    def test_the_first_draft_threshold_would_have_rejected_a_true_pair(self) -> None:
        """Guards the specific mistake: deriving this from the sameness bound."""
        from fine_art_archive.identity.crop_siblings import (
            OVERLAP_MIN_NCC,
            SAME_CONTENT_MIN_CORRELATION,
        )

        assert OVERLAP_MIN_NCC < SAME_CONTENT_MIN_CORRELATION - 0.03
