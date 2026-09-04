"""Shared path defaults for maintenance scripts."""

from __future__ import annotations

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "src"))

from fine_art_archive.api.config import DEFAULT_ART_WORKS_ROOT, env_path  # noqa: E402


def default_works_dir() -> Path:
    """Canonical sidecar root aligned with :func:`fine_art_archive.api.store._works_dir`."""
    if os.environ.get("FAA_WORKS_DIR"):
        return env_path("FAA_WORKS_DIR", DEFAULT_ART_WORKS_ROOT)
    return env_path("FAA_STAGING_DIR", DEFAULT_ART_WORKS_ROOT)
