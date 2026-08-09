"""Forced choice, because "is this good?" cannot separate a corpus of yeses.

Near-term item N-C7. It exists to close a measured gap: `rocchio.build` splits
liked from disliked at the rater's median, this corpus's median fit is exactly
9.0, and **17 of 78 works tie there and are discarded**. A tie is not evidence
either way, and no amount of further absolute rating fixes that — asking "which
of these two?" does, because a forced choice has no neutral option.

The property these tests exist to protect is the one it would be easiest to
lose: Bradley-Terry strengths are comparable only WITHIN a connected component
of the comparison graph. Ranking across disconnected components is fabrication —
nothing in the data relates one group to the other — so `comparable` must go
False and say so rather than emit a confident list.
"""

from __future__ import annotations

import pytest

from fine_art_archive.preference.bradley_terry import (
    fit,
    minimum_comparisons,
    next_pair,
    recommended_comparisons,
)


class TestItRecoversAnOrdering:
    def test_a_clear_winner_outranks_a_clear_loser(self) -> None:
        r = fit([("a", "b")] * 5)
        assert r.strengths["a"] > r.strengths["b"]

    def test_a_transitive_chain_comes_out_in_order(self) -> None:
        comps = [("a", "b")] * 4 + [("b", "c")] * 4 + [("a", "c")] * 4
        order = [w for w, _ in fit(comps).ranked()]
        assert order == ["a", "b", "c"]

    def test_evenly_matched_items_score_close(self) -> None:
        r = fit([("a", "b"), ("b", "a"), ("a", "b"), ("b", "a")])
        assert abs(r.strengths["a"] - r.strengths["b"]) < 0.05

    def test_it_converges(self) -> None:
        assert fit([("a", "b")] * 3 + [("b", "c")] * 3).converged is True


class TestItNeverInventsAComparison:
    def test_disconnected_components_are_reported(self) -> None:
        """A-B and C-D with no link: no evidence relates A to C."""
        r = fit([("a", "b"), ("c", "d")])
        assert len(r.components) == 2
        assert r.comparable is False
        assert any("disconnected" in n for n in r.notes)

    def test_a_connected_graph_is_comparable(self) -> None:
        r = fit([("a", "b"), ("b", "c"), ("c", "d")])
        assert r.comparable is True
        assert len(r.components) == 1

    def test_no_comparisons_is_not_an_empty_ranking(self) -> None:
        r = fit([])
        assert r.strengths == {}
        assert r.notes

    def test_a_self_comparison_is_ignored_and_noted(self) -> None:
        r = fit([("a", "a"), ("a", "b")])
        assert any("self-comparison" in n for n in r.notes)


class TestThePriorKeepsItFinite:
    def test_an_item_that_lost_everything_is_not_zero(self) -> None:
        """Without a prior it collapses to 0 — near-certain in a short session."""
        r = fit([("a", "b")] * 6)
        assert r.strengths["b"] > 0.0

    def test_an_item_that_won_everything_stays_finite(self) -> None:
        r = fit([("a", "b")] * 6)
        assert r.strengths["a"] < float("inf")
        assert r.strengths["a"] == pytest.approx(r.strengths["a"])  # not NaN


class TestItAsksTheUsefulQuestion:
    def test_it_connects_an_unseen_work_first(self) -> None:
        """An unattached work makes any ranking including it indefensible."""
        pair = next_pair(["a", "b", "c"], [("a", "b")])
        assert pair is not None and "c" in pair

    def test_it_bridges_two_components_before_refining_one(self) -> None:
        pair = next_pair(["a", "b", "c", "d"], [("a", "b"), ("c", "d")])
        assert pair is not None
        assert {pair[0], pair[1]} & {"a", "b"} and {pair[0], pair[1]} & {"c", "d"}

    def test_once_connected_it_asks_the_closest_pair(self) -> None:
        """Comparing an obvious favourite to an also-ran learns nothing."""
        comps = [("a", "b"), ("b", "c")]
        strengths = {"a": 3.0, "b": 1.0, "c": 0.95}
        pair = next_pair(["a", "b", "c"], comps, strengths)
        assert pair is not None and set(pair) == {"a", "c"} or set(pair) == {"b", "c"}

    def test_it_stops_when_everything_has_been_asked(self) -> None:
        assert next_pair(["a", "b"], [("a", "b")], {"a": 1.0, "b": 1.0}) is None

    def test_one_item_has_nothing_to_ask(self) -> None:
        assert next_pair(["a"], []) is None


class TestItSaysHowMuchIsEnough:
    def test_the_floor_is_what_connecting_requires(self) -> None:
        assert minimum_comparisons(17) == 16

    def test_the_recommendation_exceeds_the_floor(self) -> None:
        assert recommended_comparisons(17) > minimum_comparisons(17)

    def test_a_ten_minute_session_is_plausible_for_the_tied_works(self) -> None:
        """17 tied works — the actual gap this exists to close."""
        assert recommended_comparisons(17) <= 80


class TestItMintsNegatives:
    def test_the_lower_half_becomes_genuine_dislikes(self) -> None:
        comps = [("a", "b")] * 3 + [("b", "c")] * 3 + [("c", "d")] * 3
        neg = fit(comps).negatives(0.5)
        assert "d" in neg and "a" not in neg


class TestACompleteRoundRobinConverges:
    """The shape a real ten-minute session actually produces.

    17 works, every pair compared once: 136 comparisons, and — near-certainly —
    one work undefeated and one winless. A perfect record puts the
    maximum-likelihood strength at infinity or zero, so this is not an edge case
    to be tolerated but the normal outcome to be regularised.

    The first implementation failed exactly here. It added the win prior once
    per ITEM but the comparison prior once per PAIR, so with 16 opponents each
    the denominator got 16x more prior than the numerator: strengths collapsed
    to a 10.9-to-0.000 spread and the fit never converged in 500 iterations.
    Unit tests on three-item chains had passed throughout.
    """

    @staticmethod
    def _round_robin(n: int = 17) -> list[tuple[str, str]]:
        items = [f"w{i:02d}" for i in range(n)]
        out = []
        for i, a in enumerate(items):
            for b in items[i + 1 :]:
                out.append((a, b))  # lower index always wins -> strict order
        return out

    def test_it_converges(self) -> None:
        r = fit(self._round_robin())
        assert r.converged is True, (
            "a complete round-robin with a perfect record is the NORMAL session "
            "outcome; failing to converge on it makes the ranking unusable"
        )

    def test_the_undefeated_work_is_finite(self) -> None:
        r = fit(self._round_robin())
        best = r.ranked()[0][1]
        assert 0 < best < 100

    def test_the_winless_work_is_above_zero(self) -> None:
        r = fit(self._round_robin())
        worst = r.ranked()[-1][1]
        assert worst > 0.01, "a winless work must be small, not annihilated"

    def test_the_spread_stays_interpretable(self) -> None:
        """A 40x spread from a 16-game record is the prior failing, not signal."""
        r = fit(self._round_robin())
        best, worst = r.ranked()[0][1], r.ranked()[-1][1]
        assert best / worst < 25

    def test_the_recovered_order_matches_the_truth(self) -> None:
        r = fit(self._round_robin())
        assert [w for w, _ in r.ranked()] == [f"w{i:02d}" for i in range(17)]
