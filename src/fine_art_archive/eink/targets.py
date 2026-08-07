"""Render targets: what a specific panel needs an image to look like.

A render target is the small set of facts that decide how a master becomes a
file the panel can show — pixel dimensions, orientation, palette, and how to
reconcile a painting's aspect ratio with the panel's.

Aspect ratio deserves a note, because it is the choice most likely to annoy.
Panels above 15" are overwhelmingly 16:9 landscape; paintings are not. A 3:4
portrait in a 16:9 frame either gets cropped (losing the top of a Bruegel sky)
or letterboxed (bars of panel white down both sides). There is no correct
default, so `fit` is per-target and per-playlist rather than hardcoded, and
`letterbox` fills with the panel's real white rather than #FFFFFF so the bars
match the paper instead of glowing against it.

Sizes come from the survey (docs/EINK_DEVICE_SURVEY.md) and are the vendors'
published figures. Palettes are estimates — see palette.py.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from PIL import Image

from .palette import Palette, get_palette, map_to_panel_range, quantize

FitMode = Literal["contain", "cover", "stretch"]


@dataclass(frozen=True)
class RenderTarget:
    key: str
    label: str
    width: int
    height: int
    palette_name: str
    fit: FitMode = "contain"
    rotate: int = 0
    note: str = ""

    @property
    def palette(self) -> Palette:
        return get_palette(self.palette_name)

    @property
    def size(self) -> tuple[int, int]:
        return (self.width, self.height)

    @property
    def portrait(self) -> bool:
        return self.height > self.width

    def as_dict(self) -> dict:
        return {
            "key": self.key, "label": self.label,
            "width": self.width, "height": self.height,
            "palette": self.palette_name,
            "palette_measured": self.palette.measured,
            "fit": self.fit, "rotate": self.rotate, "note": self.note,
        }


TARGETS: dict[str, RenderTarget] = {
    t.key: t
    for t in (
        RenderTarget(
            "samsung-em32dx", 'Samsung Color E-Paper EM32DX 31.5"',
            1440, 2560, "spectra6", rotate=0,
            note="Native portrait 1440x2560. Push over MDC on TCP 1515.",
        ),
        RenderTarget(
            "bloomin8-285", 'BLOOMIN8 EinkCanvas 28.5"',
            2160, 3060, "spectra6",
            note="Portrait 3:4, 131 ppi. Accepts PRE-DITHERED data via "
                 "/image/dataUpload — the only device that does.",
        ),
        RenderTarget(
            "inkposter-tela-285", 'InkPoster Tela 28.5"',
            2160, 3060, "spectra6",
            note="Best pixel density above 15in (132 ppi, portrait 3:4). "
                 "Cloud-only ingest, so SD export does not apply.",
        ),
        RenderTarget(
            "fraimic-large-315", 'Fraimic Large Canvas 31.5"',
            2560, 1440, "spectra6", fit="contain",
            note="Landscape 16:9. Local mode advertised, endpoints undocumented.",
        ),
        RenderTarget(
            "gooddisplay-315-diy", 'Good Display GDEP315C01 31.5" (DIY, QSPI)',
            2560, 1440, "spectra6",
            note="Self-built route: DEAM-315E1 ESP32-S3 kit, SD-card first boot. "
                 "31.5in is QSPI so an MCU can drive it; 25.3in is Mini-LVDS "
                 "and cannot be driven this way.",
        ),
        RenderTarget(
            "boox-mira-pro-253", 'BOOX Mira Pro Color 25.3" (as a monitor)',
            3200, 1800, "kaleido3", fit="contain",
            note="Driven as an ordinary display over HDMI/DP — no API needed. "
                 "Kaleido 3, so markedly less saturated than Spectra 6.",
        ),
        RenderTarget(
            "visionect-32-mono", 'Visionect Place & Play 32" (mono)',
            1920, 1080, "gray16",
            note="Monochrome. Full REST API but licence-gated per device.",
        ),
        RenderTarget(
            "generic-mono-1bit", "Generic bilevel panel (test target)",
            1200, 825, "mono1bit",
            note="For checking how a work survives the harshest case.",
        ),
    )
}


def get_target(key: str) -> RenderTarget:
    try:
        return TARGETS[key]
    except KeyError:
        raise KeyError(
            f"unknown render target {key!r}; have {sorted(TARGETS)}"
        ) from None


_FIT_MODES: tuple[FitMode, ...] = ("contain", "cover", "stretch")


def coerce_fit(value: str | None) -> FitMode | None:
    """Narrow an untrusted string to a FitMode, rejecting anything else.

    `fit` arrives from an HTTP query parameter or a CLI flag, i.e. as a plain
    `str`. Casting it to the Literal would silence the type checker while
    letting a typo like "conatin" reach `fit_to_target`, where it would fall
    through to the letterbox branch and quietly produce the wrong framing.
    Rejecting loudly is better than framing 200 paintings incorrectly.
    """
    if value is None:
        return None
    if value in _FIT_MODES:
        return value  # type: ignore[return-value]
    raise ValueError(f"unknown fit mode {value!r}; expected one of {_FIT_MODES}")


def fit_to_target(img: Image.Image, target: RenderTarget,
                  fit: FitMode | None = None) -> Image.Image:
    """Resize/crop `img` to the target's pixel dimensions."""
    mode = fit or target.fit
    src = img.convert("RGB")
    if target.rotate:
        src = src.rotate(-target.rotate, expand=True)
    tw, th = target.size

    if mode == "stretch":
        return src.resize((tw, th), Image.Resampling.LANCZOS)

    sw, sh = src.size
    scale = (max if mode == "cover" else min)(tw / sw, th / sh)
    new = (max(1, round(sw * scale)), max(1, round(sh * scale)))
    src = src.resize(new, Image.Resampling.LANCZOS)

    if mode == "cover":
        left = (src.width - tw) // 2
        top = (src.height - th) // 2
        return src.crop((left, top, left + tw, top + th))

    # contain: letterbox in the panel's REAL white, so the bars read as paper
    # rather than as a bright surround the panel cannot actually produce.
    canvas = Image.new("RGB", (tw, th), target.palette.white)
    canvas.paste(src, ((tw - src.width) // 2, (th - src.height) // 2))
    return canvas


def render_for_target(
    img: Image.Image,
    target: RenderTarget,
    *,
    fit: FitMode | None = None,
    method: str = "floyd-steinberg",
    compress_range: bool = True,
    fast: bool = True,
) -> Image.Image:
    """Full pipeline: fit → range-compress → dither to the panel's palette.

    `fast` defaults to True to match `palette.quantize`. It defaulted to False
    here, which silently overrode quantize's own default and sent every caller
    -- including the app's preview endpoint -- down the 250x slower NumPy path
    for no measured benefit (0.70s vs 0.14s on a 378x213 preview).
    """
    out = fit_to_target(img, target, fit=fit)
    if compress_range:
        out = map_to_panel_range(out, target.palette)
    return quantize(out, target.palette, method=method, fast=fast)  # type: ignore[arg-type]


def write_targets_json(path: Path) -> None:
    """Emit the target list so the UI and any external tool share one source."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(
        {
            "_note": "Generated by fine_art_archive.eink.targets. Palette values "
                     "are ESTIMATES pending measurement on real hardware.",
            "targets": [t.as_dict() for t in TARGETS.values()],
        },
        indent=2,
    ))
