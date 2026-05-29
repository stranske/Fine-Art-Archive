"""Tests for the post-acquisition finalizer script (scripts/finalize_acquisition.py).

Covers the repo-specific helper that recomputes a master's sha256/size/dims and
re-derives the work_id, using a synthetic JPEG (no real archive data, no torch).
The full run_finalize integration (verify + quality + sidecar write) is exercised
operationally against real masters.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

_REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO / "scripts"))
sys.path.insert(0, str(_REPO / "src"))

import finalize_acquisition as fa  # noqa: E402


def _make_jpeg(path: Path, w: int = 320, h: int = 200) -> Path:
    Image.new("RGB", (w, h), (123, 200, 80)).save(path, "JPEG", quality=90)
    return path


def test_module_imports_pipeline_symbols() -> None:
    # Confirms the script wires to the in-repo library (sidecar/verify/quality).
    assert callable(fa.run_finalize)
    assert callable(fa.update_files_master_from_bytes)


def test_update_files_master_from_bytes(tmp_path: Path) -> None:
    master = _make_jpeg(tmp_path / "master.jpg")
    meta = {"work_id": "placeholder-the-little-street-vermeer", "files": {"master": {}}}

    fa.update_files_master_from_bytes(meta, master)

    m = meta["files"]["master"]
    assert len(m["sha256"]) == 64 and all(c in "0123456789abcdef" for c in m["sha256"])
    assert m["size_bytes"] == master.stat().st_size
    assert m["dimensions_px"] == [320, 200]
    assert m["filename"] == "master.jpg"
    assert "ICC" in m["color_profile"] or "sRGB" in m["color_profile"]
    # work_id re-derived: 7-hex sha prefix + preserved slug (schema: ^[0-9a-f]{7}-...)
    assert meta["work_id"].startswith(m["sha256"][:7])
    assert meta["work_id"].endswith("the-little-street-vermeer")


def test_work_id_slug_fallback(tmp_path: Path) -> None:
    master = _make_jpeg(tmp_path / "master.jpg")
    meta = {"work_id": "untitledplaceholder", "files": {"master": {}}}  # no hyphen
    fa.update_files_master_from_bytes(meta, master)
    assert meta["work_id"].endswith("untitled")
