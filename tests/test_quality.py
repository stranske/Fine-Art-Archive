"""Tests for the display-quality measurement module."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fine_art_archive.collect.quality import (  # noqa: E402
    DEVICE_THRESHOLDS,
    QualityReport,
    assess_fitness,
    measure_ssim,
    quality_report,
)

# Use the Vermeer Little Street sample as a known-good fixture.
SAMPLE = Path(__file__).resolve().parents[1] / "samples" / "0441b1c-the-little-street-vermeer"
MASTER = SAMPLE / "master.jpg"
NEGATIVE = SAMPLE / "resources" / "_negative_qkogy_milkmaid.jpg"


def _require_master():
    if not MASTER.exists():
        pytest.skip("Vermeer sample master.jpg not present")


def _write_synthetic_textured_jpeg(path: Path) -> Path:
    yy, xx = np.mgrid[0:240, 0:320]
    arr = np.zeros((240, 320, 3), dtype=np.uint8)
    arr[..., 0] = ((xx * 7 + yy * 3) % 256).astype(np.uint8)
    arr[..., 1] = ((xx * 2 + yy * 11) % 256).astype(np.uint8)
    arr[..., 2] = (((xx // 4 % 2) ^ (yy // 4 % 2)) * 180 + 40).astype(np.uint8)
    Image.fromarray(arr).save(path, quality=91, icc_profile=b"fake-profile")
    return path


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


def test_generated_image_quality_report_extracts_jpeg_metrics(tmp_path):
    image_path = _write_synthetic_textured_jpeg(tmp_path / "textured.jpg")

    r = quality_report(
        image_path,
        h_cm=24.0,
        w_cm=32.0,
        devices=["pimoroni_inky_13_3", "meural_landscape"],
    )

    assert r.long_edge_px == 320
    assert r.short_edge_px == 240
    assert r.pixel_area_mp == pytest.approx(0.0768)
    assert r.px_per_cm_long == pytest.approx(10.0)
    assert r.bytes_per_megapixel == pytest.approx(image_path.stat().st_size / 0.0768)
    assert r.icc_profile_present is True
    assert r.icc_profile_bytes == len(b"fake-profile")
    if r.jpeg_quality_factor is not None:
        assert 85 <= r.jpeg_quality_factor <= 95
    assert r.laplacian_variance > 100
    assert r.fft_highfreq_ratio > 0.001
    assert r.dpi_gate == {
        "pimoroni_inky_13_3": "fail",
        "meural_landscape": "fail",
    }
    assert r.no_reference_quality_score is not None
    assert np.isfinite(r.no_reference_quality_score)
    assert r.no_reference_quality_method in {"brisque", "sharpness_fft_fallback"}
    assert r.color_depth_bits == 8
    assert 0.0 <= r.observed_gamut_coverage <= 1.0
    assert r.fitness == {
        "pimoroni_inky_13_3": "unfit",
        "meural_landscape": "unfit",
    }
    assert "no embedded ICC profile; treated as sRGB" not in r.notes


def test_generated_image_quality_report_flags_low_information_jpeg(tmp_path):
    image_path = tmp_path / "flat.jpg"
    Image.new("RGB", (256, 256), (128, 128, 128)).save(image_path, quality=30)

    r = quality_report(image_path, devices=["pimoroni_inky_13_3"])

    assert r.long_edge_px == 256
    assert r.short_edge_px == 256
    assert r.px_per_cm_long is None
    assert r.bytes_per_megapixel < 75_000
    assert r.icc_profile_present is False
    assert r.laplacian_variance == 0.0
    assert r.fft_highfreq_ratio == 0.0
    assert r.dpi_gate["pimoroni_inky_13_3"] == "fail"
    assert r.no_reference_quality_score is not None
    assert np.isfinite(r.no_reference_quality_score)
    assert r.color_depth_bits == 8
    assert r.observed_gamut_coverage == pytest.approx(0.0)
    assert r.fitness["pimoroni_inky_13_3"] == "unfit"
    assert "very low FFT high-frequency energy; suspected upscale" in r.notes
    assert "aggressive JPEG compression (bpp < 75 KB/MP)" in r.notes
    assert "no embedded ICC profile; treated as sRGB" in r.notes
    if r.jpeg_quality_factor is not None:
        assert f"low JPEG Q factor: {r.jpeg_quality_factor}" in r.notes
    assert "very narrow observed RGB gamut" in r.notes


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


def test_dpi_gate_passes_adequate_and_fails_under_resolution(tmp_path):
    small = tmp_path / "small.jpg"
    large = tmp_path / "large.jpg"
    Image.new("RGB", (800, 600), "white").save(small, quality=90)
    Image.new("RGB", (1700, 1200), "white").save(large, quality=90)

    small_report = quality_report(small, devices=["pimoroni_inky_13_3"])
    large_report = quality_report(large, devices=["pimoroni_inky_13_3"])

    assert small_report.dpi_gate["pimoroni_inky_13_3"] == "fail"
    assert large_report.dpi_gate["pimoroni_inky_13_3"] == "pass"


def test_ssim_render_fidelity_identical_and_degraded(tmp_path):
    base = tmp_path / "base.png"
    same = tmp_path / "same.png"
    degraded = tmp_path / "degraded.png"
    yy, xx = np.mgrid[0:96, 0:128]
    arr = np.zeros((96, 128, 3), dtype=np.uint8)
    arr[..., 0] = ((xx * 3) % 256).astype(np.uint8)
    arr[..., 1] = ((yy * 5) % 256).astype(np.uint8)
    arr[..., 2] = (((xx + yy) * 2) % 256).astype(np.uint8)
    Image.fromarray(arr).save(base)
    Image.fromarray(arr).save(same)
    Image.fromarray(255 - arr).save(degraded)

    identical = quality_report(base, rendered_path=same, devices=[])
    degraded_report = quality_report(base, rendered_path=degraded, devices=[])

    assert identical.ssim_render_fidelity == pytest.approx(1.0)
    assert degraded_report.ssim_render_fidelity is not None
    assert degraded_report.ssim_render_fidelity < 0.5
    assert measure_ssim(Image.open(base), Image.open(same)) == pytest.approx(1.0)


def test_quality_report_populates_color_depth_and_gamut(tmp_path):
    image_path = _write_synthetic_textured_jpeg(tmp_path / "textured.jpg")

    r = quality_report(image_path, devices=[])

    assert r.color_depth_bits == 8
    assert r.observed_gamut_coverage > 0.05
    assert r.no_reference_quality_score is not None
    assert np.isfinite(r.no_reference_quality_score)


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
