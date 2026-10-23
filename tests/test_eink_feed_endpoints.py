"""The e-ink feed: what a dumb panel gets when it polls, and what it must never get.

The device on the other end of these URLs has no memory, no screen to show an error on, and no way
to tell a 404 from a blank wall. So the failure that matters here is not an exception — it is a
frame that goes dark and stays dark until somebody walks past and notices.

Two properties carry most of that weight, and both are stated in the code's own docstrings:

* *"A feed must only advertise works it can actually serve, or a device polling `next` walks into a
  404 and shows nothing."* — a playlist may resolve to works whose master file is absent, and those
  must be filtered out of the list rather than discovered at render time.
* *"Which work this returns is computed from the clock, not from server state, so it is idempotent,
  survives a reboot at either end, and two frames on the same feed stay in step."* — the rotation
  index is a pure function of the wall clock, which is what makes a stateless device correct.

Neither was tested.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from fine_art_archive import eink as _eink
from fine_art_archive.api import main as api_main
from fine_art_archive.api import store as api_store
from fine_art_archive.api.main import app
from fine_art_archive.eink.feed import rotation_index
from fine_art_archive.eink.palette import PALETTES, Palette
from fine_art_archive.eink.targets import TARGETS, RenderTarget


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def archive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A works tree, a playlist store, and a tile cache, none of them the real ones."""
    works = tmp_path / "works"
    works.mkdir()
    monkeypatch.setattr(api_store, "WORKS", works)
    monkeypatch.setattr(api_main, "ART_WORKS_ROOT", works)
    monkeypatch.setattr(api_main, "IMAGE_CACHE_DIR", tmp_path / "image_cache")
    monkeypatch.setattr(api_main, "EINK_PLAYLISTS", tmp_path / "eink_playlists.json")
    monkeypatch.setattr(
        api_main, "_playlists", _eink.PlaylistStore(tmp_path / "eink_playlists.json")
    )
    monkeypatch.setattr(api_main, "_sidecars_cache", None)
    return works


def _work(archive: Path, work_id: str, *, title: str, master: bool = True) -> None:
    """One work: a sidecar always, a master image only when asked for."""
    directory = archive / work_id
    directory.mkdir(parents=True, exist_ok=True)
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
        Image.new("RGB", (80, 60), (30, 60, 90)).save(directory / "master.jpeg", "JPEG")
    api_main._sidecars_cache = None


