"""Deterministic render-strategy selection from gamut-fit verdicts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .gamut import GamutFit

RenderStrategyName = Literal["color", "grayscale", "duotone"]

_DEFAULT_POLICY: dict[str, RenderStrategyName] = {
    "well-served": "color",
    "compromised": "duotone",
    "poorly-served": "grayscale",
}


@dataclass(frozen=True)
class RenderStrategyChoice:
    strategy: RenderStrategyName
    reason: str


def choose_render_strategy(
    fit: GamutFit,
    policy: dict[str, RenderStrategyName] | None = None,
) -> RenderStrategyChoice:
    """Map a gamut verdict to an explicit color/grayscale/duotone strategy."""
    mapping = dict(_DEFAULT_POLICY)
    if policy:
        mapping.update(policy)
    verdict = fit.verdict
    strategy = mapping.get(verdict)
    if strategy is None:
        raise ValueError(f"unsupported gamut verdict for render strategy: {verdict!r}")
    return RenderStrategyChoice(
        strategy=strategy,
        reason=f"gamut verdict {verdict}",
    )
