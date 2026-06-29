"""Tests for fine_art_archive.quality.source_quality."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from fine_art_archive.quality.source_quality import (
    COMPOSITE_WEIGHTS,
    CONFIDENCE_FLOOR_WEIGHT,
    DEFAULT_TIER_PRIORS,
    WARMUP_DAYS,
    SignalRow,
    SourceQualityAggregate,
    _infer_work_class,
    aggregate_sidecars,
    composite_score,
    extract_signals,
    score_for,
)


def test_composite_formula_matches_design():
    stats = DEFAULT_TIER_PRIORS[1]
    s = composite_score(stats, n_acquired=10)
    expected = (
        COMPOSITE_WEIGHTS["verify_pass_rate"] * 0.95
        + COMPOSITE_WEIGHTS["attribution_agreement"] * 0.95
        + COMPOSITE_WEIGHTS["link_health_30d"] * 0.98
        + COMPOSITE_WEIGHTS["metadata_completeness"] * 0.85
        + CONFIDENCE_FLOOR_WEIGHT * 1.0
    )
    assert s == pytest.approx(expected, abs=1e-9)


def test_composite_confidence_floor_partial():
    stats = DEFAULT_TIER_PRIORS[1]
    s0 = composite_score(stats, n_acquired=0)
    s5 = composite_score(stats, n_acquired=5)
    s10 = composite_score(stats, n_acquired=10)
    assert s0 < s5 < s10
    assert s10 - s0 == pytest.approx(CONFIDENCE_FLOOR_WEIGHT, abs=1e-9)


def test_composite_score_respects_empty_weight_override():
    assert composite_score(DEFAULT_TIER_PRIORS[1], n_acquired=0, weights={}) == 0.0


def test_verify_pass_all_gates_required():
    row = SignalRow(
        source="met",
        work_class="x",
        work_id="w",
        phash_match=True,
        aspect_match=True,
        dim_match=True,
    )
    assert row.verify_pass is True
    row = SignalRow(
        source="met",
        work_class="x",
        work_id="w",
        phash_match=True,
        aspect_match=False,
        dim_match=True,
    )
    assert row.verify_pass is False
    row = SignalRow(source="met", work_class="x", work_id="w")
    assert row.verify_pass is None


def test_verify_match_overrides_legacy_gate_rollup():
    row = SignalRow(
        source="met",
        work_class="x",
        work_id="w",
        verify_match=True,
        phash_match=False,
        aspect_match=True,
    )
    assert row.verify_pass is True


def test_aggregate_basic_counts():
    agg = SourceQualityAggregate(source="met", work_class="painting", host_tier=1)
    rows = [
        SignalRow(
            "met",
            "painting",
            "w1",
            phash_match=True,
            aspect_match=True,
            attribution_match=True,
            link_alive=True,
            metadata_completeness=0.9,
            ts="2026-05-20T00:00:00+00:00",
        ),
        SignalRow(
            "met",
            "painting",
            "w2",
            phash_match=True,
            aspect_match=False,
            attribution_match=True,
            link_alive=True,
            metadata_completeness=0.6,
            ts="2026-05-21T00:00:00+00:00",
        ),
    ]
    for r in rows:
        agg.add(r)
    e = agg.empirical_stats()
    assert agg.n_acquired == 2
    assert e["verify_pass_rate"] == 0.5  # 1 of 2 passes all gates
    assert e["attribution_agreement"] == 1.0
    assert e["link_health_30d"] == 1.0
    assert e["metadata_completeness"] == pytest.approx(0.75)


def test_blended_stats_warmup_window():
    agg = SourceQualityAggregate(source="met", work_class="painting", host_tier=1)
    # Single row from 1 day ago — empirical weight ≈ 1/30
    just_now = datetime.now(UTC) - timedelta(days=1)
    agg.add(
        SignalRow(
            "met",
            "painting",
            "w1",
            phash_match=False,
            aspect_match=False,
            dim_match=False,
            attribution_match=False,
            link_alive=False,
            metadata_completeness=0.0,
            ts=just_now.isoformat(timespec="seconds"),
        )
    )
    blended = agg.blended_stats()
    prior = DEFAULT_TIER_PRIORS[1]
    # Should still be near the prior since we're at 1/30 weight
    assert blended["verify_pass_rate"] > 0.5 * prior["verify_pass_rate"]
    # Far below prior since empirical was 0
    assert blended["verify_pass_rate"] < prior["verify_pass_rate"]


def test_blended_stats_after_warmup():
    agg = SourceQualityAggregate(source="met", work_class="painting", host_tier=1)
    long_ago = datetime.now(UTC) - timedelta(days=WARMUP_DAYS + 1)
    agg.add(
        SignalRow(
            "met",
            "painting",
            "w1",
            phash_match=False,
            aspect_match=False,
            dim_match=False,
            attribution_match=False,
            link_alive=False,
            metadata_completeness=0.0,
            ts=long_ago.isoformat(timespec="seconds"),
        )
    )
    blended = agg.blended_stats()
    # After warmup, no prior weight — empirical dominates (all zeros)
    assert blended["verify_pass_rate"] == pytest.approx(0.0)


def test_infer_work_class_year_buckets():
    assert _infer_work_class({"category": "painting", "year": "1500"}) == "western-painting-pre1800"
    assert _infer_work_class({"category": "painting", "year": "1850"}) == "western-painting-19c"
    assert _infer_work_class({"category": "painting", "year": "1950"}) == "western-painting-modern"
    assert _infer_work_class({"category": "painting"}) == "western-painting-unknown-period"
    assert _infer_work_class({"category": "photograph", "year": "2020"}) == "photograph"
    assert _infer_work_class({"category": "sculpture"}) == "sculpture"
    # Range form like "1495:1498"
    assert (
        _infer_work_class({"category": "painting", "year": "1495:1498"})
        == "western-painting-pre1800"
    )


def test_extract_signals_legacy_path_recovery():
    meta = {
        "work_id": "abc1234-foo",
        "category": "painting",
        "year": "1850",
        "files": {"master": {"filename": "master.jpeg"}},  # ingested_from popped
    }
    # No data anywhere — None
    assert extract_signals(meta) is None
    # Recovered via the manifest-style lookup
    row = extract_signals(meta, legacy_bucket_lookup={"abc1234-foo": "Landscape/foo.jpeg"})
    assert row is not None
    assert row.source == "legacy-landscape"
    assert row.work_class == "western-painting-19c"


def test_extract_signals_real_source_with_signals():
    meta = {
        "work_id": "real-1",
        "category": "painting",
        "year": "1880",
        "files": {"master": {"ingested_at": "2026-05-20T00:00:00+00:00"}},
        "acquisition_provenance": {"source": "met", "ts": "2026-05-20T00:00:00+00:00"},
        "verification": {
            "source_quality_inputs": {
                "phash_match": True,
                "aspect_match": True,
                "dim_match": True,
                "attribution_match": True,
                "link_alive": True,
                "metadata_completeness": 0.92,
            }
        },
    }
    row = extract_signals(meta)
    assert row.source == "met"
    assert row.work_class == "western-painting-19c"
    assert row.verify_pass is True
    assert row.attribution_match is True


def test_aggregate_sidecars_separates_real_vs_legacy(tmp_path: Path):
    staging = tmp_path / "staging_sidecars"
    staging.mkdir()
    # legacy bucket sidecar
    (staging / "abc1234-foo").mkdir()
    (staging / "abc1234-foo" / "meta.json").write_text(
        json.dumps(
            {
                "work_id": "abc1234-foo",
                "category": "painting",
                "year": "1850",
                "files": {"master": {"ingested_from": "Landscape/foo.jpeg"}},
            }
        )
    )
    # real source sidecar
    (staging / "real-1").mkdir()
    (staging / "real-1" / "meta.json").write_text(
        json.dumps(
            {
                "work_id": "real-1",
                "category": "painting",
                "year": "1880",
                "files": {"master": {"ingested_at": "2026-05-20T00:00:00+00:00"}},
                "acquisition_provenance": {"source": "met", "ts": "2026-05-20T00:00:00+00:00"},
                "verification": {
                    "source_quality_inputs": {
                        "phash_match": True,
                        "aspect_match": True,
                        "dim_match": True,
                        "attribution_match": True,
                        "link_alive": True,
                        "metadata_completeness": 0.92,
                    }
                },
            }
        )
    )
    # Use a host_registry path that doesn't exist — should not crash
    aggs = aggregate_sidecars(
        staging, host_registry_path=tmp_path / "nope.yaml", seed_priors_from_registry=False
    )
    assert "met" in aggs["sources"]
    assert "legacy-landscape" in aggs["archive_composition"]
    # Legacy entries should not have a composite_score key
    leg = aggs["archive_composition"]["legacy-landscape"]
    wc_entry = next(iter(leg.values()))
    assert "composite_score" not in wc_entry
    assert wc_entry["n_acquired"] == 1
    # Real entries should
    met_entry = next(iter(aggs["sources"]["met"].values()))
    assert "composite_score" in met_entry


def test_score_for_falls_back_to_prior_when_unknown():
    s = score_for("never-seen-source", "western-painting-19c", aggregates={"sources": {}})
    expected = composite_score(DEFAULT_TIER_PRIORS[1], n_acquired=0)
    assert s == pytest.approx(expected, abs=1e-9)
