"""Card export must not ship a render whose dither has been destroyed.

Audit finding 10 (2026-08-08). The whole point of the e-ink render path is that
every pixel IS one of the six panel inks, so the panel reproduces the intended
dither. Lossy compression reintroduces continuous tone and destroys that, and
the panel firmware then re-quantises by its own unknown rule — discarding the
project's entire dithering effort at the last step.

Measured on a 256-step gradient rendered to Spectra 6:

    PNG   -> 0 illegal colours,     0 illegal pixels
    BMP   -> 0 illegal colours,     0 illegal pixels
    JPEG  -> 5,988 illegal colours, 14,371 of 16,384 pixels (88%)

`export` accepted "jpg"/"jpeg" explicitly, and the API's `fmt` was an
unconstrained `str` with a default, so `?fmt=jpeg` reached it.
"""

from __future__ import annotations

import io

import numpy as np
import pytest
from PIL import Image

from fine_art_archive.eink import sdcard
from fine_art_archive.eink.palette import SPECTRA6, quantize
from fine_art_archive.eink.targets import get_target


def _gradient() -> Image.Image:
    return Image.fromarray(
        np.tile(np.arange(256, dtype=np.uint8).reshape(1, 256, 1), (64, 1, 3)), "RGB"
    )


def _illegal_pixels(img: Image.Image) -> int:
    allowed = {tuple(int(v) for v in c) for c in SPECTRA6.colours}
    pixels = np.asarray(img.convert("RGB")).reshape(-1, 3)
    mask = np.ones(len(pixels), dtype=bool)
    for colour in allowed:
        mask &= ~np.all(pixels == np.array(colour), axis=1)
    return int(mask.sum())


class TestRoundTripFidelity:
    """The measurement the fix rests on, kept executable rather than asserted."""

    def test_lossless_formats_preserve_the_palette_exactly(self) -> None:
        rendered = quantize(_gradient(), SPECTRA6, method="floyd-steinberg")
        for fmt in ("PNG", "BMP"):
            buf = io.BytesIO()
            rendered.save(buf, format=fmt)
            buf.seek(0)
            assert _illegal_pixels(Image.open(buf)) == 0, f"{fmt} must be exact"

    def test_jpeg_destroys_the_dither(self) -> None:
        """Not a hypothetical: q95 leaves most pixels off-palette."""
        rendered = quantize(_gradient(), SPECTRA6, method="floyd-steinberg")
        buf = io.BytesIO()
        rendered.save(buf, format="JPEG", quality=95)
        buf.seek(0)
        illegal = _illegal_pixels(Image.open(buf))
        assert illegal > 10_000, (
            "if this ever drops to 0, JPEG became lossless and the refusal "
            "below should be revisited"
        )


class TestFormatRefusal:
    @staticmethod
    def _export(tmp_path, fmt: str):
        return sdcard.export(
            [],
            tmp_path,
            get_target("gooddisplay-315-diy"),
            master_for=lambda _wid: None,
            fmt=fmt,
        )

    @pytest.mark.parametrize("fmt", ["jpg", "jpeg", "JPEG", ".jpg"])
    def test_lossy_formats_are_refused(self, tmp_path, fmt: str) -> None:
        with pytest.raises(ValueError, match="lossy"):
            self._export(tmp_path, fmt)
        assert not list(tmp_path.iterdir()), "nothing may be written on refusal"

    def test_unknown_formats_are_still_refused(self, tmp_path) -> None:
        with pytest.raises(ValueError, match="unsupported format"):
            self._export(tmp_path, "tiff")

    def test_lossless_formats_are_accepted(self) -> None:
        assert {"png", "bmp"} == sdcard.LOSSLESS_FORMATS
        assert sdcard.LOSSY_FORMATS.isdisjoint(sdcard.LOSSLESS_FORMATS)


class TestPaletteConformanceAssertion:
    """The durable guard: catches the class, not just today's known hole."""

    class _Target:
        palette = SPECTRA6

    def test_conformant_render_passes(self) -> None:
        rendered = quantize(_gradient(), SPECTRA6, method="floyd-steinberg")
        sdcard._assert_palette_conformant(rendered, self._Target())

    def test_off_palette_buffer_is_refused(self) -> None:
        stray = Image.fromarray(
            np.full((8, 8, 3), 137, dtype=np.uint8), "RGB"
        )  # a grey that is in no palette
        with pytest.raises(ValueError, match="not palette-conformant"):
            sdcard._assert_palette_conformant(stray, self._Target())

    def test_a_single_stray_pixel_is_enough(self) -> None:
        rendered = quantize(_gradient(), SPECTRA6, method="floyd-steinberg")
        arr = np.asarray(rendered.convert("RGB")).copy()
        arr[0, 0] = (1, 2, 3)
        with pytest.raises(ValueError, match="not palette-conformant"):
            sdcard._assert_palette_conformant(Image.fromarray(arr, "RGB"), self._Target())
