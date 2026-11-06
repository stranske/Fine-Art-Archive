"""Gates for the e-paper render + playlist + SD-card pipeline.

Each test here corresponds to something that actually went wrong while building
it, because those are the failures worth locking down:

* zero-padding the PIL palette let a stray #000000 pixel into 2 of 4 renders —
  a colour no reflective panel can produce;
* `artist.canonical` is a resolver RECORD, not a string, and treating it as one
  raised AttributeError on nearly every work;
* per-pixel error says dithering makes images WORSE, which inverts the real
  answer and would mislead anyone tuning the pipeline.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess

import pytest
from PIL import Image

from fine_art_archive.eink import (
    SPECTRA6,
    ExportItem,
    PlaylistSpec,
    build,
    dither_error,
    export,
    get_palette,
    get_target,
    order_series_members,
    quantize,
)
from fine_art_archive.eink.palette import Palette
from fine_art_archive.eink.playlist import _artist_of, parse_year
from fine_art_archive.eink.targets import fit_to_target, render_for_target


def gradient(w: int = 320, h: int = 200) -> Image.Image:
    """A smooth two-axis gradient — the case nearest-colour posterises worst."""
    img = Image.new("RGB", (w, h))
    px = img.load()
    for y in range(h):
        for x in range(w):
            px[x, y] = (
                int(255 * x / (w - 1)),
                int(255 * y / (h - 1)),
                int(255 * (1 - x / (w - 1))),
            )
    return img


# ---------------------------------------------------------------- palette ----
@pytest.mark.parametrize("palette_name", ["spectra6", "kaleido3", "mono1bit", "gray16"])
@pytest.mark.parametrize("method", ["none", "floyd-steinberg", "atkinson"])
def test_output_contains_only_palette_colours(palette_name, method):
    """The bug: zero-padded palette entries leaked pure #000000 into output."""
    pal = get_palette(palette_name)
    out = quantize(gradient(96, 64), pal, method=method)
    ok, illegal = pal.contains_only(out)
    assert ok, f"{palette_name}/{method} emitted non-palette colours: {illegal}"


def test_pil_palette_image_never_pads_with_black():
    pal_img = SPECTRA6.as_pil_palette_image()
    entries = pal_img.getpalette()
    legal = {tuple(c) for c in SPECTRA6.colours}
    for i in range(256):
        assert tuple(entries[i * 3 : i * 3 + 3]) in legal, f"entry {i} is not a palette colour"


def test_empty_palette_is_rejected_early():
    with pytest.raises(ValueError, match="at least one"):
        Palette("empty", ())


def test_white_is_not_pure_white_for_reflective_colour_palettes():
    """A panel that cannot render #FFFFFF must not be told that it can."""
    assert SPECTRA6.white != (255, 255, 255)
    assert SPECTRA6.black != (0, 0, 0)


def test_palettes_declare_themselves_unmeasured():
    """Estimated primaries must never silently pass as measured ones."""
    for name in ("spectra6", "kaleido3", "mono1bit", "gray16"):
        assert get_palette(name).measured is False


# ---------------------------------------------------------------- dither -----
def test_dithering_beats_nearest_colour_perceptually():
    """The metric that matters. Per-pixel error says the opposite — see docstring."""
    pal = SPECTRA6
    src = gradient()
    plain = dither_error(src, quantize(src, pal, method="none"))
    fs = dither_error(src, quantize(src, pal, method="floyd-steinberg"))
    assert (
        fs["perceived_error"] < plain["perceived_error"]
    ), "dithering should reduce PERCEIVED error"
    # And the counter-intuitive half, asserted so nobody "fixes" it later:
    assert fs["per_pixel_mean"] > plain["per_pixel_mean"], (
        "dithering is expected to INCREASE per-pixel error; that is the "
        "mechanism, not a regression"
    )


def test_dither_error_rejects_mismatched_sizes():
    with pytest.raises(ValueError):
        dither_error(gradient(32, 32), gradient(64, 64))


# `None` is deliberately NOT in this list any more: since N-E3 it is the valid
# "derive the radius from the viewing geometry, or fall back to the default"
# value, not a rejected one. -1/nan/inf are still refused.
@pytest.mark.parametrize("radius", [-1, float("nan"), float("inf")])
def test_dither_error_rejects_invalid_blur_radius(radius):
    with pytest.raises(ValueError, match="finite non-negative"):
        dither_error(gradient(32, 32), gradient(32, 32), radius)


# ---------------------------------------------------------------- targets ----
def test_fit_contain_letterboxes_in_panel_white_not_ffffff():
    t = get_target("gooddisplay-315-diy")  # 2560x1440 landscape
    tall = Image.new("RGB", (400, 1200), (10, 200, 10))
    out = fit_to_target(tall, t, fit="contain")
    assert out.size == t.size
    assert out.getpixel((2, 2)) == t.palette.white  # bar colour, not (255,255,255)


def test_fit_cover_fills_frame_and_crops():
    t = get_target("gooddisplay-315-diy")
    out = fit_to_target(Image.new("RGB", (400, 1200), (10, 200, 10)), t, fit="cover")
    assert out.size == t.size
    assert out.getpixel((2, 2)) == (10, 200, 10)  # no bars


def test_render_for_target_end_to_end_is_palette_clean():
    t = get_target("generic-mono-1bit")
    out = render_for_target(gradient(), t)
    assert out.size == t.size
    ok, illegal = t.palette.contains_only(out)
    assert ok, illegal


def test_unknown_names_raise_rather_than_defaulting():
    """A typo must not silently render to the wrong device."""
    with pytest.raises(KeyError):
        get_target("no-such-panel")
    with pytest.raises(KeyError):
        get_palette("no-such-palette")


# --------------------------------------------------------------- playlist ----
def sidecar(wid, *, artist=None, canonical=None, year=None, genre=None, tags=(), title="T"):
    a: dict = {}
    if artist:
        a["name"] = artist
    if canonical:
        a["canonical"] = canonical
    return (
        wid,
        {
            "work_id": wid,
            "title": title,
            "year": year,
            "artist": a,
            "subject": {
                "genre": genre,
                "content_tags": [{"id": t, "state": "proposed", "source": "x"} for t in tags],
            },
        },
    )


def test_artist_canonical_is_a_record_not_a_string():
    """The bug: .strip() on a dict raised AttributeError for most works."""
    _, sc = sidecar(
        "w",
        artist="Jacob von Ruisdael",
        canonical={"display_name": "Jacob van Ruisdael", "wikidata_q": "Q1", "confidence": 0.9},
    )
    assert _artist_of(sc) == "Jacob van Ruisdael"


def test_artist_filter_unifies_source_spelling_variants():
    """The whole point: 'van Ruisdael' and 'Jacob von Ruisdael' are one artist."""
    canon = {"display_name": "Jacob van Ruisdael"}
    rows = [
        sidecar("a", artist="Jacob von Ruisdael", canonical=canon, year=1650),
        sidecar("b", artist="van Ruisdael", canonical=canon, year=1660),
        sidecar("c", artist="Rembrandt", canonical={"display_name": "Rembrandt"}),
    ]
    res = build(rows, PlaylistSpec(artists=["Jacob van Ruisdael"], sort="year"))
    assert res.work_ids == ["a", "b"]


def test_artist_sort_preserves_astronomical_year_zero():
    rows = [
        sidecar("year-1500", artist="Same Artist", year=1500),
        sidecar("year-zero", artist="Same Artist", year=0),
    ]

    result = build(rows, PlaylistSpec(sort="artist"))

    assert result.work_ids == ["year-zero", "year-1500"]


@pytest.mark.parametrize(
    "raw,expected",
    [
        (0, 0),
        (1648, 1648),
        ("1648", 1648),
        ("c. 1648", 1648),
        ("1648–1650", 1648),
        ("oil on canvas", None),
        (None, None),
        ("", None),
        ("12", None),
        ("300", 300),
        ("2100", 2100),
        ("299", None),
        ("2101", None),
        (False, None),
    ],
)
def test_parse_year_handles_real_record_messiness(raw, expected):
    assert parse_year(raw) == expected


def test_mood_is_a_query_over_tags_that_exist():
    rows = [
        sidecar("night", tags=["setting:night"]),
        sidecar("day", tags=["setting:outdoor"]),
    ]
    res = build(rows, PlaylistSpec(moods=["nocturne"]))
    assert res.work_ids == ["night"]


def test_mood_not_tags_excludes():
    rows = [
        sidecar("calm", tags=["setting:interior"], genre="painting/still-life"),
        sidecar("violent", tags=["setting:interior", "filter:violence"]),
    ]
    res = build(rows, PlaylistSpec(moods=["quiet-interior"]))
    assert res.work_ids == ["calm"]


def test_period_filter_and_missing_year_is_reported_not_hidden():
    rows = [
        sidecar("in", year=1650),
        sidecar("out", year=1850),
        sidecar("noyear", year=None),
    ]
    res = build(rows, PlaylistSpec(periods=["golden-age"]))
    assert res.work_ids == ["in"]
    assert res.coverage["excluded_for_missing_metadata"]["no year"] == 1


@pytest.mark.parametrize(
    "year_from,year_to,expected",
    [
        (None, 0, ["minus-one", "zero"]),
        (0, None, ["zero", "one"]),
        (0, 0, ["zero"]),
    ],
    ids=["upper-only", "lower-only", "double-zero"],
)
def test_year_zero_bounds_filter_and_report_missing_year(year_from, year_to, expected):
    """An explicit bound of 0 is a real bound, not "no filter" (#806)."""
    rows = [
        sidecar("minus-one", year=-1),
        sidecar("zero", year=0),
        sidecar("one", year=1),
        sidecar("undated", year=None),
    ]
    res = build(rows, PlaylistSpec(year_from=year_from, year_to=year_to, sort="year"))
    assert res.work_ids == expected
    assert res.coverage["excluded_for_missing_metadata"]["no year"] == 1


def test_year_zero_omitted_bounds_leave_the_date_filter_off():
    rows = [
        sidecar("minus-one", year=-1),
        sidecar("zero", year=0),
        sidecar("one", year=1),
        sidecar("undated", year=None),
    ]
    res = build(rows, PlaylistSpec(sort="year"))
    assert set(res.work_ids) == {"minus-one", "zero", "one", "undated"}
    assert "no year" not in res.coverage["excluded_for_missing_metadata"]


@pytest.mark.parametrize("field,value", [("year_from", ""), ("year_to", "0"), ("year_from", True)])
def test_year_bounds_reject_non_integer_values_before_filtering(field, value):
    with pytest.raises(ValueError, match=f"{field} must be an integer or null"):
        PlaylistSpec.from_dict({field: value})


@pytest.mark.parametrize(
    "year_from,year_to,expected",
    [
        (None, 0, set()),
        (0, 0, set()),
        (None, None, {"dated", "undated"}),
    ],
    ids=["upper-zero", "double-zero", "no-date-filter"],
)
def test_year_zero_bounds_on_schema_shaped_string_years(year_from, year_to, expected):
    rows = [sidecar("dated", year="1500"), sidecar("undated", year=None)]
    res = build(rows, PlaylistSpec(year_from=year_from, year_to=year_to))
    assert set(res.work_ids) == expected


def test_exclude_filters_accepts_bare_or_prefixed_names():
    rows = [sidecar("nude", tags=["filter:nudity-full"]), sidecar("clean", tags=[])]
    for spec in (["nudity-full"], ["filter:nudity-full"]):
        assert build(rows, PlaylistSpec(exclude_filters=spec)).work_ids == ["clean"]


def test_rating_filter_uses_fit_and_reports_unrated():
    rows = [sidecar("hi"), sidecar("lo"), sidecar("unrated")]
    ratings = {"hi": {"fit": 9, "quality": 5}, "lo": {"fit": 3, "quality": 10}}
    res = build(rows, PlaylistSpec(min_fit=8), ratings=ratings)
    assert res.work_ids == ["hi"]
    assert res.coverage["excluded_for_missing_metadata"]["unrated (fit)"] == 1


def test_preference_diverse_playlist_filters_then_selects():
    rows = [
        sidecar("near-a", artist="Included"),
        sidecar("near-b", artist="Included"),
        sidecar("diverse", artist="Included"),
        sidecar("filtered", artist="Excluded"),
    ]
    qualities = {"near-a": 1.0, "near-b": 0.99, "diverse": 0.85}
    embeddings = {
        "near-a": [1.0, 0.0],
        "near-b": [0.999, 0.04],
        "diverse": [0.0, 1.0],
    }

    result = build(
        rows,
        PlaylistSpec(
            artists=["Included"],
            selection_mode="preference-diverse",
            limit=2,
            seed=17,
        ),
        quality_scores=qualities,
        embeddings=embeddings,
    )

    assert result.matched == 3
    assert result.work_ids == ["near-a", "diverse"]
    assert [item["work_id"] for item in result.selection_diagnostics] == result.work_ids


def test_playlist_preview_matches_direct_diverse_selection(tmp_path, monkeypatch):
    from fine_art_archive.api import main as api_main
    from fine_art_archive.preference.exhibition import select_quality_diverse

    rows = [sidecar(work_id) for work_id in ("near-a", "near-b", "diverse")]
    qualities = {"near-a": 1.0, "near-b": 0.99, "diverse": 0.85}
    embeddings = {
        "near-a": [1.0, 0.0],
        "near-b": [0.999, 0.04],
        "diverse": [0.0, 1.0],
    }
    direct = select_quality_diverse(
        [work_id for work_id, _meta in rows], qualities, embeddings, 2, seed=17
    )
    monkeypatch.setattr(api_main, "_all_sidecars", lambda: rows)
    monkeypatch.setattr(api_main.store, "RATINGS_LOG", tmp_path / "absent.jsonl")
    monkeypatch.setattr(api_main.store, "work_ids_with_dossier", frozenset)

    response = api_main.eink_playlist_preview(
        api_main.PlaylistIn(
            spec={"selection_mode": "preference-diverse", "limit": 2, "seed": 17},
            quality_scores=qualities,
            embeddings=embeddings,
        )
    )

    assert response["work_ids"] == direct.selected_ids
    assert [item["work_id"] for item in response["selection_diagnostics"]] == direct.selected_ids


_PREVIEW_EVIDENCE_FIELDS = ("render_strategy", "render_strategy_reason", "gamut_verdict")


def _temporary_preview_archive(tmp_path, monkeypatch):
    """Two sidecars and one temporary master. The second work has no image."""
    from fine_art_archive.api import main as api_main

    masters = tmp_path / "works"
    held = masters / "held-master"
    held.mkdir(parents=True)
    Image.new("RGB", (48, 32), (180, 40, 40)).save(held / "master.png")
    (masters / "missing-master").mkdir()
    rows = [
        sidecar("held-master", artist="Included", title="Held", year=1650),
        sidecar("missing-master", artist="Included", title="Missing", year=1660),
    ]
    ratings = tmp_path / "ratings.jsonl"
    ratings.write_text("")
    monkeypatch.setattr(api_main, "_all_sidecars", lambda: rows)
    monkeypatch.setattr(api_main.store, "RATINGS_LOG", ratings)
    monkeypatch.setattr(api_main.store, "work_ids_with_dossier", frozenset)
    monkeypatch.setattr(api_main, "ART_WORKS_ROOT", masters)
    return api_main


