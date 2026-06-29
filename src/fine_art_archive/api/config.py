"""Configuration helpers for the companion API."""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]


def env_path(name: str, default: Path) -> Path:
    return Path(os.environ.get(name, default)).expanduser()


DEFAULT_ART_WORKS_ROOT = (
    Path.home() / "Library" / "CloudStorage" / "Dropbox" / "Pictures" / "Art" / "works"
)
