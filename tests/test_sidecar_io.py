from __future__ import annotations

from pathlib import Path

from scripts._sidecar_io import sidecar_paths, write_existing_mirrors

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
