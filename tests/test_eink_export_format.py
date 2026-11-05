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
import json
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from fine_art_archive.api import main as api_main
from fine_art_archive.api import store as api_store
from fine_art_archive.api.main import app
from fine_art_archive.eink import sdcard
from fine_art_archive.eink.palette import SPECTRA6, quantize
from fine_art_archive.eink.targets import TARGETS, RenderTarget, get_target


@pytest.mark.parametrize("strategy", ["color", "grayscale", "duotone"])
def test_export_applies_selected_strategy_with_native_palette(tmp_path, strategy):
    """Keep the issue's named export gate tied to real card pixels."""
    import json

    from fine_art_archive.display.render import gamut_render_evidence
    from fine_art_archive.eink.targets import RenderTarget

    image = Image.new("RGB", (40, 20), SPECTRA6.colours[2])
    if strategy == "grayscale":
        image.paste((255, 0, 255), (0, 0, 40, 20))
    elif strategy == "duotone":
        image.paste((255, 0, 255), (0, 0, 4, 20))
    assert gamut_render_evidence(image).strategy == strategy
    master = tmp_path / "master.png"
    image.save(master)
    target = RenderTarget("test", "Test", 40, 20, "spectra6")
    card = tmp_path / "card"
    report = sdcard.export(
        [sdcard.ExportItem("work")],
        card,
        target,
        master_for=lambda _: master,
        method="none",
        dry_run=False,
    )
    assert len(report.written) == 1, report.skipped
    manifest = json.loads((card / "playlist.json").read_text())
    assert manifest["items"][0]["render_strategy"] == strategy
    with Image.open(card / report.written[0]) as rendered:
        assert rendered.size == target.size
        present = set(rendered.convert("RGB").getdata())
        assert present <= set(target.palette.colours)
        endpoints = {target.palette.black, target.palette.white}
        if strategy == "color":
            assert present - endpoints
        else:
            assert present <= endpoints


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


_COUNT_FIRST = "aaa1111-first-work"
_COUNT_SECOND = "bbb2222-second-work"
_COUNT_SPEC = {"sort": "title"}
_EMPTY_SPEC = {"sort": "title", "artists": ["No Such Artist"]}


def _export_client_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    rows: list[tuple[str, str, bool]],
):
    """Isolated archive wired to the production export route."""
    works = tmp_path / "works"
    works.mkdir()
    monkeypatch.setattr(api_store, "WORKS", works)
    monkeypatch.setattr(api_main, "ART_WORKS_ROOT", works)
    monkeypatch.setattr(api_main, "IMAGE_CACHE_DIR", tmp_path / "image_cache")
    monkeypatch.setattr(api_main, "EINK_EXPORT_ROOTS", [tmp_path])
    monkeypatch.setattr(api_store, "RATINGS_LOG", tmp_path / "ratings.jsonl")
    monkeypatch.setattr(api_main, "_sidecars_cache", None)
    monkeypatch.setattr(api_main, "_ratings_cache", None)
    monkeypatch.setitem(
        TARGETS,
        "count-contract",
        RenderTarget("count-contract", "Count contract", 8, 6, "mono1bit"),
    )
    for work_id, title, master in rows:
        directory = works / work_id
        directory.mkdir()
        (directory / "meta.json").write_text(
            json.dumps(
                {
                    "work_id": work_id,
                    "title": title,
                    "artist": {"name": "A Painter"},
                    "year": "1650",
                    "subject": {},
                }
            ),
            encoding="utf-8",
        )
        if master:
            Image.new("RGB", (8, 6), (30, 60, 90)).save(directory / "master.jpeg", "JPEG")
    api_main._sidecars_cache = None
    return TestClient(app)


def _export_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, masters: tuple[bool, bool]):
    """Isolated two-work archive wired to the production export route."""
    return _export_client_rows(
        tmp_path,
        monkeypatch,
        [(_COUNT_FIRST, "First", masters[0]), (_COUNT_SECOND, "Second", masters[1])],
    )


def _write_card(client: TestClient, tmp_path: Path, spec: dict, name: str) -> tuple[Path, dict]:
    card = tmp_path / name
    response = client.post(
        "/eink/playlist/export",
        json={
            "spec": spec,
            "target": "count-contract",
            "dither": "none",
            "path": str(card),
            "write": True,
            "overwrite": True,
        },
    )
    assert response.status_code == 200, response.text
    return card, response.json()


@pytest.mark.parametrize(
    ("masters", "spec", "selected", "written", "omissions", "files"),
    [
        ((True, False), _COUNT_SPEC, 2, 1, 1, ["001_aaa1111-first-work.png"]),
        (
            (True, True),
            _COUNT_SPEC,
            2,
            2,
            0,
            ["001_aaa1111-first-work.png", "002_bbb2222-second-work.png"],
        ),
        ((False, False), _COUNT_SPEC, 2, 0, 2, []),
        ((True, False), _EMPTY_SPEC, 0, 0, 0, []),
    ],
    ids=["mixed", "all-master", "all-missing", "empty"],
)
def test_export_counts_follow_files_written_not_master_availability(
    tmp_path, monkeypatch, masters, spec, selected, written, omissions, files
):
    """The card reports the writer's files and missing-master skips.

    ``selected`` still counts every chosen work. ``written`` and the files on
    disk are the observed write. These fixtures have no render failure, so
    ``missing_master_omissions`` happens to equal ``selected - written``;
    the render-failure test below is what separates those two numbers.
    """
    client = _export_client(tmp_path, monkeypatch, masters)
    card, body = _write_card(client, tmp_path, spec, "card")

    assert body["selected"] == selected
    assert body["written"] == written
    assert body["dry_run"] is False
    assert body["missing_master_omissions"] == omissions
    assert sorted(path.name for path in card.glob("*.png")) == files
    if files:
        manifest = json.loads((card / "playlist.json").read_text(encoding="utf-8"))
        assert manifest["count"] == written
        assert [row["file"] for row in manifest["items"]] == files
        assert body["bytes_written"] > 0
    else:
        assert not (card / "playlist.json").exists()
        assert body["bytes_written"] == 0
    if masters == (True, False) and spec == _COUNT_SPEC:
        assert body["skipped_detail"] == [[_COUNT_SECOND, "no local master image"]]
        assert body["skipped"] == 1


