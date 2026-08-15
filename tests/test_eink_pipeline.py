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


@pytest.mark.parametrize(
    "raw,expected",
    [
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
def test_etag_changes_when_the_master_or_render_settings_change():
    base = item_etag("w1", "t1", "floyd-steinberg", 1000)
    assert base == item_etag("w1", "t1", "floyd-steinberg", 1000)
    assert base != item_etag("w1", "t1", "floyd-steinberg", 1001), "re-master must bust cache"
    assert base != item_etag("w1", "t2", "floyd-steinberg", 1000), "panel change must bust cache"
    assert base != item_etag("w1", "t1", "atkinson", 1000), "dither change must bust cache"


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
