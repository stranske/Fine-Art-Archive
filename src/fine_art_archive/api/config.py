"""Configuration helpers for the companion API."""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def env_path(name: str, default: Path) -> Path:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default.expanduser()

    path = Path(raw).expanduser()
    return path if path.is_absolute() else REPO_ROOT / path


DEFAULT_ART_WORKS_ROOT = (
    Path.home() / "Library" / "CloudStorage" / "Dropbox" / "Pictures" / "Art" / "works"
)
