"""Focused boundary coverage for coverage-autopilot issue #816.

These tests deliberately exercise observable error and recovery paths rather
than using mocks merely to execute lines: each one pins a contract used by the
API, discovery pipeline, source-quality publisher, or filename parser.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fine_art_archive.api import main
from fine_art_archive.collect import discovery
from fine_art_archive.parsers import semantic
from fine_art_archive.quality import source_quality


def _entity(property_id: str, value: object) -> dict:
    return {
        "claims": {
            property_id: [{"mainsnak": {"snaktype": "value", "datavalue": {"value": value}}}]
        }
    }


def test_api_helpers_keep_paths_contained_and_make_validation_details_json_safe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    work_dir = tmp_path / "work"
    work_dir.mkdir()

    assert main._contained_master_filename(work_dir, "master.jpg") == work_dir / "master.jpg"
    with pytest.raises(main.HTTPException, match="escapes"):
        main._contained_master_filename(work_dir, "../outside.jpg")

    safe = main._json_safe(
        {"number": float("inf"), "error": ValueError("bad"), "list": [float("nan")]}
    )
    assert safe == {"number": "inf", "error": "bad", "list": ["nan"]}

    monkeypatch.setattr(main.store, "get_manifest_row", lambda _work_id: {"title": "Untitled"})
    assert main._manifest_placeholder_work("w-1") == {
        "work_id": "w-1",
        "title": "Untitled",
        "artist": {"name": "", "wikidata_q": ""},
        "year": "",
        "medium": "",
        "files": {"variants": []},
        "_sidecar_status": "missing",
        "_sidecar_message": "Metadata is not staged yet for this work.",
    }


def test_discovery_resolvers_preserve_each_source_failure_shape() -> None:
    commons = discovery._resolve_commons(
        _entity("P18", "bad.jpg"), lambda _url: {"query": {"pages": {"1": {}}}}
    )
    assert commons[0]["error"] == "Commons imageinfo missing"

    rijks = discovery._resolve_rijksmuseum(
        _entity("P350", "SK-A-1"),
        lambda _url: (_ for _ in ()).throw(discovery.DiscoveryFetchError("bad info")),
        lambda _url: '<meta property="og:image" content="https://iiif.micr.io/ABC/full.jpg">',
    )
    assert rijks == [{"source": "rijksmuseum", "error": "bad info"}]

    artic = discovery._resolve_artic(
        _entity("P9173", "42"), lambda _url: {"data": {"image_id": ""}}
    )
    assert artic == []

    artic_error = discovery._resolve_artic(
        _entity("P9173", "42"),
        lambda _url: (_ for _ in ()).throw(discovery.DiscoveryFetchError("offline")),
    )
    assert artic_error == [{"source": "artic", "error": "offline"}]


def test_source_quality_recovers_legacy_rows_and_rejects_non_finite_publish(
    tmp_path: Path,
) -> None:
    staging = tmp_path / "staging"
    legacy = staging / "legacy"
    legacy.mkdir(parents=True)
    (legacy / "meta.json").write_text(
        json.dumps({"work_id": "legacy", "category": "painting", "year": "1799"})
    )
    manifest = tmp_path / "manifest.csv"
    manifest.write_text("work_id,master_ingested_from\nlegacy,Meural/opaque.jpg\n")

    aggregates = source_quality.aggregate_sidecars(
        staging, manifest_csv=manifest, seed_priors_from_registry=False
    )
    assert aggregates["n_legacy_bucket_recovered"] == 1
    assert aggregates["archive_composition"]["legacy-meural"]["western-painting-pre1800"] == {
        "source": "legacy-meural",
        "work_class": "western-painting-pre1800",
        "n_acquired": 1,
        "first_seen": None,
        "last_seen": None,
    }

    out_path = tmp_path / "config" / "source_quality.yaml"
    out_path.parent.mkdir()
    out_path.write_text("preserved: true\n")
    invalid = {"sources": {"museum": {"painting": {"composite_score": float("nan")}}}}
    with pytest.raises(ValueError, match="composite_score must be finite"):
        source_quality.write_aggregates_atomically(invalid, out_path)
    assert out_path.read_text() == "preserved: true\n"


def test_source_quality_loads_empty_and_configured_prior_paths(tmp_path: Path) -> None:
    absent = tmp_path / "absent.yaml"
    assert source_quality.load_aggregates(absent) == {"sources": {}}
    assert source_quality._configured_tier_prior(
        {"tier_priors": {"2": {"verify_pass_rate": "0.8"}}}, 2
    ) == {"verify_pass_rate": 0.8}
    assert source_quality._record_blended_stats(
        {"host_tier": 2, "blended": {"verify_pass_rate": "0.7"}}, {}
    ) == {"verify_pass_rate": 0.7}


def test_source_quality_aggregate_tracks_observed_and_prior_metrics() -> None:
    aggregate = source_quality.SourceQualityAggregate(
        source="museum", work_class="western-painting-19c", host_tier=2
    )
    aggregate.add(
        source_quality.SignalRow(
            source="museum",
            work_class="western-painting-19c",
            work_id="w1",
            verify_match=True,
            attribution_match=False,
            link_alive=True,
            metadata_completeness=0.5,
            ts="2026-01-01T00:00:00Z",
        )
    )
    aggregate.add(
        source_quality.SignalRow(
            source="museum",
            work_class="western-painting-19c",
            work_id="w2",
            phash_match=True,
            aspect_match=True,
            dim_match=True,
            ts="2026-01-02T00:00:00+00:00",
        )
    )
    assert aggregate.empirical_stats() == {
        "verify_pass_rate": 1.0,
        "attribution_agreement": 0.0,
        "link_health_30d": 1.0,
        "metadata_completeness": 0.5,
    }
    assert aggregate.first_seen == "2026-01-01T00:00:00Z"
    assert aggregate.last_seen == "2026-01-02T00:00:00+00:00"
    assert aggregate.blended_stats(
        now=source_quality._parse_source_timestamp("2026-03-01T00:00:00Z")
    ) == {
        "verify_pass_rate": 1.0,
        "attribution_agreement": 0.0,
        "link_health_30d": 1.0,
        "metadata_completeness": 0.5,
    }


def test_source_quality_aggregate_ignores_bad_sidecars_and_seeds_host_priors(
    tmp_path: Path,
) -> None:
    staging = tmp_path / "staging"
    (staging / "empty").mkdir(parents=True)
    broken = staging / "broken"
    broken.mkdir()
    (broken / "meta.json").write_text("not json")
    host_registry = tmp_path / "hosts.yaml"
    host_registry.write_text("hosts:\n  institution:\n    source_tier: 2\n")

    aggregates = source_quality.aggregate_sidecars(staging, host_registry)

    assert aggregates["n_sidecars_scanned"] == 1
    assert aggregates["n_with_signals"] == 0
    assert aggregates["n_prior_only_rows"] == 3
    assert set(aggregates["sources"]["institution"]) == {
        "western-painting-pre1800",
        "western-painting-19c",
        "western-painting-modern",
    }


def test_semantic_corpus_and_comma_tie_breaks_are_deterministic(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(semantic, "_KNOWN_ARTISTS_FULL", set())
    monkeypatch.setattr(semantic, "_KNOWN_ARTISTS_SURNAMES", set())
    inventory = tmp_path / "inventory.csv"
    inventory.write_text("artist\nEugène Boudin\nEugène Boudin\nClaude Monet\n")
    assert semantic.load_known_artists(inventory, min_frequency=2)[0] >= 2
    assert semantic.matches_known_artist("Eugene Boudin") == "full"

    semantic._KNOWN_ARTISTS_FULL.update({"claude monet", "mary cassatt"})
    semantic._KNOWN_ARTISTS_SURNAMES.update({"monet", "cassatt"})
    # Same-tier, equally-confident candidates must use the documented last-piece rule.
    assert semantic._maybe_subsplit_fragment("Claude Monet, Mary Cassatt") == [
        "Claude Monet",
        "Mary Cassatt",
    ]

    no_artist = semantic.parse_semantic("a quiet landscape; 1890")
    assert no_artist.notes == ["no artist identified — title may be misclassified"]
    low_confidence = semantic.parse_semantic("a title; Giotto")
    assert low_confidence.artist == "Giotto"
    assert low_confidence.notes == ["low artist confidence (0.55)"]


def test_semantic_classifiers_keep_structural_fields_out_of_artist_slots() -> None:
    assert semantic.looks_like_dimensions("100 x 80")[1] == 0.70
    assert semantic.looks_like_dimensions("not dimensions") == (False, 0.0, "")
    assert semantic.looks_like_medium("oil on canvas, mounted")[1] == 0.85
    assert semantic.looks_like_name("lower case name") == (False, 0.0, "")
    assert semantic._maybe_subsplit_fragment("A title, 1890") == ["A title", "1890"]
    assert semantic._maybe_subsplit_fragment("title, another title") == ["title, another title"]