def _save(client: TestClient, **body) -> dict:
    payload = {"name": "Wall", "spec": {}, "interval": "daily"}
    payload.update(body)
    response = client.post("/eink/playlists", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def test_feed_etag_tracks_ordered_palette_and_measurement_only(monkeypatch):
    palette = Palette("feed-validator", ((0, 0, 0), (255, 255, 255)))
    target = RenderTarget("palette-validator", "Palette validator", 8, 6, palette.name)
    monkeypatch.setitem(TARGETS, target.key, target)
    monkeypatch.setitem(PALETTES, palette.name, palette)

    # Fingerprint is ordered colours + measured only; provenance fields are ignored.
    assert _eink.palette_fingerprint(palette) == "[[[0,0,0],[255,255,255]],false]"
    assert _eink.palette_fingerprint(replace(palette, name="alias", note="x")) == (
        _eink.palette_fingerprint(palette)
    )
    assert _eink.palette_fingerprint(
        replace(palette, colours=((1, 2, 3), (255, 255, 255)))
    ) != _eink.palette_fingerprint(palette)
    assert _eink.palette_fingerprint(
        replace(palette, colours=tuple(reversed(palette.colours)))
    ) != _eink.palette_fingerprint(palette)
    assert _eink.palette_fingerprint(replace(palette, measured=True)) != (
        _eink.palette_fingerprint(palette)
    )

    def tag(value):
        return _eink.item_etag("work", target.key, "none", 123, fit="contain", palette=value)

    original = tag(palette)
    assert tag(replace(palette)) == original
    assert tag(replace(palette, name="alias", note="provenance only")) == original
    assert tag(replace(palette, colours=((1, 2, 3), (255, 255, 255)))) != original
    assert tag(replace(palette, colours=tuple(reversed(palette.colours)))) != original
    assert tag(replace(palette, measured=True)) != original
    # Master mtime, fit and strategy stay in the validator alongside the fingerprint.
    assert (
        _eink.item_etag(
            "work",
            target.key,
            "none",
            123,
            fit="contain",
            render_strategy="color",
            palette=palette,
        )
        == original
    )
    assert (
        _eink.item_etag(
            "work",
            target.key,
            "none",
            124,
            fit="contain",
            render_strategy="color",
            palette=palette,
        )
        != original
    )
    # The default path must also observe palette changes for existing callers.
    assert _eink.item_etag("work", target.key, "none", 123, fit="contain") == original
    monkeypatch.setitem(PALETTES, palette.name, replace(palette, measured=True))
    assert _eink.item_etag("work", target.key, "none", 123, fit="contain") != original


@pytest.mark.parametrize("route", ["image/0", "current"])
@pytest.mark.parametrize("change", ["colours", "measured"])
def test_palette_change_revalidates_feed_image(client, archive, monkeypatch, route, change):
    work_id = "aaa1111-palette-cache"
    _work(archive, work_id, title="Palette cache")
    palette = Palette("feed-cache", ((0, 0, 0), (255, 255, 255), (255, 0, 0)))
    target = RenderTarget("palette-cache", "Palette cache", 8, 6, palette.name)
    monkeypatch.setitem(PALETTES, palette.name, palette)
    monkeypatch.setitem(TARGETS, target.key, target)
    saved = _save(client, target=target.key, dither="none", fit="contain")
    url = f"/feed/{saved['id']}/{route}"
    master_mtime = (archive / work_id / "master.jpeg").stat().st_mtime
    original = client.get(url)
    assert original.status_code == 200
    old_tag = original.headers["ETag"]
    assert original.headers["X-Palette-Measured"] == "False"
    unchanged = client.get(url)
    assert unchanged.headers["ETag"] == old_tag
    assert unchanged.content == original.content
    assert client.get(url, headers={"If-None-Match": old_tag}).status_code == 304

    updated_palette = (
        replace(palette, colours=((10, 20, 30), (220, 230, 240), (100, 150, 200)))
        if change == "colours"
        else replace(palette, measured=True)
    )
    monkeypatch.setitem(PALETTES, palette.name, updated_palette)
    refreshed = client.get(url, headers={"If-None-Match": old_tag})
    assert refreshed.status_code == 200, "palette changes must invalidate the old validator"
    assert refreshed.headers["ETag"] != old_tag
    assert refreshed.headers["X-Palette-Measured"] == str(updated_palette.measured)
    assert refreshed.headers["X-Render-Strategy"] == original.headers["X-Render-Strategy"]
    assert refreshed.headers["Cache-Control"] == original.headers["Cache-Control"]
    assert (archive / work_id / "master.jpeg").stat().st_mtime == master_mtime
    with (
        Image.open(BytesIO(original.content)) as before,
        Image.open(BytesIO(refreshed.content)) as after,
    ):
        before_pixels = list(before.convert("RGB").getdata())
        after_pixels = list(after.convert("RGB").getdata())
    if change == "colours":
        assert after_pixels != before_pixels
        assert set(after_pixels) <= set(updated_palette.colours)
    else:
        assert after_pixels == before_pixels
    current = client.get(url, headers={"If-None-Match": refreshed.headers["ETag"]})
    assert current.status_code == 304
    assert current.content == b""


@pytest.mark.parametrize("route", ["image/0", "current"])
@pytest.mark.parametrize(
    "before,after", [("contain", "cover"), ("cover", "stretch"), ("stretch", "contain")]
)
def test_fit_change_invalidates_saved_feed_image(
    client, archive, monkeypatch, route, before, after
):
    work_id = "aaa1111-fit-cache"
    _work(archive, work_id, title="Fit cache")
    # Unequal geometry and patterned pixels distinguish all three actual renderings.
    master = Image.new("RGB", (10, 30), "white")
    for y in range(30):
        for x in range(10):
            master.putpixel((x, y), (0, 0, 0) if x < 4 and 5 <= y < 25 else (255, 255, 255))
    master.save(archive / work_id / "master.jpeg", "JPEG")
    target = RenderTarget("fit-cache", "Fit cache", 30, 20, "spectra6")
    monkeypatch.setitem(TARGETS, target.key, target)
    saved = _save(client, target=target.key, dither="none", fit=before)
    url = f"/feed/{saved['id']}/{route}"
    original = client.get(url)
    assert original.status_code == 200
    old_tag = original.headers["ETag"]
    assert client.get(url, headers={"If-None-Match": old_tag}).status_code == 304

    updated = _save(client, id=saved["id"], target=target.key, dither="none", fit=after)
    assert updated["id"] == saved["id"]
    unconditional = client.get(url)
    assert unconditional.status_code == 200
    assert unconditional.content != original.content
    with Image.open(BytesIO(unconditional.content)) as rendered:
        assert rendered.size == target.size
    revalidated = client.get(url, headers={"If-None-Match": old_tag})
    assert revalidated.status_code == 200, "changed framing must invalidate the old image"
    assert revalidated.content == unconditional.content
    assert revalidated.headers["ETag"] != old_tag
    assert revalidated.headers["Cache-Control"] == original.headers["Cache-Control"]
    current = client.get(url, headers={"If-None-Match": revalidated.headers["ETag"]})
    assert current.status_code == 304
    assert current.content == b""


@pytest.mark.parametrize("route", ["image/0", "current"])
@pytest.mark.parametrize("default_fit", ["contain", "cover", "stretch"])
@pytest.mark.parametrize("unset_fit", [None, ""])
def test_unset_fit_and_explicit_target_default_share_feed_etag(
    client, archive, monkeypatch, route, default_fit, unset_fit
):
    _work(archive, "aaa1111-fit-default", title="Default fit")
    target = RenderTarget("fit-default", "Fit default", 30, 20, "spectra6", fit=default_fit)
    monkeypatch.setitem(TARGETS, target.key, target)
    saved = _save(client, target=target.key, dither="none", fit=unset_fit)
    url = f"/feed/{saved['id']}/{route}"
    original = client.get(url)
    assert original.status_code == 200
    _save(client, id=saved["id"], target=target.key, dither="none", fit=default_fit)
    explicit = client.get(url)
    assert explicit.status_code == 200
    assert explicit.content == original.content
    assert explicit.headers["ETag"] == original.headers["ETag"]
    assert client.get(url, headers={"If-None-Match": original.headers["ETag"]}).status_code == 304


def test_applied_strategy_change_invalidates_etag(client, archive, monkeypatch):
    """The issue's named feed gate rejects a validator for the former policy."""
    import io

    from fine_art_archive.eink import render_strategy

    _work(archive, "magenta", title="Magenta")
    Image.new("RGB", (40, 20), (255, 0, 255)).save(
        archive / "magenta" / "master.jpeg", format="PNG"
    )
    target = _eink.RenderTarget("strategy-test", "Test", 40, 20, "spectra6")
    monkeypatch.setitem(_eink.TARGETS, target.key, target)
    playlist = _save(client, target=target.key, dither="none")
    url = f"/feed/{playlist['id']}/current"
    first = client.get(url)
    assert first.status_code == 200
    assert first.headers["X-Render-Strategy"] == "grayscale"
    monkeypatch.setitem(render_strategy._DEFAULT_POLICY, "poorly-served", "color")
    changed = client.get(url, headers={"If-None-Match": first.headers["ETag"]})
    assert changed.status_code == 200
    assert changed.headers["X-Render-Strategy"] == "color"
    assert changed.headers["ETag"] != first.headers["ETag"]
    assert changed.content != first.content
    with Image.open(io.BytesIO(changed.content)) as rendered:
        assert set(rendered.getdata()) - {target.palette.black, target.palette.white}


def test_atomic_sidecar_writer_forces_utf8_under_ascii_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An ASCII process locale must not prevent sidecars from preserving artist names."""
    real_fdopen = api_main.os.fdopen
    encodings: list[str | None] = []

    def ascii_default_fdopen(fd: int, mode: str = "r", *args, **kwargs):
        encoding = kwargs.get("encoding")
        encodings.append(encoding)
        if "b" not in mode and encoding in (None, "locale"):
            kwargs["encoding"] = "ascii"
        return real_fdopen(fd, mode, *args, **kwargs)

    monkeypatch.setattr(api_main.os, "fdopen", ascii_default_fdopen)
    sidecar = tmp_path / "meta.json"

    api_main._write_sidecar_atomic(sidecar, {"artist": {"name": "Albrecht Dürer"}})

    assert encodings == ["utf-8"]
    assert json.loads(sidecar.read_bytes().decode("utf-8"))["artist"]["name"] == "Albrecht Dürer"


def test_subject_tag_event_writer_forces_utf8_under_ascii_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Subject-tag audit events use the same explicit encoding guarantee as sidecars."""
    events = tmp_path / "subject_tag_events.jsonl"
    real_open = open
    encodings: list[str | None] = []

    def ascii_default_open(file, mode: str = "r", *args, **kwargs):
        encoding = kwargs.get("encoding")
        if Path(file) == events:
            encodings.append(encoding)
            if "b" not in mode and encoding in (None, "locale"):
                kwargs["encoding"] = "ascii"
        return real_open(file, mode, *args, **kwargs)

    monkeypatch.setattr(api_main, "SUBJECT_TAG_EVENTS", events)
    monkeypatch.setattr(api_main, "open", ascii_default_open, raising=False)

    api_main._append_subject_tag_event({"reviewer": "Björk", "tag": "café"})

    assert encodings == ["utf-8"]
    assert json.loads(events.read_bytes().decode("utf-8"))["reviewer"] == "Björk"


# ---------------------------------------------------------------------------------------------
# A feed only advertises what it can serve.
# ---------------------------------------------------------------------------------------------


def test_a_work_with_no_master_is_left_out_of_the_feed(client, archive):
    """The property the code names: a device polling `next` must never be handed a work whose
    image is missing, because it walks straight into a 404 and shows nothing."""
    _work(archive, "aaa1111-with-a-master", title="Served", master=True)
    _work(archive, "bbb2222-without-master", title="Sidecar only", master=False)
    playlist = _save(client)

    listed = client.get("/eink/playlists").json()["playlists"][0]
    nxt = client.get(f"/feed/{playlist['id']}/next").json()

    assert listed["resolved_count"] == 1
    assert nxt["count"] == 1
    assert nxt["work_id"] == "aaa1111-with-a-master"


def test_a_playlist_that_resolves_to_nothing_says_so_rather_than_erroring(client, archive):
    """Every one of its works has lost its master. That is a real state — an archive mid-move —
    and it has to read as an empty feed, not a crash."""
    _work(archive, "bbb2222-without-master", title="Sidecar only", master=False)
    playlist = _save(client)

    for path in ("current", "next", "image/0"):
        response = client.get(f"/feed/{playlist['id']}/{path}")
        assert response.status_code == 404, path
        assert "no works with local images" in response.json()["detail"]


def test_the_listing_reports_a_resolve_failure_without_failing_the_whole_list(client, archive):
    """One malformed saved playlist must not take out the page that would let you fix it."""
    _work(archive, "aaa1111-with-a-master", title="Served")
    good = _save(client, name="Good")
    bad = _save(client, name="Bad")
    store = api_main._playlists
    broken = store.get(bad["id"])
    broken.spec = {"sort": "no-such-sort-order"}
    store.save(broken)

    rows = {row["id"]: row for row in client.get("/eink/playlists").json()["playlists"]}

    assert rows[good["id"]]["resolved_count"] == 1
    assert rows[bad["id"]]["resolved_count"] is None
    assert "error" in rows[bad["id"]]


def test_the_listing_scans_the_corpus_once_for_every_playlist(client, archive, monkeypatch):
    """`_all_sidecars()` walks the whole works tree. Doing it per saved playlist turns a page
    render into N corpus scans over a Dropbox-mounted archive."""
    _work(archive, "aaa1111-with-a-master", title="Served")
    for index in range(4):
        _save(client, name=f"Wall {index}")

    scans = {"count": 0}
    real = api_main._all_sidecars

    def counted():
        scans["count"] += 1
        return real()

    monkeypatch.setattr(api_main, "_all_sidecars", counted)
    assert client.get("/eink/playlists").status_code == 200

    assert scans["count"] == 1


# ---------------------------------------------------------------------------------------------
# The clock decides, not the server.
# ---------------------------------------------------------------------------------------------


def test_the_same_instant_gives_the_same_index():
    """Idempotence is what lets a panel poll the same URL forever without flickering between
    works on every request."""
    now = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)
    first = rotation_index(7, "daily", now=now)
    second = rotation_index(7, "daily", now=now)

    assert first == second


