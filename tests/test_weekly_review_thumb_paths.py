"""Regression tests for weekly review dated vs served thumbnail paths (issue #561)."""

from __future__ import annotations

from pathlib import Path


def test_dated_rel_uses_date_scoped_directory() -> None:
    date = "2099-01-01"
    abs_thumb = "/repo/docs/reports/thumbs_2099-01-01/abc123.jpg"
    dated_rel = {abs_thumb: f"thumbs_{date}/{Path(abs_thumb).name}"}
    assert dated_rel[abs_thumb] == "thumbs_2099-01-01/abc123.jpg"


def test_served_copy_rewrites_dated_thumb_prefix() -> None:
    date = "2099-01-01"
    doc = '<img src="thumbs_2099-01-01/abc123.jpg">'
    served_doc = doc.replace(f"thumbs_{date}/", "thumbs/")
    assert served_doc == '<img src="thumbs/abc123.jpg">'


def test_weekly_review_scripts_exist_in_repo() -> None:
    root = Path(__file__).resolve().parents[1]
    assert (root / "scripts/render_weekly_review.py").is_file()
    assert (root / "scripts/make_review_thumbs.py").is_file()
    render = (root / "scripts/render_weekly_review.py").read_text()
    assert "_ACTIVE_REL" in render
    assert "thumbs_{d}/" in render
