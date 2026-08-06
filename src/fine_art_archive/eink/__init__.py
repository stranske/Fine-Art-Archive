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
from .palette import (  # noqa: F401
    KALEIDO3, MONO1BIT, PALETTES, SPECTRA6, Palette,
    dither_error, get_palette, map_to_panel_range, quantize,
)
from .playlist import (  # noqa: F401
    MOODS, PERIODS, PlaylistResult, PlaylistSpec, build, load_ratings, parse_year,
)
from .sdcard import ExportItem, ExportReport, export  # noqa: F401
from .targets import (  # noqa: F401
    TARGETS, RenderTarget, fit_to_target, get_target, render_for_target,
)