def test_two_devices_on_the_same_feed_agree():
    """No shared state, no handshake — only the clock. Two frames in the same room show the same
    work because they compute the same number, not because they talked."""
    now = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)

    assert rotation_index(5, "hourly", now=now) == rotation_index(5, "hourly", now=now)


def test_an_offset_shifts_a_second_frame_to_a_different_work():
    """A pair of frames on one wall showing the same painting is the reason `offset` exists."""
    now = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)

    assert rotation_index(5, "daily", now=now, offset=1) != rotation_index(5, "daily", now=now)


def test_the_index_advances_once_per_interval():
    """A minute later is the same work; an interval later is the next one. Getting this wrong
    either freezes the frame or exhausts an e-ink panel's refresh budget."""
    now = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)

    assert rotation_index(9, "hourly", now=now + timedelta(minutes=1)) == rotation_index(
        9, "hourly", now=now
    )
    assert rotation_index(9, "hourly", now=now + timedelta(hours=1)) != rotation_index(
        9, "hourly", now=now
    )


@pytest.mark.parametrize("interval", sorted(_eink.INTERVALS))
def test_every_declared_interval_advances_after_its_own_period(interval):
    seconds = _eink.INTERVALS[interval]
    now = datetime(2026, 8, 31, 0, 0, tzinfo=UTC)

    before = rotation_index(11, interval, now=now)
    after = rotation_index(11, interval, now=now + timedelta(seconds=seconds))

    assert after == (before + 1) % 11


