from __future__ import annotations

import importlib
import json
from pathlib import Path

from fastapi.testclient import TestClient

from fine_art_archive.api.config import REPO_ROOT, env_path


def _reload_api_modules():
    import fine_art_archive.api.config as api_config
    import fine_art_archive.api.main as api_main
    import fine_art_archive.api.store as api_store

    api_config = importlib.reload(api_config)
    api_store = importlib.reload(api_store)
    api_main = importlib.reload(api_main)
    return api_main, api_store


def test_companion_paths_resolve_from_env_roots(tmp_path: Path, monkeypatch) -> None:
    try:
        work_id = "env-root-work"
        art_root = tmp_path / "art-works"
        staging = tmp_path / "sidecars"
        ratings_log = tmp_path / "ratings" / "ratings.jsonl"
        manifest_csv = tmp_path / "manifest.csv"
        image_cache = tmp_path / "image-cache"

        monkeypatch.setenv("FAA_ART_WORKS_ROOT", str(art_root))
        monkeypatch.setenv("FAA_STAGING_DIR", str(staging))
        monkeypatch.setenv("FAA_RATINGS_LOG", str(ratings_log))
        monkeypatch.setenv("FAA_MANIFEST_CSV", str(manifest_csv))
        monkeypatch.setenv("FAA_IMAGE_CACHE_DIR", str(image_cache))

        (art_root / work_id).mkdir(parents=True)
        master = art_root / work_id / "master.jpg"
        master.write_bytes(b"fake-master")
        (staging / work_id).mkdir(parents=True)
        (staging / work_id / "meta.json").write_text(
            json.dumps(
                {
                    "work_id": work_id,
                    "title": "Env Root Work",
                    "files": {"master": {"filename": "master.jpg"}},
                }
            )
        )
        manifest_csv.write_text("work_id,title,artist_name\n")

        api_main, api_store = _reload_api_modules()
        client = TestClient(api_main.app)

        work_response = client.get(f"/works/{work_id}")
        assert work_response.status_code == 200
        assert work_response.json()["title"] == "Env Root Work"
        assert staging == api_store.STAGING
        assert manifest_csv == api_store.MANIFEST_CSV
        assert ratings_log == api_store.RATINGS_LOG

        full_response = client.get(f"/works/{work_id}/full")
        assert full_response.status_code == 200
        assert full_response.content == b"fake-master"
        assert art_root == api_main.ART_WORKS_ROOT
        assert image_cache == api_main.IMAGE_CACHE_DIR
    finally:
        monkeypatch.undo()
        _reload_api_modules()


def test_env_path_anchors_relative_overrides(monkeypatch) -> None:
    monkeypatch.setenv("FAA_STAGING_DIR", "tmp/sidecars")

    assert (
        env_path("FAA_STAGING_DIR", REPO_ROOT / "staging_sidecars")
        == REPO_ROOT / "tmp" / "sidecars"
    )
