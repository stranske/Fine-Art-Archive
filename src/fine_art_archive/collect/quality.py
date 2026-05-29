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
        "min_jpeg_q": 75,
        "min_fft_highfreq_ratio": 0.0015,
    },
    "hisense_canvastv": {
        "min_long_edge_px": 3840,
        "min_jpeg_q": 75,
        "min_fft_highfreq_ratio": 0.0012,
    },
    "samsung_frame": {
        "min_long_edge_px": 3840,
        "min_jpeg_q": 75,
        "min_fft_highfreq_ratio": 0.0012,
    },
    "pimoroni_inky_13_3": {
        "min_long_edge_px": 1600,
        "min_jpeg_q": 70,
        "min_fft_highfreq_ratio": 0.0010,
    },
    "meural_landscape": {
        "min_long_edge_px": 1920,
        "min_jpeg_q": 70,
        "min_fft_highfreq_ratio": 0.0010,
    },
    "meural_portrait": {
        "min_long_edge_px": 1920,
        "min_jpeg_q": 70,
        "min_fft_highfreq_ratio": 0.0010,
    },
    "archival_a2_print": {
        "min_long_edge_px": 7016,  # 300 DPI at A2
        "min_jpeg_q": 85,
        "min_fft_highfreq_ratio": 0.0020,
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
    devices: list[str] | None = None,
) -> QualityReport:
    """Compute the full cheap-deterministic quality report for an image."""
    path = Path(image_path)
    img = Image.open(path)
    rpt = QualityReport()
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

    return rpt