def test_an_unknown_interval_falls_back_to_daily_rather_than_raising():
    """The interval is read off a stored playlist, which may predate a renamed interval. A
    KeyError here would take down every feed that references it."""
    now = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)

    assert rotation_index(6, "fortnightly", now=now) == rotation_index(6, "daily", now=now)


def test_an_empty_playlist_indexes_to_zero_rather_than_dividing_by_zero():
    assert rotation_index(0, "daily") == 0


def test_the_index_always_lands_inside_the_playlist():
    """It is used directly as a list subscript."""
    now = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)
    for count in range(1, 13):
        for offset in (0, 1, 5, 100):
            assert 0 <= rotation_index(count, "daily", now=now, offset=offset) < count


# ---------------------------------------------------------------------------------------------
# The cursor pull.
# ---------------------------------------------------------------------------------------------


def test_next_starts_at_the_beginning_when_the_device_has_no_position(client, archive):
    _work(archive, "aaa1111-first-work-here", title="First")
    _work(archive, "bbb2222-second-work-ok", title="Second")
    playlist = _save(client)

    body = client.get(f"/feed/{playlist['id']}/next").json()

    assert body["index"] == 0
    assert body["count"] == 2


def test_next_advances_from_the_cursor_the_device_reports(client, archive):
    _work(archive, "aaa1111-first-work-here", title="First")
    _work(archive, "bbb2222-second-work-ok", title="Second")
    playlist = _save(client)

    first = client.get(f"/feed/{playlist['id']}/next").json()
    second = client.get(
        f"/feed/{playlist['id']}/next", params={"after": first["next_after"]}
    ).json()

    assert second["index"] == 1
    assert second["work_id"] != first["work_id"]


def test_next_wraps_at_the_end(client, archive):
    """A panel left running for a year must come back round rather than stopping."""
    _work(archive, "aaa1111-first-work-here", title="First")
    _work(archive, "bbb2222-second-work-ok", title="Second")
    playlist = _save(client)

    last = client.get(f"/feed/{playlist['id']}/next", params={"after": "bbb2222-second-work-ok"})

    assert last.json()["index"] == 0


