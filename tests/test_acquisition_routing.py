"""Routing tests for score-based source selection in acquisition flow."""

from __future__ import annotations

from fine_art_archive.collect.acquisition_flow import rank_sources, select_source


def _aggregates_for(rijks_score: float, met_score: float) -> dict:
    return {
        "sources": {
            "rijksmuseum": {"western-painting-19c": {"composite_score": rijks_score}},
            "met": {"western-painting-19c": {"composite_score": met_score}},
        }
    }


def test_rank_sources_orders_by_score() -> None:
    aggregates = _aggregates_for(0.90, 0.70)
    ranked = rank_sources("western-painting-19c", ["met", "rijksmuseum"], aggregates)
    # Reversing rank_sources sort direction should fail this assertion.
    assert ranked[0][0] == "rijksmuseum"
    assert ranked[1][0] == "met"


def test_select_source_margin_rule() -> None:
    margin_pick = select_source(
        "western-painting-19c",
        ["met", "rijksmuseum"],
        _aggregates_for(0.90, 0.70),
    )
    assert margin_pick == ("rijksmuseum", "margin")

    tied_pick = select_source(
        "western-painting-19c",
        ["met", "rijksmuseum"],
        _aggregates_for(0.90, 0.85),
    )
    assert tied_pick == ("rijksmuseum", "tied-fallback")