def _preview_evidence(payload: dict) -> list[dict]:
    return [
        {
            "work_id": item["work_id"],
            "has_master": item["has_master"],
            **{key: item.get(key) for key in _PREVIEW_EVIDENCE_FIELDS},
        }
        for item in payload["items"]
    ]


def test_playlist_preview_reports_resolved_target_and_stable_spectra6_evidence(
    tmp_path, monkeypatch
):
    """Outcome 1: valid panels share selection and master-derived evidence."""
    from fastapi.testclient import TestClient

    api_main = _temporary_preview_archive(tmp_path, monkeypatch)
    client = TestClient(api_main.app)
    spec = {"sort": "year"}
    bodies = []
    for target in ("gooddisplay-315-diy", "generic-mono-1bit"):
        response = client.post(
            "/eink/playlist/preview",
            json={"spec": spec, "target": target, "sample": 24},
        )
        assert response.status_code == 200, response.text
        bodies.append(response.json())

    color, mono = bodies
    assert color["target"] == "gooddisplay-315-diy"
    assert mono["target"] == "generic-mono-1bit"
    for body in bodies:
        assert body["evidence_calibration"] == "Spectra-6"
        assert body["evidence_scope"] == "master-derived and target-independent"
        for key in (
            "total_candidates",
            "matched",
            "selected",
            "coverage",
            "facets",
            "selection_diagnostics",
            "items",
            "work_ids",
        ):
            assert key in body
    assert color["work_ids"] == mono["work_ids"] == ["held-master", "missing-master"]
    assert _preview_evidence(color) == _preview_evidence(mono)
    held = color["items"][0]
    assert held["has_master"] is True
    assert held["render_strategy"]
    assert held["gamut_verdict"]
    assert held["render_strategy_reason"]
    missing = color["items"][1]
    assert missing == {
        "work_id": "missing-master",
        "title": "Missing",
        "artist": "Included",
        "year": 1660,
        "has_master": False,
    }

    omitted = client.post("/eink/playlist/preview", json={"spec": spec, "sample": 24})
    assert omitted.status_code == 200, omitted.text
    assert omitted.json()["target"] == "gooddisplay-315-diy"
    assert omitted.json()["work_ids"] == color["work_ids"]
    assert _preview_evidence(omitted.json()) == _preview_evidence(color)

    zero = client.post(
        "/eink/playlist/preview",
        json={"spec": spec, "target": "generic-mono-1bit", "sample": 0},
    )
    assert zero.status_code == 200, zero.text
    zero_body = zero.json()
    assert zero_body["target"] == "generic-mono-1bit"
    assert zero_body["evidence_calibration"] == "Spectra-6"
    assert zero_body["evidence_scope"] == "master-derived and target-independent"
    assert zero_body["items"] == []
    assert zero_body["work_ids"] == color["work_ids"]
    assert zero_body["selected"] == color["selected"]


def test_playlist_preview_unknown_target_returns_400_including_sample_zero(tmp_path, monkeypatch):
    """Unknown panels are rejected before selection, including an empty sample."""
    from fastapi.testclient import TestClient

    api_main = _temporary_preview_archive(tmp_path, monkeypatch)
    calls = []
    real_build = api_main._build_eink_playlist

    def counting_build(*args, **kwargs):
        calls.append(args)
        return real_build(*args, **kwargs)

    monkeypatch.setattr(api_main, "_build_eink_playlist", counting_build)
    client = TestClient(api_main.app)
    for sample in (24, 0):
        response = client.post(
            "/eink/playlist/preview",
            json={"spec": {"sort": "year"}, "target": "not-a-panel", "sample": sample},
        )
        assert response.status_code == 400, response.text
        assert "unknown render target" in response.json()["detail"]
        assert "not-a-panel" in response.json()["detail"]
    assert calls == []


def test_random_sort_is_seeded_so_a_card_is_reproducible():
    rows = [sidecar(f"w{i}") for i in range(30)]
    a = build(rows, PlaylistSpec(sort="random", seed=7)).work_ids
    b = build(rows, PlaylistSpec(sort="random", seed=7)).work_ids
    c = build(rows, PlaylistSpec(sort="random", seed=8)).work_ids
    assert a == b and a != c


def test_unknown_spec_field_raises_rather_than_being_ignored():
    """A typo'd facet must not yield an unfiltered playlist that looks filtered."""
    with pytest.raises(ValueError):
        PlaylistSpec.from_dict({"artistz": ["x"]})


def test_unknown_mood_and_period_raise():
    with pytest.raises(KeyError):
        build([sidecar("w")], PlaylistSpec(moods=["nope"]))
    with pytest.raises(KeyError):
        build([sidecar("w")], PlaylistSpec(periods=["nope"]))


def test_series_order_uses_evidence_and_reports_missing_and_duplicates():
    rows = [
        ("third", {"series": {"position": 3}}),
        ("unknown-a", {}),
        ("first-a", {"series": {"position": 1}}),
        ("first-b", {"series": {"position": 1}}),
        ("unknown-b", {"series": None}),
    ]

    result = order_series_members(rows)

    assert result.work_ids == ["first-a", "first-b", "third", "unknown-a", "unknown-b"]
    assert result.missing_positions == ["unknown-a", "unknown-b"]
    assert result.duplicate_positions == {1: ["first-a", "first-b"]}


def test_corrupt_ratings_line_does_not_sink_the_playlist(tmp_path):
    from fine_art_archive.eink import load_ratings

    p = tmp_path / "r.jsonl"
    p.write_text('{"work_id":"a","fit":9}\nNOT JSON\n{"work_id":"b","fit":4}\n')
    r = load_ratings(p)
    assert r["a"]["fit"] == 9 and r["b"]["fit"] == 4


def test_nan_rating_is_not_treated_as_a_value(tmp_path):
    from fine_art_archive.eink import load_ratings

    p = tmp_path / "r.jsonl"
    p.write_text('{"work_id":"a","fit":NaN,"quality":7}\n')
    r = load_ratings(p)
    assert "fit" not in r["a"] and r["a"]["quality"] == 7


def test_infinite_rating_is_not_treated_as_a_value(tmp_path):
    from fine_art_archive.eink import load_ratings

    p = tmp_path / "r.jsonl"
    p.write_text('{"work_id":"a","fit":Infinity,"quality":7}\n')
    r = load_ratings(p)
    assert "fit" not in r["a"] and r["a"]["quality"] == 7


# ----------------------------------------------------------------- card ------
def _master_factory(tmp_path):
    src = tmp_path / "masters"
    src.mkdir()
    gradient(200, 140).save(src / "w1.png")
    gradient(140, 200).save(src / "w2.png")
    return lambda wid: (src / f"{wid}.png") if (src / f"{wid}.png").exists() else None


def test_export_writes_ordered_playable_card(tmp_path):
    card = tmp_path / "card"
    items = [ExportItem("w1", "One", "A", 1600), ExportItem("w2", "Two", "B", 1700)]
    rep = export(
        items,
        card,
        get_target("generic-mono-1bit"),
        master_for=_master_factory(tmp_path),
        dry_run=False,
    )
    names = sorted(p.name for p in card.glob("*.png"))
    assert names == ["001_w1.png", "002_w2.png"], "ordinal prefix IS the play order"
    assert rep.bytes_written > 0
    manifest = json.loads((card / "playlist.json").read_text())
    assert manifest["count"] == 2
    assert [i["work_id"] for i in manifest["items"]] == ["w1", "w2"]
    assert (card / "playlist.m3u").read_text().splitlines() == names
    # An unmeasured palette must warn on the card itself, not just in our docs.
    assert manifest["palette_measured"] is False
    assert manifest["palette_warning"]
    assert "ESTIMATED" in (card / "README.txt").read_text()


def test_export_dry_run_writes_nothing(tmp_path):
    card = tmp_path / "card"
    rep = export(
        [ExportItem("w1")],
        card,
        get_target("generic-mono-1bit"),
        master_for=_master_factory(tmp_path),
        dry_run=True,
    )
    assert rep.written == ["001_w1.png"]
    assert not card.exists() or not list(card.glob("*.png"))


def test_export_refuses_to_clobber_without_overwrite(tmp_path):
    card = tmp_path / "card"
    mf = _master_factory(tmp_path)
    t = get_target("generic-mono-1bit")
    export([ExportItem("w1")], card, t, master_for=mf, dry_run=False)
    with pytest.raises(FileExistsError):
        export([ExportItem("w2")], card, t, master_for=mf, dry_run=False)


def test_export_never_deletes_files_it_did_not_write(tmp_path):
    """Someone's photos must survive an --overwrite of a shared card."""
    card = tmp_path / "card"
    mf = _master_factory(tmp_path)
    t = get_target("generic-mono-1bit")
    export([ExportItem("w1")], card, t, master_for=mf, dry_run=False)
    precious = card / "HOLIDAY_PHOTOS.jpg"
    precious.write_bytes(b"not ours")
    sub = card / "DCIM"
    sub.mkdir()
    rep = export([ExportItem("w2")], card, t, master_for=mf, dry_run=False, overwrite=True)
    assert precious.exists(), "an unrelated file was deleted"
    assert sub.is_dir(), "an unrelated directory was removed"
    assert "001_w1.png" in rep.removed


def test_export_reports_missing_master_instead_of_failing(tmp_path):
    rep = export(
        [ExportItem("w1"), ExportItem("ghost")],
        tmp_path / "c",
        get_target("generic-mono-1bit"),
        master_for=_master_factory(tmp_path),
        dry_run=False,
    )
    assert rep.written == ["001_w1.png"]
    assert rep.skipped and rep.skipped[0][0] == "ghost"


def test_export_numbers_by_written_count_when_earlier_items_skip(tmp_path):
    """Skipped works must not leave gaps in filenames or manifest order."""
    card = tmp_path / "card"
    items = [ExportItem("ghost"), ExportItem("w1"), ExportItem("w2")]
    rep = export(
        items,
        card,
        get_target("generic-mono-1bit"),
        master_for=_master_factory(tmp_path),
        dry_run=False,
    )
    assert rep.written == ["001_w1.png", "002_w2.png"]
    assert rep.skipped and rep.skipped[0][0] == "ghost"
    manifest = json.loads((card / "playlist.json").read_text())
    assert [i["order"] for i in manifest["items"]] == [1, 2]
    assert [i["file"] for i in manifest["items"]] == ["001_w1.png", "002_w2.png"]


@pytest.mark.parametrize("kwargs", [{"fit": "conatin"}, {"method": "nope"}])
def test_export_rejects_invalid_render_settings(tmp_path, kwargs):
    with pytest.raises(ValueError):
        export(
            [ExportItem("w1")],
            tmp_path / "card",
            get_target("generic-mono-1bit"),
            master_for=_master_factory(tmp_path),
            dry_run=False,
            **kwargs,
        )


def test_export_rejects_unsafe_work_id_before_writing(tmp_path):
    with pytest.raises(ValueError, match="unsafe work_id"):
        export(
            [ExportItem("../outside")],
            tmp_path / "card",
            get_target("generic-mono-1bit"),
            master_for=_master_factory(tmp_path),
            dry_run=False,
        )


def test_coerce_fit_treats_empty_string_as_unset():
    from fine_art_archive.eink.targets import coerce_fit

    assert coerce_fit(None) is None
    assert coerce_fit("") is None
    assert coerce_fit("contain") == "contain"
    with pytest.raises(ValueError):
        coerce_fit("nope")


# ------------------------------------------------------- feed + facets -------
from datetime import UTC, datetime, timedelta  # noqa: E402

from fine_art_archive.eink import (  # noqa: E402
    INTERVALS,
    PlaylistStore,
    SavedPlaylist,
    build_manifest,
    discover_facets,
    item_etag,
    rotation_index,
    slugify,
)


def test_facets_are_discovered_from_data_not_declared():
    """The point of the whole facet layer: new tag families appear by themselves."""
    rows = [
        sidecar("a", genre="painting/landscape", tags=["setting:night", "mood-new:brooding"]),
        sidecar("b", genre="painting/landscape", tags=["setting:night"]),
        sidecar("c", tags=["brand-new-family:some-value"]),
    ]
    f = discover_facets(rows)
    fams = f["families"]
    assert fams["setting"]["values"][0] == {"value": "night", "tag": "setting:night", "count": 2}
    # A family invented after this test was written must still surface.
    assert "brand-new-family" in fams, "a new tag family must appear without a code change"
    assert "mood-new" in fams
    assert fams["genre"]["count"] == 2


def test_facets_skip_non_dict_content_tags():
    rows = [
        (
            "messy",
            {
                "subject": {
                    "content_tags": ["legacy-string-tag", {"id": "setting:night"}, None],
                }
            },
        ),
    ]
    f = discover_facets(rows)
    assert f["families"]["setting"]["count"] == 1


def test_facets_report_real_counts_so_an_empty_filter_reads_as_empty():
    rows = [sidecar("a", tags=["palette:cool-toned"])]
    f = discover_facets(rows)
    assert f["families"]["palette"]["count"] == 1
    # Curated moods still declare which tags they rest on, so a mood with no
    # coverage is legible rather than mysteriously returning nothing.
    nocturne = next(m for m in f["moods"] if m["key"] == "nocturne")
    assert "setting:night" in nocturne["uses"]


def test_facets_year_range_ignores_unparseable_years():
    rows = [
        sidecar("a", year=1648),
        sidecar("b", year="oil on canvas"),
        sidecar("c", year="c. 1700"),
    ]
    f = discover_facets(rows)
    assert f["year_range"] == [1648, 1700]
    assert f["years_known"] == 2


# ---- rotation: the property a dumb one-URL panel depends on -----------------
def test_rotation_is_stable_within_an_interval_and_advances_after():
    t0 = datetime(2026, 8, 6, 3, 0, tzinfo=UTC)
    a = rotation_index(5, "daily", now=t0)
    b = rotation_index(5, "daily", now=t0 + timedelta(hours=6))
    c = rotation_index(5, "daily", now=t0 + timedelta(days=1))
    assert a == b, "a panel polling twice in one day must see the same work"
    assert c != a, "the next day must advance"


def test_rotation_is_deterministic_across_processes():
    """Two frames that never talk must agree — so no server-side cursor."""
    t = datetime(2026, 1, 1, tzinfo=UTC)
    assert rotation_index(7, "daily", now=t) == rotation_index(7, "daily", now=t)


def test_rotation_offset_separates_two_frames_in_one_room():
    t = datetime(2026, 1, 1, tzinfo=UTC)
    assert rotation_index(9, "daily", now=t) != rotation_index(9, "daily", now=t, offset=1)


def test_rotation_survives_empty_and_single_item_playlists():
    assert rotation_index(0, "daily") == 0
    assert rotation_index(1, "daily") == 0


def test_rotation_cycles_through_every_item():
    t = datetime(2026, 3, 1, tzinfo=UTC)
    seen = {rotation_index(4, "daily", now=t + timedelta(days=d)) for d in range(8)}
    assert seen == {0, 1, 2, 3}, "every work must eventually be shown"