def test_an_unknown_cursor_restarts_rather_than_failing(client, archive):
    """The work the device last showed may have been removed from the archive since. Restarting
    is the recoverable answer; a 404 leaves the frame dark forever."""
    _work(archive, "aaa1111-first-work-here", title="First")
    playlist = _save(client)

    body = client.get(f"/feed/{playlist['id']}/next", params={"after": "gone-from-the-archive"})

    assert body.status_code == 200
    assert body.json()["index"] == 0


def test_next_hands_back_a_url_the_device_can_fetch(client, archive):
    """The device is told where the image is rather than being sent the image, so it can skip a
    work it already holds."""
    _work(archive, "aaa1111-first-work-here", title="First")
    playlist = _save(client)

    body = client.get(f"/feed/{playlist['id']}/next").json()
    fetched = client.get(body["image_url"].replace("http://testserver", ""))

    assert fetched.status_code == 200
    assert fetched.headers["content-type"].startswith("image/")


def test_next_carries_the_metadata_a_caption_needs(client, archive):
    _work(archive, "aaa1111-first-work-here", title="A Real Title")
    playlist = _save(client)

    body = client.get(f"/feed/{playlist['id']}/next").json()

    assert body["title"] == "A Real Title"
    assert body["artist"] == "A Painter"
    assert body["year"] == 1650


# ---------------------------------------------------------------------------------------------
# Indexed access and unknown playlists.
# ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize("path", ["current", "next", "image/0"])
def test_an_unknown_playlist_is_a_404_on_every_feed_url(client, archive, path):
    response = client.get(f"/feed/no-such-playlist/{path}")

    assert response.status_code == 404
    assert "no playlist" in response.json()["detail"]


@pytest.mark.parametrize("index", [-1, 2, 99])
def test_an_out_of_range_index_names_the_range(client, archive, index):
    """The device computed the index itself, so telling it the valid range is what lets it
    recover without a round trip."""
    _work(archive, "aaa1111-first-work-here", title="First")
    _work(archive, "bbb2222-second-work-ok", title="Second")
    playlist = _save(client)

    response = client.get(f"/feed/{playlist['id']}/image/{index}")

    assert response.status_code == 404
    assert "0..1" in response.json()["detail"]


def test_each_index_serves_its_own_work(client, archive):
    _work(archive, "aaa1111-first-work-here", title="First")
    _work(archive, "bbb2222-second-work-ok", title="Second")
    playlist = _save(client)

    first = client.get(f"/feed/{playlist['id']}/image/0")
    second = client.get(f"/feed/{playlist['id']}/image/1")

    assert first.status_code == second.status_code == 200
    assert first.headers["X-Work-Id"] == "aaa1111-first-work-here"
    assert second.headers["X-Work-Id"] == "bbb2222-second-work-ok"


# ---------------------------------------------------------------------------------------------
# Saving a playlist.
# ---------------------------------------------------------------------------------------------


def test_a_saved_playlist_reports_what_it_resolves_to(client, archive):
    """The count is the only feedback an author gets that their query matched anything."""
    _work(archive, "aaa1111-first-work-here", title="First")

    saved = _save(client)

    assert saved["resolved_count"] == 1
    assert saved["feed_url"].endswith(f"/feed/{saved['id']}/current")


def test_saving_with_an_id_updates_rather_than_duplicating(client, archive):
    """Editing a playlist must not leave the old one behind, or a device still polling the old
    feed keeps showing the query the author just replaced."""
    _work(archive, "aaa1111-first-work-here", title="First")
    saved = _save(client, name="Original")

    updated = _save(client, id=saved["id"], name="Renamed")

    rows = client.get("/eink/playlists").json()["playlists"]
    assert updated["id"] == saved["id"]
    assert [row["name"] for row in rows] == ["Renamed"]


def test_updating_an_unknown_playlist_is_a_404(client, archive):
    response = client.post(
        "/eink/playlists", json={"id": "nope", "name": "X", "spec": {}, "interval": "daily"}
    )

    assert response.status_code == 404


@pytest.mark.parametrize("interval", ["yearly", "", "1h", "DAILY"])
def test_an_unknown_interval_is_refused_at_save_time(client, archive, interval):
    """Stored unchecked, it silently becomes `daily` at render time — so the author sets hourly,
    sees daily, and has nothing to tell them why."""
    response = client.post("/eink/playlists", json={"name": "X", "spec": {}, "interval": interval})

    assert response.status_code == 400
    assert "interval must be one of" in response.json()["detail"]


@pytest.mark.parametrize("dither", ["none", "floyd-steinberg", "atkinson"])
def test_every_supported_dither_is_accepted(client, archive, dither):
    _work(archive, "aaa1111-first-work-here", title="First")

    assert _save(client, dither=dither)["dither"] == dither


@pytest.mark.parametrize("dither", ["ordered", "", "Floyd-Steinberg"])
def test_an_unsupported_dither_is_refused_and_the_options_listed(client, archive, dither):
    """Dither is what makes a four-colour panel legible. A silent fallback would ship a
    posterised image the author never chose."""
    response = client.post(
        "/eink/playlists", json={"name": "X", "spec": {}, "interval": "daily", "dither": dither}
    )

    assert response.status_code == 400
    assert "none|floyd-steinberg|atkinson" in response.json()["detail"]


