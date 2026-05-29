"""Tests for the display-quality measurement module."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fine_art_archive.collect.quality import (  # noqa: E402
    DEVICE_THRESHOLDS,
    QualityReport,
    assess_fitness,
    quality_report,
)

# Use the Vermeer Little Street sample as a known-good fixture.
SAMPLE = Path(__file__).resolve().parents[1] / "samples" / "0441b1c-the-little-street-vermeer"
MASTER = SAMPLE / "master.jpg"
NEGATIVE = SAMPLE / "resources" / "_negative_qkogy_milkmaid.jpg"


def _require_master():
    if not MASTER.exists():
        pytest.skip("Vermeer sample master.jpg not present")


# ---------------------------------------------------------------------------
# Real measurements on the Vermeer master
# ---------------------------------------------------------------------------


def test_vermeer_resolution_metrics():
    _require_master()
    r = quality_report(MASTER, h_cm=54.3, w_cm=44.0)
    assert r.long_edge_px == 6344
    assert r.short_edge_px == 5190
    # 6344 / 54.3 ≈ 116.8 px/cm
    assert r.px_per_cm_long is not None
    assert 110 < r.px_per_cm_long < 125
    # 5190 × 6344 ≈ 32.9 MP
    assert 32.0 < r.pixel_area_mp < 33.5


def test_vermeer_bytes_per_megapixel():
    _require_master()
    r = quality_report(MASTER, h_cm=54.3, w_cm=44.0)
    # 7.95 MB / 32.9 MP ≈ 242 KB/MP
    assert 200_000 < r.bytes_per_megapixel < 280_000


def test_vermeer_passes_fitness_for_all_consumer_displays():
    _require_master()
    r = quality_report(MASTER, h_cm=54.3, w_cm=44.0)
    # The 32.9 MP master should be fit for every display target we ship.
    for dev in [
        "inkposter_tela_28_5",
        "hisense_canvastv",
        "samsung_frame",
        "pimoroni_inky_13_3",
        "meural_landscape",
        "meural_portrait",
    ]:
        assert r.fitness[dev] in ("fit", "borderline"), f"{dev} unfit: {r.fitness[dev]}"


def test_vermeer_fft_signal_is_real_not_upscaled():
    _require_master()
    r = quality_report(MASTER, h_cm=54.3, w_cm=44.0)
    # Real high-res scans of paintings produce fft_highfreq_ratio in the
    # ~0.004-0.008 range when measured on the 1024-downscaled version.
    # The threshold for "suspected upscale" is 0.0010; we should be well above.
    assert r.fft_highfreq_ratio > 0.0020


def test_vermeer_laplacian_indicates_sharpness():
    _require_master()
    r = quality_report(MASTER, h_cm=54.3, w_cm=44.0)
    # Vermeer's fine detail should produce non-trivial Laplacian variance.
    assert r.laplacian_variance > 100


# ---------------------------------------------------------------------------
# Fitness assessment unit tests (independent of any real file)
# ---------------------------------------------------------------------------


def test_fitness_fit_for_high_quality_synthetic():
    # Values calibrated against the Vermeer master measurements; long edge
    # exceeds archival_a2_print's 7016 minimum.
    r = QualityReport(
        long_edge_px=8000,
        short_edge_px=6000,
        pixel_area_mp=48.0,
        px_per_cm_long=120.0,
        bytes_per_megapixel=250_000,
        icc_profile_present=True,
        jpeg_quality_factor=92,
        laplacian_variance=1000.0,
        fft_highfreq_ratio=0.005,
    )
    f = assess_fitness(r)
    for dev, status in f.items():
        assert status in ("fit", "borderline"), f"{dev}: {status}"


def test_fitness_unfit_for_low_resolution():
    r = QualityReport(
        long_edge_px=800,
        short_edge_px=600,
        pixel_area_mp=0.48,
        jpeg_quality_factor=90,
        fft_highfreq_ratio=0.005,
    )
    f = assess_fitness(r, devices=["inkposter_tela_28_5", "hisense_canvastv"])
    assert f["inkposter_tela_28_5"] == "unfit"
    assert f["hisense_canvastv"] == "unfit"


def test_fitness_unfit_for_suspected_upscale():
    r = QualityReport(
        long_edge_px=4000,
        short_edge_px=3000,
        pixel_area_mp=12.0,
        jpeg_quality_factor=90,
        fft_highfreq_ratio=0.0005,  # extremely low — upscale signature
    )
    f = assess_fitness(r, devices=["inkposter_tela_28_5", "meural_landscape"])
    # InkPoster threshold for fft is 0.0015; 0.0005 fails.
    assert f["inkposter_tela_28_5"] == "unfit"
    # Meural threshold is 0.0010; 0.0005 fails.
    assert f["meural_landscape"] == "unfit"


def test_fitness_unfit_for_low_jpeg_q():
    r = QualityReport(
        long_edge_px=4000,
        short_edge_px=3000,
        pixel_area_mp=12.0,
        jpeg_quality_factor=55,
        fft_highfreq_ratio=0.005,
    )
    f = assess_fitness(r, devices=["inkposter_tela_28_5"])
    assert f["inkposter_tela_28_5"] == "unfit"


def test_device_thresholds_present():
    for dev in [
        "inkposter_tela_28_5",
        "hisense_canvastv",
        "samsung_frame",
        "meural_landscape",
        "pimoroni_inky_13_3",
    ]:
        assert dev in DEVICE_THRESHOLDS
        thr = DEVICE_THRESHOLDS[dev]
        assert "min_long_edge_px" in thr
        assert "min_jpeg_q" in thr
        assert "min_fft_highfreq_ratio" in thr
