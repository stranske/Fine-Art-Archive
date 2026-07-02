"""Load-bearing source-quality routing tests."""

from __future__ import annotations

import math
from pathlib import Path

import pytest
import yaml

from fine_art_archive.collect import acquisition_flow as af
from fine_art_archive.collect.verify import verify
from fine_art_archive.quality.source_quality import _infer_work_class


def _make_work(dirp: Path) -> Path:
    from PIL import Image

    dirp.mkdir(parents=True)
    Image.new("RGB", (120, 90), "white").save(dirp / "master.jpg", "JPEG")
    (dirp / "meta.json").write_text('{"dimensions_original":{"h_cm":9,"w_cm":12}}')
    return dirp


def _write_quality_config(path: Path, *, met: float, rijksmuseum: float) -> None:
    data = {
        "schema_version": "1.0",
        "warmup_days": 30,
        "composite_weights": {
            "verify_pass_rate": 1.0,
            "attribution_agreement": 0.0,
            "link_health_30d": 0.0,
            "metadata_completeness": 0.0,
        },
        "confidence_floor_weight": 0.0,
        "sources": {
            "met": {
                "western-painting-19c": {
                    "n_acquired": 10,
                    "blended": {
                        "verify_pass_rate": met,
                        "attribution_agreement": 0.0,
                        "link_health_30d": 0.0,
                        "metadata_completeness": 0.0,
                    },
                    "composite_score": 0.01,
                }
            },
            "rijksmuseum": {
                "western-painting-19c": {
                    "n_acquired": 10,
                    "blended": {
                        "verify_pass_rate": rijksmuseum,
                        "attribution_agreement": 0.0,
                        "link_health_30d": 0.0,
                        "metadata_completeness": 0.0,
                    },
                    "composite_score": 0.01,
                }
            },
        },
    }
    path.write_text(yaml.safe_dump(data, sort_keys=False))


def test_source_quality_yaml_drives_candidate_routing(tmp_path: Path) -> None:
    work = _make_work(tmp_path / "work")
    quality_config = tmp_path / "source_quality.yaml"

    _write_quality_config(quality_config, met=0.30, rijksmuseum=0.95)
    [first] = af.run_acquisition_flow(
        "met",
        [work],
        candidate_sources=["met", "rijksmuseum"],
        source_quality_path=quality_config,
    )
    assert first.source == "rijksmuseum"

    _write_quality_config(quality_config, met=0.95, rijksmuseum=0.30)
    [second] = af.run_acquisition_flow(
        "met",
        [work],
        candidate_sources=["met", "rijksmuseum"],
        source_quality_path=quality_config,
    )
    assert second.source == "met"


def test_source_quality_routing_normalizes_source_aliases() -> None:
    aggregates = {
        "sources": {
            "cleveland": {"western-painting-19c": {"composite_score": 0.95}},
            "met": {"western-painting-19c": {"composite_score": 0.20}},
        }
    }

    selected, _reason = af.select_source(
        "western-painting-19c",
        ["met", "cleveland_museum_of_art"],
        aggregates,
    )

    assert selected == "cleveland_museum_of_art"


def test_source_quality_routing_prefers_configured_host_id_before_alias() -> None:
    aggregates = {
        "sources": {
            "cleveland_museum_of_art": {
                "western-painting-19c": {
                    "n_acquired": 10,
                    "blended": {
                        "verify_pass_rate": 0.05,
                        "attribution_agreement": 0.0,
                        "link_health_30d": 0.0,
                        "metadata_completeness": 0.0,
                    },
                    "composite_score": 0.05,
                }
            },
            "met": {"western-painting-19c": {"composite_score": 0.80}},
        }
    }

    selected, _reason = af.select_source(
        "western-painting-19c",
        ["met", "cleveland_museum_of_art"],
        aggregates,
    )

    assert selected == "met"


def test_nan_composite_score_cannot_win() -> None:
    aggregates = {
        "sources": {
            "met": {"western-painting-19c": {"composite_score": math.nan}},
            "rijksmuseum": {"western-painting-19c": {"composite_score": 0.50}},
        }
    }
    assert af.select_source("western-painting-19c", ["met", "rijksmuseum"], aggregates)[0] == (
        "rijksmuseum"
    )


@pytest.mark.parametrize("year", ["1800.0", "circa 1800", "1800?"])
def test_infer_work_class_parses_fuzzy_years(year: str) -> None:
    assert _infer_work_class({"category": "painting", "year": year}) == "western-painting-19c"


def test_verify_threads_aspect_threshold() -> None:
    report = verify(h_cm=10.0, w_cm=10.0, h_px=1000, w_px=1100, aspect_threshold=0.10)
    check = next(item for item in report.checks if item.name == "aspect_ratio")
    assert check.status == "PASS"
    assert check.detail["threshold"] == 0.10


def test_host_registry_chain_drives_candidate_routing(tmp_path: Path) -> None:
    work = _make_work(tmp_path / "work")
    quality_config = tmp_path / "source_quality.yaml"
    registry = tmp_path / "host_registry.yaml"
    _write_quality_config(quality_config, met=0.20, rijksmuseum=0.95)
    registry.write_text(
        yaml.safe_dump(
            {
                "hosts": {
                    "met": {
                        "wikidata_q": "Q160236",
                        "primary_acquisition": {"adapter": "met"},
                        "fallback_chain": ["rijksmuseum"],
                    }
                }
            },
            sort_keys=False,
        )
    )

    [result] = af.run_acquisition_flow(
        "met",
        [work],
        host_qid="Q160236",
        source_quality_path=quality_config,
        host_registry_path=registry,
    )

    assert result.source == "rijksmuseum"


def test_host_registry_qid_without_source_chain_fails_loudly(tmp_path: Path) -> None:
    work = _make_work(tmp_path / "work")
    registry = tmp_path / "host_registry.yaml"
    registry.write_text(
        yaml.safe_dump(
            {
                "hosts": {
                    "unsupported": {
                        "wikidata_q": "Q999",
                        "primary_acquisition": {},
                        "fallback_chain": [],
                    }
                }
            },
            sort_keys=False,
        )
    )

    with pytest.raises(ValueError, match="no acquisition source chain"):
        af.run_acquisition_flow("met", [work], host_qid="Q999", host_registry_path=registry)
