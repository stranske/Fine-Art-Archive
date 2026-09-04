from __future__ import annotations

from pathlib import Path

from scripts._sidecar_io import script_env_path, sidecar_paths, write_existing_mirrors

from fine_art_archive import sidecar


def test_sidecar_paths_includes_flat_json(tmp_path: Path) -> None:
    nested = tmp_path / "nested" / "meta.json"
    nested.parent.mkdir()
    nested.write_text("{}")
    flat = tmp_path / "legacy.json"
    flat.write_text("{}")
    (tmp_path / "ignored.json").mkdir()

    assert sidecar_paths(tmp_path) == [flat, nested]


def test_write_existing_mirrors_skips_exclude(monkeypatch, tmp_path: Path) -> None:
    art_works_root = tmp_path / "art-works"
    excluded = art_works_root / "works" / "work-42" / "meta.json"
    mirror = art_works_root / "work-42" / "meta.json"
    excluded.parent.mkdir(parents=True)
    mirror.parent.mkdir(parents=True)
    excluded.write_text("excluded")
    mirror.write_text("mirror")
    written: list[Path] = []
    monkeypatch.setattr(sidecar, "write", lambda path, meta: written.append(path))

    result = write_existing_mirrors({"work_id": "work-42"}, art_works_root, exclude=excluded)

    assert result == [mirror]
    assert written == [mirror]
    assert excluded.read_text() == "excluded"


def test_write_existing_mirrors_rejects_escape_symlink(monkeypatch, tmp_path: Path) -> None:
    art_works_root = tmp_path / "art-works"
    outside = tmp_path / "outside.json"
    mirror = art_works_root / "work-42" / "meta.json"
    excluded = tmp_path / "staging" / "work-42" / "meta.json"
    outside.write_text("outside")
    mirror.parent.mkdir(parents=True)
    mirror.symlink_to(outside)
    excluded.parent.mkdir(parents=True)
    excluded.write_text("excluded")
    written: list[Path] = []
    monkeypatch.setattr(sidecar, "write", lambda path, meta: written.append(path))

    result = write_existing_mirrors({"work_id": "work-42"}, art_works_root, exclude=excluded)

    assert result == []
    assert written == []
    assert outside.read_text() == "outside"


def test_script_env_path_handles_empty_home_and_relative(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("FAA_TEST_PATH", raising=False)
    assert script_env_path("FAA_TEST_PATH") is None
    monkeypatch.setenv("FAA_TEST_PATH", "")
    assert script_env_path("FAA_TEST_PATH") is None
    monkeypatch.setenv("FAA_TEST_PATH", "~/archive")
    assert script_env_path("FAA_TEST_PATH") == Path.home() / "archive"
    monkeypatch.setenv("FAA_TEST_PATH", "relative/archive")
    assert script_env_path("FAA_TEST_PATH") == Path(__file__).resolve().parents[1] / "relative/archive"