@pytest.mark.parametrize("interval", sorted(INTERVALS))
def test_every_declared_interval_actually_rotates(interval):
    t = datetime(2026, 5, 5, tzinfo=UTC)
    later = t + timedelta(seconds=INTERVALS[interval])
    assert rotation_index(3, interval, now=t) != rotation_index(3, interval, now=later)


# ---- etag ------------------------------------------------------------------
def test_etag_changes_when_the_master_or_render_settings_change(monkeypatch):
    from fine_art_archive.eink.targets import TARGETS, RenderTarget

    t1 = RenderTarget("t1", "ETag t1", 30, 20, "spectra6")
    t2 = RenderTarget("t2", "ETag t2", 30, 20, "spectra6")
    monkeypatch.setitem(TARGETS, t1.key, t1)
    monkeypatch.setitem(TARGETS, t2.key, t2)
    base = item_etag("w1", "t1", "floyd-steinberg", 1000, fit="contain")
    assert base == item_etag("w1", "t1", "floyd-steinberg", 1000, fit="contain")
    assert base != item_etag("w1", "t1", "floyd-steinberg", 1001, fit="contain")
    assert base != item_etag("w1", "t2", "floyd-steinberg", 1000, fit="contain")
    assert base != item_etag("w1", "t1", "atkinson", 1000, fit="contain")
    assert base != item_etag("w1", "t1", "floyd-steinberg", 1000, fit="cover")
    assert base != item_etag("w1", "t1", "floyd-steinberg", 1000, fit="stretch")


@pytest.mark.parametrize("default_fit", ["contain", "cover", "stretch"])
def test_etag_unset_fit_matches_explicit_target_default(monkeypatch, default_fit):
    from fine_art_archive.eink.targets import TARGETS, RenderTarget

    target = RenderTarget("etag-default", "ETag default", 30, 20, "spectra6", fit=default_fit)
    monkeypatch.setitem(TARGETS, target.key, target)
    assert item_etag("w1", target.key, "none", 1000, fit=None) == item_etag(
        "w1", target.key, "none", 1000, fit=default_fit
    )


# ---- store -----------------------------------------------------------------
def test_playlist_store_roundtrip_and_delete(tmp_path):
    st = PlaylistStore(tmp_path / "pl.json")
    pl = SavedPlaylist.new("Dutch Landscapes", {"genres": ["painting/landscape"]})
    st.save(pl)
    assert [p.name for p in st.list()] == ["Dutch Landscapes"]
    assert st.get(pl.id).spec == {"genres": ["painting/landscape"]}
    assert st.delete(pl.id) is True
    assert st.get(pl.id) is None and st.delete(pl.id) is False


def test_playlist_ids_are_readable_and_unique(tmp_path):
    a = SavedPlaylist.new("Winter", {})
    b = SavedPlaylist.new("Winter", {})
    assert a.id.startswith("winter-") and b.id.startswith("winter-")
    assert a.id != b.id, "two playlists with one name must not collide"


def test_corrupt_playlist_store_returns_empty_rather_than_raising(tmp_path):
    """A broken store must not make every page load fail."""
    p = tmp_path / "pl.json"
    p.write_text("{ not json")
    assert PlaylistStore(p).list() == []


def test_playlist_store_skips_non_string_name(tmp_path):
    p = tmp_path / "pl.json"
    p.write_text(json.dumps({"playlists": {"bad": {"id": "bad", "name": None, "spec": {}}}}))
    assert PlaylistStore(p).list() == []


def test_slugify_never_returns_empty():
    assert slugify("") == "playlist"
    assert slugify("!!!") == "playlist"
    assert slugify("Sea & Ships") == "sea-ships"


# ---- manifest --------------------------------------------------------------
def test_manifest_urls_are_absolute_and_indices_line_up():
    pl = SavedPlaylist.new("X", {}, interval="daily")
    items = [
        {"work_id": f"w{i}", "title": f"T{i}", "artist": "A", "year": 1600 + i} for i in range(3)
    ]
    m = build_manifest(
        pl, items, base_url="http://host:8932/", now=datetime(2026, 8, 6, tzinfo=UTC)
    )
    assert m["count"] == 3
    assert m["items"][2]["url"] == f"http://host:8932/feed/{pl.id}/image/2"
    assert m["current_url"] == f"http://host:8932/feed/{pl.id}/current"
    assert m["items"][m["current_index"]]["work_id"] == items[m["current_index"]]["work_id"]
    assert m["resolved_live"] is True


def test_empty_manifest_has_no_current_url_to_poll():
    pl = SavedPlaylist.new("Empty", {})
    m = build_manifest(pl, [], base_url="http://h")
    assert m["count"] == 0 and m["current_url"] is None


# ---- API error mapping (direct handler calls; no TestClient/httpx) ---------
def test_checked_export_dir_rejects_paths_outside_roots(tmp_path, monkeypatch):
    from fastapi import HTTPException

    from fine_art_archive.api import main as api_main

    monkeypatch.setattr(api_main, "EINK_EXPORT_ROOTS", [tmp_path / "allowed"])
    with pytest.raises(HTTPException) as ei:
        api_main._checked_export_dir(str(tmp_path / "outside" / "card"))
    assert ei.value.status_code == 400
    assert "export path must be under" in ei.value.detail


def test_feed_current_404_when_playlist_resolves_empty(tmp_path, monkeypatch):
    from fastapi import HTTPException
    from starlette.requests import Request

    from fine_art_archive.api import main as api_main
    from fine_art_archive.eink import PlaylistStore, SavedPlaylist

    store_path = tmp_path / "pl.json"
    pl_store = PlaylistStore(store_path)
    empty = SavedPlaylist.new("Empty feed", {"all_tags": ["theme:__no_such__"]})
    pl_store.save(empty)
    monkeypatch.setattr(api_main, "_playlists", pl_store)
    monkeypatch.setattr(api_main, "_all_sidecars", lambda: [])
    monkeypatch.setattr(api_main.store, "work_ids_with_dossier", frozenset)
    monkeypatch.setattr(api_main.store, "RATINGS_LOG", tmp_path / "absent.jsonl")
    scope = {
        "type": "http",
        "method": "GET",
        "path": f"/feed/{empty.id}/current",
        "headers": [],
        "query_string": b"",
        "server": ("test", 80),
        "scheme": "http",
    }
    request = Request(scope)
    with pytest.raises(HTTPException) as ei:
        api_main.feed_current(empty.id, request, offset=0)
    assert ei.value.status_code == 404
    assert "no works" in ei.value.detail


def test_export_maps_file_exists_to_409(tmp_path, monkeypatch):
    from fastapi import HTTPException

    from fine_art_archive.api import main as api_main

    allowed = tmp_path / "allowed"
    allowed.mkdir()
    monkeypatch.setattr(api_main, "EINK_EXPORT_ROOTS", [allowed])
    monkeypatch.setattr(api_main, "_all_sidecars", lambda: [])

    def _boom(*_a, **_k):
        raise FileExistsError("card already has files; pass overwrite=true")

    monkeypatch.setattr(api_main._eink, "export", _boom)
    monkeypatch.setattr(
        api_main._eink,
        "build",
        lambda *a, **k: type("R", (), {"work_ids": []})(),
    )
    body = api_main.ExportIn(path=str(allowed / "card"), spec={}, write=True, overwrite=False)
    with pytest.raises(HTTPException) as ei:
        api_main.eink_playlist_export(body)
    assert ei.value.status_code == 409
    assert "overwrite" in ei.value.detail


# ---- survey merge stream-key handling --------------------------------------
def test_merge_survey_stream_keys_known_vs_unknown(tmp_path, monkeypatch, capsys):
    """Loader-level coverage for research_reference_only vs unknown top-level keys."""
    import importlib.util
    from pathlib import Path

    script = Path(__file__).resolve().parents[1] / "scripts" / "merge_eink_survey.py"
    spec = importlib.util.spec_from_file_location("merge_eink_survey", script)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    research = tmp_path / "research"
    research.mkdir()
    known = research / "known.json"
    unknown = research / "unknown.json"
    known.write_text(
        json.dumps(
            {
                "devices": [
                    {
                        "vendor": "TestVendor",
                        "model": "Panel A",
                        "diagonal_in": 25,
                    }
                ],
                "vendors": [],
                "research_reference_only": [
                    {
                        "vendor": "RefOnly",
                        "model": "ShouldNotMerge",
                        "diagonal_in": 99,
                    }
                ],
            }
        )
    )
    unknown.write_text(
        json.dumps(
            {
                "devices": [],
                "vendors": [],
                "totally_unknown_bucket": [{"x": 1}],
            }
        )
    )
    out = tmp_path / "config" / "eink_targets.json"
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    monkeypatch.setattr(mod, "STREAMS", [("known", known), ("unknown", unknown)])
    monkeypatch.setattr(mod, "SIDECAR_STREAMS", [])
    monkeypatch.setattr(mod, "OUT", out)
    monkeypatch.setattr(mod, "CORRECTIONS", [])

    assert mod.main() == 0
    captured = capsys.readouterr().out
    assert "UNREAD KEYS in known" not in captured
    assert "UNREAD KEYS in unknown: totally_unknown_bucket" in captured

    payload = json.loads(out.read_text())
    models = {d.get("model") for d in payload["devices"]}
    assert "Panel A" in models
    assert "ShouldNotMerge" not in models


# ------------------------------------------------- UI reaches the selector ----
# #549's quality x diversity selector shipped behind `selection_mode`, and the
# operator UI never emitted that key: einkSpec() built ten spec keys and none of
# them was it, so every previewed, saved and exported playlist used "ordered".
# Its SelectionDiagnostic records were computed, returned by the API, and
# rendered by nothing. These two tests pin the wire and the default.

UI_SPEC_KEYS = {
    "sort",
    "artists",
    "periods",
    "all_tags",
    "moods",
    "min_fit",
    "limit",
    "exclude_filters",
    "require_dossier",
}


def _ui_shaped_spec() -> dict:
    """Exactly the keys `einkSpec()` can emit, at their maximal extent."""
    return {
        "sort": "fit",
        "artists": ["Included"],
        "periods": ["golden-age"],
        "all_tags": ["setting:outdoor"],
        "moods": ["open-air"],
        "min_fit": 8,
        "limit": 2,
        "exclude_filters": ["nudity-full", "violence", "disturbing"],
        "require_dossier": False,
    }


def _diverse_fixture(tmp_path, monkeypatch):
    from fine_art_archive.api import main as api_main

    work_ids = ("near-a", "near-b", "diverse")
    rows = [
        sidecar(
            wid,
            artist="Included",
            year=1650,
            genre="painting/landscape",
            tags=("setting:outdoor",),
        )
        for wid in work_ids
    ]
    ratings = tmp_path / "ratings.jsonl"
    ratings.write_text(
        "\n".join(json.dumps({"work_id": wid, "fit": 9, "quality": 9}) for wid in work_ids)
    )
    monkeypatch.setattr(api_main, "_all_sidecars", lambda: rows)
    monkeypatch.setattr(api_main.store, "RATINGS_LOG", ratings)
    monkeypatch.setattr(api_main.store, "work_ids_with_dossier", frozenset)
    return {
        "quality_scores": {"near-a": 1.0, "near-b": 0.99, "diverse": 0.85},
        "embeddings": {"near-a": [1.0, 0.0], "near-b": [0.999, 0.04], "diverse": [0.0, 1.0]},
    }


def test_ui_shaped_spec_reaches_preference_diverse_selection(tmp_path, monkeypatch):
    """The exact spec the browser builds must be able to request the selector."""
    from fastapi.testclient import TestClient

    from fine_art_archive.api.main import UI_FILE, app

    evidence = _diverse_fixture(tmp_path, monkeypatch)
    client = TestClient(app)

    # The browser's single spec builder must actually emit the key. Without
    # this the rest of the test would pass against a UI that can never ask for
    # the mode, which is exactly the defect: the selector was reachable from a
    # hand-written spec and from nowhere an operator can click.
    assert (
        "spec.selection_mode" in UI_FILE.read_text()
    ), "einkSpec() does not emit selection_mode — the selector is unreachable from the UI"

    spec = {**_ui_shaped_spec(), "selection_mode": "preference-diverse"}
    assert set(spec) == UI_SPEC_KEYS | {"selection_mode"}

    response = client.post("/eink/playlist/preview", json={"spec": spec, "sample": 24, **evidence})
    assert response.status_code == 200, response.text
    diagnostics = response.json()["selection_diagnostics"]
    assert diagnostics, "preference-diverse must return the reason each work was chosen"
    assert [item["work_id"] for item in diagnostics] == response.json()["work_ids"]

    # the default is pinned in the same test: drop the one key and the selector
    # must not run, so "ordered" stays the behaviour of every saved playlist.
    ordered = client.post(
        "/eink/playlist/preview", json={"spec": _ui_shaped_spec(), "sample": 24, **evidence}
    )
    assert ordered.status_code == 200, ordered.text
    assert ordered.json()["selection_diagnostics"] == []


