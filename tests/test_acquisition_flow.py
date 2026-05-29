"""Tests for the acquisition-flow orchestration (src/fine_art_archive/collect/acquisition_flow.py).

Network fetch lives in the collectors' shell scripts (run operationally); these
tests cover the pure glue — source registry/validation, discovery-script
passthrough, and the verify+quality assessment over synthetic masters.
"""

from __future__ import annotations

import json
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


def test_run_acquisition_flow_unknown_source(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="unknown source"):
        af.run_acquisition_flow("nope", [tmp_path])
