"""Source-quality scoring subsystem.

Per-source, per-work-class reliability scores that the acquisition
orchestrator consults when more than one source could provide the same
work. See `source_quality_design.md` for the full design.
"""

from .source_quality import (
    DEFAULT_TIER_PRIORS,
    SignalRow,
    SourceQualityAggregate,
    aggregate_sidecars,
    composite_score,
    extract_signals,
    load_aggregates,
    score_for,
    write_aggregates,
)

__all__ = [
    "DEFAULT_TIER_PRIORS",
    "SignalRow",
    "SourceQualityAggregate",
    "aggregate_sidecars",
    "composite_score",
    "extract_signals",
    "load_aggregates",
    "score_for",
    "write_aggregates",
]
