"""Shared sidecar discovery, mirror writing, and environment-path helpers."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fine_art_archive import sidecar


def _sidecar_paths(staging_dir: Path) -> list[Path]:
    """Return nested sidecars and flat JSON sidecars in deterministic order."""
    paths = set(staging_dir.rglob("meta.json"))
    paths.update(staging_dir.glob("*.json"))
    return sorted(path for path in paths if path.is_file())


sidecar_paths = _sidecar_paths


def write_existing_mirrors(
    meta: dict[str, Any], art_works_root: Path | None, *, exclude: Path
) -> list[Path]:
    """Write only pre-existing canonical mirrors, never creating a new layout."""
    if art_works_root is None:
        return []
    work_id = str(meta["work_id"])
    candidates = {
        art_works_root / "works" / work_id / "meta.json",
        art_works_root / work_id / "meta.json",
    }
    written: list[Path] = []
    for candidate in sorted(candidates):
        if candidate.is_file() and candidate.resolve() != exclude.resolve():
            sidecar.write(candidate, meta)
            written.append(candidate)
    return written


def script_env_path(name: str) -> Path | None:
    """Return an optional script-path environment value without inventing a default."""
    raw = os.environ.get(name)
    return Path(raw).expanduser() if raw else None