def test_an_unknown_target_is_refused(client, archive):
    """The target is a physical panel's geometry. An unknown one has no dimensions to render at."""
    response = client.post(
        "/eink/playlists",
        json={"name": "X", "spec": {}, "interval": "daily", "target": "no-such-panel"},
    )

    assert response.status_code == 400


def test_a_malformed_spec_is_refused_before_it_is_stored(client, archive):
    """The comment on that line says "validate before storing", and BEFORE is the whole property.

    A malformed spec is refused either way — resolving it fails too — so a test that only checked
    the status code passes against a version that stores the playlist first and then errors. What
    separates them is what is left behind: a persisted playlist that cannot resolve, sitting in
    the list, with a feed URL a device can already be polling.
    """
    response = client.post(
        "/eink/playlists",
        json={"name": "X", "spec": {"sort": "no-such-sort-order"}, "interval": "daily"},
    )

    assert response.status_code == 400
    assert client.get("/eink/playlists").json()["playlists"] == []


@pytest.mark.parametrize(
    "body",
    [
        {"name": "X", "spec": {}, "interval": "yearly"},
        {"name": "X", "spec": {}, "interval": "daily", "dither": "ordered"},
        {"name": "X", "spec": {}, "interval": "daily", "target": "no-such-panel"},
        {"name": "X", "spec": {}, "interval": "daily", "fit": "squish"},
    ],
)
def test_no_refused_save_leaves_a_playlist_behind(client, archive, body):
    """Every validation on this endpoint runs before the store, not after."""
    assert client.post("/eink/playlists", json=body).status_code == 400
    assert client.get("/eink/playlists").json()["playlists"] == []


def test_an_unknown_fit_is_refused(client, archive):
    response = client.post(
        "/eink/playlists",
        json={"name": "X", "spec": {}, "interval": "daily", "fit": "squish"},
    )

    assert response.status_code == 400


@pytest.fixture
def diverse_archive(archive, tmp_path, monkeypatch):
    ids = ["aaa1111-red-work", "bbb2222-near-red", "ccc3333-blue-work"]
    for wid, colour in zip(ids, [(220, 40, 40), (210, 50, 50), (40, 70, 220)], strict=True):
        _work(archive, wid, title=wid)
        Image.new("RGB", (80, 60), colour).save(archive / wid / "master.jpeg")
    ratings = tmp_path / "ratings.jsonl"
    ratings.write_text(
        "\n".join(
            json.dumps({"work_id": wid, "fit": 9, "quality": quality})
            for wid, quality in zip(ids, [9, 8, 7], strict=True)
        )
    )
    monkeypatch.setattr(api_store, "RATINGS_LOG", ratings)
    monkeypatch.setattr(api_main, "_ratings_cache", None)
    monkeypatch.setattr(api_main, "EINK_EXPORT_ROOTS", [tmp_path])
    return {"sort": "fit", "min_fit": 8, "limit": 2, "selection_mode": "preference-diverse"}


@pytest.mark.parametrize("write", [False, True])
def test_preference_diverse_preview_saved_feed_and_exports_agree(
    client, archive, diverse_archive, tmp_path, write
):
    # This is the companion's payload, with no caller-supplied evidence.
    spec = diverse_archive
    preview = client.post("/eink/playlist/preview", json={"spec": spec})
    assert preview.status_code == 200, preview.text
    selected = preview.json()["work_ids"]
    assert set(selected) == {"aaa1111-red-work", "ccc3333-blue-work"}
    saved = _save(client, spec=spec)
    assert saved["resolved_count"] == 2
    listed = client.get("/eink/playlists")
    assert listed.status_code == 200
    assert listed.json()["playlists"][0]["resolved_count"] == 2
    manifest = client.get(f"/feed/{saved['id']}/manifest.json")
    assert manifest.status_code == 200, manifest.text
    assert [row["work_id"] for row in manifest.json()["items"]] == selected
    after = ""
    for expected in selected:
        nxt = client.get(f"/feed/{saved['id']}/next", params={"after": after})
        assert nxt.status_code == 200, nxt.text
        assert nxt.json()["work_id"] == expected
        image = client.get(nxt.json()["image_url"])
        assert image.status_code == 200, image.text
        assert image.headers["X-Work-Id"] == expected
        after = expected
    for index, request in enumerate([{"spec": spec}, {"playlist_id": saved["id"]}]):
        card = tmp_path / f"card-{index}"
        exported = client.post(
            "/eink/playlist/export", json={**request, "path": str(card), "write": write}
        )
        assert exported.status_code == 200, exported.text
        assert exported.json()["selected"] == 2
        assert [row["work_id"] for row in exported.json()["render_evidence"]] == selected
        assert exported.json()["written"] == 2
        if write:
            manifest = json.loads((card / "playlist.json").read_text())
            assert [row["work_id"] for row in manifest["items"]] == selected
            for row in manifest["items"]:
                with Image.open(card / row["file"]) as image:
                    assert image.format == "PNG"
            assert exported.json()["bytes_written"] > 0
        else:
            assert not card.exists(), "dry-run must not write a card"


