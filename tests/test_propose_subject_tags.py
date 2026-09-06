"""Tests for the Tier 1/2 subject tagger (scripts/propose_subject_tags.py).

Covers tag_work's Tier-2 title-heuristic path with fetch_wd=False (no network);
the Tier-1 Wikidata path is exercised operationally against real sidecars.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import propose_subject_tags as pst  # noqa: E402


def _tag_ids(result: dict[str, Any]) -> set[str]:
    return {t["id"] for t in result["content_tags"]}


def test_battle_title_flags_violence_and_war() -> None:
    r = pst.tag_work({"title": "The Battle of San Romano"}, fetch_wd=False)
    assert r["genre"] == "painting/history"
    assert "filter:violence" in _tag_ids(r)
    assert "theme:war" in _tag_ids(r)
    assert r["needs_review"] is True


def test_portrait_title() -> None:
    r = pst.tag_work({"title": "Portrait of a Lady"}, fetch_wd=False)
    assert r["genre"] == "painting/portrait"
    assert "subject:single-figure" in _tag_ids(r)


def test_still_life_title() -> None:
    r = pst.tag_work({"title": "Still Life with Apples and Grapes"}, fetch_wd=False)
    assert r["genre"] == "painting/still-life"


def test_unmatched_title_is_unknown_and_skips_review() -> None:
    r = pst.tag_work({"title": "Composition No. 5"}, fetch_wd=False)
    assert r["genre"] == "unknown"
    assert r["content_tags"] == []
    assert r["needs_review"] is False


def test_fetch_wd_false_skips_wikidata() -> None:
    # A wikidata_q present but fetch_wd=False must NOT fetch; only title rules apply
    # (this title matches nothing → unknown, proving Tier 1 was skipped).
    r = pst.tag_work(
        {"title": "Composition", "stable_identifiers": {"wikidata_q": "Q12418"}},
        fetch_wd=False,
    )
    assert r["genre"] == "unknown"


def _configure_main(
    monkeypatch: Any,
    tmp_path: Path,
    *,
    title: str,
    output: Path,
) -> Path:
    staging = tmp_path / "staging"
    sidecar_path = staging / "unicode-work" / "meta.json"
    sidecar_path.parent.mkdir(parents=True)
    sidecar_path.write_text(
        json.dumps({"title": title, "artist": {"name": "Édouard Manet"}}, ensure_ascii=False),
        encoding="utf-8",
    )
    root = tmp_path / "workspace"
    monkeypatch.setattr(pst, "ROOT", root)
    monkeypatch.setattr(pst, "STAGING", staging)
    monkeypatch.setattr(pst, "PREVIEW_CSV", output)
    monkeypatch.setattr(sys, "argv", ["propose_subject_tags.py", "--no-wikidata"])
    return sidecar_path


def test_main_uses_utf8_for_non_ascii_sidecar_and_preview(monkeypatch: Any, tmp_path: Path) -> None:
    output = tmp_path / "workspace" / "subject_tags_v1_preview.csv"
    output.parent.mkdir(parents=True)
    sidecar_path = _configure_main(
        monkeypatch,
        tmp_path,
        title="中文 · Café",
        output=output,
    )
    monkeypatch.setattr(sys, "argv", ["propose_subject_tags.py", "--no-wikidata", "--apply"])

    assert pst.main() == 0
    assert "中文 · Café" in output.read_bytes().decode("utf-8")
    updated_sidecar = json.loads(sidecar_path.read_bytes().decode("utf-8"))
    assert updated_sidecar["subject"]["genre"] == "unknown"


def test_main_creates_preview_parent_directory(monkeypatch: Any, tmp_path: Path) -> None:
    output = tmp_path / "workspace" / "nested" / "subject_tags_v1_preview.csv"
    _configure_main(monkeypatch, tmp_path, title="Landscape", output=output)

    assert not output.parent.exists()
    assert pst.main() == 0
    assert output.exists()
