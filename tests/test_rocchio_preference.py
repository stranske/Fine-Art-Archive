"""A preference vector that admits what it does not know.

Near-term item N-C6 / owner decision D6.

The corpus this runs on is small and lopsided: 93 rating events over 79 works,
fit averaging 8.2 on a 1-10 scale, because Tim rates what he already chose to
acquire. Two design choices follow from that, and both are asserted here
because both are easy to "simplify" back into being wrong:

  * the like/dislike split is the rater's own MEDIAN, not a fixed 5/10 — an
    absolute threshold puts 90% of this corpus on one side and learns nothing —
    and ties AT the median are dropped, because an earlier version that swept
    them into "disliked" counted every work rated 9/10 as a dislike;
  * `is_well_posed` and `negative_support` are reported, so a caller can see
    that a dislike signal rests on three examples instead of being handed a
    confident-looking vector built from noise.
"""

from __future__ import annotations

import math

from fine_art_archive.preference import build, features_of, score
from fine_art_archive.preference.rocchio import MIN_SUPPORT_PER_CLASS


def _work(artist: str, tags: list[str], *, rejected: list[str] | None = None) -> dict:
    content = [{"id": t, "state": "confirmed"} for t in tags]
    content += [{"id": t, "state": "rejected"} for t in (rejected or [])]
    return {"artist": {"name": artist}, "subject": {"content_tags": content}}


class TestFeatureExtraction:
    def test_tags_and_artist_become_features(self) -> None:
        f = features_of(_work("Goya", ["theme:war", "subject:male"]))
        assert f == {"artist:Goya", "tag:theme:war", "tag:subject:male"}

    def test_rejected_tags_are_excluded(self) -> None:
        """A rejected tag is evidence about the tagger, not about the work."""
        f = features_of(_work("Goya", ["theme:war"], rejected=["theme:still-life"]))
        assert "tag:theme:still-life" not in f

    def test_a_work_with_nothing_yields_nothing(self) -> None:
        assert features_of({}) == set()


class TestTheSplitAdaptsToTheData:
    def test_it_splits_at_the_median_not_a_fixed_threshold(self) -> None:
        """Every score above 5/10 — a fixed cut would put all of them 'liked'."""
        rated = [(_work(f"A{i}", [f"t{i}"]), float(s)) for i, s in enumerate([7, 8, 8, 9, 10])]
        v = build(rated)
        assert v.split_value == 8.0
        assert v.positive_support == 2  # 9, 10
        assert v.negative_support == 1  # 7
        assert any("exactly at the median" in n for n in v.notes), (
            "the two works AT 8.0 must be excluded from both classes, not "
            "swept into one — that inversion silently counted 9/10 as a dislike"
        )

    def test_a_uniform_corpus_is_reported_as_having_no_contrast(self) -> None:
        rated = [(_work(f"A{i}", [f"tag:t{i}"]), 8.0) for i in range(6)]
        v = build(rated)
        assert any("one side of the median" in n for n in v.notes)

    def test_no_ratings_at_all_is_not_a_silent_empty_vector(self) -> None:
        v = build([])
        assert v.weights == {}
        assert v.notes and math.isnan(v.split_value)


class TestItSaysWhenItIsUnderpowered:
    def test_a_thin_negative_class_is_flagged(self) -> None:
        """The real corpus shape: almost everything liked."""
        rated = [(_work("A", ["tag:x"]), 9.0) for _ in range(30)]
        rated += [(_work("B", ["tag:y"]), 2.0) for _ in range(3)]
        v = build(rated)
        assert v.negative_support < MIN_SUPPORT_PER_CLASS
        assert v.is_well_posed is False
        assert any("negative centroid" in n for n in v.notes)

    def test_balanced_support_is_well_posed(self) -> None:
        rated = [(_work("A", ["tag:x"]), 9.0) for _ in range(12)]
        rated += [(_work("B", ["tag:y"]), 3.0) for _ in range(12)]
        assert build(rated).is_well_posed is True


class TestTheVectorSeparatesLikedFromDisliked:
    @staticmethod
    def _corpus() -> list[tuple[dict, float]]:
        liked = [(_work("Bruegel", ["tag:theme:war", "tag:subject:male"]), 10.0) for _ in range(12)]
        disliked = [(_work("Other", ["tag:setting:outdoor"]), 3.0) for _ in range(12)]
        return liked + disliked

    def test_liked_features_score_above_disliked_ones(self) -> None:
        v = build(self._corpus())
        liked = score(_work("Bruegel", ["tag:theme:war", "tag:subject:male"]), v)
        disliked = score(_work("Other", ["tag:setting:outdoor"]), v)
        assert liked > 0 > disliked

    def test_an_unseen_work_scores_neutrally_rather_than_confidently(self) -> None:
        v = build(self._corpus())
        assert score(_work("Nobody", ["tag:brand:new"]), v) == 0.0

    def test_scoring_is_normalised_by_feature_count(self) -> None:
        """Otherwise a heavily-tagged work outranks a good one for having more tags."""
        v = build(self._corpus())
        few = score(_work("Bruegel", ["tag:theme:war"]), v)
        many = score(_work("Bruegel", ["tag:theme:war", "tag:brand:new", "tag:brand:new2"]), v)
        assert many < few, "padding a work with unknown tags must not raise its score"


class TestIdfStopsCommonTagsDominating:
    def test_a_feature_on_every_work_carries_little_weight(self) -> None:
        rated = [(_work("A", ["everywhere", "rare-good"]), 10.0) for _ in range(12)]
        rated += [(_work("B", ["everywhere"]), 3.0) for _ in range(12)]
        v = build(rated)
        assert v.weights["tag:rare-good"] > v.weights.get("tag:everywhere", 0.0)