@pytest.mark.parametrize("write", [None, False], ids=["default-dry-run", "explicit-dry-run"])
@pytest.mark.parametrize(
    ("masters", "spec", "selected", "planned_ids", "missing_ids"),
    [
        ((True, False), _COUNT_SPEC, 2, [_COUNT_FIRST], [_COUNT_SECOND]),
        ((True, True), _COUNT_SPEC, 2, [_COUNT_FIRST, _COUNT_SECOND], []),
        ((False, False), _COUNT_SPEC, 2, [], [_COUNT_FIRST, _COUNT_SECOND]),
        ((True, False), _EMPTY_SPEC, 0, [], []),
    ],
    ids=["mixed", "all-master", "all-missing", "empty"],
)
def test_export_dry_run_reports_planned_counts_without_writing(
    tmp_path, monkeypatch, write, masters, spec, selected, planned_ids, missing_ids
):
    """The production dry-run response describes a plan, with no files written.

    Exercise both an omitted write flag and an explicit false value. The UI
    relies on ``dry_run`` to display zero actually written even when the
    writer reports a nonzero planned ``written`` count.
    """
    client = _export_client(tmp_path, monkeypatch, masters)
    card = tmp_path / "dry-run-card"
    request = {
        "spec": spec,
        "target": "count-contract",
        "dither": "none",
        "path": str(card),
    }
    if write is not None:
        request["write"] = write
    response = client.post("/eink/playlist/export", json=request)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["selected"] == selected
    assert body["dry_run"] is True
    assert body["written"] == len(planned_ids)
    assert body["missing_master_omissions"] == len(missing_ids)
    assert body["skipped"] == len(missing_ids)
    assert body["skipped_detail"] == [[wid, "no local master image"] for wid in missing_ids]
    assert [row["work_id"] for row in body["render_evidence"]] == planned_ids
    assert body["bytes_written"] == 0
    assert body["removed"] == 0
    assert not card.exists(), "a dry run must not create card images or manifests"


def test_render_failure_is_not_a_missing_master_or_a_successful_write(tmp_path, monkeypatch):
    """A master file that cannot be rendered is not delivered and not 'missing'.

    Both master files exist, so master availability is 2. The writer saves
    one image and records a render failure for the other. ``written`` is that
    file, and ``missing_master_omissions`` stays 0 rather than becoming
    ``selected - written``.
    """
    client = _export_client(tmp_path, monkeypatch, (True, True))
    first_master = tmp_path / "works" / _COUNT_FIRST / "master.jpeg"
    second_master = tmp_path / "works" / _COUNT_SECOND / "master.jpeg"
    second_master.write_bytes(b"not a jpeg")
    assert first_master.is_file()
    assert second_master.is_file()

    card, body = _write_card(client, tmp_path, _COUNT_SPEC, "render-fail")

    assert body["selected"] == 2
    assert body["written"] == 1
    assert body["dry_run"] is False
    assert body["missing_master_omissions"] == 0
    assert body["skipped"] == 1
    assert body["skipped_detail"][0][0] == _COUNT_SECOND
    assert str(body["skipped_detail"][0][1]).startswith("render failed:")
    assert sorted(path.name for path in card.glob("*.png")) == ["001_aaa1111-first-work.png"]
    manifest = json.loads((card / "playlist.json").read_text(encoding="utf-8"))
    assert manifest["count"] == 1
    assert [row["work_id"] for row in manifest["items"]] == [_COUNT_FIRST]


def test_missing_master_omissions_count_past_the_skipped_detail_cap(tmp_path, monkeypatch):
    """Omissions count the full writer record, not the capped detail list.

    Twenty-one works have no master and one has a corrupt master file. Title
    order puts the corrupt file first, so ``skipped_detail`` holds that render
    failure plus nineteen missing-master rows and drops the last two skips.
    ``missing_master_omissions`` still counts all twenty-one missing masters
    and leaves the render failure out.
    """
    corrupt_id = "ccc0000-corrupt-master"
    rows = [(corrupt_id, "A Corrupt", True)]
    rows.extend(
        (f"mmm{index:02d}-missing-master", f"Missing {index:02d}", False) for index in range(21)
    )
    client = _export_client_rows(tmp_path, monkeypatch, rows)
    corrupt_master = tmp_path / "works" / corrupt_id / "master.jpeg"
    corrupt_master.write_bytes(b"not a jpeg")
    assert corrupt_master.is_file()

    card, body = _write_card(client, tmp_path, _COUNT_SPEC, "detail-cap")

    assert body["selected"] == 22
    assert body["written"] == 0
    assert body["dry_run"] is False
    assert body["skipped"] == 22
    assert body["missing_master_omissions"] == 21
    assert len(body["skipped_detail"]) == 20
    reasons = [reason for _work_id, reason in body["skipped_detail"]]
    assert reasons[0].startswith("render failed:")
    assert reasons[1:] == ["no local master image"] * 19
    assert body["skipped_detail"][0][0] == corrupt_id
    assert body["bytes_written"] == 0
    assert list(card.glob("*.png")) == []
    assert not (card / "playlist.json").exists()
