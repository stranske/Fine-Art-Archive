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
from .feed import (  # noqa: F401
    INTERVALS,
    PlaylistStore,
    SavedPlaylist,
    build_manifest,
    item_etag,
    rotation_index,
    slugify,
)
from .palette import (  # noqa: F401
    KALEIDO3,
    MONO1BIT,
    PALETTES,
    SPECTRA6,
    Palette,
    dither_error,
    get_palette,
    map_to_panel_range,
    quantize,
)
from .playlist import (  # noqa: F401
    MOODS,
    PERIODS,
    PlaylistResult,
    PlaylistSpec,
    build,
    discover_facets,
    load_ratings,
    parse_year,
)
from .sdcard import ExportItem, ExportReport, export  # noqa: F401
from .targets import (  # noqa: F401
    TARGETS,
    FitMode,
    RenderTarget,
    coerce_fit,
    fit_to_target,
    get_target,
    render_for_target,
)

# Explicit re-export list. Without it mypy (no_implicit_reexport) rejects every
# `from fine_art_archive.eink import X` in the API layer: a lint-suppressed
# import is not an export as far as the type checker is concerned. (The comment
# avoids spelling the suppression directive literally -- ruff parses it as a
# real directive even inside prose and warns that it is malformed.)
__all__ = [
    "KALEIDO3", "MONO1BIT", "MOODS", "PALETTES", "PERIODS", "SPECTRA6",
    "TARGETS", "ExportItem", "FitMode", "coerce_fit", "ExportReport", "Palette", "PlaylistResult",
    "PlaylistSpec", "RenderTarget", "INTERVALS", "PlaylistStore", "SavedPlaylist", "build", "build_manifest",
    "discover_facets", "dither_error", "export", "item_etag",
    "rotation_index", "slugify",
    "fit_to_target", "get_palette", "get_target", "load_ratings",
    "map_to_panel_range", "parse_year", "quantize", "render_for_target",
]
