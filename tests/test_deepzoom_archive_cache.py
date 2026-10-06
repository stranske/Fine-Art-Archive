"""DeepZoom archive lifecycle and HTTP rejection before tile I/O."""

from __future__ import annotations

import json
import os
import zipfile
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from fine_art_archive.api import main as api_main
from fine_art_archive.api import store


@pytest.fixture
def archive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Keep all sidecars, containers, proxy cache, and open handles local."""
    works = tmp_path / "works"
    works.mkdir()
    monkeypatch.setattr(store, "WORKS", works)
    monkeypatch.setattr(api_main, "ART_WORKS_ROOT", works)
    monkeypatch.setattr(api_main, "TILES_CACHE_DIR", tmp_path / "proxy")
    monkeypatch.setattr(api_main, "_dz_zip_cache", {})
    handles = []

    def open_container(wid: str = "work", layer: str = "VIS"):
        handle = api_main._dz_container(wid, layer)
        if handle is not None:
            handles.append(handle)
        return handle

    try:
        yield works, open_container
    finally:
        # Evicted/replaced handles are no longer in the cache; retain every
        # returned handle so fixture cleanup also closes those resources.
        for handle in handles:
            handle.close()


def write_container(works: Path, wid: str = "work", payload: bytes = b"first tile") -> Path:
    """Write a real ZIP, avoiding a mocked archive implementation."""
    path = works / wid / "deepzoom-vis.zip"
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as handle:
        handle.writestr("12/3_4.jpg", payload)
    return path


def test_unchanged_container_reuses_handle_across_layer_case(archive) -> None:
    """Repeated reads reuse the parsed directory and normalize the layer name."""
    works, open_container = archive
    write_container(works)

    first = open_container(layer="VIS")
    second = open_container(layer="vis")

    assert first is not None
    assert second is first
    assert second.read("12/3_4.jpg") == b"first tile"
    assert len(api_main._dz_zip_cache) == 1


def test_replaced_container_reopens_and_serves_new_bytes(archive) -> None:
    """A changed nanosecond signature must not serve an obsolete container."""
    works, open_container = archive
    path = write_container(works)
    first = open_container()
    previous_mtime = path.stat().st_mtime_ns
    replacement = path.with_suffix(".new")
    with zipfile.ZipFile(replacement, "w") as handle:
        handle.writestr("12/3_4.jpg", b"replacement tile")
    os.utime(replacement, ns=(previous_mtime + 1, previous_mtime + 1))
    replacement.replace(path)

    second = open_container()

    assert first is not None
    assert second is not None and second is not first
    assert second.read("12/3_4.jpg") == b"replacement tile"
    assert api_main._dz_zip_cache[str(path)][0] == previous_mtime + 1


def test_missing_container_clears_stale_cache_and_can_reappear(archive) -> None:
    """An absent file clears its positive cache without caching absence."""
    works, open_container = archive
    path = write_container(works)
    assert open_container() is not None
    path.unlink()

    assert open_container() is None
    assert str(path) not in api_main._dz_zip_cache
    write_container(works, payload=b"returned tile")
    returned = open_container()
    assert returned is not None
    assert returned.read("12/3_4.jpg") == b"returned tile"


def test_corrupt_container_allows_fallback_and_later_repair(archive) -> None:
    """Bad ZIP bytes permit fallback, then a repaired file becomes readable."""
    works, open_container = archive
    path = works / "work" / "deepzoom-vis.zip"
    path.parent.mkdir()
    path.write_bytes(b"not a zip")

    assert open_container() is None
    assert str(path) not in api_main._dz_zip_cache
    write_container(works, payload=b"repaired tile")
    repaired = open_container()
    assert repaired is not None
    assert repaired.read("12/3_4.jpg") == b"repaired tile"


def test_unreadable_container_allows_fallback_without_cache_entry(
    archive, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An archive-open OS error stays a cache miss, rather than escaping."""
    works, open_container = archive
    path = write_container(works)

    def deny_open(filename):
        assert filename == path
        raise PermissionError("fixture archive is unreadable")

    monkeypatch.setattr(api_main.zipfile, "ZipFile", deny_open)
    assert open_container() is None
    assert str(path) not in api_main._dz_zip_cache


