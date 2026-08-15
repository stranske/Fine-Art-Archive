"""Deterministic quality-times-diversity selection for small exhibitions.

The selector deliberately accepts already-computed embeddings.  Playlist
selection should not import torch, load a model, or silently make a fresh
similarity claim; the caller owns the versioned embedding evidence.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class ExhibitionSelection:
    """A selected order plus evidence that makes the trade-off inspectable."""

    work_ids: list[str]
    diagnostics: dict[str, object]


def _tie_break(seed: int, work_id: str) -> str:
    return hashlib.sha256(f"{seed}:{work_id}".encode()).hexdigest()


def _validated_inputs(
    work_ids: Sequence[str],
    quality_scores: Sequence[float],
    embeddings: Sequence[Sequence[float]],
    subset_size: int,
) -> tuple[list[str], np.ndarray, np.ndarray]:
    ids = list(work_ids)
    if not ids:
        raise ValueError("exhibition selection requires at least one candidate")
    if len(set(ids)) != len(ids):
        raise ValueError("exhibition selection requires unique work IDs")
    if subset_size < 1:
        raise ValueError("exhibition subset size must be at least one")
    if subset_size > len(ids):
        raise ValueError("exhibition subset size cannot exceed the candidate set")
    if len(quality_scores) != len(ids) or len(embeddings) != len(ids):
        raise ValueError("work IDs, quality scores, and embeddings must have equal lengths")

    quality = np.asarray(quality_scores, dtype=float)
    if quality.ndim != 1 or not np.isfinite(quality).all():
        raise ValueError("exhibition quality scores must be finite numbers")
    if (quality < 0).any():
        raise ValueError("exhibition quality scores must be non-negative")

    try:
        vectors = np.asarray(embeddings, dtype=float)
    except ValueError as exc:
        raise ValueError("exhibition embeddings must be a non-empty rectangular matrix") from exc
    if vectors.ndim != 2 or vectors.shape[0] != len(ids) or vectors.shape[1] == 0:
        raise ValueError("exhibition embeddings must be a non-empty rectangular matrix")
    if not np.isfinite(vectors).all():
        raise ValueError("exhibition embeddings must contain only finite numbers")
    norms = np.linalg.norm(vectors, axis=1)
    if (norms == 0).any():
        raise ValueError("exhibition embeddings must not contain a zero vector")
    return ids, quality, vectors / norms[:, None]


def select_quality_diverse(
    work_ids: Sequence[str],
    quality_scores: Sequence[float],
    embeddings: Sequence[Sequence[float]],
    subset_size: int,
    *,
    seed: int = 42,
) -> ExhibitionSelection:
    """Select a deterministic MAP-style subset from ``L = diag(Q) D diag(Q)``.

    ``D`` is an RBF kernel over normalized embeddings, so it is positive
    semidefinite and close visual duplicates suppress each other's conditional
    gain.  Greedy conditional variance maximization is the bounded, transparent
    approximation used here instead of stochastic DPP sampling.
    """
    ids, quality, unit_embeddings = _validated_inputs(
        work_ids, quality_scores, embeddings, subset_size
    )
    maximum = float(quality.max())
    # All-zero evidence should still be a deterministic diversity selection;
    # use equal quality rather than manufacture a quality ordering.
    normalized_quality = np.ones_like(quality) if maximum == 0 else quality / maximum
    distances_sq = np.maximum(
        0.0, 2.0 - 2.0 * np.clip(unit_embeddings @ unit_embeddings.T, -1.0, 1.0)
    )
    diversity = np.exp(-distances_sq / 2.0)
    kernel = normalized_quality[:, None] * diversity * normalized_quality[None, :]

    selected: list[int] = []
    conditional_gains = np.diag(kernel).copy()
    for _ in range(subset_size):
        candidates = [i for i in range(len(ids)) if i not in selected]
        best = min(
            candidates,
            key=lambda i: (-round(float(conditional_gains[i]), 12), _tie_break(seed, ids[i])),
        )
        selected.append(best)
        selected_kernel = kernel[np.ix_(selected, selected)]
        for candidate in candidates:
            if candidate in selected:
                continue
            cross = kernel[candidate, selected]
            try:
                solved = np.linalg.solve(selected_kernel, cross)
                conditional_gains[candidate] = max(
                    0.0, float(kernel[candidate, candidate] - cross @ solved)
                )
            except np.linalg.LinAlgError:
                # Exact duplicate vectors may make a principal minor singular.
                # Their zero conditional variance is precisely the diversity
                # signal we need, so keep selection deterministic and safe.
                conditional_gains[candidate] = 0.0

    selected_ids = [ids[i] for i in selected]
    selected_diagnostics = []
    for position, index in enumerate(selected):
        earlier = selected[:position]
        nearest = max((float(diversity[index, other]) for other in earlier), default=None)
        selected_diagnostics.append(
            {
                "work_id": ids[index],
                "quality": float(quality[index]),
                "normalized_quality": float(normalized_quality[index]),
                "quality_contribution": float(normalized_quality[index] ** 2),
                "nearest_selected_similarity": nearest,
                "tie_break": _tie_break(seed, ids[index]),
            }
        )
    return ExhibitionSelection(
        work_ids=selected_ids,
        diagnostics={
            "mode": "preference-diverse",
            "kernel": "L = diag(Q) D diag(Q); D = RBF(normalized embeddings)",
            "seed": seed,
            "selected": selected_diagnostics,
        },
    )
