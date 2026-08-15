"""Deterministic quality-times-diversity selection for bounded exhibitions."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np


class ExhibitionValidationError(ValueError):
    """Base class for invalid exhibition evidence."""


class EmbeddingDimensionError(ExhibitionValidationError):
    """Embedding vectors are empty or do not share one dimension."""


class NonFiniteEvidenceError(ExhibitionValidationError):
    """Quality or embedding evidence contains NaN or infinity."""


class NegativeQualityError(ExhibitionValidationError):
    """A quality score is negative."""


class SubsetSizeError(ExhibitionValidationError):
    """The requested exhibition size is not supported by the candidates."""


class MissingEvidenceError(ExhibitionValidationError):
    """A candidate lacks supplied quality or embedding evidence."""


@dataclass(frozen=True)
class SelectionDiagnostic:
    work_id: str
    quality_contribution: float
    nearest_selected_similarity: float | None
    marginal_determinant: float
    tie_break_rank: int


@dataclass(frozen=True)
class ExhibitionSelection:
    selected_ids: list[str]
    diagnostics: list[SelectionDiagnostic]


def _tie_break_rank(work_id: str, seed: int) -> int:
    digest = hashlib.sha256(f"{seed}:{work_id}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


def _validate_inputs(
    work_ids: Sequence[str],
    quality_scores: Mapping[str, float],
    embeddings: Mapping[str, Sequence[float]],
    subset_size: int,
) -> tuple[np.ndarray, np.ndarray]:
    if isinstance(subset_size, bool) or not isinstance(subset_size, int) or subset_size < 1:
        raise SubsetSizeError("subset_size must be a positive integer")
    if subset_size > len(work_ids):
        raise SubsetSizeError(f"subset_size {subset_size} exceeds candidate count {len(work_ids)}")
    if len(set(work_ids)) != len(work_ids):
        raise ExhibitionValidationError("work_ids must be unique")

    qualities: list[float] = []
    vectors: list[np.ndarray] = []
    dimension: int | None = None
    for work_id in work_ids:
        if work_id not in quality_scores or work_id not in embeddings:
            raise MissingEvidenceError(f"{work_id}: quality and embedding evidence are required")
        quality = float(quality_scores[work_id])
        if not math.isfinite(quality):
            raise NonFiniteEvidenceError(f"{work_id}: quality must be finite")
        if quality < 0:
            raise NegativeQualityError(f"{work_id}: quality must be non-negative")
        vector = np.asarray(embeddings[work_id], dtype=float)
        if vector.ndim != 1 or vector.size == 0:
            raise EmbeddingDimensionError(f"{work_id}: embedding must be a non-empty vector")
        if dimension is None:
            dimension = int(vector.size)
        elif vector.size != dimension:
            raise EmbeddingDimensionError(
                f"{work_id}: embedding dimension {vector.size} does not match {dimension}"
            )
        if not np.isfinite(vector).all():
            raise NonFiniteEvidenceError(f"{work_id}: embedding must contain only finite values")
        norm = float(np.linalg.norm(vector))
        if norm <= 0:
            raise EmbeddingDimensionError(f"{work_id}: embedding must have non-zero norm")
        qualities.append(quality)
        vectors.append(vector / norm)
    return np.asarray(qualities, dtype=float), np.vstack(vectors)


def select_quality_diverse(
    work_ids: Sequence[str],
    quality_scores: Mapping[str, float],
    embeddings: Mapping[str, Sequence[float]],
    subset_size: int,
    *,
    seed: int = 0,
) -> ExhibitionSelection:
    """Greedy MAP selection over ``L = diag(Q) @ D @ diag(Q)``.

    ``D`` is the Gram matrix of normalized caller-supplied embeddings. At each
    step the candidate producing the largest determinant is chosen. Exact
    determinant ties prefer greater quality, then a stable seeded SHA-256 rank;
    input order never decides a tie.
    """
    ids = list(work_ids)
    qualities, normalized = _validate_inputs(ids, quality_scores, embeddings, subset_size)
    diversity = normalized @ normalized.T
    kernel = np.diag(qualities) @ diversity @ np.diag(qualities)
    tie_ranks = [_tie_break_rank(work_id, seed) for work_id in ids]
    selected: list[int] = []
    diagnostics: list[SelectionDiagnostic] = []

    for _ in range(subset_size):
        scored: list[tuple[float, float, int, int, float]] = []
        for candidate in range(len(ids)):
            if candidate in selected:
                continue
            indices = [*selected, candidate]
            determinant = float(np.linalg.det(kernel[np.ix_(indices, indices)]))
            if abs(determinant) < 1e-12:
                determinant = 0.0
            scored.append(
                (
                    determinant,
                    float(qualities[candidate]),
                    -tie_ranks[candidate],
                    candidate,
                    determinant,
                )
            )
        _det, _quality, _tie, chosen, marginal = max(scored)
        nearest = (
            max(float(diversity[chosen, previous]) for previous in selected) if selected else None
        )
        selected.append(chosen)
        diagnostics.append(
            SelectionDiagnostic(
                work_id=ids[chosen],
                quality_contribution=float(qualities[chosen] ** 2),
                nearest_selected_similarity=nearest,
                marginal_determinant=marginal,
                tie_break_rank=tie_ranks[chosen],
            )
        )
    return ExhibitionSelection([ids[index] for index in selected], diagnostics)