@pytest.mark.parametrize("status", [400, 404], ids=["invalid-work", "absent-work"])
def test_unavailable_work_directory_allows_container_fallback(
    archive, monkeypatch: pytest.MonkeyPatch, status: int
) -> None:
    """Work-directory lookup failures must not escape the optional ZIP lookup."""
    _, open_container = archive

    def reject_work(wid):
        assert wid == "work"
        raise HTTPException(status, "fixture work unavailable")

    monkeypatch.setattr(api_main, "_archive_work_dir_checked", reject_work)
    assert open_container() is None
    assert not api_main._dz_zip_cache


def test_container_cache_evicts_old_entries_and_keeps_new_handle(archive) -> None:
    """Opening the 26th distinct layer evicts the prior 25 cache entries."""
    works, open_container = archive
    for index in range(26):
        wid = f"work-{index}"
        path = write_container(works, wid, payload=wid.encode())
        handle = open_container(wid)
        assert handle is not None
        assert handle.read("12/3_4.jpg") == wid.encode()
        if index == 24:
            assert len(api_main._dz_zip_cache) == 25

    assert list(api_main._dz_zip_cache) == [str(path)]
    assert api_main._dz_zip_cache[str(path)][1] is handle


@pytest.mark.parametrize("endpoint", ["deepzoom", "dz/VIS/12/3_4.jpg"])
def test_missing_sidecar_returns_not_found(archive, endpoint: str) -> None:
    """Both descriptor and tile routes preserve the missing-sidecar response."""
    with TestClient(api_main.app) as client:
        response = client.get(f"/works/missing/{endpoint}")
    assert response.status_code == 404
    assert response.json() == {"detail": "no sidecar for missing"}


@pytest.mark.parametrize(
    "layers",
    [[], [{"layer": "IRR", "fid": "other"}], [{"layer": "VIS"}]],
    ids=["no-layers", "other-layer", "missing-fid"],
)
def test_absent_layer_returns_not_found(archive, layers: list[dict]) -> None:
    """A nonexistent or incomplete layer cannot launch a tile fetch."""
    works, _ = archive
    directory = works / "work"
    directory.mkdir()
    (directory / "meta.json").write_text(json.dumps({"deepzoom": {"layers": layers}}))
    with TestClient(api_main.app) as client:
        response = client.get("/works/work/dz/VIS/12/3_4.jpg")
    assert response.status_code == 404
    assert response.json() == {"detail": "no VIS deepzoom layer for work"}


@pytest.mark.parametrize(
    ("fid", "level", "tile"),
    [
        ("safe_fid", -1, "3_4.jpg"),
        ("safe_fid", 25, "3_4.jpg"),
        ("unsafe-fid", 12, "3_4.jpg"),
        ("safe_fid", 12, "10000_4.jpg"),
        ("safe_fid", 12, "3_10000.jpg"),
        ("safe_fid", 12, "3_4.png"),
    ],
    ids=["negative-level", "large-level", "unsafe-fid", "large-column", "large-row", "not-jpeg"],
)
def test_invalid_tile_request_is_rejected_before_archive_or_network(
    archive, monkeypatch: pytest.MonkeyPatch, fid: str, level: int, tile: str
) -> None:
    """Invalid coordinates and IDs never reach archive lookup or network I/O."""
    works, _ = archive
    directory = works / "work"
    directory.mkdir()
    (directory / "meta.json").write_text(
        json.dumps({"deepzoom": {"layers": [{"layer": "VIS", "fid": fid}]}})
    )

    def forbidden_io(*args, **kwargs):
        pytest.fail("invalid tile request reached archive or network I/O")

    monkeypatch.setattr(api_main, "_dz_container", forbidden_io)
    monkeypatch.setattr(api_main.urllib.request, "urlopen", forbidden_io)
    with TestClient(api_main.app) as client:
        response = client.get(f"/works/work/dz/VIS/{level}/{tile}")
    assert response.status_code == 404
    assert response.json() == {"detail": "bad tile request"}
