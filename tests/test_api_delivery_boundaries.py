"""Failure and selection contracts at the Companion API boundary."""

from __future__ import annotations

import io
import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from PIL import Image
from starlette.requests import Request

from fine_art_archive.api import main as api
from fine_art_archive.api import store


def test_impossible_quarantine_date_is_reported_without_a_ttl(tmp_path):
    name = "2026-01-01__reason__purge-after-2026-02-30"
    (tmp_path / name).mkdir()
    assert api._quarantine_report(tmp_path) == {"overdue": [], "no_ttl": [name], "total": 1}


def test_work_response_attaches_latest_rating_without_mutating_sidecar(monkeypatch):
    work = {"title": "A work"}
    rating = {"quality": 8, "ts": "2026-10-01"}
    monkeypatch.setattr(api, "_get_work_checked", lambda _wid: work)
    monkeypatch.setattr(store, "latest_rating", lambda _wid: rating)
    monkeypatch.setattr(store, "master_health", lambda _wid: "truncated")
    assert api.get_work("held") == {
        "title": "A work",
        "_latest_rating": rating,
        "_file_health": "truncated",
    }
    assert work == {"title": "A work"}


def test_blank_export_path_is_a_client_error():
    with pytest.raises(HTTPException) as caught:
        api._checked_export_dir(" \t ")
    assert (caught.value.status_code, caught.value.detail) == (400, "export path required")


def test_invalid_work_id_has_no_eink_master():
    assert api._eink_master("../outside") is None


def test_facets_include_live_mood_counts(monkeypatch):
    rows = [
        (
            "held",
            {
                "artist": {"name": "Painter"},
                "title": "Landscape",
                "year": 1650,
                "subject": {"content_tags": [{"id": "setting:winter"}]},
            },
        )
    ]
    monkeypatch.setattr(api, "_all_sidecars", lambda: rows)
    facets = api.eink_facets()
    assert facets["artists"] == [{"value": "Painter", "count": 1}]
    assert facets["total_works"] == 1
    assert facets["year_range"] == [1650, 1650]
    assert facets["mood_counts"] == {"winter-light": 1}


@pytest.mark.parametrize(
    "operation", ["preview-spec", "export-spec", "export-target", "export-dither"]
)
def test_invalid_delivery_configuration_is_a_client_error(tmp_path, monkeypatch, operation):
    monkeypatch.setattr(api, "EINK_EXPORT_ROOTS", (tmp_path,))
    monkeypatch.setattr(api, "_all_sidecars", list)
    monkeypatch.setattr(api, "_cached_ratings", dict)
    if operation == "preview-spec":

        def call():
            return api.eink_playlist_preview(api.PlaylistIn(spec={"unknown": True}))

    else:
        kwargs = {
            "export-spec": {"spec": {"unknown": True}},
            "export-target": {"target": "no-such-target"},
            "export-dither": {"dither": "no-such-dither"},
        }[operation]

        def call():
            return api.eink_playlist_export(api.ExportIn(path=str(tmp_path / "card"), **kwargs))

    with pytest.raises(HTTPException) as caught:
        call()
    assert caught.value.status_code == 400
    assert not (tmp_path / "card").exists()


def test_export_plan_omits_render_evidence_for_missing_master(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "EINK_EXPORT_ROOTS", (tmp_path,))
    monkeypatch.setattr(api, "_all_sidecars", lambda: [("missing", {"title": "Lost"})])
    monkeypatch.setattr(api, "_cached_ratings", dict)
    monkeypatch.setattr(api, "_eink_master", lambda _wid: None)
    result = api.eink_playlist_export(api.ExportIn(path=str(tmp_path / "card")))
    assert result["selected"] == 1
    assert result["render_evidence"] == []
    assert not (tmp_path / "card").exists()


@pytest.mark.parametrize("operation", ["acquisitions", "works", "artists", "gate"])
def test_review_lists_reject_nonpositive_limits(operation):
    calls = {
        "acquisitions": api.list_acquisitions,
        "works": api.review_works,
        "artists": api.review_artists,
        "gate": lambda **kw: api.review_gate("unknown", **kw),
    }
    with pytest.raises(HTTPException) as caught:
        calls[operation](limit=0)
    assert (caught.value.status_code, caught.value.detail) == (400, "limit must be >= 1")


def test_work_decision_rejects_invalid_qid_before_writing(monkeypatch):
    def unexpected_write(*args, **kwargs):
        pytest.fail("invalid work identity reached the decision log")

    monkeypatch.setattr(api.gates, "append_work_decision", unexpected_write)
    with pytest.raises(HTTPException) as caught:
        api.work_decision("Q0", api.WorkDecisionIn(decision="keep"))
    assert (caught.value.status_code, caught.value.detail) == (
        400,
        "work_qid must look like Q12345",
    )


