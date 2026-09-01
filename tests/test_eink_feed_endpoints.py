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
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from fine_art_archive import eink as _eink
from fine_art_archive.api import main as api_main
from fine_art_archive.api import store as api_store
from fine_art_archive.api.main import app
from fine_art_archive.eink.feed import rotation_index


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
    assert first.headers["X-Work-Id"] != second.headers["X-Work-Id"]


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
