from __future__ import annotations

import math

import pytest

from fine_art_archive.preference.exhibition import (
    EmbeddingDimensionError,
    NegativeQualityError,
    NonFiniteEvidenceError,
    SubsetSizeError,
    select_quality_diverse,
)

WORK_IDS = ["near-a", "near-b", "diverse"]
QUALITY = {"near-a": 1.0, "near-b": 0.99, "diverse": 0.85}
EMBEDDINGS = {
    "near-a": [1.0, 0.0],
    "near-b": [0.999, 0.04],
    "diverse": [0.0, 1.0],
}


def test_quality_diversity_beats_naive_top_n():
    naive = sorted(WORK_IDS, key=lambda work_id: -QUALITY[work_id])[:2]

    result = select_quality_diverse(WORK_IDS, QUALITY, EMBEDDINGS, 2, seed=17)

    assert naive == ["near-a", "near-b"]
    assert result.selected_ids == ["near-a", "diverse"]
    assert result.diagnostics[1].nearest_selected_similarity == pytest.approx(0.0)
    assert result.diagnostics[0].quality_contribution == pytest.approx(1.0)


def test_seeded_tie_break_is_deterministic_and_input_order_independent():
    qualities = dict.fromkeys(WORK_IDS, 1.0)
    embeddings = {work_id: [1.0, 0.0] for work_id in WORK_IDS}

    forward = select_quality_diverse(WORK_IDS, qualities, embeddings, 2, seed=9)
    reverse = select_quality_diverse(list(reversed(WORK_IDS)), qualities, embeddings, 2, seed=9)

    assert forward.selected_ids == reverse.selected_ids
    assert [item.tie_break_rank for item in forward.diagnostics] == [
        item.tie_break_rank for item in reverse.diagnostics
    ]


def test_invalid_embedding_dimensions_are_named():
    with pytest.raises(EmbeddingDimensionError, match="dimension"):
        select_quality_diverse(WORK_IDS, QUALITY, {**EMBEDDINGS, "diverse": [0.0, 1.0, 0.0]}, 2)


def test_nan_quality_is_named():
    with pytest.raises(NonFiniteEvidenceError, match="quality must be finite"):
        select_quality_diverse(WORK_IDS, {**QUALITY, "near-a": math.nan}, EMBEDDINGS, 2)


def test_negative_quality_is_named():
    with pytest.raises(NegativeQualityError, match="non-negative"):
        select_quality_diverse(WORK_IDS, {**QUALITY, "near-a": -0.1}, EMBEDDINGS, 2)


def test_subset_larger_than_candidate_set_is_named():
    with pytest.raises(SubsetSizeError, match="exceeds candidate count"):
        select_quality_diverse(WORK_IDS, QUALITY, EMBEDDINGS, 4)