def test_acquisition_review_refuses_invalid_sidecar_without_writing(tmp_path, monkeypatch):
    work = tmp_path / "held"
    work.mkdir()
    path = work / "meta.json"
    original = '{"history": [{"op": "acquired"}]}'
    path.write_text(original)
    monkeypatch.setattr(store, "WORKS", tmp_path)
    log = tmp_path / "events.jsonl"
    monkeypatch.setattr(api, "ACQUISITION_REVIEW_EVENTS", log)
    with pytest.raises(HTTPException) as caught:
        api.acquisition_review("held", api.AcquisitionReviewIn())
    assert caught.value.status_code == 500
    assert path.read_text() == original
    assert not log.exists()


def test_review_artists_skips_unattributed_work_and_recovers_later_label(monkeypatch):
    gate = api.gates.Gate(
        "new_artist",
        "Artists",
        3,
        3,
        "approve",
        items=[
            {"id": "unattributed"},
            {"id": "first", "artist_qid": "Q123"},
            {"id": "second", "artist_qid": "Q123", "artist_label": "Painter", "sitelinks": 5},
        ],
    )
    monkeypatch.setattr(api, "_all_gates", lambda: [gate])
    monkeypatch.setattr(api.gates, "load_allowlisted_artists", dict)
    result = api.review_artists()
    assert result["total_artists"] == 1
    assert result["total_works"] == 2
    artist = result["artists"][0]
    assert artist["artist_label"] == "Painter"
    assert artist["n_released"] == 2
    assert [w["id"] for w in artist["works"]] == ["second", "first"]


@pytest.mark.parametrize("name", ["held", "absent"])
def test_gate_lookup_returns_limited_items_or_404(monkeypatch, name):
    first = api.gates.Gate("other", "Other", 0, 0, "clear")
    held = api.gates.Gate("held", "Held", 2, 1, "review", items=[{"id": "one"}, {"id": "two"}])
    monkeypatch.setattr(api, "_all_gates", lambda: [first, held])
    if name == "absent":
        with pytest.raises(HTTPException) as caught:
            api.review_gate(name, limit=1)
        assert (caught.value.status_code, caught.value.detail) == (404, "no gate named 'absent'")
    else:
        result = api.review_gate(name, limit=1)
        assert result["blocking"] == 2
        assert result["drainable"] == 1
        assert result["returned"] == 1
        assert result["items"] == [{"id": "one"}]


@pytest.mark.parametrize(
    "failure,status", [("missing", 404), ("target", 404), ("fit", 400), ("pixels", 500)]
)
def test_saved_feed_reports_render_failures_with_playlist_context(
    tmp_path, monkeypatch, failure, status
):
    master = tmp_path / "master.png"
    Image.new("RGB", (8, 8), "red").save(master)
    monkeypatch.setattr(api, "_eink_master", lambda _wid: None if failure == "missing" else master)
    playlist = SimpleNamespace(
        id="wall",
        target="invalid" if failure == "target" else "generic-mono-1bit",
        fit="invalid" if failure == "fit" else None,
        dither="none",
    )
    if failure == "pixels":
        master.write_bytes(b"not an image")
    with pytest.raises(HTTPException) as caught:
        api._render_feed_image(playlist, "held", Request({"type": "http", "headers": []}))
    assert caught.value.status_code == status
    assert (
        "wall"
        if failure in {"target", "fit"}
        else "render failed" if failure == "pixels" else "no local master"
    ) in caught.value.detail


@pytest.mark.parametrize("exists", [True, False])
def test_delete_playlist_changes_store_and_reports_missing(tmp_path, monkeypatch, exists):
    playlists = api._eink.PlaylistStore(tmp_path / "playlists.json")
    monkeypatch.setattr(api, "_playlists", playlists)
    if exists:
        saved = playlists.save(api._eink.SavedPlaylist(id="wall", name="Wall", spec={}))
        assert api.eink_delete_playlist(saved.id) == {"deleted": saved.id}
        assert playlists.get(saved.id) is None
    else:
        with pytest.raises(HTTPException) as caught:
            api.eink_delete_playlist("absent")
        assert (caught.value.status_code, caught.value.detail) == (404, "no playlist 'absent'")


@pytest.mark.parametrize("raw", [b"not json", b"[]", b'{"event": 1}'])
def test_debug_log_invalid_body_is_422(raw):
    with pytest.raises(HTTPException) as caught:
        api._parse_debug_log_body(raw)
    assert (caught.value.status_code, caught.value.detail) == (422, "invalid debug log payload")


def test_recent_ratings_are_newest_first_and_limited(tmp_path, monkeypatch):
    log = tmp_path / "ratings.jsonl"
    rows = [
        {"work_id": "old", "ts": "2026-01-01"},
        {"work_id": "new", "ts": "2026-10-01"},
        {"work_id": "middle", "ts": "2026-05-01"},
    ]
    log.write_text("\n" + "\n\n".join(json.dumps(row) for row in rows) + "\n")
    monkeypatch.setattr(store, "RATINGS_LOG", log)
    monkeypatch.setattr(store, "_RATINGS_CACHE", None)
    monkeypatch.setattr(store, "_RATINGS_BY_WORK", None)
    monkeypatch.setattr(store, "_RATINGS_SIGNATURE", None)
    monkeypatch.setattr(store, "_RATINGS_CORRUPT_LINES", 0)
    with TestClient(api.app) as client:
        response = client.get("/ratings/recent?limit=2")
    assert response.status_code == 200
    assert response.json() == {"ratings": [rows[1], rows[2]]}