def test_year_zero_lower_bound_agrees_across_preview_saved_feed_and_export(
    client, archive, tmp_path, monkeypatch
):
    """An explicit year_from=0 filters on every delivery path, not just the preview (#806)."""
    monkeypatch.setattr(api_main, "EINK_EXPORT_ROOTS", [tmp_path])
    _work(archive, "aaa1111-dated", title="Dated")
    _work(archive, "bbb2222-undated", title="Undated")
    meta_path = archive / "bbb2222-undated" / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["year"] = None
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    api_main._sidecars_cache = None
    spec = {"year_from": 0}

    preview = client.post("/eink/playlist/preview", json={"spec": spec})
    assert preview.status_code == 200, preview.text
    assert preview.json()["work_ids"] == ["aaa1111-dated"]
    assert preview.json()["coverage"]["excluded_for_missing_metadata"]["no year"] == 1

    saved = _save(client, spec=spec)
    assert saved["resolved_count"] == 1
    manifest = client.get(f"/feed/{saved['id']}/manifest.json")
    assert manifest.status_code == 200, manifest.text
    assert [row["work_id"] for row in manifest.json()["items"]] == ["aaa1111-dated"]

    card = tmp_path / "card"
    exported = client.post(
        "/eink/playlist/export", json={"spec": spec, "path": str(card), "write": True}
    )
    assert exported.status_code == 200, exported.text
    assert exported.json()["selected"] == 1
    written = json.loads((card / "playlist.json").read_text())
    assert [row["work_id"] for row in written["items"]] == ["aaa1111-dated"]


def test_preview_rejects_non_integer_year_bound(client):
    response = client.post("/eink/playlist/preview", json={"spec": {"year_from": ""}})
    assert response.status_code == 400
    assert response.json()["detail"] == "year_from must be an integer or null"


@pytest.mark.parametrize("update", [False, True])
@pytest.mark.parametrize("missing", ["quality", "master", "unreadable", "zero-vector"])
def test_preference_diverse_invalid_evidence_never_commits(
    client, archive, diverse_archive, tmp_path, update, missing
):
    existing = _save(client, name="Original") if update else None
    before = api_main._playlists.path.read_bytes() if existing else None
    if missing == "quality":
        api_store.RATINGS_LOG.write_text(
            "\n".join(
                json.dumps({"work_id": wid, "fit": 9})
                for wid in ["aaa1111-red-work", "bbb2222-near-red", "ccc3333-blue-work"]
            )
        )
        api_main._ratings_cache = None
    elif missing == "master":
        (archive / "aaa1111-red-work" / "master.jpeg").unlink()
    elif missing == "unreadable":
        (archive / "aaa1111-red-work" / "master.jpeg").write_text("not an image")
    else:
        Image.new("RGB", (80, 60), (0, 0, 0)).save(archive / "aaa1111-red-work" / "master.jpeg")
    response = client.post(
        "/eink/playlists",
        json={
            "id": existing["id"] if existing else None,
            "name": "Changed",
            "spec": diverse_archive,
        },
    )
    assert response.status_code == 400, response.text
    assert "evidence" in response.json()["detail"] or "embedding" in response.json()["detail"]
    if existing:
        assert api_main._playlists.path.read_bytes() == before
    else:
        assert not api_main._playlists.path.exists()
    listed = client.get("/eink/playlists")
    assert listed.status_code == 200
    assert [row["name"] for row in listed.json()["playlists"]] == (["Original"] if update else [])
    # Both export routes must refuse the same evidence without creating output.
    bad = _eink.SavedPlaylist.new("Old bad entry", diverse_archive)
    api_main._playlists.save(bad)
    for request in [{"spec": diverse_archive}, {"playlist_id": bad.id}]:
        exported = client.post(
            "/eink/playlist/export", json={**request, "path": str(tmp_path / "card")}
        )
        assert exported.status_code == 400, exported.text
    assert not (tmp_path / "card").exists()
    rows = {row["id"]: row for row in client.get("/eink/playlists").json()["playlists"]}
    assert rows[bad.id]["resolved_count"] is None
    assert rows[bad.id]["error"]
    for endpoint in ["manifest.json", "next", "current", "image/0"]:
        assert client.get(f"/feed/{bad.id}/{endpoint}").status_code == 400


def test_preference_diverse_filters_before_deriving_and_resolves_live(
    client, archive, diverse_archive
):
    _work(archive, "ddd4444-filtered-out", title="No master outside filter", master=False)
    saved = _save(client, spec=diverse_archive)
    # A missing master outside min_fit must not invalidate the selection.
    first = client.get(f"/feed/{saved['id']}/manifest.json")
    assert first.status_code == 200, first.text
    assert "ddd4444-filtered-out" not in [r["work_id"] for r in first.json()["items"]]
    with api_store.RATINGS_LOG.open("a") as log:
        log.write("\n" + json.dumps({"work_id": "ddd4444-filtered-out", "fit": 9, "quality": 9}))
    changed = client.get(f"/feed/{saved['id']}/manifest.json")
    assert changed.status_code == 400, "saved specs must re-resolve newly matching evidence"
    assert "ddd4444-filtered-out" in changed.json()["detail"]


