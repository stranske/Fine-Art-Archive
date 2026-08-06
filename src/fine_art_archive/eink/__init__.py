"""E-paper output: palettes, dithering, render targets, playlists, SD cards.

The pipeline is deliberately device-agnostic in the middle and thin at the
edges, because the survey found three unrelated ways to get an image onto a
>15in panel and no single one that is safe to bet on:

  render (here)  ->  framebuffer / HDMI    (BOOX Mira Pro — no API needed)
                 ->  local HTTP push       (Samsung MDC, BLOOMIN8, Fraimic)
                 ->  file drop to SD/USB   (Good Display DIY, MEiNK, SEEKINK)

Dithering stays on our side of that boundary. It is the largest single
determinant of how a reproduction looks, and every vendor except BLOOMIN8
performs it internally with an undocumented pipeline. See palette.py.
"""
from .palette import (
    KALEIDO3 as KALEIDO3,
)
from .palette import (
    MONO1BIT as MONO1BIT,
)
from .palette import (
    PALETTES as PALETTES,
)
from .palette import (
    SPECTRA6 as SPECTRA6,
)
from .palette import (
    Palette as Palette,
)
from .palette import (
    dither_error as dither_error,
)
from .palette import (
    get_palette as get_palette,
)
from .palette import (
    map_to_panel_range as map_to_panel_range,
)
from .palette import (
    quantize as quantize,
)
from .playlist import (
    MOODS as MOODS,
)
from .playlist import (
    PERIODS as PERIODS,
)
from .playlist import (
    PlaylistResult as PlaylistResult,
)
from .playlist import (
    PlaylistSpec as PlaylistSpec,
)
from .playlist import (
    build as build,
)
from .playlist import (
    load_ratings as load_ratings,
)
from .playlist import (
    parse_year as parse_year,
)
from .sdcard import ExportItem as ExportItem
from .sdcard import ExportReport as ExportReport
from .sdcard import export as export
from .targets import (
    TARGETS as TARGETS,
)
from .targets import (
    RenderTarget as RenderTarget,
)
from .targets import (
    fit_to_target as fit_to_target,
)
from .targets import (
    get_target as get_target,
)
from .targets import (
    render_for_target as render_for_target,
)

__all__ = [
    "KALEIDO3",
    "MONO1BIT",
    "MOODS",
    "PALETTES",
    "PERIODS",
    "SPECTRA6",
    "ExportItem",
    "ExportReport",
    "Palette",
    "PlaylistResult",
    "PlaylistSpec",
    "RenderTarget",
    "TARGETS",
    "build",
    "dither_error",
    "export",
    "fit_to_target",
    "get_palette",
    "get_target",
    "load_ratings",
    "map_to_panel_range",
    "parse_year",
    "quantize",
    "render_for_target",
]
