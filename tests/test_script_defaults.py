"""Tests for maintenance-script CLI defaults."""

from __future__ import annotations

import argparse
import importlib.util
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import NoReturn

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"


class _ParsedArgsError(Exception):
    def __init__(self, namespace: argparse.Namespace) -> None:
        super().__init__("captured parsed arguments")
        self.namespace = namespace


def _load_script_module(name: str):
    path = SCRIPTS / name
    mod_name = name.replace(".py", "").replace("-", "_")
    original_path = sys.path[:]
    had_previous_module = mod_name in sys.modules
    previous_module = sys.modules.get(mod_name)
    try:
        sys.path.insert(0, str(SCRIPTS))
        spec = importlib.util.spec_from_file_location(mod_name, path)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        sys.modules[mod_name] = module
        spec.loader.exec_module(module)
    finally:
        sys.path[:] = original_path
        if had_previous_module:
            assert previous_module is not None
            sys.modules[mod_name] = previous_module
        else:
            sys.modules.pop(mod_name, None)
    return module


def _staging_dir_default(script_name: str, monkeypatch: pytest.MonkeyPatch) -> Path:
    module = _load_script_module(script_name)
    original_parse_args = argparse.ArgumentParser.parse_args

    def capture_parse_args(
        parser: argparse.ArgumentParser,
        args: Sequence[str] | None = None,
        namespace: argparse.Namespace | None = None,
    ) -> NoReturn:
        raise _ParsedArgsError(original_parse_args(parser, args, namespace))

    monkeypatch.setattr(argparse.ArgumentParser, "parse_args", capture_parse_args)
    with pytest.raises(_ParsedArgsError) as captured:
        module.main([])
    return captured.value.namespace.staging_dir


def test_backfill_artist_qids_default_staging_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FAA_STAGING_DIR", raising=False)
    monkeypatch.delenv("FAA_WORKS_DIR", raising=False)

    default = _staging_dir_default("backfill_artist_qids.py", monkeypatch)

    assert "staging_sidecars" not in str(default)
    assert default.name == "works"


def test_resolve_work_qids_default_staging_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FAA_STAGING_DIR", raising=False)
    monkeypatch.delenv("FAA_WORKS_DIR", raising=False)

    default = _staging_dir_default("resolve_work_qids.py", monkeypatch)

    assert "staging_sidecars" not in str(default)
    assert default.name == "works"


def test_retired_root_is_not_an_implicit_script_default() -> None:
    offenders = [
        path.name
        for path in sorted(SCRIPTS.glob("*.py"))
        if 'ROOT / "staging_sidecars"' in path.read_text(encoding="utf-8")
    ]

    assert offenders == []