def test_preference_diverse_preview_keeps_explicit_evidence(client, archive, diverse_archive):
    ids = ["aaa1111-red-work", "bbb2222-near-red", "ccc3333-blue-work"]
    supplied = {
        "quality_scores": dict(zip(ids, [1, 10, 1], strict=True)),
        "embeddings": dict(zip(ids, [[1, 0], [1, 0], [0, 1]], strict=True)),
    }
    response = client.post("/eink/playlist/preview", json={"spec": diverse_archive, **supplied})
    assert response.status_code == 200, response.text
    assert response.json()["work_ids"][0] == "bbb2222-near-red"
    for field in ["quality_scores", "embeddings"]:
        refused = client.post(
            "/eink/playlist/preview", json={"spec": diverse_archive, **supplied, field: {}}
        )
        assert refused.status_code == 400, "explicit empty evidence must not be re-derived"
        assert "evidence" in refused.json()["detail"]


def test_repeated_manifest_reuses_descriptors_and_keeps_ratings_live(
    client, archive, diverse_archive, monkeypatch
):
    saved = _save(client, spec=diverse_archive)
    url = f"/feed/{saved['id']}/manifest.json"
    # Resolve once with storage disabled to compare membership with no reuse.
    with monkeypatch.context() as uncached:
        uncached.setattr(api_main, "_visual_descriptor_cache", {})
        uncached.setattr(api_main, "_VISUAL_DESCRIPTOR_CACHE_MAX_ENTRIES", 0)
        baseline = client.get(url)
    assert baseline.status_code == 200, baseline.text
    monkeypatch.setattr(api_main, "_visual_descriptor_cache", {})
    reads = []
    original_compute = api_main._compute_visual_descriptor

    def counted_compute(source):
        reads.append(source.name)
        return original_compute(source)

    monkeypatch.setattr(api_main, "_compute_visual_descriptor", counted_compute)
    cold = client.get(url)
    warm = client.get(url)
    assert cold.status_code == warm.status_code == 200
    assert cold.json()["items"] == warm.json()["items"] == baseline.json()["items"]
    assert sorted(reads) == sorted(
        str(archive / wid / "master.jpeg")
        for wid in ["aaa1111-red-work", "bbb2222-near-red", "ccc3333-blue-work"]
    ), "manifest requests must decode each matching descriptor only once"
    rendered = client.get(f"/feed/{saved['id']}/image/0")
    assert rendered.status_code == 200, rendered.text
    assert len(reads) == 3, "response image rendering must not derive descriptors again"
    old_ids = [row["work_id"] for row in warm.json()["items"]]
    api_store.RATINGS_LOG.write_text(
        "\n".join(
            json.dumps({"work_id": wid, "fit": 9, "quality": quality})
            for wid, quality in zip(
                ["aaa1111-red-work", "bbb2222-near-red", "ccc3333-blue-work"],
                [1, 10, 1],
                strict=True,
            )
        )
    )
    changed = client.get(url)
    assert changed.status_code == 200
    assert [row["work_id"] for row in changed.json()["items"]] != old_ids
    assert len(reads) == 3, "ratings must stay live without decoding unchanged descriptors"

    # A new matching work must enter selection while the first three still hit.
    new_id = "ddd4444-new-work"
    _work(archive, new_id, title="New matching work")
    with api_store.RATINGS_LOG.open("a") as log:
        log.write("\n" + json.dumps({"work_id": new_id, "fit": 10, "quality": 10}))
    added = client.get(url)
    assert added.status_code == 200, added.text
    assert new_id in [row["work_id"] for row in added.json()["items"]]
    assert len(reads) == 4
    assert reads[-1] == str(archive / new_id / "master.jpeg")


@pytest.mark.parametrize("failure", ["missing", "unreadable", "access"])
def test_warm_descriptor_cache_preserves_http_evidence_failure(
    client, archive, diverse_archive, monkeypatch, failure
):
    saved = _save(client, spec=diverse_archive)
    url = f"/feed/{saved['id']}/manifest.json"
    assert client.get(url).status_code == 200
    master = archive / "aaa1111-red-work" / "master.jpeg"
    if failure == "missing":
        master.unlink()
    elif failure == "unreadable":
        master.write_text("not an image")
    else:
        original_open = Path.open

        def deny_master(path, *args, **kwargs):
            if path == master:
                raise PermissionError("test master access revoked")
            return original_open(path, *args, **kwargs)

        monkeypatch.setattr(Path, "open", deny_master)
    for endpoint in ["manifest.json", "next", "current", "image/0"]:
        failed = client.get(f"/feed/{saved['id']}/{endpoint}")
        assert failed.status_code == 400, failed.text
        assert "evidence" in failed.json()["detail"]


@pytest.mark.parametrize("missing", ["quality_scores", "embeddings"])
def test_preference_diverse_builder_names_missing_evidence(missing):
    supplied = {"quality_scores": {}, "embeddings": {}}
    supplied.pop(missing)
    with pytest.raises(ValueError, match="requires quality and embedding evidence"):
        _eink.build(
            [], _eink.PlaylistSpec(selection_mode="preference-diverse", limit=1), **supplied
        )
