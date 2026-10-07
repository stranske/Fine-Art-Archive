"""Master-image HTTP responses must preserve rendering, cache and failure semantics."""

from __future__ import annotations

import builtins
import io
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from fine_art_archive.api import main as api_main
from fine_art_archive.api import store


@pytest.fixture
def image_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    works = tmp_path / "works"
    work = works / "sample-work"
    work.mkdir(parents=True)
    cache = tmp_path / "cache"
    monkeypatch.setattr(api_main, "ART_WORKS_ROOT", works)
    monkeypatch.setattr(api_main, "IMAGE_CACHE_DIR", cache)
    monkeypatch.setattr(store, "WORKS", works)
    return {"works": works, "work": work, "cache": cache}


def test_transparent_master_is_a_bounded_jpeg(image_files: dict[str, Path]) -> None:
    master = image_files["work"] / "master.png"
    Image.new("RGBA", (128, 64), (220, 40, 20, 128)).save(master)
    original = master.read_bytes()

    with TestClient(api_main.app) as client:
        response = client.get("/works/sample-work/image?max=64")

    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "image/jpeg"
    assert response.headers["cache-control"] == "public, max-age=86400"
    with Image.open(io.BytesIO(response.content)) as rendered:
        assert rendered.format == "JPEG"
        assert rendered.mode == "RGB"
        assert rendered.size == (64, 32)
        red, green, blue = rendered.getpixel((32, 16))
        assert red > green > blue
    assert master.read_bytes() == original


def test_cached_master_response_does_not_decode_again(
    image_files: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    master = image_files["work"] / "master.png"
    Image.new("RGB", (96, 48), "red").save(master)
    with TestClient(api_main.app) as client:
        first = client.get("/works/sample-work/image?max=64")
        assert first.status_code == 200
        cached = next(image_files["cache"].glob("*.jpg"))
        before = (cached.stat().st_mtime_ns, cached.read_bytes())

        def unexpected_decode(*args, **kwargs):
            pytest.fail("unchanged master cache hit decoded the source again")

        monkeypatch.setattr(Image, "open", unexpected_decode)
        second = client.get("/works/sample-work/image?max=64")

    assert second.status_code == 200
    assert second.content == first.content
    assert (cached.stat().st_mtime_ns, cached.read_bytes()) == before
    assert len(list(image_files["cache"].iterdir())) == 1


def test_missing_master_is_404_without_creating_cache(image_files: dict[str, Path]) -> None:
    with TestClient(api_main.app, raise_server_exceptions=False) as client:
        response = client.get("/works/sample-work/image?max=64")

    assert response.status_code == 404
    assert response.json() == {"detail": "no master image for sample-work"}
    assert not image_files["cache"].exists()


def test_corrupt_master_reports_resize_failure_without_cached_output(
    image_files: dict[str, Path],
) -> None:
    master = image_files["work"] / "master.png"
    master.write_bytes(b"not an image")
    with TestClient(api_main.app, raise_server_exceptions=False) as client:
        response = client.get("/works/sample-work/image?max=64")

    assert response.status_code == 500
    assert response.json()["detail"].startswith("resize failed:")
    assert list(image_files["cache"].iterdir()) == []
    assert master.read_bytes() == b"not an image"


def test_unavailable_pillow_reports_specific_failure(
    image_files: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    Image.new("RGB", (96, 48), "red").save(image_files["work"] / "master.png")
    original_import = builtins.__import__

    def without_pillow(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "PIL" and "Image" in (fromlist or ()):
            raise ImportError("test dependency outage")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", without_pillow)
    with TestClient(api_main.app, raise_server_exceptions=False) as client:
        response = client.get("/works/sample-work/image?max=64")

    assert response.status_code == 500
    assert response.json() == {"detail": "Pillow not installed"}
    assert list(image_files["cache"].iterdir()) == []


def test_sidecar_master_filename_fallback_is_served(image_files: dict[str, Path]) -> None:
    work = image_files["work"]
    Image.new("RGB", (96, 48), "blue").save(work / "scan.png")
    (work / "meta.json").write_text(
        json.dumps({"work_id": "sample-work", "files": {"master": {"filename": "scan.png"}}}),
        encoding="utf-8",
    )

    with TestClient(api_main.app) as client:
        response = client.get("/works/sample-work/image?max=64")

    assert response.status_code == 200, response.text
    with Image.open(io.BytesIO(response.content)) as rendered:
        assert rendered.size == (64, 32)
        red, _, blue = rendered.getpixel((32, 16))
        assert blue > red
