"""Tests for the Tier 1/2 subject tagger (scripts/propose_subject_tags.py).

Covers tag_work's Tier-2 title-heuristic path with fetch_wd=False (no network);
the Tier-1 Wikidata path is exercised operationally against real sidecars.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import propose_subject_tags as pst  # noqa: E402


def _tag_ids(result: dict) -> set[str]:
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