def test_candidate_proxy_converts_rgba_to_resized_jpeg(tmp_path, monkeypatch):
    image = io.BytesIO()
    Image.new("RGBA", (300, 150), (255, 0, 0, 128)).save(image, "PNG")
    monkeypatch.setattr(api, "IMAGE_CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(
        api.gates, "candidate_image_url", lambda _qid: "https://museum.example/image.png"
    )
    monkeypatch.setattr(api, "_fetch_candidate_bytes", lambda *_args, **_kwargs: image.getvalue())
    response = api.review_candidate_image("Q123", width=120)
    with Image.open(response.path) as rendered:
        assert rendered.mode == "RGB"
        assert rendered.format == "JPEG"
        assert rendered.size == (120, 60)


def test_targets_publish_supported_device_and_export_roots(tmp_path, monkeypatch):
    monkeypatch.setattr(api, "EINK_EXPORT_ROOTS", (tmp_path,))
    result = api.eink_targets()
    assert result["export_roots"] == [str(tmp_path)]
    assert "daily" in result["intervals"]
    assert "generic-mono-1bit" in {target["key"] for target in result["targets"]}
    assert "ESTIMATES" in result["palette_warning"]


def test_acquisition_review_rejects_invalid_id():
    with pytest.raises(HTTPException) as caught:
        api.acquisition_review("../outside", api.AcquisitionReviewIn())
    assert caught.value.status_code == 400
    assert "work_id" in caught.value.detail


def test_rating_rejects_unknown_legacy_reason_before_append(monkeypatch):
    def unexpected_append(_event):
        pytest.fail("invalid reason reached the ratings log")

    monkeypatch.setattr(store, "append_rating", unexpected_append)
    with pytest.raises(HTTPException) as caught:
        api.rate_work("held", api.RatingIn(quality=8, reason_code="no-such-reason"))
    assert caught.value.status_code == 400
    assert "reason_code must be in" in caught.value.detail


def test_queue_signature_records_disappearing_file(tmp_path, monkeypatch):
    path = tmp_path / "queue.json"
    path.write_text("{}")
    monkeypatch.setattr(api, "QUEUES_DIR", tmp_path)
    original_stat = type(path).stat

    def disappearing(self, *args, **kwargs):
        if self == path:
            raise FileNotFoundError("removed during scan")
        return original_stat(self, *args, **kwargs)

    monkeypatch.setattr(type(path), "stat", disappearing)
    assert api._queue_files_with_signature() == ([path], ((str(path), -1, -1),))


@pytest.mark.parametrize(
    "error,message",
    [
        (PermissionError(13, "permission denied", "/private/queue.json"), "permission denied"),
        (OSError(), "OSError"),
    ],
)
def test_queue_file_error_message_omits_host_paths(error, message):
    assert api._safe_queue_file_message(error) == message


def test_debug_rotation_replaces_previous_backup(tmp_path, monkeypatch):
    log = tmp_path / "debug.log"
    backup = log.with_suffix(".log.1")
    log.write_text("current generation\n")
    backup.write_text("obsolete generation\n")
    monkeypatch.setattr(api, "DEBUG_LOG", log)
    monkeypatch.setattr(api, "DEBUG_LOG_MAX_BYTES", 1)
    with TestClient(api.app) as client:
        response = client.post("/debug/log", json={"where": "rotation"})
    assert response.status_code == 200
    assert backup.read_text() == "current generation\n"
    assert json.loads(log.read_text())["where"] == "rotation"


def test_variant_candidate_without_matching_row_has_no_local_path(tmp_path, monkeypatch):
    path = tmp_path / "candidates.csv"
    path.write_text("existing_wid,candidate_path\nother,/unused.jpg\n")
    monkeypatch.setattr(api, "VARIANT_UPGRADE_CSV", path)
    assert api._variant_candidate_path("held") is None


def test_variant_decision_with_nonstring_identity_does_not_mask_valid_decision(
    tmp_path, monkeypatch
):
    candidates = tmp_path / "candidates.csv"
    candidates.write_text("existing_wid,candidate_path\nheld,\n")
    decisions = tmp_path / "decisions.jsonl"
    decisions.write_text(
        '{"existing_wid": "held", "decision": "reject"}\n{"existing_wid": 123, "decision": "accept"}\n'
    )
    monkeypatch.setattr(api, "VARIANT_UPGRADE_CSV", candidates)
    monkeypatch.setattr(api, "VARIANT_UPGRADE_DECISIONS", decisions)
    monkeypatch.setattr(api, "_master_path", lambda _wid: None)
    monkeypatch.setattr(api, "_variant_upgrade_fallback_work", lambda _wid: None)
    result = api.variant_upgrades()
    assert len(result["candidates"]) == 1
    assert result["candidates"][0]["decision"] == "reject"
