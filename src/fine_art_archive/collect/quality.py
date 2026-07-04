"""Display-quality measurement for acquired masters.

The companion to `verify.py` (identity verification). Where verify answers
"are these the bytes of the work we think they are?", this module answers
"are these bytes good enough to display, and which displays?"

See `display_quality_design.md` for the full design. This module implements
the cheap deterministic measurements:

  - px_per_cm                 — long-edge density relative to physical size
  - bytes_per_megapixel       — JPEG compression proxy
  - icc_profile_present       — color management hint
  - jpeg_quality_factor       — via ImageMagick `identify` when available
  - laplacian_variance        — sharpness / focus
  - fft_highfreq_ratio        — upscale detection signal
  - dpi_gate                  — deterministic per-device resolution gate
  - no_reference_quality_score — optional BRISQUE/NIQE-style IQA, lazy fallback
  - ssim_render_fidelity      — full-reference render-vs-master fidelity
  - color_depth_bits          — source color depth factor
  - observed_gamut_coverage   — normalized RGB gamut occupancy factor

Plus a composite `quality_report()` that bundles them, and `assess_fitness()`
that maps the report onto target-device adequacy.
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
from PIL import Image

# ---------------------------------------------------------------------------
# Device thresholds (mirrors config/device_profiles.yaml; kept inline so the
# module is self-contained for tests and for one-off scripts).
# ---------------------------------------------------------------------------

# NOTE on min_fft_highfreq_ratio calibration:
# Measured on the Vermeer Little Street master (32.9 MP real Rijksmuseum
# scan): 0.0046. Measured on its Wikidata P18 Commons display (1280x1585):
# 0.0069. Measured on the QkOGy/Milkmaid bytes (24.1 MP): 0.0043. All
# three are real high-res scans of paintings; the absolute magnitudes are
# low because natural image energy concentrates in low frequencies. The
# threshold here gates "completely synthetic / extremely upscaled" outputs
# (which would score near 0.0005-0.001), not "high-frequency-rich
# photographs". The signal becomes much more discriminating when compared
# across same-resolution candidates of the same work; absolute thresholds
# are a coarse first filter only.

DEVICE_THRESHOLDS: dict[str, dict] = {
    "inkposter_tela_28_5": {
        "min_long_edge_px": 3060,
        "min_short_edge_px": 2160,
        "min_jpeg_q": 75,
        "min_fft_highfreq_ratio": 0.0015,
        "min_color_depth_bits": 8,
    },
    "hisense_canvastv": {
        "min_long_edge_px": 3840,
        "min_short_edge_px": 2160,
        "min_jpeg_q": 75,
        "min_fft_highfreq_ratio": 0.0012,
        "min_color_depth_bits": 8,
    },
    "samsung_frame": {
        "min_long_edge_px": 3840,
        "min_short_edge_px": 2160,
        "min_jpeg_q": 75,
        "min_fft_highfreq_ratio": 0.0012,
        "min_color_depth_bits": 8,
    },
    "pimoroni_inky_13_3": {
        "min_long_edge_px": 1600,
        "min_short_edge_px": 1200,
        "min_jpeg_q": 70,
        "min_fft_highfreq_ratio": 0.0010,
        "min_color_depth_bits": 8,
    },
    "meural_landscape": {
        "min_long_edge_px": 1920,
        "min_short_edge_px": 1080,
        "min_jpeg_q": 70,
        "min_fft_highfreq_ratio": 0.0010,
        "min_color_depth_bits": 8,
    },
    "meural_portrait": {
        "min_long_edge_px": 1920,
        "min_short_edge_px": 1080,
        "min_jpeg_q": 70,
        "min_fft_highfreq_ratio": 0.0010,
        "min_color_depth_bits": 8,
    },
    "archival_a2_print": {
        "min_long_edge_px": 7016,  # 300 DPI at A2
        "min_short_edge_px": 4960,
        "min_jpeg_q": 85,
        "min_fft_highfreq_ratio": 0.0020,
        "min_color_depth_bits": 8,
    },
}


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------


@dataclass
class QualityReport:
    long_edge_px: int = 0
    short_edge_px: int = 0
    pixel_area_mp: float = 0.0
    px_per_cm_long: float | None = None
    bytes_per_megapixel: float = 0.0
    icc_profile_present: bool = False
    icc_profile_bytes: int = 0
    jpeg_quality_factor: int | None = None
    laplacian_variance: float = 0.0
    fft_highfreq_ratio: float = 0.0
    dpi_gate: dict[str, str] = field(default_factory=dict)
    no_reference_quality_score: float | None = None
    no_reference_quality_method: str | None = None
    ssim_render_fidelity: float | None = None
    color_depth_bits: int = 0
    observed_gamut_coverage: float = 0.0
    fitness: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------------


def measure_resolution(
    img: Image.Image, h_cm: float | None, w_cm: float | None
) -> tuple[int, int, float | None]:
    w, h = img.size
    long_edge = max(w, h)
    short_edge = min(w, h)
    px_per_cm = None
    if h_cm and w_cm and (h_cm > 0 and w_cm > 0):
        long_cm = max(h_cm, w_cm)
        px_per_cm = long_edge / long_cm
    return long_edge, short_edge, px_per_cm


def measure_bytes_per_megapixel(file_size: int, w: int, h: int) -> float:
    mp = (w * h) / 1e6
    return file_size / mp if mp > 0 else 0.0


def measure_icc(img: Image.Image) -> tuple[bool, int]:
    icc = img.info.get("icc_profile")
    return (bool(icc), len(icc) if icc else 0)


def measure_jpeg_quality(path: Path) -> int | None:
    """Read JPEG quantization factor via ImageMagick when available."""
    if not shutil.which("identify"):
        return None
    try:
        out = subprocess.run(
            ["identify", "-format", "%Q", str(path)],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if out.returncode == 0:
            return int(out.stdout.strip())
    except (subprocess.TimeoutExpired, ValueError):
        pass
    return None


def measure_laplacian_variance(img: Image.Image, max_dim: int = 1024) -> float:
    """Laplacian variance as a sharpness proxy.

    Downsamples to max_dim long edge first to make the measurement
    comparable across resolutions (otherwise a 32 MP image's variance
    isn't comparable to a 4 MP image's).
    """
    gray = img.convert("L")
    if max(gray.size) > max_dim:
        ratio = max_dim / max(gray.size)
        new_size = (int(gray.size[0] * ratio), int(gray.size[1] * ratio))
        gray = gray.resize(new_size, Image.Resampling.LANCZOS)
    arr = np.asarray(gray, dtype=np.float32)
    # 3x3 Laplacian via slicing (an explicit kernel + FFT convolution would be overkill)
    h, w = arr.shape
    pad = np.pad(arr, 1, mode="edge")
    lap = pad[:-2, 1:-1] + pad[2:, 1:-1] + pad[1:-1, :-2] + pad[1:-1, 2:] - 4 * arr
    return float(np.var(lap))


def measure_fft_highfreq_ratio(img: Image.Image, max_dim: int = 1024) -> float:
    """Ratio of energy in the high-frequency tail to total spectral energy.

    Compute 2D FFT of a downscaled luminance image; sum the magnitude in
    the outer 10% of spatial frequencies and divide by total magnitude.
    Genuinely high-resolution images have energy out to Nyquist; upscaled
    images have energy that falls off above the original's Nyquist.
    """
    gray = img.convert("L")
    if max(gray.size) > max_dim:
        ratio = max_dim / max(gray.size)
        new_size = (int(gray.size[0] * ratio), int(gray.size[1] * ratio))
        gray = gray.resize(new_size, Image.Resampling.LANCZOS)
    arr = np.asarray(gray, dtype=np.float32)
    f = np.fft.fftshift(np.fft.fft2(arr))
    mag = np.abs(f)
    h, w = mag.shape
    # Distance from spectrum center, normalized to [0, 1]
    yy, xx = np.mgrid[0:h, 0:w]
    cy, cx = h / 2.0, w / 2.0
    r = np.sqrt((yy - cy) ** 2 + (xx - cx) ** 2) / np.sqrt(cy**2 + cx**2)
    # Sum total magnitude (excluding the DC bin which dominates)
    mask_total = r > 0.01
    total = mag[mask_total].sum()
    # Sum high-frequency tail (outer 10%)
    mask_high = r > 0.9
    high = mag[mask_high].sum()
    return float(high / total) if total > 0 else 0.0


def assess_dpi_gate(report: QualityReport, devices: list[str] | None = None) -> dict[str, str]:
    """Return deterministic pass/fail DPI adequacy by device."""
    if devices is None:
        devices = list(DEVICE_THRESHOLDS.keys())
    gate = {}
    for dev in devices:
        thr = DEVICE_THRESHOLDS.get(dev)
        if not thr:
            continue
        long_ok = report.long_edge_px >= thr["min_long_edge_px"]
        short_ok = report.short_edge_px >= thr.get("min_short_edge_px", 0)
        gate[dev] = "pass" if long_ok and short_ok else "fail"
    return gate


def measure_no_reference_quality(img: Image.Image) -> tuple[float | None, str | None]:
    """Return an optional no-reference IQA score.

    BRISQUE/NIQE implementations are intentionally optional because they add
    heavy dependencies. When they are absent, return a finite in-repo fallback
    based on the existing sharpness and high-frequency signals so the quality
    report still exposes a stable no-reference factor.
    """
    try:
        import piq  # type: ignore[import-not-found]
        import torch  # type: ignore[import-not-found]

        arr = np.asarray(img.convert("RGB").resize((256, 256)), dtype=np.float32) / 255.0
        tensor = torch.from_numpy(arr).permute(2, 0, 1).unsqueeze(0)
        brisque_score = float(piq.brisque(tensor, data_range=1.0).item())
        if np.isfinite(brisque_score):
            # BRISQUE is lower-is-better. Report a stable higher-is-better
            # quality score so callers can compare methods consistently.
            return float(np.clip(100.0 - brisque_score, 0.0, 100.0)), "brisque_normalized"
    except ImportError:
        pass

    lap = measure_laplacian_variance(img)
    fft = measure_fft_highfreq_ratio(img)
    # Higher is better, roughly 0..100 for typical local images.
    score = min(100.0, (np.log1p(lap) * 8.0) + (fft * 2500.0))
    return float(score), "sharpness_fft_fallback"


def measure_color_depth_bits(img: Image.Image) -> int:
    """Estimate bits per color channel for the source image."""
    if img.mode in {"1"}:
        return 1
    if img.mode in {"L", "P"}:
        return 8
    if img.mode in {"I;16", "I;16B", "I;16L"}:
        return 16
    return 8


def measure_observed_gamut_coverage(img: Image.Image, max_dim: int = 512) -> float:
    """Estimate normalized RGB gamut occupancy from robust channel spans."""
    rgb = img.convert("RGB")
    if max(rgb.size) > max_dim:
        ratio = max_dim / max(rgb.size)
        rgb = rgb.resize((int(rgb.size[0] * ratio), int(rgb.size[1] * ratio)), Image.Resampling.BOX)
    arr = np.asarray(rgb, dtype=np.float32).reshape(-1, 3)
    low = np.percentile(arr, 1, axis=0)
    high = np.percentile(arr, 99, axis=0)
    spans = np.maximum(high - low, 0.0) / 255.0
    span_volume = float(np.prod(spans))
    if span_volume < 1e-12:
        return 0.0
    if np.any(np.std(arr, axis=0) < 1e-9):
        channel_independence = 0.0
    else:
        corr = np.corrcoef(arr, rowvar=False)
        upper = np.abs(corr[np.triu_indices(3, k=1)])
        channel_independence = float(1.0 - np.mean(upper))
    return float(np.clip(span_volume * channel_independence, 0.0, 1.0))


def measure_ssim(master: Image.Image, rendered: Image.Image, max_dim: int = 512) -> float:
    """Compute a small grayscale SSIM score without requiring scikit-image."""
    left = master.convert("L")
    right = rendered.convert("L")
    if left.size != right.size:
        right = right.resize(left.size, Image.Resampling.LANCZOS)
    if max(left.size) > max_dim:
        ratio = max_dim / max(left.size)
        new_size = (int(left.size[0] * ratio), int(left.size[1] * ratio))
        left = left.resize(new_size, Image.Resampling.LANCZOS)
        right = right.resize(new_size, Image.Resampling.LANCZOS)

    x = np.asarray(left, dtype=np.float64)
    y = np.asarray(right, dtype=np.float64)
    c1 = (0.01 * 255) ** 2
    c2 = (0.03 * 255) ** 2
    mux = x.mean()
    muy = y.mean()
    sigx = ((x - mux) ** 2).mean()
    sigy = ((y - muy) ** 2).mean()
    sigxy = ((x - mux) * (y - muy)).mean()
    score = ((2 * mux * muy + c1) * (2 * sigxy + c2)) / (
        (mux**2 + muy**2 + c1) * (sigx + sigy + c2)
    )
    return float(np.clip(score, -1.0, 1.0))


# ---------------------------------------------------------------------------
# Composite report + fitness
# ---------------------------------------------------------------------------


def assess_fitness(report: QualityReport, devices: list[str] | None = None) -> dict[str, str]:
    """Map a quality report to per-device fitness (fit / borderline / unfit)."""
    if devices is None:
        devices = list(DEVICE_THRESHOLDS.keys())
    fitness = {}
    for dev in devices:
        thr = DEVICE_THRESHOLDS.get(dev)
        if not thr:
            continue
        fails = []
        warns = []
        if report.long_edge_px < thr["min_long_edge_px"]:
            fails.append(f"long edge {report.long_edge_px} < {thr['min_long_edge_px']}")
        elif report.long_edge_px < thr["min_long_edge_px"] * 1.1:
            warns.append("long edge near minimum")
        min_short_edge = thr.get("min_short_edge_px")
        if min_short_edge and report.short_edge_px < min_short_edge:
            fails.append(f"short edge {report.short_edge_px} < {min_short_edge}")
        if (
            report.jpeg_quality_factor is not None
            and report.jpeg_quality_factor < thr["min_jpeg_q"]
        ):
            fails.append(f"Q {report.jpeg_quality_factor} < {thr['min_jpeg_q']}")
        if report.fft_highfreq_ratio < thr["min_fft_highfreq_ratio"]:
            fails.append(
                f"fft_highfreq_ratio {report.fft_highfreq_ratio:.3f} "
                f"< {thr['min_fft_highfreq_ratio']}"
            )
        if report.color_depth_bits and report.color_depth_bits < thr["min_color_depth_bits"]:
            warns.append(f"color depth {report.color_depth_bits} < {thr['min_color_depth_bits']}")
        if fails:
            fitness[dev] = "unfit"
        elif warns:
            fitness[dev] = "borderline"
        else:
            fitness[dev] = "fit"
    return fitness


def quality_report(
    image_path: Path,
    *,
    h_cm: float | None = None,
    w_cm: float | None = None,
    rendered_path: Path | None = None,
    devices: list[str] | None = None,
) -> QualityReport:
    """Compute the full cheap-deterministic quality report for an image."""
    path = Path(image_path)
    rpt = QualityReport()
    with Image.open(path) as img:
        rpt.long_edge_px, rpt.short_edge_px, rpt.px_per_cm_long = measure_resolution(
            img, h_cm=h_cm, w_cm=w_cm
        )
        rpt.pixel_area_mp = (img.size[0] * img.size[1]) / 1e6
        rpt.bytes_per_megapixel = measure_bytes_per_megapixel(
            path.stat().st_size, img.size[0], img.size[1]
        )
        rpt.icc_profile_present, rpt.icc_profile_bytes = measure_icc(img)
        rpt.jpeg_quality_factor = measure_jpeg_quality(path)
        rpt.laplacian_variance = measure_laplacian_variance(img)
        rpt.fft_highfreq_ratio = measure_fft_highfreq_ratio(img)
        rpt.dpi_gate = assess_dpi_gate(rpt, devices=devices)
        (
            rpt.no_reference_quality_score,
            rpt.no_reference_quality_method,
        ) = measure_no_reference_quality(img)
        rpt.color_depth_bits = measure_color_depth_bits(img)
        rpt.observed_gamut_coverage = measure_observed_gamut_coverage(img)
        if rendered_path is not None:
            with Image.open(rendered_path) as rendered:
                rpt.ssim_render_fidelity = measure_ssim(img, rendered)
    rpt.fitness = assess_fitness(rpt, devices=devices)

    # Informational notes (advisory; don't gate fitness alone)
    if rpt.fft_highfreq_ratio < 0.0010:
        rpt.notes.append("very low FFT high-frequency energy; suspected upscale")
    if rpt.bytes_per_megapixel < 75_000:
        rpt.notes.append("aggressive JPEG compression (bpp < 75 KB/MP)")
    if not rpt.icc_profile_present:
        rpt.notes.append("no embedded ICC profile; treated as sRGB")
    if rpt.jpeg_quality_factor is not None and rpt.jpeg_quality_factor < 75:
        rpt.notes.append(f"low JPEG Q factor: {rpt.jpeg_quality_factor}")
    if rpt.observed_gamut_coverage < 0.01:
        rpt.notes.append("very narrow observed RGB gamut")

    return rpt
