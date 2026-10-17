"""Tests for the acquisition-flow orchestration (src/fine_art_archive/collect/acquisition_flow.py).

Network fetch lives in the collectors' shell scripts (run operationally); these
tests cover the pure glue — source registry/validation, discovery-script
passthrough, and the verify+quality assessment over synthetic masters.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from fine_art_archive.collect import acquisition_flow as af


def _work(dirp: Path, w: int = 800, h: int = 600, h_cm: float = 60.0, w_cm: float = 80.0) -> Path:
    dirp.mkdir(parents=True, exist_ok=True)
    _make_jpeg(dirp / "master.jpg", w, h)
    (dirp / "meta.json").write_text(
        json.dumps({"dimensions_original": {"h_cm": h_cm, "w_cm": w_cm}})
    )
    return dirp


def _make_jpeg(path: Path, w: int, h: int) -> None:
    from PIL import Image

    # A non-uniform image so quality metrics (fft/laplacian) are well-defined.
    img = Image.new("RGB", (w, h))
    px = img.load()
    for y in range(h):
        for x in range(w):
            px[x, y] = (x % 256, y % 256, (x + y) % 256)
    img.save(path, "JPEG", quality=88)


def test_get_collector_known_and_unknown() -> None:
    for s in ["met", "rijksmuseum", "cleveland", "artic", "google_arts_culture"]:
        assert af.get_collector(s) is not None
    with pytest.raises(ValueError, match="unknown source"):
        af.get_collector("louvre")


def test_plan_discovery_returns_script() -> None:
    script = af.plan_discovery("Q12418", "/tmp/discovery.json")
    assert "Q12418" in script
    assert "set -e" in script


def test_assess_master_populates_sections(tmp_path: Path) -> None:
    work = _work(tmp_path / "abc1234-mona-lisa")
    a = af.assess_master(work / "master.jpg", source="met", h_cm=60.0, w_cm=80.0)
    assert a.source == "met"
    assert a.work_dir == work
    assert "status" in a.verification
    assert isinstance(a.quality, dict)
    assert isinstance(a.fitness, dict) and a.fitness  # at least one device scored


@pytest.mark.parametrize(
    "missing_reference", [False, True], ids=["no-reference", "missing-reference"]
)
@pytest.mark.parametrize("catalogue_matches", [True, False], ids=["upright-match", "raw-size-trap"])
def test_assess_master_checks_exif_orientation_without_reference(
    tmp_path: Path, missing_reference: bool, catalogue_matches: bool
) -> None:
    """Missing hash references must not change the aspect identity decision."""
    from PIL import Image

    master = tmp_path / "master.jpg"
    exif = Image.Exif()
    exif[274] = 6  # Stored landscape pixels display as a portrait.
    Image.new("RGB", (120, 80), "navy").save(master, exif=exif)
    reference = tmp_path / "absent.jpg" if missing_reference else None
    h_cm, w_cm = (30.0, 20.0) if catalogue_matches else (20.0, 30.0)

    assessment = af.assess_master(
        master, source="met", h_cm=h_cm, w_cm=w_cm, reference_path=reference
    )

    expected_status = "PASS" if catalogue_matches else "FAIL"
    assert assessment.verification["status"] == expected_status
    [aspect] = assessment.verification["checks"]
    assert aspect["name"] == "aspect_ratio"
    assert aspect["status"] == expected_status
    assert aspect["detail"]["px_aspect"] == 1.5
    assert assessment.quality
    assert assessment.fitness


def test_run_acquisition_flow_batch_and_cap(tmp_path: Path) -> None:
    dirs = [_work(tmp_path / f"w{i}") for i in range(3)]
    results = af.run_acquisition_flow("met", dirs)
    assert len(results) == 3
    assert all(r.source == "met" for r in results)

    capped = af.run_acquisition_flow("met", dirs, max_items=1)
    assert len(capped) == 1


def test_run_acquisition_flow_skips_missing_master(tmp_path: Path) -> None:
    good = _work(tmp_path / "good")
    empty = tmp_path / "empty"
    empty.mkdir()
    results = af.run_acquisition_flow("artic", [good, empty])
    assert len(results) == 1  # the master-less dir is skipped


def test_run_acquisition_flow_continues_after_corrupt_meta(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    corrupt = _work(tmp_path / "corrupt")
    valid = _work(tmp_path / "valid")
    (corrupt / "meta.json").write_text("{not valid json")

    with caplog.at_level(logging.WARNING, logger=af.__name__):
        results = af.run_acquisition_flow("met", [corrupt, valid])

    assert len(results) == 2
    assert {result.work_dir.name for result in results} == {"corrupt", "valid"}
    assert any(
        "continuing with empty metadata" in record.message
        and str(corrupt / "meta.json") in record.message
        and "Expecting property name" in record.message
        for record in caplog.records
    )


def test_run_acquisition_flow_unknown_source(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown source"):
        af.run_acquisition_flow("nope", [tmp_path])


@pytest.mark.parametrize(
    "payload", [None, ["unexpected"], "unexpected", 42], ids=["null", "array", "string", "number"]
)
def test_run_acquisition_flow_continues_after_non_object_meta(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, payload: object
) -> None:
    invalid = _work(tmp_path / "invalid")
    valid = _work(tmp_path / "valid")
    (invalid / "meta.json").write_text(json.dumps(payload))

    with caplog.at_level(logging.WARNING, logger=af.__name__):
        results = af.run_acquisition_flow("met", [invalid, valid])

    assert [result.work_dir for result in results] == [invalid, valid]
    assert [result.verification["status"] for result in results] == ["UNVERIFIED", "PASS"]
    assert all(result.quality and result.fitness for result in results)
    [warning] = [record for record in caplog.records if record.name == af.__name__]
    assert str(invalid / "meta.json") in warning.message
    assert "continuing with empty metadata" in warning.message
    assert "JSON object" in warning.message


@pytest.mark.parametrize(
    "dimensions", [[60, 80], "60 x 80", 60, True], ids=["array", "string", "number", "boolean"]
)
def test_run_acquisition_flow_recovers_non_object_dimensions(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, dimensions: object
) -> None:
    invalid = _work(tmp_path / "invalid", w=80, h=60)
    valid = _work(tmp_path / "valid", w=80, h=60)
    (invalid / "meta.json").write_text(
        json.dumps(
            {
                "title": "Paris Street",
                "artist": {"name": "Gustave Caillebotte"},
                "dimensions_original": dimensions,
            }
        )
    )
    inventory = tmp_path / "inventory.csv"
    inventory.write_text(
        "rel_path,size_bytes,title,artist\n" "Paris.jpeg,1000,Paris Street,Gustave Caillebotte\n"
    )

    with caplog.at_level(logging.WARNING, logger=af.__name__):
        results = af.run_acquisition_flow("met", [invalid, valid], inventory_csv=inventory)

    assert [result.work_dir for result in results] == [invalid, valid]
    assert [result.verification["status"] for result in results] == ["UNVERIFIED", "PASS"]
    assert all(result.quality and result.fitness for result in results)
    # Recover only dimensions: title/artist must still participate in deduplication.
    assert results[0].inventory_match is not None
    assert results[0].inventory_match.has_strong_match
    assert results[1].inventory_match is not None
    assert not results[1].inventory_match.has_strong_match
    [warning] = [record for record in caplog.records if record.name == af.__name__]
    assert str(invalid / "meta.json") in warning.message
    assert "dimensions_original" in warning.message
    assert "JSON object" in warning.message


def test_run_acquisition_flow_selects_candidate_source_by_scores(tmp_path: Path) -> None:
    work = _work(tmp_path / "w0")
    aggregates = {
        "sources": {
            "rijksmuseum": {"western-painting-19c": {"composite_score": 0.90}},
            "met": {"western-painting-19c": {"composite_score": 0.70}},
        }
    }
    results = af.run_acquisition_flow(
        "met",
        [work],
        candidate_sources=["met", "rijksmuseum"],
        work_class="western-painting-19c",
        aggregates=aggregates,
    )
    assert len(results) == 1
    assert results[0].source == "rijksmuseum"


def test_run_acquisition_flow_ignores_empty_candidate_sources(tmp_path: Path) -> None:
    work = _work(tmp_path / "w0")
    results = af.run_acquisition_flow("met", [work], candidate_sources=[])
    assert len(results) == 1
    assert results[0].source == "met"
