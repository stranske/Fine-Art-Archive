"""Smoke tests for dependency sync tooling used by CI autofix steps."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_sync_test_dependencies_verify_passes() -> None:
    """The dependency sync script should pass verify mode for this repo."""
    repo_root = Path(__file__).resolve().parents[1]
    script = repo_root / "scripts" / "sync_test_dependencies.py"

    completed = subprocess.run(  # noqa: S603
        [sys.executable, str(script), "--verify"],
        check=False,
        capture_output=True,
        text=True,
        cwd=repo_root,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
