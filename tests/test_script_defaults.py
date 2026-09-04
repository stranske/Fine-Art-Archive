"""Tests for maintenance-script CLI defaults."""

from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"


def _load_script_module(name: str):
    path = SCRIPTS / name
    mod_name = name.replace(".py", "").replace("-", "_")
    spec = importlib.util.spec_from_file_location(mod_name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    spec.loader.exec_module(module)
    return module


def _staging_dir_default(script_name: str) -> Path:
    module = _load_script_module(script_name)
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--staging-dir",
        type=Path,
        default=module.default_works_dir(),
    )
    return parser.parse_args([]).staging_dir


def test_backfill_artist_qids_default_staging_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FAA_STAGING_DIR", raising=False)
    monkeypatch.delenv("FAA_WORKS_DIR", raising=False)

    default = _staging_dir_default("backfill_artist_qids.py")

    assert "staging_sidecars" not in str(default)
    assert default.name == "works"


def test_resolve_work_qids_default_staging_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FAA_STAGING_DIR", raising=False)
    monkeypatch.delenv("FAA_WORKS_DIR", raising=False)

    default = _staging_dir_default("resolve_work_qids.py")

    assert "staging_sidecars" not in str(default)
    assert default.name == "works"