def test_ui_shaped_request_without_evidence_returns_a_selection(tmp_path, monkeypatch):
    """The browser payload derives local, non-degenerate visual evidence."""
    from fastapi.testclient import TestClient

    from fine_art_archive.api import main as api_main

    work_ids = ("near-a", "near-b", "diverse")
    rows = [sidecar(work_id, artist="Included") for work_id in work_ids]
    ratings = tmp_path / "ratings.jsonl"
    ratings.write_text(
        "\n".join(json.dumps({"work_id": work_id, "fit": 9, "quality": 9}) for work_id in work_ids)
    )
    masters = tmp_path / "works"
    for work_id, colour in zip(
        work_ids, ((220, 40, 40), (210, 50, 50), (40, 70, 220)), strict=True
    ):
        work_dir = masters / work_id
        work_dir.mkdir(parents=True)
        Image.new("RGB", (32, 24), colour).save(work_dir / "master.png")
    monkeypatch.setattr(api_main, "_all_sidecars", lambda: rows)
    monkeypatch.setattr(api_main.store, "RATINGS_LOG", ratings)
    monkeypatch.setattr(api_main.store, "work_ids_with_dossier", frozenset)
    monkeypatch.setattr(api_main, "ART_WORKS_ROOT", masters)

    response = TestClient(api_main.app).post(
        "/eink/playlist/preview",
        json={
            "spec": {"selection_mode": "preference-diverse", "limit": 2},
            "target": "gooddisplay-315-diy",
            "sample": 24,
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["selection_diagnostics"]
    derived = api_main._derived_preference_evidence(
        list(work_ids), api_main._eink.load_ratings(ratings)
    )[1]
    assert derived["near-a"] != derived["diverse"], "visual embeddings must not be constant"

    rows_with_missing = [*rows, sidecar("missing", artist="Included")]
    ratings.write_text(
        "\n".join(
            json.dumps({"work_id": work_id, "fit": 9, "quality": 9})
            for work_id in (*work_ids, "missing")
        )
    )
    monkeypatch.setattr(api_main, "_all_sidecars", lambda: rows_with_missing)
    missing = TestClient(api_main.app).post(
        "/eink/playlist/preview",
        json={
            "spec": {"selection_mode": "preference-diverse", "limit": 2},
            "target": "gooddisplay-315-diy",
            "sample": 24,
        },
    )
    assert missing.status_code == 400, missing.text
    assert "local master image evidence is missing for missing" in missing.json()["detail"]

    unreadable_dir = masters / "unreadable"
    unreadable_dir.mkdir()
    (unreadable_dir / "master.png").write_text("not an image")
    monkeypatch.setattr(
        api_main, "_all_sidecars", lambda: [sidecar("unreadable", artist="Included")]
    )
    ratings.write_text(json.dumps({"work_id": "unreadable", "fit": 9, "quality": 9}))
    unreadable = TestClient(api_main.app).post(
        "/eink/playlist/preview",
        json={
            "spec": {"selection_mode": "preference-diverse", "limit": 2},
            "target": "gooddisplay-315-diy",
            "sample": 24,
        },
    )
    assert unreadable.status_code == 400, unreadable.text
    assert (
        "local master image evidence for unreadable cannot be read" in unreadable.json()["detail"]
    )


def test_supplied_embeddings_do_not_require_local_masters(tmp_path, monkeypatch):
    """Omitting quality alone must not trigger unnecessary master-image reads."""
    from fastapi.testclient import TestClient

    from fine_art_archive.api import main as api_main

    evidence = _diverse_fixture(tmp_path, monkeypatch)
    response = TestClient(api_main.app).post(
        "/eink/playlist/preview",
        json={
            "spec": {"selection_mode": "preference-diverse", "limit": 2},
            "target": "gooddisplay-315-diy",
            "sample": 24,
            "embeddings": evidence["embeddings"],
        },
    )

    assert response.status_code == 200, response.text
    assert response.json()["selection_diagnostics"]


def test_local_descriptors_reuse_unchanged_images(tmp_path, monkeypatch):
    """Repeated derivation reads each master once, without changing its vector."""
    from fine_art_archive.api import main as api_main

    paths = {}
    for wid, colour in [("red", (220, 40, 40)), ("blue", (40, 70, 220))]:
        path = tmp_path / f"{wid}.png"
        Image.new("RGB", (32, 24), colour).save(path)
        paths[wid] = path
    monkeypatch.setattr(api_main, "_eink_master", paths.get)
    monkeypatch.setattr(api_main, "_visual_descriptor_cache", {})
    # Independent uncached recipe: cache reuse must preserve the original vectors.
    baseline = {}
    for wid, path in paths.items():
        with Image.open(path) as image:
            pixels = image.convert("RGB").resize((16, 16), Image.Resampling.BILINEAR)
            baseline[wid] = [channel / 255.0 for pixel in pixels.getdata() for channel in pixel]
    reads = []
    original_compute = api_main._compute_visual_descriptor

    def counted_compute(source):
        reads.append(source.name)
        return original_compute(source)

    monkeypatch.setattr(api_main, "_compute_visual_descriptor", counted_compute)
    first = api_main._derived_preference_evidence(list(paths), {})[1]
    second = api_main._derived_preference_evidence(list(paths), {})[1]
    assert first == second == baseline
    assert first["red"] != first["blue"]
    assert reads == [
        str(path) for path in paths.values()
    ], "unchanged masters must not be decoded again"


@pytest.mark.parametrize("change", ["mtime-ns", "size", "replacement", "symlink"])
def test_local_descriptor_file_signature_changes_recompute(tmp_path, monkeypatch, change):
    from fine_art_archive.api import main as api_main

    master = tmp_path / "master.bmp"
    Image.new("RGB", (32, 24), (220, 40, 40)).save(master)
    current = tmp_path / "current.bmp"
    current.symlink_to(master.name)
    monkeypatch.setattr(api_main, "_eink_master", lambda _: current)
    monkeypatch.setattr(api_main, "_visual_descriptor_cache", {})
    reads = []
    original_compute = api_main._compute_visual_descriptor

    def counted_compute(source):
        reads.append(source.name)
        return original_compute(source)

    monkeypatch.setattr(api_main, "_compute_visual_descriptor", counted_compute)
    first = api_main._local_visual_embedding("work")
    before = master.stat()
    replacement = tmp_path / "replacement.bmp"
    Image.new("RGB", (32, 24), (40, 70, 220)).save(replacement)
    if change == "symlink":
        # Even equal timestamps and sizes cannot alias different resolved paths.
        os.utime(replacement, ns=(before.st_atime_ns, before.st_mtime_ns))
        current.unlink()
        current.symlink_to(replacement.name)
    elif change == "replacement":
        os.utime(replacement, ns=(before.st_atime_ns, before.st_mtime_ns))
        replacement.replace(master)
        assert master.stat().st_ino != before.st_ino
    else:
        master.write_bytes(replacement.read_bytes())
        if change == "mtime-ns":
            os.utime(master, ns=(before.st_atime_ns, before.st_mtime_ns + 1))
            assert master.stat().st_size == before.st_size
            assert master.stat().st_mtime_ns == before.st_mtime_ns + 1
        else:
            with master.open("ab") as output:
                output.write(b"trailing BMP bytes")
            os.utime(master, ns=(before.st_atime_ns, before.st_mtime_ns))
            assert master.stat().st_size != before.st_size
    second = api_main._local_visual_embedding("work")
    assert second != first
    assert api_main._local_visual_embedding("work") == second
    assert len(reads) == 2, "only the changed signature should trigger a second decode"


@pytest.mark.parametrize("change", ["pixels", "path", "version", "missing", "unreadable"])
def test_local_descriptor_cache_revalidates_current_master(tmp_path, monkeypatch, change):
    from fine_art_archive.api import main as api_main

    master = tmp_path / "master.png"
    Image.new("RGB", (32, 24), (220, 40, 40)).save(master)
    monkeypatch.setattr(api_main, "_eink_master", lambda _: master if master.exists() else None)
    first = api_main._local_visual_embedding("work")
    if change == "pixels":
        Image.new("RGB", (32, 24), (40, 70, 220)).save(master)
    elif change == "path":
        replacement = tmp_path / "replacement.png"
        Image.new("RGB", (32, 24), (40, 70, 220)).save(replacement)
        monkeypatch.setattr(api_main, "_eink_master", lambda _: replacement)
    elif change == "version":
        monkeypatch.setattr(api_main, "_VISUAL_DESCRIPTOR_VERSION", "test-next-version")
    elif change == "missing":
        master.unlink()
    else:
        master.write_text("not an image")
    if change in {"missing", "unreadable"}:
        with pytest.raises(ValueError, match="evidence.*(missing|cannot be read)"):
            api_main._local_visual_embedding("work")
    elif change == "version":
        reads = []
        original_open = Image.open

        def counted_open(*args, **kwargs):
            reads.append(args[0])
            return original_open(*args, **kwargs)

        monkeypatch.setattr(Image, "open", counted_open)
        assert api_main._local_visual_embedding("work") == first
        assert len(reads) == 1, "descriptor recipe version is part of cache identity"
    else:
        assert api_main._local_visual_embedding("work") != first


def test_local_descriptor_cache_still_checks_read_access(tmp_path, monkeypatch):
    from pathlib import Path

    from fine_art_archive.api import main as api_main

    master = tmp_path / "master.png"
    Image.new("RGB", (32, 24), (220, 40, 40)).save(master)
    monkeypatch.setattr(api_main, "_eink_master", lambda _: master)
    api_main._local_visual_embedding("work")
    original_open = Path.open

    def deny_master(path, *args, **kwargs):
        if path == master:
            raise PermissionError("test master access revoked")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", deny_master)
    with pytest.raises(ValueError, match="cannot be read"):
        api_main._local_visual_embedding("work")


def test_local_descriptor_cache_is_bounded_and_does_not_share_mutable_vectors(
    tmp_path, monkeypatch
):
    from fine_art_archive.api import main as api_main

    monkeypatch.setattr(api_main, "_VISUAL_DESCRIPTOR_CACHE_MAX_ENTRIES", 2)
    monkeypatch.setattr(api_main, "_visual_descriptor_cache", {})
    paths = {}
    for wid, colour in [("red", (220, 40, 40)), ("green", (40, 220, 40)), ("blue", (40, 70, 220))]:
        path = tmp_path / f"{wid}.png"
        Image.new("RGB", (32, 24), colour).save(path)
        paths[wid] = path
    monkeypatch.setattr(api_main, "_eink_master", paths.get)
    reads = []
    original_open = Image.open

    def counted_open(*args, **kwargs):
        reads.append(args[0])
        return original_open(*args, **kwargs)

    monkeypatch.setattr(Image, "open", counted_open)
    red = api_main._local_visual_embedding("red")
    expected = red.copy()
    red[0] = -100
    green = api_main._local_visual_embedding("green")
    assert api_main._local_visual_embedding("red") == expected
    api_main._local_visual_embedding("blue")
    assert len(api_main._visual_descriptor_cache) == 2
    assert api_main._local_visual_embedding("red") == expected
    assert len(reads) == 3, "a hit must promote red ahead of green for eviction"
    assert api_main._local_visual_embedding("green") == green
    assert len(reads) == 4, "the least recently used entry must be decoded again"


def test_operator_ui_can_emit_selection_mode_and_render_its_diagnostics():
    """The key and the diagnostics must both exist in the one screen that builds specs."""
    from fine_art_archive.api.main import UI_FILE

    ui = UI_FILE.read_text()
    assert "selection_mode" in ui, "einkSpec() cannot request the selector"
    assert 'id="ek-selmode"' in ui, "no control emits it"
    assert "preference-diverse" in ui
    assert "selection_diagnostics" in ui, "the explanations are returned and rendered by nothing"


def test_operator_ui_forwards_fit_to_preview_images_save_and_export():
    """The fit control must reach every surface the preview claims to match.

    The companion preview renders each item through
    ``/works/{id}/eink_preview``; the saved feed renders with ``pl.fit`` and
    the SD export with the export body's ``fit``. If the UI's ``ek-fitmode``
    value reached only the export, the on-screen preview would show
    ``contain`` framing while the card/feed delivered ``cover`` — the exact
    preview-vs-delivery divergence the audit tracks. Disconnecting the
    ``fitQ`` interpolation in the preview ``<img>`` URL must fail this test.
    """
    from fine_art_archive.api.main import UI_FILE

    ui = UI_FILE.read_text()
    assert 'id="ek-fitmode"' in ui, "no fit control exists for the operator to set"
    # Preview images: the fit query param is built from the control and
    # interpolated into the eink_preview URL actually rendered on screen.
    assert 'const fitQ = fitMode ? `&fit=${encodeURIComponent(fitMode)}` : "";' in ui
    assert "eink_preview?target=${encodeURIComponent(target)}" in ui
    assert "&dither=${encodeURIComponent(dither)}${fitQ}&max_px=380" in ui, (
        "preview <img> does not forward the chosen fit — preview would not "
        "match the framing delivered by feed/export"
    )
    # Saved feed and SD export consume the same control, so all three
    # surfaces agree on framing for one operator action.
    assert (
        ui.count('document.getElementById("ek-fitmode").value || null') >= 2
    ), "fit must be sent both when saving a playlist (feed) and on export (SD card)"


def test_operator_ui_forwards_dither_and_target_to_preview_images_save_and_export():
    """Dither and panel target must reach every surface the preview claims to match.

    ``eink_preview`` renders with its ``target``/``dither`` query params
    (api/main.py), the saved feed renders with ``pl.target``/``pl.dither``
    and the SD export with the export body's ``target``/``dither``. If the
    UI's ``ek-target``/``ek-dither`` values reached only the export, the
    on-screen preview would show a different panel size and dither texture
    than the card/feed delivered — the same preview-vs-delivery divergence
    class the audit tracks for ``fit``. Disconnecting the ``dither``
    interpolation in the preview ``<img>`` URL must fail this test.
    """
    from fine_art_archive.api.main import UI_FILE

    ui = UI_FILE.read_text()
    assert 'id="ek-target"' in ui, "no target control exists for the operator to set"
    assert 'id="ek-dither"' in ui, "no dither control exists for the operator to set"
    # Preview images: both values are read from their controls in
    # einkPreview() and interpolated into the eink_preview URL on screen.
    assert 'const target = document.getElementById("ek-target").value;' in ui
    assert 'const dither = document.getElementById("ek-dither").value;' in ui
    assert (
        "eink_preview?target=${encodeURIComponent(target)}"
        "&dither=${encodeURIComponent(dither)}${fitQ}&max_px=380" in ui
    ), (
        "preview <img> does not forward the chosen target/dither — preview "
        "would not match the panel/dither delivered by feed/export"
    )
    # Saved feed and SD export consume the same controls, so all three
    # surfaces agree on panel and dither for one operator action.
    assert (
        ui.count('document.getElementById("ek-target").value') >= 3
    ), "target must be read for preview images, saving a playlist (feed) and export (SD card)"
    assert (
        ui.count('document.getElementById("ek-dither").value') >= 3
    ), "dither must be read for preview images, saving a playlist (feed) and export (SD card)"


def test_operator_ui_forwards_same_spec_to_preview_save_and_export():
    """One shared ``einkSpec()`` must feed preview, saved feed and SD export.

    ``einkSpec()`` (index.html) builds the ``PlaylistSpec`` — filters, sort,
    limit and the A15 ``selection_mode`` — from the operator controls. The
    preview POSTs it to ``/eink/playlist/preview``, ``einkSavePlaylist``
    persists it for the feed, and ``einkExport`` sends it to
    ``/eink/playlist/export``. If any surface stopped calling the shared
    builder (e.g. export inlined its own spec literal), the works previewed
    could differ from the works delivered — the ``spec.*`` row of the
    divergence audit, currently marked already-correct only on source
    reading. Replacing ``spec: einkSpec()`` in the export body must fail
    this test. The rotation ``interval`` is the one deliberate asymmetry:
    it is saved with the playlist (feed rotation) and sent nowhere else.
    """
    from fine_art_archive.api.main import UI_FILE

    ui = UI_FILE.read_text()
    assert "function einkSpec()" in ui, "no shared spec builder exists"
    # Preview: the playlist preview request carries the shared spec.
    assert "body: JSON.stringify({ spec: einkSpec(), target, sample: 24 })" in ui, (
        "playlist preview does not send the shared einkSpec() — previewed "
        "selection could diverge from the saved/exported selection"
    )
    # Saved feed: the playlist-create body carries the same shared spec,
    # plus the rotation interval only a saved feed consumes.
    assert (
        "name: name.trim(), spec: einkSpec()," in ui
    ), "saving a playlist (feed) does not send the shared einkSpec()"
    assert (
        'interval: document.getElementById("ek-interval").value,' in ui
    ), "saved feed loses the operator's rotation interval"
    # SD export: the export body carries the same shared spec.
    assert 'spec: einkSpec(), target: document.getElementById("ek-target").value,' in ui, (
        "SD export does not send the shared einkSpec() — exported selection "
        "could diverge from the previewed/saved selection"
    )
    assert (
        ui.count("spec: einkSpec()") == 3
    ), "exactly preview, save and export should consume the shared spec builder"


@pytest.mark.parametrize("fit", ["", "contain", "cover", "stretch"])
def test_ui_preview_save_and_export_carry_the_same_inputs(tmp_path, fit):
    """Execute the UI producers: a hand-built payload cannot prove UI parity."""
    from fine_art_archive.api.main import UI_FILE

    node = shutil.which("node")
    if node is None:
        pytest.skip("node is required to verify the companion's request producers")
    ui = UI_FILE.read_text()
    functions = []
    for start, end in (
        ("    function einkSpec() {", "    async function einkSavePlaylist()"),
        ("    async function einkSavePlaylist() {", "    let einkCardPlaylistId"),
        ("    async function einkPreview() {", "    async function einkExport(write)"),
        ("    async function einkExport(write) {", "    function toggleGallery()"),
    ):
        functions.append(ui[ui.index(start) : ui.index(end, ui.index(start))])

    # Compile checked-in functions as a normal script, with only DOM/network
    # boundaries replaced. No copied implementation or dynamic evaluation.
    runner = tmp_path / "companion-inputs.cjs"
    runner.write_text(
        "const selectedFit = "
        + json.dumps(fit)
        + ";\n"
        + """
const controls = {
  'ek-sort': {value: 'fit'}, 'ek-limit': {value: '2'},
  'ek-artist': {value: 'ArtistA'}, 'ek-period': {value: 'Modern'},
  'ek-mood': {value: 'Quiet'}, 'ek-fit': {value: '3'},
  'ek-excl': {checked: true}, 'ek-dossier': {checked: true},
  'ek-selmode': {value: 'preference-diverse'},
  'ek-target': {value: 'gooddisplay-315-diy'},
  'ek-dither': {value: 'atkinson'}, 'ek-fitmode': {value: selectedFit},
  'ek-plname': {value: 'Input parity'}, 'ek-interval': {value: 'daily'},
  'ek-path': {value: '/fixture/card'},
  'ek-out': {innerHTML: '', insertAdjacentHTML() {}}, 'ek-status': {},
};
const document = {
  getElementById: id => controls[id] || null,
  querySelectorAll: selector => selector === ".ek-fam" ? [{value: "shape:round"}, {value: ""}] : [],
};
const calls = [];
let einkLastPreview, einkCardPlaylistId = "fixture/playlist";
const messages = [];
const toast = message => messages.push(message);
const einkLoadPlaylists = async () => {};
const einkEsc = value => String(value);
const confirm = () => true;
const fetch = async (url, options) => {
  calls.push({url, body: JSON.parse(options.body)});
  return {ok: true, json: async () => ({
    coverage: {}, items: [{work_id: 'fixture/work', has_master: true}],
    selected: 1, matched: 1, total_candidates: 1, selection_diagnostics: [],
    target: 'gooddisplay-315-diy',
    evidence_calibration: 'Spectra-6',
    evidence_scope: 'master-derived and target-independent',
    name: 'Input parity', resolved_count: 1, written: 1, palette_measured: true,
  })};
};
"""
        + "\n".join(functions)
        + """
(async () => {
  await einkPreview();
  const previewHTML = controls['ek-out'].innerHTML;
  await einkSavePlaylist();
  await einkExport(false);
  console.log(JSON.stringify({calls, previewHTML}));
})().catch(error => { console.error(error); process.exitCode = 1; });
""",
        encoding="utf-8",
    )
    result = subprocess.run([node, str(runner)], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    observed = json.loads(result.stdout)
    preview, saved, exported = observed["calls"]
    assert [call["url"] for call in observed["calls"]] == [
        "/eink/playlist/preview",
        "/eink/playlists",
        "/eink/playlist/export",
    ]
    expected_spec = {
        "sort": "fit",
        "limit": 2,
        "selection_mode": "preference-diverse",
        "artists": ["ArtistA"],
        "periods": ["Modern"],
        "all_tags": ["shape:round"],
        "moods": ["Quiet"],
        "min_fit": 3,
        "exclude_filters": ["nudity-full", "violence", "disturbing"],
        "require_dossier": True,
    }
    assert preview["body"]["spec"] == saved["body"]["spec"] == exported["body"]["spec"]
    assert preview["body"]["spec"] == expected_spec
    assert preview["body"]["target"] == saved["body"]["target"] == exported["body"]["target"]
    assert saved["body"]["fit"] == exported["body"]["fit"] == (fit or None)
    assert saved["body"]["dither"] == exported["body"]["dither"] == "atkinson"
    assert exported["body"]["playlist_id"] == "fixture/playlist"
    assert exported["body"]["write"] is False
    assert exported["body"]["overwrite"] is True
    assert exported["body"]["path"] == "/fixture/card"

    from html import unescape
    from urllib.parse import parse_qs, urlsplit

    html = observed["previewHTML"]
    image_url = unescape(html.split('src="', 1)[1].split('"', 1)[0])
    assert urlsplit(image_url).path == "/works/fixture%2Fwork/eink_preview"
    params = parse_qs(urlsplit(image_url).query)
    assert params == {
        "target": [saved["body"]["target"]],
        "dither": [saved["body"]["dither"]],
        "max_px": ["380"],
        **({"fit": [fit]} if fit else {}),
    }
    assert 'id="ek-target-evidence"' in html
    assert (
        "Resolved target gooddisplay-315-diy. Strategy and gamut evidence use "
        "Spectra-6 policy (master-derived and target-independent), rather than "
        "a measurement for the selected panel." in html
    )


def test_operator_ui_einkspec_forwards_each_spec_control():
    """Every ``ek-*`` spec control must populate the shared ``einkSpec()``.

    The shared-spec regression above proves preview, save and export all
    call ``einkSpec()``; it does not prove the builder reads each control.
    If ``einkSpec()`` dropped e.g. ``ek-limit`` or ``ek-excl``, all three
    surfaces would agree with each other but silently diverge from the
    operator's stated filters — the ``spec.*`` row of the divergence
    audit, already-correct only on source reading. Removing any single
    control mapping inside ``einkSpec()`` must fail this test.
    """
    from fine_art_archive.api.main import UI_FILE

    ui = UI_FILE.read_text()
    assert "function einkSpec()" in ui, "no shared spec builder exists"
    mappings = [
        ('const spec = { sort: v("ek-sort") || "fit" };', "sort (ek-sort)"),
        ('if (v("ek-artist")) spec.artists = [v("ek-artist")];', "artists (ek-artist)"),
        ('if (v("ek-period")) spec.periods = [v("ek-period")];', "periods (ek-period)"),
        ("if (tags.length) spec.all_tags = tags;", "all_tags (.ek-fam family selects)"),
        ('if (v("ek-mood")) spec.moods = [v("ek-mood")];', "moods (ek-mood)"),
        ('if (v("ek-fit")) spec.min_fit = parseInt(v("ek-fit"), 10);', "min_fit (ek-fit)"),
        ('if (v("ek-limit")) spec.limit = parseInt(v("ek-limit"), 10);', "limit (ek-limit)"),
        (
            'if (on("ek-excl")) spec.exclude_filters = ["nudity-full", "violence", "disturbing"];',
            "exclude_filters (ek-excl)",
        ),
        ('if (on("ek-dossier")) spec.require_dossier = true;', "require_dossier (ek-dossier)"),
        (
            'if (v("ek-selmode") === "preference-diverse" && spec.limit) {',
            "selection_mode guard (ek-selmode, requires limit)",
        ),
        ('spec.selection_mode = "preference-diverse";', "selection_mode (ek-selmode)"),
    ]
    for snippet, label in mappings:
        assert snippet in ui, f"einkSpec() does not forward {label} — operator filter is lost"
    assert 'document.querySelectorAll(".ek-fam")' in ui
    assert ".map(el => el.value).filter(Boolean)" in ui


def test_operator_ui_forwards_exact_delivery_fields_to_save_and_export():
    """Save/export bodies must carry the exact delivery fields, not just counts.

    Earlier forwarding tests assert read counts (``>= 2``/``>= 3``), which
    still pass if one surface drops a field while another reads it twice.
    This locks the literal body fields: saved feed and SD export each send
    ``target``/``dither``/``fit`` from their controls, and export forwards
    a chosen saved feed as ``playlist_id`` so the card uses the feed's
    selection (main.py:813) instead of re-resolving the filter spec.
    Deleting the ``body.playlist_id`` line in ``index.html`` must fail it.
    """
    from fine_art_archive.api.main import UI_FILE

    ui = UI_FILE.read_text()
    # Saved feed body: exact delivery fields persisted for feed rendering.
    assert 'target: document.getElementById("ek-target").value,' in ui
    assert 'dither: document.getElementById("ek-dither").value,' in ui
    # Both save and export send fit as ``|| null`` (unset means panel default).
    assert (
        ui.count('fit: document.getElementById("ek-fitmode").value || null,') == 2
    ), "fit must be sent exactly by playlist save (feed) and SD export"
    # SD export body: card destination/write flags plus saved-feed selection.
    assert "path, write, overwrite: true," in ui, "export loses card path/write flags"
    assert "if (einkCardPlaylistId) body.playlist_id = einkCardPlaylistId;" in ui, (
        "export does not forward the chosen saved feed — card would "
        "re-resolve filters instead of using the feed selection"
    )
    assert "einkCardPlaylistId = id;" in ui, "no UI path chooses a saved feed for the card"


def test_operator_ui_selection_mode_requires_limit_guard():
    """``preference-diverse`` must not be requestable without a limit.

    The backend raises ``preference-diverse selection requires limit``
    (eink/playlist.py) and ``einkSpec()`` only emits the mode with one, but
    the operator-facing guard is ``einkSyncSelectionMode()``: it disables
    the option without a limit, resets a stale selection to ``ordered``
    and explains why in ``ek-selnote``. Earlier tests only check that
    ``selection_mode`` exists in the UI. Disconnecting the disable line
    in ``index.html`` must fail this test.
    """
    from fine_art_archive.api.main import UI_FILE

    ui = UI_FILE.read_text()
    assert (
        'oninput="einkSyncSelectionMode()"' in ui
    ), "changing the limit must re-sync whether preference-diverse is available"
    assert (
        'onchange="einkSyncSelectionMode()"' in ui
    ), "changing the selection mode must re-sync the limit guard"
    assert "if (opt) opt.disabled = !hasLimit;" in ui, (
        "preference-diverse must be disabled without a limit — operator "
        "could otherwise request a mode the backend rejects"
    )
    assert (
        'if (!hasLimit && sel.value === "preference-diverse") sel.value = "ordered";' in ui
    ), "clearing the limit must reset a chosen preference-diverse mode to ordered"
    assert (
        "preference-diverse needs a Limit — set one to enable it." in ui
    ), "the guard must explain why preference-diverse is unavailable"
    assert "einkSyncSelectionMode();" in ui, "guard must run on panel render, not only on edit"


def test_operator_ui_export_write_flag_and_saved_feed_clearing():
    """Export write flag and saved-feed choice must not drift from delivery.

    The exact-fields test locks the export body (``path, write, …``) but not
    where ``write`` comes from: ``einkExport(false)`` is the dry run and
    ``einkExport(true)`` writes the card. Wiring dry run to ``true`` would
    write files the operator only meant to preview. Likewise a chosen saved
    feed (``einkCardPlaylistId``) must be clearable via ``ek-clear`` and
    auto-cleared when that feed is deleted, else export keeps sending a
    stale ``playlist_id``. Flipping the dry-run button to
    ``einkExport(true)`` in ``index.html`` must fail this test.
    """
    from fine_art_archive.api.main import UI_FILE

    ui = UI_FILE.read_text()
    import re

    assert re.search(
        r'<button\b[^>]*onclick="einkExport\(false\)"[^>]*>\s*Dry run\s*</button>', ui
    ), "Dry run must bind the non-writing action"
    assert re.search(
        r'<button\b[^>]*onclick="einkExport\(true\)"[^>]*>\s*Write card\s*</button>', ui
    ), "Write card must bind the writing action"
    assert (
        'if (!path) { toast("enter a card path first"); return; }' in ui
    ), "export without a card path must stop before calling the export endpoint"
    assert (
        "ev.preventDefault(); einkCardPlaylistId = null;" in ui
    ), "the 'use filters instead' clear link must drop the saved-feed choice"
    assert (
        "if (einkCardPlaylistId === id) einkCardPlaylistId = null;" in ui
    ), "deleting the chosen saved feed must clear it from export, not send a stale id"


def test_operator_ui_discloses_estimated_palette_on_export():
    """Export must warn when the palette is estimated, not measured.

    The export response carries ``palette_measured`` from the target palette
    (main.py, ``tgt.palette.measured``; also in the SD manifest at
    sdcard.py). Backend tests lock that flag in the manifest, but nothing
    locked the operator-facing disclosure: ``einkExport`` appends
    ``colours estimated`` only when ``d.palette_measured`` is false. Dropping
    that branch would let an unmeasured palette read as measured on the one
    screen that writes the card — the audit's palette row and its
    no-physical-panel-acceptance caveat. Removing the disclosure in
    ``index.html`` must fail this test.
    """
    from fine_art_archive.api.main import UI_FILE

    ui = UI_FILE.read_text()
    assert (
        'd.palette_measured ? "" : ` · <span style="color:#a06000">colours estimated</span>`' in ui
    ), (
        "export result must disclose 'colours estimated' when palette_measured "
        "is false — an estimated palette must not read as measured"
    )
    # The warning must be tied to the export response, not shown (or hidden)
    # unconditionally: the ternary on d.palette_measured is the disclosure.
    assert (
        ui.count("d.palette_measured") == 1
    ), "palette disclosure must come from the export response's palette_measured flag exactly once"


def test_operator_ui_discloses_no_master_works_in_preview():
    """Preview must disclose selected works that have no local image.

    Preview ``selected`` includes no-master works (flagged ``has_master``),
    while the feed excludes them and export skips them at write — the
    no-master count row of the divergence audit (#827). The operator-facing
    mitigation in ``einkPreview`` counts ``!i.has_master`` items and appends
    ``— N shown have no local image`` to the selection header only when
    that count is non-zero. Dropping the disclosure would let the preview
    count read as deliverable works the feed/card cannot show. Removing
    the conditional disclosure in ``index.html`` must fail this test.
    """
    from fine_art_archive.api.main import UI_FILE

    ui = UI_FILE.read_text()
    assert (
        "const noMaster = d.items.filter(i => !i.has_master).length;" in ui
    ), "preview does not count items flagged has_master=false"
    assert '${noMaster ? ` — ${noMaster} shown have no local image` : ""}' in ui, (
        "preview header does not disclose no-master works — preview count "
        "would read as deliverable works the feed/card cannot show"
    )
    assert (
        ui.count("shown have no local image") == 1
    ), "no-master disclosure must come from the preview response's has_master flags exactly once"


def test_operator_ui_discloses_skipped_works_on_export():
    """Export must disclose works skipped at write, not just files written.

    The SD writer skips selected works with no local master (or a failed
    render) and reports ``skipped`` in the export response (sdcard.py:185,
    :107) — the export side of the no-master count row of the divergence
    audit (#827). The operator-facing mitigation in ``einkExport`` appends
    ``· N skipped`` to the result line only when ``d.skipped`` is non-zero,
    so ``Wrote N file(s)`` cannot read as the full selected count. Dropping
    that disclosure would hide exactly the preview-vs-delivery gap the
    preview header discloses. Removing it in ``index.html`` must fail
    this test.
    """
    from fine_art_archive.api.main import UI_FILE

    ui = UI_FILE.read_text()
    assert '(d.skipped ? ` · ${d.skipped} skipped` : "")' in ui, (
        "export result does not disclose skipped works — 'Wrote N file(s)' "
        "would read as the full selection the card cannot show"
    )
    assert (
        ui.count("${d.skipped} skipped") == 1
    ), "skipped disclosure must come from the export response's skipped count exactly once"


def test_operator_ui_discloses_missing_metadata_drops_in_preview():
    """Preview must disclose candidates dropped for missing metadata.

    The builder reports ``coverage.excluded_for_missing_metadata`` for
    candidates excluded because a required field is absent (playlist.py:448;
    backend counts locked at test level above), and the preview response
    carries that coverage to the UI. The operator-facing disclosure in
    ``einkPreview`` renders ``Dropped for missing metadata: <reason> <n>``
    only when that map is non-empty, so ``selected of matched`` cannot read
    as if every matching work were eligible for the feed/card. Dropping the
    disclosure would hide a preview-vs-delivery-relevant exclusion on the
    one screen where the selection is made. Removing it in ``index.html``
    must fail this test.
    """
    from fine_art_archive.api.main import UI_FILE

    ui = UI_FILE.read_text()
    assert (
        "const cov = d.coverage.excluded_for_missing_metadata || {};" in ui
    ), "preview does not read the response's excluded_for_missing_metadata coverage"
    assert "Dropped for missing metadata: " in ui, (
        "preview does not disclose works dropped for missing metadata — "
        "'selected of matched' would read as fully eligible for feed/card"
    )
    assert "${covTxt}" in ui, "missing-metadata disclosure is built but never rendered"
    assert (
        ui.count("Dropped for missing metadata") == 1
    ), "missing-metadata disclosure must come from the preview response's coverage exactly once"


def test_operator_ui_renders_selection_diagnostics_in_preview():
    """Preview must render the A15 pick explanations, not just receive them.

    ``select_quality_diverse`` explains every pick and the preview response
    carries ``selection_diagnostics`` (backend rows locked at test level
    above; the existing UI test only checks the key string exists). The
    operator-facing rendering in ``einkPreview`` builds ``diagTxt`` from
    ``d.selection_diagnostics`` — one row per pick with its quality
    contribution, nearest-selected similarity and marginal gain — and
    interpolates it into the preview markup only when non-empty. Building
    the table but never rendering it would discard the reason for the
    choice on the one screen where the choice is made. Removing the
    interpolation in ``index.html`` must fail this test.
    """
    from fine_art_archive.api.main import UI_FILE

    ui = UI_FILE.read_text()
    assert (
        "const diags = d.selection_diagnostics || [];" in ui
    ), "preview does not read the response's selection_diagnostics"
    assert "Why these ${diags.length} were chosen" in ui, (
        "preview does not label the pick explanations — the A15 quality x "
        "diversity reasoning would be invisible to the operator"
    )
    for field in ("quality_contribution", "nearest_selected_similarity", "marginal_determinant"):
        assert f"g.{field}" in ui, f"diagnostics table does not render {field} per pick"
    assert "${diagTxt}" in ui, "selection diagnostics are built but never rendered"
    assert ui.count("selection_diagnostics") == 1, (
        "diagnostics rendering must come from the preview response's "
        "selection_diagnostics exactly once"
    )


def test_enumerated_eink_surface_inputs_match_backend_signatures():
    """The audit's input enumeration must stay complete as surfaces evolve.

    The divergence audit enumerates every input consumed by the companion
    preview (``eink_playlist_preview`` + ``eink_preview``), saved-playlist
    resolution (``_resolve_playlist``), the feed render
    (``_render_feed_image``) and the SD export (``eink_playlist_export``),
    plus the helpers they delegate to (``render_for_target``,
    ``sdcard.export``, ``item_etag``, ``gamut_render_evidence`` and the
    exhibition validator). This locks that enumeration to the real
    signatures: adding an input to any surface without updating the audit
    (and this test) fails here, which is the check that a fourth input
    cannot silently diverge the way the three scope-named defects did.
    """
    import inspect

    from fine_art_archive.api import main as api_main
    from fine_art_archive.display.render import gamut_render_evidence
    from fine_art_archive.eink.feed import (
        SavedPlaylist,
        build_manifest,
        item_etag,
        palette_fingerprint,
        rotation_index,
    )
    from fine_art_archive.eink.sdcard import export as export_card
    from fine_art_archive.eink.targets import render_evidence, render_for_target
    from fine_art_archive.preference.exhibition import _validate_inputs, select_quality_diverse

    def params(fn):
        return list(inspect.signature(fn).parameters)

    # The four named surfaces (api/main.py).
    assert params(api_main.eink_playlist_preview) == ["body"]
    assert set(api_main.PlaylistIn.model_fields) == {
        "spec",
        "quality_scores",
        "embeddings",
        "target",
        "sample",
    }
    assert params(api_main.eink_preview) == ["work_id", "target", "dither", "fit", "max_px"]
    assert params(api_main.eink_playlist_export) == ["body"]
    assert set(api_main.ExportIn.model_fields) == {
        "playlist_id",
        "spec",
        "target",
        "path",
        "dither",
        "fit",
        "fmt",
        "write",
        "overwrite",
    }
    assert set(api_main.SavePlaylistIn.model_fields) == {
        "name",
        "spec",
        "target",
        "dither",
        "fit",
        "interval",
        "id",
    }
    assert params(api_main._resolve_playlist) == ["pl", "sidecars"]
    assert params(api_main._render_feed_image) == ["pl", "work_id", "request"]
    assert params(api_main._build_eink_playlist) == [
        "sidecars",
        "spec",
        "ratings",
        "quality_scores",
        "embeddings",
    ]
    # Selection inputs shared by every surface via the one builder.
    assert set(PlaylistSpec.__dataclass_fields__) == {
        "artists",
        "genres",
        "moods",
        "periods",
        "year_from",
        "year_to",
        "any_tags",
        "all_tags",
        "not_tags",
        "exclude_filters",
        "min_fit",
        "min_quality",
        "require_dossier",
        "selection_mode",
        "limit",
        "sort",
        "seed",
    }
    assert set(SavedPlaylist.__dataclass_fields__) == {
        "id",
        "name",
        "spec",
        "target",
        "dither",
        "fit",
        "interval",
        "created_at",
        "updated_at",
    }
    # Render/validator helpers traced for the audit (render.py, targets.py,
    # feed.py, sdcard.py, exhibition.py).
    assert params(render_evidence) == ["img"]
    assert params(gamut_render_evidence) == ["image", "policy"]
    assert params(render_for_target) == [
        "img",
        "target",
        "fit",
        "method",
        "compress_range",
        "fast",
        "strategy",
    ]
    assert params(export_card) == [
        "items",
        "root",
        "target",
        "master_for",
        "fmt",
        "method",
        "fit",
        "compress_range",
        "fast",
        "overwrite",
        "dry_run",
        "spec",
        "progress",
    ]
    assert params(item_etag) == [
        "work_id",
        "target_key",
        "dither",
        "mtime",
        "fit",
        "render_strategy",
        "palette",
        "palette_identity",
    ]
    # Feed-manifest helpers enumerated in the audit (feed.py) but not
    # previously locked: a new input here (e.g. a fit or strategy field on
    # the manifest) must update the audit matrix, not slip in silently.
    assert params(rotation_index) == ["n_items", "interval", "now", "offset"]
    assert params(palette_fingerprint) == ["palette"]
    assert params(build_manifest) == ["playlist", "items", "base_url", "now"]
    assert params(_validate_inputs) == [
        "work_ids",
        "quality_scores",
        "embeddings",
        "subset_size",
    ]
    assert params(select_quality_diverse) == [
        "work_ids",
        "quality_scores",
        "embeddings",
        "subset_size",
        "seed",
    ]


def test_enumerated_eink_surface_defaults_match_audit_matrix():
    """The enumerated inputs must keep the defaults the audit matrix assumes.

    ``test_enumerated_eink_surface_inputs_match_backend_signatures`` locks
    which inputs exist; this locks what each input means when the caller
    omits it. A changed default is a divergence of exactly the audited
    kind: preview would render with one implicit target/dither/fit while
    the saved feed or SD card rendered with another, and no signature
    would have changed. Every value below is the default recorded in the
    audit's input-by-surface matrix (``PlaylistIn``/``ExportIn``/
    ``SavePlaylistIn`` in api/main.py, ``PlaylistSpec`` in playlist.py,
    ``SavedPlaylist`` in feed.py, and the traced helper signatures).
    """
    import inspect

    from fine_art_archive.api import main as api_main
    from fine_art_archive.display.render import gamut_render_evidence
    from fine_art_archive.eink.feed import SavedPlaylist, item_etag
    from fine_art_archive.eink.sdcard import export as export_card
    from fine_art_archive.eink.targets import render_for_target
    from fine_art_archive.preference.exhibition import select_quality_diverse

    preview_in = api_main.PlaylistIn()
    assert preview_in.spec == {}
    assert preview_in.quality_scores == {}
    assert preview_in.embeddings == {}
    assert preview_in.target == "gooddisplay-315-diy"
    assert preview_in.sample == 24

    export_in = api_main.ExportIn(path="card")
    assert export_in.playlist_id is None
    assert export_in.spec == {}
    assert export_in.target == "gooddisplay-315-diy"
    assert export_in.dither == "floyd-steinberg"
    assert export_in.fit is None
    assert export_in.fmt == "png"
    assert export_in.write is False
    assert export_in.overwrite is False

    save_in = api_main.SavePlaylistIn(name="Winter")
    assert save_in.spec == {}
    assert save_in.target == "gooddisplay-315-diy"
    assert save_in.dither == "floyd-steinberg"
    assert save_in.fit is None
    assert save_in.interval == "daily"
    assert save_in.id is None

    spec = PlaylistSpec()
    assert spec.selection_mode == "ordered"
    assert spec.sort == "fit"
    assert spec.seed == 42
    assert spec.require_dossier is False
    assert spec.limit is None
    assert spec.min_fit is None
    assert spec.min_quality is None
    assert spec.year_from is None
    assert spec.year_to is None
    for field_name in (
        "artists",
        "genres",
        "moods",
        "periods",
        "any_tags",
        "all_tags",
        "not_tags",
        "exclude_filters",
    ):
        assert getattr(spec, field_name) == []

    saved = SavedPlaylist(id="winter-abc123", name="Winter", spec={})
    assert saved.target == "gooddisplay-315-diy"
    assert saved.dither == "floyd-steinberg"
    assert saved.fit is None
    assert saved.interval == "daily"
    assert saved.created_at == ""
    assert saved.updated_at == ""

    def defaults(fn):
        return {name: param.default for name, param in inspect.signature(fn).parameters.items()}

    preview_defaults = defaults(api_main.eink_preview)
    assert preview_defaults["target"] == "gooddisplay-315-diy"
    assert preview_defaults["dither"] == "floyd-steinberg"
    assert preview_defaults["fit"] is None

    render_defaults = defaults(render_for_target)
    assert render_defaults["fit"] is None
    assert render_defaults["method"] == "floyd-steinberg"
    assert render_defaults["compress_range"] is True
    assert render_defaults["fast"] is True
    assert render_defaults["strategy"] is None

    assert defaults(gamut_render_evidence)["policy"] is None
    assert defaults(select_quality_diverse)["seed"] == 0

    etag_defaults = defaults(item_etag)
    assert etag_defaults["fit"] is inspect.Parameter.empty
    assert etag_defaults["render_strategy"] == "color"
    assert etag_defaults["palette"] is None
    assert etag_defaults["palette_identity"] is None

    export_defaults = defaults(export_card)
    assert export_defaults["fmt"] == "png"
    assert export_defaults["method"] == "floyd-steinberg"
    assert export_defaults["fit"] is None
    assert export_defaults["compress_range"] is True
    assert export_defaults["fast"] is True
    assert export_defaults["overwrite"] is False
    assert export_defaults["dry_run"] is True
    assert export_defaults["spec"] is None
    assert export_defaults["progress"] is None


def test_operator_ui_renders_preview_item_identity_in_selection_order():
    """Preview captions must carry the same item identity as the manifests.

    ``_resolve_playlist``, the feed manifest and the SD manifest all carry
    each work's selection order, title, artist and year. The companion
    preview is the only surface the operator actually reads, and its
    figcaption renders that same identity: a zero-padded ordinal matching
    the card's filename order, the year (with a ``????`` fallback so an
    unknown or zero year never reads as a real date — the zero-year
    instance held under the parent audit issue), then artist and title.
    Removing the year fallback in ``index.html`` must fail this test.
    """
    from fine_art_archive.api.main import UI_FILE

    ui = UI_FILE.read_text()
    assert '${String(n + 1).padStart(3, "0")} · ${einkEsc(i.year || "????")}<br>' in ui, (
        "preview caption does not render selection order and year — the "
        "work's identity on screen would not match the feed/card manifest"
    )
    assert (
        '${einkEsc((i.artist || "—").slice(0, 30))}<br>' in ui
    ), "preview caption does not render the item artist the manifests carry"
    assert (
        '<em>${einkEsc((i.title || "").slice(0, 42))}</em>' in ui
    ), "preview caption does not render the item title the manifests carry"
    assert ui.count('i.year || "????"') == 1, (
        "unknown/zero year must fall back to ???? exactly once, in the "
        "preview caption, so it never reads as a real date"
    )


def test_operator_ui_renders_preview_and_delivery_counts():
    """Preview and delivery counts must both be visible to the operator.

    The audit's no-master row (#827) is that each surface counts
    differently on purpose: preview ``selected`` includes works with no
    local image, the saved feed's ``resolved_count`` excludes them, and
    SD export reports ``written`` after skipping them at write. Those
    counts are only reconcilable where the operator actually sees them:
    the preview header (``selected`` of ``matched`` over
    ``total_candidates``), the save toast (``resolved_count``) and the
    export result (``written``). Dropping any one would let preview,
    feed and card report irreconcilable totals with no visible reason.
    Removing ``of ${d.matched} matching`` in ``index.html`` must fail
    this test.
    """
    from fine_art_archive.api.main import UI_FILE

    ui = UI_FILE.read_text()
    assert "<strong>${d.selected}</strong> selected" in ui, (
        "preview header does not render selected — preview count "
        "could not be compared to the feed's resolved count"
    )
    assert "<strong>${d.available_for_delivery}</strong> available for delivery" in ui, (
        "preview header does not render the deliverable count — works with "
        "no local image would read as deliverable"
    )
    assert (
        "of ${d.matched} matching" in ui
    ), "preview header does not render the matched count it selected from"
    assert (
        "(${d.total_candidates} in archive)" in ui
    ), "preview header does not render the archive total it matched against"
    assert 'toast(`saved "${d.name}" — ${d.resolved_count} works`);' in ui, (
        "save toast does not report the feed's resolved count — a saved "
        "feed whose count collapsed after the preview would read as saved"
    )
    assert "const actuallyWritten = d.dry_run ? 0 : d.written;" in ui, (
        "export result does not separate planned from actually written — "
        "a dry run would read as files placed on the card"
    )
    assert "<strong>${actuallyWritten}</strong> actually written" in ui, (
        "export result does not render the card's written count — dry-run "
        "and write would be indistinguishable from a partial card"
    )
    assert (
        "would write ${d.written} file(s)" in ui
    ), "export dry run does not render the planned file count"
    assert (
        ui.count("${d.selected}") == 2
    ), "selected count must come from the preview and export responses, once each"
    assert (
        ui.count("${d.available_for_delivery}") == 1
    ), "deliverable count must come from the preview response exactly once"
    assert (
        ui.count("${d.resolved_count} works") == 1
    ), "saved-feed count must come from the save response exactly once"
    assert (
        ui.count("${d.written} file(s)") == 1
    ), "card written count must come from the export response exactly once"


def test_helper_edge_render_evidence_uses_default_spectra6_policy():
    """The A11 edge: e-ink surfaces share one default-policy evidence call.

    ``gamut_render_evidence`` (display/render.py) accepts a ``policy``
    override, but the e-ink wrapper ``render_evidence`` (eink/targets.py)
    forwards only the image, so preview, feed and SD export all apply the
    same Spectra-6-calibrated default policy. A caller that could smuggle
    a policy into one surface would re-open the reported-vs-applied
    divergence the audit closed. The display-layer ``render_for_device``
    path keeps its own hint-driven policy; that input is intentionally
    unsupported on the e-ink surfaces and has no parameter to reach.
    """
    import inspect

    from fine_art_archive.display.render import gamut_render_evidence
    from fine_art_archive.eink.targets import render_evidence

    magenta = Image.new("RGB", (16, 16), (255, 0, 255))
    assert render_evidence(magenta) == gamut_render_evidence(magenta)
    assert render_evidence(magenta).strategy == "grayscale"
    assert render_evidence(magenta).gamut_verdict == "poorly-served"
    overridden = gamut_render_evidence(magenta, policy={"poorly-served": "color"})
    assert overridden.strategy == "color"
    assert list(inspect.signature(render_evidence).parameters) == ["img"]
    on_palette = Image.new("RGB", (16, 16), SPECTRA6.colours[2])
    assert render_evidence(on_palette).strategy == "color"


def test_helper_edge_render_for_target_derives_strategy_when_unspecified():
    """The render edge: an omitted strategy must mean the reported strategy.

    Preview, feed and SD export all pass ``strategy=evidence.strategy``
    explicitly (targets.py ``render_for_target``), but the helper's
    ``strategy=None`` fallback re-derives from the same
    ``render_evidence`` policy. If that fallback ever consulted a
    different policy, any future caller omitting the argument would
    silently render a different strategy than the surfaces report —
    the reported-vs-applied divergence the audit closed. The derived
    render must be byte-identical to the explicit render.
    """
    from fine_art_archive.eink.targets import RenderTarget, render_evidence

    small = RenderTarget(
        key="audit-small",
        label="Audit small",
        width=32,
        height=24,
        palette_name="spectra6",
    )
    magenta = Image.new("RGB", (16, 16), (255, 0, 255))
    derived = render_for_target(magenta, small)
    explicit = render_for_target(magenta, small, strategy=render_evidence(magenta).strategy)
    assert render_evidence(magenta).strategy == "grayscale"
    assert derived.size == explicit.size == small.size
    assert derived.tobytes() == explicit.tobytes()

    on_palette = Image.new("RGB", (16, 16), SPECTRA6.colours[2])
    derived_colour = render_for_target(on_palette, small)
    explicit_colour = render_for_target(
        on_palette, small, strategy=render_evidence(on_palette).strategy
    )
    assert render_evidence(on_palette).strategy == "color"
    assert derived_colour.tobytes() == explicit_colour.tobytes()


def test_helper_edge_validate_inputs_rejects_each_bad_evidence_class():
    """The A15 edge: invalid evidence must fail before any selection runs.

    ``_validate_inputs`` (preference/exhibition.py) is the only gate
    between caller-supplied or derived ``quality_scores``/``embeddings``
    and the greedy selector reached from ``playlist.build``. Each bad
    class below must raise its named error; silently coercing any of
    them would let preview and saved resolution consume different
    effective evidence for the same spec.
    """
    from fine_art_archive.preference.exhibition import (
        EmbeddingDimensionError,
        ExhibitionValidationError,
        MissingEvidenceError,
        NegativeQualityError,
        NonFiniteEvidenceError,
        SubsetSizeError,
        _validate_inputs,
    )

    ids = ["a", "b"]
    qualities = {"a": 1.0, "b": 0.5}
    vectors = {"a": [1.0, 0.0], "b": [0.0, 1.0]}
    _validate_inputs(ids, qualities, vectors, 1)
    with pytest.raises(SubsetSizeError):
        _validate_inputs(ids, qualities, vectors, 0)
    with pytest.raises(SubsetSizeError):
        _validate_inputs(ids, qualities, vectors, True)
    with pytest.raises(SubsetSizeError):
        _validate_inputs(ids, qualities, vectors, 3)
    with pytest.raises(ExhibitionValidationError, match="unique"):
        _validate_inputs(["a", "a"], qualities, vectors, 1)
    with pytest.raises(MissingEvidenceError):
        _validate_inputs(ids, {"a": 1.0}, vectors, 1)
    with pytest.raises(MissingEvidenceError):
        _validate_inputs(ids, qualities, {"a": [1.0, 0.0]}, 1)
    with pytest.raises(NegativeQualityError):
        _validate_inputs(ids, {"a": -1.0, "b": 0.5}, vectors, 1)
    with pytest.raises(NonFiniteEvidenceError):
        _validate_inputs(ids, {"a": float("nan"), "b": 0.5}, vectors, 1)
    with pytest.raises(EmbeddingDimensionError):
        _validate_inputs(ids, qualities, {"a": [1.0, 0.0], "b": [1.0]}, 1)
    with pytest.raises(EmbeddingDimensionError):
        _validate_inputs(ids, qualities, {"a": [0.0, 0.0], "b": [0.0, 1.0]}, 1)
    with pytest.raises(NonFiniteEvidenceError):
        _validate_inputs(ids, qualities, {"a": [float("inf"), 0.0], "b": [0.0, 1.0]}, 1)


def test_helper_edge_select_quality_diverse_is_seeded_and_diagnosed():
    """The selector edge: same evidence and seed must give the same picks.

    ``select_quality_diverse`` validates via ``_validate_inputs``, then
    picks greedily by determinant with quality and a seeded SHA-256 rank
    as tie-breaks. Preview and saved resolution share this code through
    ``_build_eink_playlist``/``playlist.build``, so non-determinism or
    diagnostics that drift from the pick order would diverge the two
    surfaces even with identical inputs.
    """
    from fine_art_archive.preference.exhibition import (
        MissingEvidenceError,
        select_quality_diverse,
    )

    ids = ["near-a", "near-b", "diverse"]
    qualities = {"near-a": 1.0, "near-b": 0.99, "diverse": 0.85}
    vectors = {"near-a": [1.0, 0.0], "near-b": [0.999, 0.04], "diverse": [0.0, 1.0]}
    first = select_quality_diverse(ids, qualities, vectors, 2, seed=17)
    second = select_quality_diverse(ids, qualities, vectors, 2, seed=17)
    assert first.selected_ids == second.selected_ids == ["near-a", "diverse"]
    assert [item.work_id for item in first.diagnostics] == first.selected_ids
    assert first.diagnostics[0].nearest_selected_similarity is None
    assert first.diagnostics[1].nearest_selected_similarity is not None
    with pytest.raises(MissingEvidenceError):
        select_quality_diverse(ids, {"near-a": 1.0}, vectors, 2, seed=17)


def test_helper_edge_feed_manifest_consumes_saved_playlist_inputs():
    """The feed-manifest edge: manifest must carry the saved render inputs.

    ``build_manifest`` (eink/feed.py) is what a polling device reads; it
    consumes the saved playlist's ``target``/``dither``/``interval`` plus
    the resolved items in selection order, ``base_url`` and ``now``.
    ``rotation_index`` turns ``interval``/``now``/``offset`` into the
    current position, and ``palette_fingerprint`` (bound into the feed
    ETag by ``_render_feed_image``) must track colours and measured
    status while ignoring provenance-only fields. If any of these inputs
    stopped being consumed, the manifest a device polls could diverge
    from the images the feed renders without any test failing.
    """
    from datetime import UTC, datetime

    from fine_art_archive.eink.feed import (
        SavedPlaylist,
        build_manifest,
        palette_fingerprint,
        rotation_index,
    )

    playlist = SavedPlaylist(
        id="winter-abc123",
        name="Winter",
        spec={"sort": "fit"},
        target="gooddisplay-315-diy",
        dither="atkinson",
        fit="cover",
        interval="daily",
    )
    items = [
        {"work_id": "work-a", "title": "A", "artist": "Artist A", "year": 1650},
        {"work_id": "work-b", "title": "B", "artist": "Artist B", "year": None},
    ]
    now = datetime(2026, 1, 1, tzinfo=UTC)
    manifest = build_manifest(playlist, items, base_url="https://panel.example/", now=now)
    assert manifest["playlist_id"] == "winter-abc123"
    assert manifest["target"] == "gooddisplay-315-diy"
    assert manifest["dither"] == "atkinson"
    assert manifest["interval"] == "daily"
    assert manifest["count"] == 2
    assert manifest["current_index"] == rotation_index(2, "daily", now=now)
    assert manifest["current_url"] == "https://panel.example/feed/winter-abc123/current"
    assert [item["work_id"] for item in manifest["items"]] == ["work-a", "work-b"]
    assert manifest["items"][1]["url"] == "https://panel.example/feed/winter-abc123/image/1"
    assert manifest["items"][1]["year"] is None
    empty = build_manifest(playlist, [], base_url="https://panel.example", now=now)
    assert empty["count"] == 0 and empty["current_url"] is None
    # Rotation: offset separates a second frame; empty playlists index to 0.
    assert rotation_index(0, "daily", now=now) == 0
    assert (
        rotation_index(3, "daily", now=now, offset=1)
        == (rotation_index(3, "daily", now=now) + 1) % 3
    )
    # Palette fingerprint: provenance is excluded, pixels/measured are not.
    base = Palette(name="p", colours=((1, 2, 3), (4, 5, 6)), note="one")
    renamed = Palette(name="q", colours=((1, 2, 3), (4, 5, 6)), note="two")
    recoloured = Palette(name="p", colours=((1, 2, 3), (4, 5, 7)), note="one")
    measured = Palette(name="p", colours=((1, 2, 3), (4, 5, 6)), measured=True)
    assert palette_fingerprint(base) == palette_fingerprint(renamed)
    assert palette_fingerprint(base) != palette_fingerprint(recoloured)
    assert palette_fingerprint(base) != palette_fingerprint(measured)


def test_enumerated_api_only_spec_fields_filter_preview_selection(tmp_path, monkeypatch):
    """API-only ``PlaylistSpec`` fields must filter the preview selection.

    The audit enumeration lists ``genres``, ``year_from``/``year_to``,
    ``any_tags``, ``not_tags`` and ``min_quality`` as API-only: the operator
    UI's ``einkSpec()`` never emits them, so no UI-forwarding test can lock
    them, yet the audit marks them already-correct because every backend
    surface consumes them through the one shared builder
    (``_build_eink_playlist``). Until now only their existence and defaults
    were locked (signature/default tests above); their filtering behaviour
    was not. Each spec below must select the same works through the
    companion preview endpoint as through ``build`` directly, in input
    order (``sort="as-filtered"``), so a dropped filter branch in
    ``eink/playlist.py`` — e.g. removing the ``min_quality`` block — fails
    here rather than silently previewing works delivery would exclude.
    """
    from fine_art_archive.api import main as api_main

    rows = [
        sidecar(
            "landscape-1650",
            genre="painting/landscape",
            year=1650,
            tags=("setting:outdoor", "shape:round"),
        ),
        sidecar(
            "portrait-1800",
            genre="painting/portrait",
            year=1800,
            tags=("setting:indoor",),
        ),
        sidecar(
            "landscape-1900",
            genre="painting/landscape",
            year=1900,
            tags=("setting:outdoor", "theme:sea"),
        ),
    ]
    ratings = tmp_path / "ratings.jsonl"
    ratings.write_text(
        "\n".join(
            json.dumps({"work_id": wid, "fit": 9, "quality": quality})
            for wid, quality in (
                ("landscape-1650", 9),
                ("portrait-1800", 4),
                ("landscape-1900", 7),
            )
        )
    )
    monkeypatch.setattr(api_main, "_all_sidecars", lambda: rows)
    monkeypatch.setattr(api_main.store, "RATINGS_LOG", ratings)
    monkeypatch.setattr(api_main.store, "work_ids_with_dossier", frozenset)

    cases = [
        ({"genres": ["painting/landscape"]}, ["landscape-1650", "landscape-1900"]),
        ({"year_from": 1700, "year_to": 1850}, ["portrait-1800"]),
        ({"any_tags": ["theme:sea", "setting:indoor"]}, ["portrait-1800", "landscape-1900"]),
        ({"not_tags": ["setting:outdoor"]}, ["portrait-1800"]),
        ({"min_quality": 7}, ["landscape-1650", "landscape-1900"]),
    ]
    for spec_dict, expected in cases:
        spec = {**spec_dict, "sort": "as-filtered"}
        direct = build(
            rows, PlaylistSpec.from_dict(spec), ratings=api_main._eink.load_ratings(ratings)
        )
        assert direct.work_ids == expected, f"direct build disagrees for {spec_dict}"
        response = api_main.eink_playlist_preview(api_main.PlaylistIn(spec=spec))
        assert response["work_ids"] == expected, (
            f"preview does not consume {sorted(spec_dict)} — previewed works "
            "would diverge from the saved feed and SD export selection"
        )


def test_operator_ui_renders_saved_feed_delivery_identity():
    """Saved feeds must list the delivery identity the operator saved.

    ``GET /eink/playlists`` returns each ``SavedPlaylist`` plus the derived
    ``resolved_count``/``error``, ``feed_url`` and ``manifest_url``
    (api/main.py ``eink_playlists``). ``einkLoadPlaylists`` (index.html) is
    the only operator surface that lists saved feeds: it renders name,
    work count (or an error marker), panel target, rotation interval and
    the device URL, and wires the ``to card`` / ``delete`` actions that
    choose or remove a saved feed for SD export. The enumeration locks
    the backend fields, and the forwarding tests lock save/export bodies,
    but nothing locked this list rendering: dropping e.g. the interval
    cell or the manifest link would leave a saved feed whose delivered
    panel/rotation the operator could no longer verify against the
    preview, with every backend test still passing. Removing the
    interval cell in ``index.html`` must fail this test.
    """
    from fine_art_archive.api.main import UI_FILE

    ui = UI_FILE.read_text()
    assert "No saved feeds yet." in ui, "empty saved-feed list renders nothing"
    fields = [
        ("${einkEsc(p.name)}", "saved feed name"),
        ("${einkEsc(p.target)}", "saved panel target"),
        ("${einkEsc(p.interval)}", "saved rotation interval"),
        ("${einkEsc(origin)}${einkEsc(p.feed_url)}", "device feed URL"),
        ('href="${einkEsc(p.manifest_url)}"', "manifest link"),
        ('href="${einkEsc(p.feed_url)}"', "feed view link"),
        ('data-eink-use="${einkEsc(p.id)}">to card</a>', "to-card action"),
        ('data-eink-del="${einkEsc(p.id)}"', "delete action"),
        ('data-eink-name="${einkEsc(p.name)}"', "delete confirmation name"),
    ]
    for snippet, label in fields:
        assert snippet in ui, f"saved-feed list does not render {label}"
    assert "p.resolved_count == null" in ui, "unresolvable feed must read as an error"
    assert "'<span style=\"color:#a00\">error</span>'" in ui, "resolve error is not marked"
    assert ": p.resolved_count}" in ui, "resolved work count is not rendered for a healthy feed"
    assert 'host.querySelectorAll("[data-eink-use]")' in ui, "to-card action is unwired"
    assert (
        'einkUseForCard(a.getAttribute("data-eink-use"));' in ui
    ), "to-card action does not choose that saved feed for export"
    assert 'host.querySelectorAll("[data-eink-del]")' in ui, "delete action is unwired"
    assert (
        'einkDeletePlaylist(a.getAttribute("data-eink-del")' in ui
    ), "delete action does not delete that saved feed"
    assert 'a.getAttribute("data-eink-name")' in ui, "delete loses the feed name"


def test_operator_ui_discloses_saved_feed_overrides_filters_on_export():
    """Choosing a saved feed for the card must disclose filters are ignored.

    When ``einkCardPlaylistId`` is set, ``einkExport`` still sends the
    filter ``spec`` but the backend replaces it with the saved playlist's
    ``spec``/``target``/``dither``/``fit`` (api/main.py
    ``eink_playlist_export``, the ``playlist_id`` override in the audit
    enumeration). ``einkUseForCard`` (index.html) is the operator-facing
    side of that override: it sets the choice, says the card will use
    that feed's selection, and renders a banner naming the feed and
    stating the filters above are ignored, with a ``use filters
    instead`` clear link. The body-forwarding tests lock that
    ``playlist_id`` is sent; nothing locked this disclosure. Dropping
    the banner text in ``index.html`` would let the operator believe
    the visible filters still shape a card that actually delivers the
    saved feed. Removing that text must fail this test.
    """
    from fine_art_archive.api.main import UI_FILE

    ui = UI_FILE.read_text()
    assert "function einkUseForCard(id) {" in ui, "no saved-feed card choice exists"
    assert "einkCardPlaylistId = id;" in ui, "to-card choice is not recorded"
    assert "card will use that saved feed" in ui, "choice does not say the feed is used"
    assert (
        "Card uses saved feed <strong>${einkEsc(id)}</strong>" in ui
    ), "banner does not name the saved feed the card will deliver"
    assert (
        "filters above are ignored." in ui
    ), "banner does not disclose that the filter spec is overridden by the saved feed on export"
    assert (
        '<a href="#" id="ek-clear">use filters instead</a>' in ui
    ), "no way back from the saved-feed override to the filter spec"
    assert (
        'document.getElementById("ek-clear")?.addEventListener("click"' in ui
    ), "the clear link in the override banner is unwired"
    assert 'banner.textContent = "";' in ui, "clearing the choice leaves the banner up"


# ---------------------------------------------------------------- counts ----
_COUNT_FIRST = "aaa1111-first-work"
_COUNT_SECOND = "bbb2222-second-work"
_COUNT_SPEC = {"sort": "title"}
_EMPTY_SPEC = {"sort": "title", "artists": ["No Such Artist"]}


def _count_client(tmp_path, monkeypatch, masters: tuple[bool, bool]):
    """Two selected works on an isolated archive. ``masters`` is (first, second)."""
    from fastapi.testclient import TestClient

    from fine_art_archive.api import main as api_main
    from fine_art_archive.api import store as api_store
    from fine_art_archive.api.main import app

    works = tmp_path / "works"
    works.mkdir()
    monkeypatch.setattr(api_store, "WORKS", works)
    monkeypatch.setattr(api_main, "ART_WORKS_ROOT", works)
    monkeypatch.setattr(api_main, "IMAGE_CACHE_DIR", tmp_path / "image_cache")
    monkeypatch.setattr(api_store, "RATINGS_LOG", tmp_path / "ratings.jsonl")
    monkeypatch.setattr(api_main, "_sidecars_cache", None)
    monkeypatch.setattr(api_main, "_ratings_cache", None)
    for work_id, title, master in (
        (_COUNT_FIRST, "First", masters[0]),
        (_COUNT_SECOND, "Second", masters[1]),
    ):
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


@pytest.mark.parametrize(
    ("masters", "spec", "selected", "available"),
    [
        ((True, False), _COUNT_SPEC, 2, 1),
        ((True, True), _COUNT_SPEC, 2, 2),
        ((False, False), _COUNT_SPEC, 2, 0),
        ((True, False), _EMPTY_SPEC, 0, 0),
    ],
    ids=["mixed", "all-master", "all-missing", "empty"],
)
def test_playlist_preview_counts_selected_and_available_for_delivery(
    tmp_path, monkeypatch, masters, spec, selected, available
):
    """Selection counts include missing masters; delivery counts do not.

    The mixed case keeps both works and flags the one without a master.
    ``available_for_delivery`` is computed over the full selection, so a
    ``sample=0`` response still reports it when ``items`` is empty.
    """
    client = _count_client(tmp_path, monkeypatch, masters)
    response = client.post("/eink/playlist/preview", json={"spec": spec})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["selected"] == selected
    assert body["available_for_delivery"] == available
    assert len(body["work_ids"]) == selected
    if masters == (True, False) and spec == _COUNT_SPEC:
        assert body["work_ids"] == [_COUNT_FIRST, _COUNT_SECOND]
        flagged = {item["work_id"]: item["has_master"] for item in body["items"]}
        assert flagged == {_COUNT_FIRST: True, _COUNT_SECOND: False}
        truncated = client.post("/eink/playlist/preview", json={"spec": spec, "sample": 0})
        assert truncated.status_code == 200, truncated.text
        short = truncated.json()
        assert short["items"] == []
        assert short["work_ids"] == [_COUNT_FIRST, _COUNT_SECOND]
        assert short["selected"] == 2
        assert short["available_for_delivery"] == 1


@pytest.mark.parametrize("sample", [0, 1, 24], ids=["no-rows", "one-row", "full-sample"])
@pytest.mark.parametrize(
    "masters", [(True, False), (False, True)], ids=["missing-last", "missing-first"]
)
def test_ui_preview_counts_match_the_production_mixed_master_response(
    tmp_path, monkeypatch, sample, masters
):
    """Real preview responses keep full totals across empty and truncated samples."""
    from fine_art_archive.api.main import UI_FILE

    node = shutil.which("node")
    assert node is not None, "node is required to verify the companion's count consumers"
    client = _count_client(tmp_path, monkeypatch, masters)
    response = client.post("/eink/playlist/preview", json={"spec": _COUNT_SPEC, "sample": sample})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["selected"] == 2
    assert body["available_for_delivery"] == 1
    assert body["work_ids"] == [_COUNT_FIRST, _COUNT_SECOND]
    assert [item["has_master"] for item in body["items"]] == list(masters[:sample])

    ui = UI_FILE.read_text()
    start = ui.index("    async function einkPreview() {")
    preview_function = ui[start : ui.index("    async function einkExport(write)", start)]
    runner = tmp_path / "production-preview-counts.cjs"
    runner.write_text(
        """
const response = JSON.parse(process.argv[2]);
const controls = {
  'ek-target': {value: response.target},
  'ek-dither': {value: 'none'},
  'ek-fitmode': {value: ''},
  'ek-out': {innerHTML: ''},
};
const document = {getElementById: id => controls[id] || null};
let einkLastPreview;
const einkSpec = () => ({sort: 'title'});
const einkEsc = value => String(value);
const fetch = async () => ({ok: true, json: async () => response});
"""
        + preview_function
        + """
einkPreview().then(() => {
  console.log(JSON.stringify({html: controls['ek-out'].innerHTML, last: einkLastPreview}));
}).catch(error => { console.error(error); process.exitCode = 1; });
""",
        encoding="utf-8",
    )
    result = subprocess.run(
        [node, str(runner), json.dumps(body)],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    observed = json.loads(result.stdout)
    assert observed["last"] == body
    html = observed["html"]
    assert "<strong>2</strong> selected" in html
    assert "<strong>1</strong> available for delivery" in html
    assert "<strong>2</strong> available for delivery" not in html
    assert "<strong>0</strong> available for delivery" not in html
    assert html.count('<img loading="lazy"') == min(sample, 2)
    missing_shown = sum(not item["has_master"] for item in body["items"])
    if missing_shown:
        assert f"{missing_shown} shown have no local image" in html
    else:
        assert "shown have no local image" not in html


@pytest.mark.parametrize(
    ("selected", "available"),
    [(2, 1), (2, 2), (2, 0), (0, 0)],
    ids=["mixed", "all-master", "all-missing", "empty"],
)
def test_ui_count_consumers_do_not_treat_the_sample_as_delivered(tmp_path, selected, available):
    """Selection, delivery and write labels retain explicit totals, including zero.

    Nonempty preview samples mark both rows ``has_master: true`` even when
    the response's full delivery total is zero or one. Empty selections have
    no rows. A zero total must not fall back to the selection or sample size.
    Export and dry-run responses cover the same four selection cases, but
    always carry ``available_for_delivery: 2`` as a trap. Their rendered
    totals must follow the writer's ``written`` / ``dry_run`` /
    ``missing_master_omissions`` fields, including zero. A dry run must
    display 0 actually written even when its planned count is nonzero.

    Two further writer payloads keep those fields from collapsing into each
    other. A render failure has ``written`` 1 and ``missing_master_omissions``
    0 while ``available_for_delivery`` is still 2, so the screen must not
    invent an omission from ``selected - written``. A second payload has
    ``written`` 0, ``skipped`` 2 and ``missing_master_omissions`` 1, so the
    omission label cannot be the skip total or ``selected - written`` either.
    """
    from fine_art_archive.api.main import UI_FILE

    node = shutil.which("node")
    assert node is not None, "node is required to verify the companion's count consumers"
    ui = UI_FILE.read_text()
    functions = []
    for start, end in (
        ("    async function einkPreview() {", "    async function einkExport(write)"),
        ("    async function einkExport(write) {", "    function toggleGallery()"),
    ):
        functions.append(ui[ui.index(start) : ui.index(end, ui.index(start))])

    runner = tmp_path / "count-consumers.cjs"
    runner.write_text(
        """
const controls = {
  'ek-target': {value: 'count-contract'},
  'ek-dither': {value: 'none'},
  'ek-fitmode': {value: ''},
  'ek-path': {value: '/fixture/card'},
  'ek-out': {innerHTML: '', insertAdjacentHTML() {}},
  'ek-status': {innerHTML: ''},
};
const document = {getElementById: id => controls[id] || null};
let einkLastPreview, einkCardPlaylistId = null;
const einkSpec = () => ({sort: 'title'});
const einkEsc = value => String(value);
const confirm = () => true;
const toast = () => {};
const previewCounts = JSON.parse(process.argv[2]);
let exportCall = 0;
const fetch = async (url, options) => {
  const body = JSON.parse(options.body);
  if (url === '/eink/playlist/preview') {
    return {ok: true, json: async () => ({
      coverage: {},
      items: previewCounts.selected ? [
        {work_id: 'aaa1111-first-work', has_master: true, year: 1650, artist: 'A', title: 'First'},
        {work_id: 'bbb2222-second-work', has_master: true, year: 1650, artist: 'A', title: 'Second'},
      ] : [],
      selected: previewCounts.selected,
      available_for_delivery: previewCounts.available,
      matched: previewCounts.selected,
      total_candidates: 2,
      selection_diagnostics: [],
    })};
  }
  exportCall += 1;
  if (exportCall <= 2) {
    return {ok: true, json: async () => ({
      selected: previewCounts.selected,
      written: previewCounts.available,
      dry_run: !body.write,
      bytes_written: body.write ? 2048 * previewCounts.available : 0,
      path: '/fixture/card',
      skipped: previewCounts.selected - previewCounts.available,
      missing_master_omissions: previewCounts.selected - previewCounts.available,
      available_for_delivery: 2,
      palette_measured: true,
    })};
  }
  if (exportCall === 3) {
    return {ok: true, json: async () => ({
      selected: 2,
      written: 1,
      dry_run: !body.write,
      bytes_written: 2048,
      path: '/fixture/card',
      skipped: 1,
      missing_master_omissions: 0,
      available_for_delivery: 2,
      palette_measured: true,
    })};
  }
  return {ok: true, json: async () => ({
    selected: 2,
    written: 0,
    dry_run: !body.write,
    bytes_written: 0,
    path: '/fixture/card',
    skipped: 2,
    missing_master_omissions: 1,
    available_for_delivery: 2,
    palette_measured: true,
  })};
};
"""
        + "\n".join(functions)
        + """
(async () => {
  await einkPreview();
  const previewHTML = controls['ek-out'].innerHTML;
  await einkExport(true);
  const writeHTML = controls['ek-status'].innerHTML;
  await einkExport(false);
  const dryHTML = controls['ek-status'].innerHTML;
  await einkExport(true);
  const renderFailHTML = controls['ek-status'].innerHTML;
  await einkExport(true);
  const divergeHTML = controls['ek-status'].innerHTML;
  console.log(JSON.stringify({previewHTML, writeHTML, dryHTML, renderFailHTML, divergeHTML}));
})().catch(error => { console.error(error); process.exitCode = 1; });
""",
        encoding="utf-8",
    )
    result = subprocess.run(
        [node, str(runner), json.dumps({"selected": selected, "available": available})],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    observed = json.loads(result.stdout)
    preview = observed["previewHTML"]
    written = observed["writeHTML"]
    dry = observed["dryHTML"]
    render_fail = observed["renderFailHTML"]
    diverge = observed["divergeHTML"]
    assert f"<strong>{selected}</strong> selected" in preview
    assert f"<strong>{available}</strong> available for delivery" in preview
    for other in {0, 1, 2} - {available}:
        assert f"<strong>{other}</strong> available for delivery" not in preview
    assert f"<strong>{selected}</strong> selected" in written
    assert f"<strong>{available}</strong> actually written" in written
    for other in {0, 1, 2} - {available}:
        assert f"<strong>{other}</strong> actually written" not in written
    assert "would write" not in written
    assert f"<strong>{selected}</strong> selected" in dry
    assert "<strong>0</strong> actually written" in dry
    assert "<strong>1</strong> actually written" not in dry
    assert "<strong>2</strong> actually written" not in dry
    assert f"would write {available} file(s)" in dry
    omissions = selected - available
    for html in (written, dry):
        if omissions:
            suffix = "s" if omissions != 1 else ""
            assert f"{omissions} missing-master omission{suffix}" in html
            assert f"{omissions} skipped" in html
        else:
            assert "missing-master omission" not in html
            assert " skipped" not in html
    assert "<strong>1</strong> actually written" in render_fail
    assert "<strong>2</strong> actually written" not in render_fail
    assert "missing-master omission" not in render_fail
    assert "<strong>0</strong> actually written" in diverge
    assert "<strong>2</strong> actually written" not in diverge
    assert "1 missing-master omission" in diverge
    assert "2 missing-master omission" not in diverge
