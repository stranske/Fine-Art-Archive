"""Missing modality inputs and originals must produce useful HTTP responses."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from fine_art_archive.api import main as api_main
from fine_art_archive.api import store


@pytest.fixture
def archive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Path, Path]:
    works = tmp_path / "works"
    work = works / "sample-work"
    work.mkdir(parents=True)
    cache = tmp_path / "image-cache"
    monkeypatch.setattr(store, "WORKS", works)
    monkeypatch.setattr(api_main, "ART_WORKS_ROOT", works)
    monkeypatch.setattr(api_main, "IMAGE_CACHE_DIR", cache)
    return work, cache


def test_modality_requires_sidecar_even_when_master_exists(archive: tuple[Path, Path]) -> None:
    work, cache = archive
    Image.new("RGB", (96, 48), "red").save(work / "master.png")

    with TestClient(api_main.app, raise_server_exceptions=False) as client:
        response = client.get("/works/sample-work/modality/IRR/image?max=64")

    assert response.status_code == 404
    assert response.json() == {"detail": "no sidecar for sample-work"}
    assert not cache.exists()


@pytest.mark.parametrize("filename", [None, ""], ids=["absent", "empty"])
def test_modality_descriptor_without_filename_is_404(
    archive: tuple[Path, Path], filename: str | None
) -> None:
    work, cache = archive
    entry = {"modality": "IRR", "label": "Underdrawing"}
    if filename is not None:
        entry["filename"] = filename
    (work / "meta.json").write_text(
        json.dumps({"work_id": "sample-work", "modalities": [entry]}), encoding="utf-8"
    )

    with TestClient(api_main.app, raise_server_exceptions=False) as client:
        response = client.get("/works/sample-work/modality/irr/image?max=64")

    assert response.status_code == 404
    assert response.json() == {"detail": "no irr modality for sample-work"}
    assert not cache.exists()


def test_missing_modality_file_does_not_fall_back_to_master(archive: tuple[Path, Path]) -> None:
    work, cache = archive
    Image.new("RGB", (96, 48), "red").save(work / "master.png")
    (work / "meta.json").write_text(
        json.dumps(
            {
                "work_id": "sample-work",
                "modalities": [{"modality": "IRR", "filename": "underdrawing.png"}],
            }
        ),
        encoding="utf-8",
    )

    with TestClient(api_main.app, raise_server_exceptions=False) as client:
        response = client.get("/works/sample-work/modality/IRR/image?max=64")

    assert response.status_code == 404
    assert response.json() == {"detail": "IRR file missing for sample-work"}
    assert not cache.exists()
    assert not (work / "underdrawing.png").exists()


def test_original_download_with_stale_master_filename_is_404(archive: tuple[Path, Path]) -> None:
    work, cache = archive
    (work / "meta.json").write_text(
        json.dumps(
            {"work_id": "sample-work", "files": {"master": {"filename": "lost-original.tif"}}}
        ),
        encoding="utf-8",
    )

    with TestClient(api_main.app, raise_server_exceptions=False) as client:
        response = client.get("/works/sample-work/full")

    assert response.status_code == 404
    assert response.json() == {"detail": "no master image for sample-work"}
    assert "content-disposition" not in response.headers
    assert not cache.exists()
    assert not (work / "lost-original.tif").exists()
