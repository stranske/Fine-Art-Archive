"""Acceptance tests for quality-times-diversity exhibition selection."""

from __future__ import annotations

import math

import pytest

from fine_art_archive.eink import PlaylistSpec, build, select_quality_diverse


def _sidecar(work_id: str) -> tuple[str, dict]:
    return work_id, {"work_id": work_id, "title": work_id, "artist": {}, "subject": {}}


def test_quality_diversity_beats_naive_top_n() -> None:
    """A slightly lower-quality outlier belongs beside one near-duplicate."""
    selected = select_quality_diverse(
        ["near-a", "near-b", "diverse"],
        [10.0, 9.9, 9.0],
        [[1.0, 0.0], [0.999, 0.001], [0.0, 1.0]],
        2,
        seed=7,
    )
    assert set(selected.work_ids) == {"near-a", "diverse"}
    naive_top_n = {"near-a", "near-b"}
    assert set(selected.work_ids) != naive_top_n
    assert selected.diagnostics["selected"][1]["nearest_selected_similarity"] < 0.5


def test_playlist_mode_filters_then_returns_selector_order_and_diagnostics() -> None:
    spec = PlaylistSpec(
        limit=2,
        selection_mode="preference-diverse",
        selection_quality={"near-a": 10.0, "near-b": 9.9, "diverse": 9.0},
        selection_embeddings={
            "near-a": [1.0, 0.0],
            "near-b": [0.999, 0.001],
            "diverse": [0.0, 1.0],
        },
        seed=7,
    )
    result = build([_sidecar("near-a"), _sidecar("near-b"), _sidecar("diverse")], spec)
    assert result.work_ids == ["near-a", "diverse"]
    assert result.selection["mode"] == "preference-diverse"
    assert result.selection["selected"][0]["quality_contribution"] == 1.0


def test_api_preview_preserves_direct_selector_order_and_diagnostics(monkeypatch) -> None:
    from fine_art_archive.api import main

    rows = [_sidecar("near-a"), _sidecar("near-b"), _sidecar("diverse")]
    monkeypatch.setattr(main, "_all_sidecars", lambda: rows)
    monkeypatch.setattr(main.store, "work_ids_with_dossier", lambda: [])
    monkeypatch.setattr(main.store, "RATINGS_LOG", main.store.REPO_ROOT / "missing-ratings.jsonl")
    response = main.eink_playlist_preview(
        main.PlaylistIn(
            sample=3,
            spec={
                "limit": 2,
                "selection_mode": "preference-diverse",
                "selection_quality": {"near-a": 10.0, "near-b": 9.9, "diverse": 9.0},
                "selection_embeddings": {
                    "near-a": [1.0, 0.0],
                    "near-b": [0.999, 0.001],
                    "diverse": [0.0, 1.0],
                },
                "seed": 7,
            },
        )
    )
    assert response["work_ids"] == ["near-a", "diverse"]
    assert response["selection"]["selected"][1]["work_id"] == "diverse"


@pytest.mark.parametrize(
    ("qualities", "embeddings", "message"),
    [
        ([1.0, -1.0], [[1.0, 0.0], [0.0, 1.0]], "non-negative"),
        ([1.0, math.nan], [[1.0, 0.0], [0.0, 1.0]], "finite"),
        ([1.0, 1.0], [[1.0], [1.0, 0.0]], "rectangular"),
    ],
)
def test_selector_rejects_invalid_evidence(qualities, embeddings, message) -> None:
    with pytest.raises(ValueError, match=message):
        select_quality_diverse(["a", "b"], qualities, embeddings, 2)


def test_selector_rejects_subset_larger_than_candidates() -> None:
    with pytest.raises(ValueError, match="cannot exceed"):
        select_quality_diverse(["a"], [1.0], [[1.0, 0.0]], 2)
