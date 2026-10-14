"""Real companion/SD pixels must implement the reported A11 strategy."""

from __future__ import annotations

import io
import json
import os

import numpy as np
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from fine_art_archive import eink
from fine_art_archive.api import main as api
from fine_art_archive.api import store
from fine_art_archive.display.render import gamut_render_evidence
from fine_art_archive.eink import sdcard


def _master(strategy):
    image = Image.new("RGB", (40, 20), eink.SPECTRA6.colours[2])
    if strategy == "grayscale":
        image.paste((255, 0, 255), (0, 0, 40, 20))
    elif strategy == "duotone":
        # 10% genuinely out-of-gamut pixels, 90% panel red: no classifier stub.
        image.paste((255, 0, 255), (0, 0, 4, 20))
    assert gamut_render_evidence(image).strategy == strategy
    return image


def _pixels(image):
    return set(image.convert("RGB").getdata())


def _assert_pixels(image, target, strategy):
    assert image.size == target.size
    present = _pixels(image)
    assert present <= set(target.palette.colours)
    if strategy in {"grayscale", "duotone"}:
        assert present <= {target.palette.black, target.palette.white}
    else:
        assert present - {target.palette.black, target.palette.white}


@pytest.fixture
def delivery(tmp_path, monkeypatch):
    works = tmp_path / "works"
    works.mkdir()
    monkeypatch.setattr(store, "WORKS", works)
    monkeypatch.setattr(store, "RATINGS_LOG", tmp_path / "ratings.jsonl")
    monkeypatch.setattr(api, "ART_WORKS_ROOT", works)
    monkeypatch.setattr(api, "IMAGE_CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(api, "EINK_EXPORT_ROOTS", [tmp_path])
    monkeypatch.setattr(api, "_playlists", eink.PlaylistStore(tmp_path / "playlists.json"))
    monkeypatch.setattr(api, "_sidecars_cache", None)
    monkeypatch.setattr(api, "_ratings_cache", None)
    target = eink.RenderTarget("test-strategy", "Test", 40, 20, "spectra6")
    monkeypatch.setitem(eink.TARGETS, target.key, target)
    return TestClient(api.app), works, target


def _work(works, strategy):
    directory = works / strategy
    directory.mkdir()
    (directory / "meta.json").write_text(json.dumps({"work_id": strategy, "title": strategy}))
    # Lossless content avoids JPEG changing the known gamut distribution.
    path = directory / "master.jpeg"
    _master(strategy).save(path, format="PNG")
    return path


@pytest.mark.parametrize("strategy", ["color", "grayscale", "duotone"])
@pytest.mark.parametrize("method", ["none", "floyd-steinberg", "atkinson"])
def test_companion_feed_and_sd_apply_reported_strategy(delivery, tmp_path, strategy, method):
    client, works, target = delivery
    _work(works, strategy)
    preview = client.post("/eink/playlist/preview", json={"target": target.key})
    assert preview.status_code == 200, preview.text
    evidence = preview.json()["items"][0]
    assert evidence["render_strategy"] == strategy
    saved = client.post(
        "/eink/playlists", json={"name": "Test", "target": target.key, "dither": method}
    )
    assert saved.status_code == 200, saved.text
    playlist_id = saved.json()["id"]
    routes = [
        f"/works/{strategy}/eink_preview?target={target.key}&dither={method}",
        f"/feed/{playlist_id}/image/0",
        f"/feed/{playlist_id}/current",
    ]
    images = []
    for route in routes:
        response = client.get(route)
        assert response.status_code == 200, response.text
        image = Image.open(io.BytesIO(response.content))
        _assert_pixels(image, target, strategy)
        assert response.headers["X-Render-Strategy"] == strategy
        images.append(image.tobytes())
    card = tmp_path / "card"
    exported = client.post(
        "/eink/playlist/export",
        json={"playlist_id": playlist_id, "path": str(card), "write": True},
    )
    assert exported.status_code == 200, exported.text
    assert exported.json()["written"] == 1
    assert exported.json()["render_evidence"][0]["render_strategy"] == strategy
    manifest = json.loads((card / "playlist.json").read_text())
    item = manifest["items"][0]
    assert item["render_strategy"] == strategy
    with Image.open(card / item["file"]) as rendered:
        _assert_pixels(rendered, target, strategy)
        assert rendered.tobytes() == images[0] == images[1] == images[2]


@pytest.mark.parametrize("route", ["image/0", "current"])
def test_strategy_change_invalidates_feed_even_with_same_master_mtime(delivery, route):
    client, works, target = delivery
    master = _work(works, "color")
    saved = client.post(
        "/eink/playlists", json={"name": "Test", "target": target.key, "dither": "none"}
    )
    url = f"/feed/{saved.json()['id']}/{route}"
    first = client.get(url)
    assert first.status_code == 200
    stat = master.stat()
    _master("grayscale").save(master, format="PNG")
    os.utime(master, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    response = client.get(url, headers={"If-None-Match": first.headers["ETag"]})
    assert response.status_code == 200
    assert response.headers["ETag"] != first.headers["ETag"]
    assert response.content != first.content
    _assert_pixels(Image.open(io.BytesIO(response.content)), target, "grayscale")
    assert client.get(url, headers={"If-None-Match": response.headers["ETag"]}).status_code == 304


@pytest.mark.parametrize("strategy", ["color", "grayscale", "duotone"])
@pytest.mark.parametrize("fmt", ["png", "bmp"])
def test_card_formats_preserve_strategy_pixels_and_manifest(tmp_path, strategy, fmt):
    master = tmp_path / "master.png"
    _master(strategy).save(master)
    target = eink.RenderTarget("test", "Test", 40, 20, "spectra6")
    card = tmp_path / "card"
    report = sdcard.export(
        [sdcard.ExportItem("work")],
        card,
        target,
        master_for=lambda _: master,
        fmt=fmt,
        method="none",
        dry_run=False,
    )
    assert len(report.written) == 1, report.skipped
    manifest = json.loads((card / "playlist.json").read_text())
    assert manifest["items"][0]["render_strategy"] == strategy
    with Image.open(card / report.written[0]) as rendered:
        _assert_pixels(rendered, target, strategy)


def test_grayscale_preserves_native_gray_levels_and_duotone_uses_endpoints():
    from fine_art_archive.eink.targets import render_for_target

    target = eink.RenderTarget("gray", "Gray", 40, 20, "gray16")
    levels = np.linspace(20, 228, 40, dtype=np.uint8)
    image = Image.fromarray(np.tile(levels[None, :, None], (20, 1, 3)))
    gray = render_for_target(image, target, strategy="grayscale", method="none")
    duo = render_for_target(image, target, strategy="duotone", method="none")
    assert len(_pixels(gray)) > 2
    assert _pixels(gray) <= set(target.palette.colours)
    assert _pixels(duo) == {target.palette.black, target.palette.white}


def test_duotone_uniform_luminance_uses_midpoint_threshold():
    from fine_art_archive.eink.targets import render_for_target

    target = eink.RenderTarget("test", "Test", 8, 8, "spectra6")
    for level, expected in ((20, target.palette.black), (200, target.palette.white)):
        uniform = Image.new("RGB", (8, 8), (level, level, level))
        rendered = render_for_target(uniform, target, strategy="duotone", method="none")
        assert _pixels(rendered) == {expected}


@pytest.mark.parametrize("route", ["image/0", "current"])
def test_changed_policy_invalidates_cached_strategy(delivery, monkeypatch, route):
    from fine_art_archive.eink import render_strategy

    client, works, target = delivery
    _work(works, "grayscale")
    saved = client.post(
        "/eink/playlists", json={"name": "Test", "target": target.key, "dither": "none"}
    )
    url = f"/feed/{saved.json()['id']}/{route}"
    first = client.get(url)
    assert first.status_code == 200
    _assert_pixels(Image.open(io.BytesIO(first.content)), target, "grayscale")
    # Change the existing policy input, without replacing classifier/renderer.
    monkeypatch.setitem(render_strategy._DEFAULT_POLICY, "poorly-served", "color")
    changed = client.get(url, headers={"If-None-Match": first.headers["ETag"]})
    assert changed.status_code == 200
    assert changed.headers["X-Render-Strategy"] == "color"
    assert changed.headers["ETag"] != first.headers["ETag"]
    _assert_pixels(Image.open(io.BytesIO(changed.content)), target, "color")
    preview = client.post("/eink/playlist/preview", json={"target": target.key})
    assert preview.json()["items"][0]["render_strategy"] == "color"


@pytest.mark.parametrize("fit", ["contain", "cover", "stretch"])
@pytest.mark.parametrize("palette_name", ["spectra6", "kaleido3", "gray16", "mono1bit"])
def test_strategy_preserves_target_size_and_native_inks(fit, palette_name):
    from fine_art_archive.eink.targets import render_for_target

    target = eink.RenderTarget("test", "Test", 23, 31, palette_name, rotate=90)
    for strategy in ["color", "grayscale", "duotone"]:
        rendered = render_for_target(_master("grayscale"), target, fit=fit, strategy=strategy)
        assert rendered.size == target.size
        assert _pixels(rendered) <= set(target.palette.colours)
        if strategy == "duotone" or (strategy == "grayscale" and palette_name != "gray16"):
            assert _pixels(rendered) <= {target.palette.black, target.palette.white}


def test_failed_card_item_has_no_applied_strategy_evidence(tmp_path):
    master = tmp_path / "master.png"
    _master("grayscale").save(master)
    broken = tmp_path / "broken.png"
    broken.write_bytes(b"not an image")
    paths = {"ok": master, "broken": broken}
    target = eink.RenderTarget("test", "Test", 40, 20, "spectra6")
    card = tmp_path / "card"
    report = sdcard.export(
        [sdcard.ExportItem("ok"), sdcard.ExportItem("broken")],
        card,
        target,
        master_for=paths.get,
        method="none",
        dry_run=False,
    )
    assert len(report.written) == 1
    assert report.skipped[0][0] == "broken"
    assert [item["work_id"] for item in report.render_evidence] == ["ok"]
    manifest = json.loads((card / "playlist.json").read_text())
    assert manifest["count"] == 1
    assert manifest["items"][0]["render_strategy"] == "grayscale"


@pytest.mark.parametrize("value", ["", "rgb", "monochrome"])
def test_unknown_strategy_is_rejected(value):
    from fine_art_archive.eink.targets import render_for_target

    target = eink.RenderTarget("test", "Test", 40, 20, "spectra6")
    with pytest.raises(ValueError, match="invalid render strategy"):
        render_for_target(_master("grayscale"), target, strategy=value)
