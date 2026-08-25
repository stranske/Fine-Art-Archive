"""Regression tests for weekly review dated vs served thumbnail paths (issue #561).

These tests EXECUTE `scripts/render_weekly_review.py` — they load the script by
path and assert on values the renderer returns — rather than asserting on its
source text or on literals defined in this file.

That distinction is the whole point. Until 2026-08-25 two of the three cases
here asserted Python string operations on their own literals and imported
nothing from the repository, so reintroducing the exact defect #561 repaired
(`src = furl(path)` at `scripts/render_weekly_review.py:60`, which emits
`file://` URLs that do not load when the page is served over http) left the
suite at `3 passed`. Only renaming an identifier could make it fail, and it
failed on `assert '_ACTIVE_REL' in <file text>` — a grep, not a behaviour.
A guard that cannot fail for the reason it was written is worse than no guard,
because it reports coverage of a fix it does not observe.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
RENDERER = ROOT / "scripts" / "render_weekly_review.py"

DATE = "2099-01-01"
MASTER = "/archive/works/wid-001/master.tif"
ABS_THUMB = f"/repo/docs/reports/thumbs_{DATE}/abc123.jpg"

# The two scopes the renderer used to hardcode. G47's is the one an unknown
# grant inherited from the `else` branch.
G41_SCOPE = "8 duplicate pairs; metadata transfer + quarantine"
G47_SCOPE = "6 sidecars with wrong artist Q-IDs; modify-in-place only"


def load_renderer() -> ModuleType:
    """`scripts/` is not an importable package, so load the script by path."""
    spec = importlib.util.spec_from_file_location("render_weekly_review", RENDERER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def renderer() -> ModuleType:
    """A freshly executed renderer, so module-level state never leaks between tests."""
    module = load_renderer()
    module.THUMBS.clear()
    module._ACTIVE_REL.clear()
    return module


@pytest.fixture
def payload() -> dict:
    """A minimal synthetic weekly_review_<date>.json, six required top-level keys.

    `main()` reads `ungranted`, `candidates`, `unpromoted`, `collisions`,
    `allowed_p31` and `live_works` unconditionally; `grants` and `ops` are
    optional. Kept to one screen deliberately — see the Non-Goals on #596.
    """
    return {
        "ungranted": {
            "total": 1,
            "by_grant": {
                "G41": [
                    {
                        "wid": "wid-001",
                        "title": "A Work",
                        "artist": "An Artist",
                        "master": MASTER,
                        "size_mb": 12,
                        "batch": "b-01",
                    }
                ]
            },
        },
        "candidates": {"by_status": {"screened": 0}, "top": []},
        "unpromoted": [],
        "collisions": {"qids_on_multiple": 0},
        "allowed_p31": [],
        "live_works": 1,
    }


@pytest.fixture
def full_payload(payload: dict) -> dict:
    """The minimal payload widened to what a whole-document render touches.

    Three grants — two the payload records a scope for, and G99, which it does
    not. Lists stay empty wherever the renderer only iterates them.
    """
    item = payload["ungranted"]["by_grant"]["G41"][0]
    data = dict(payload)
    data["ungranted"] = {
        "total": 3,
        "by_grant": {
            "G41": [item],
            "G47": [dict(item, wid="wid-047")],
            "G99": [dict(item, wid="wid-099")],
        },
    }
    data["grants"] = {
        "standing_acquisition": [],
        "scopes": {"G41": G41_SCOPE, "G47": G47_SCOPE},
    }
    data["candidates"] = {
        "top": [],
        "frontier_total": 0,
        "by_status": {"screened": 0, "review": 0, "rejected": 0},
        "latest_run": {"ts": f"{DATE}T00:00:00Z", "raw_by_generator": {}, "added": 0},
    }
    # Non-empty, because the renderer gates the whole unpromoted card on
    # `if unprom:` — with an empty list the block that carried the frozen "78"
    # is never emitted, and an assertion that it is absent would be vacuous.
    data["unpromoted"] = [
        {
            "wid": "wid-900",
            "title": "A Staged Work",
            "artist": "An Artist",
            "size_mb": 30,
            "staged_master": "/staging/wid-900/master.tif",
            "collision_master": "",
            "title_collision_with": "",
        }
    ]
    data["collisions"] = {"qids_on_multiple": 2, "extra_assignments": 3, "worst": []}
    data["allowed_p31"] = {
        "definitions": [{"file": "config/allowed_p31.json", "classes": []}],
        "dropped": {"qid": "Q93184"},
    }
    data["filed_issues"] = {
        "rows": [
            {
                "number": 406,
                "finding": "artist Q-IDs do not denote the named artist",
                "state": "closed",
            },
            {"number": 409, "finding": "steps falsely marked completed", "state": "closed"},
        ],
        "note": "Both closed on the remote; listed for orientation only.",
    }
    return data


def _activate(renderer: ModuleType, date: str) -> None:
    """Reproduce what `main()` does between loading thumbs and rendering."""
    renderer._ACTIVE_REL.clear()
    for abs_thumb in set(renderer.THUMBS.values()):
        renderer._ACTIVE_REL[abs_thumb] = f"thumbs_{date}/{Path(abs_thumb).name}"


def test_dated_thumb_src_is_date_scoped(renderer: ModuleType, payload: dict) -> None:
    """The dated page must reference `thumbs_<date>/`, not a bare `thumbs/`.

    Driven from a payload item's `master` path through the same THUMBS ->
    _ACTIVE_REL chain `main()` builds, and asserted on the renderer's own
    output.
    """
    item = payload["ungranted"]["by_grant"]["G41"][0]
    renderer.THUMBS[item["master"]] = ABS_THUMB
    _activate(renderer, DATE)

    markup = renderer.thumb(item["master"], item["title"])

    assert f'src="thumbs_{DATE}/abc123.jpg"' in markup
    assert "file://" not in markup


def test_served_relative_path_wins_over_file_url(renderer: ModuleType) -> None:
    """The #561 fix, pinned on behaviour: `_ACTIVE_REL` beats the `file://` form.

    `scripts/render_weekly_review.py:60` is `src = _ACTIVE_REL.get(path) or
    furl(path)`. Reverting it to `src = furl(path)` emits `file://` URLs that
    do not load over http — the failure #561 was opened for — and this
    assertion is what turns red when that happens.
    """
    renderer.THUMBS[MASTER] = ABS_THUMB
    _activate(renderer, DATE)

    markup = renderer.thumb(MASTER, "A Work")

    assert f'src="thumbs_{DATE}/abc123.jpg"' in markup, "the served relative src must win"
    assert renderer.furl(ABS_THUMB) not in markup, "the file:// form must not be emitted"
    assert "file://" not in markup


def test_path_absent_from_active_rel_falls_back_to_file_url(renderer: ModuleType) -> None:
    """The other direction, so the fix is pinned both ways.

    Without a served copy there is nothing relative to point at, and the
    standalone `file://` page is the intended output. A test that only checked
    the relative form would pass against an unconditional rewrite.
    """
    renderer.THUMBS[MASTER] = ABS_THUMB
    renderer._ACTIVE_REL.clear()

    markup = renderer.thumb(MASTER, "A Work")

    assert renderer.furl(ABS_THUMB) in markup
    assert f"thumbs_{DATE}/abc123.jpg" not in markup.replace(renderer.furl(ABS_THUMB), "")


def render_document(
    renderer: ModuleType, data: dict, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> str:
    """Run `main()` over a payload and return the HTML it wrote.

    `main()` reads `weekly_review_<date>.json` from REPORTS and writes the page
    back there, so pointing REPORTS at a tmp dir renders the real document with
    no repo state involved.
    """
    reports = tmp_path / "reports"
    reports.mkdir()
    (reports / f"weekly_review_{DATE}.json").write_text(json.dumps(data))
    monkeypatch.setattr(renderer, "REPORTS", reports)
    monkeypatch.setattr(sys, "argv", ["render_weekly_review.py", "--date", DATE, "--serve-dir", ""])
    renderer.main()
    return (reports / f"weekly_review_{DATE}.html").read_text()


def test_unknown_grant_does_not_inherit_another_grants_scope(
    renderer: ModuleType, full_payload: dict, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A grant the page has never seen must not be labelled with G47's scope.

    `scripts/render_weekly_review.py` used to branch `if grant == "G41" ...
    else`, so every third grant id inherited G47's recorded scope verbatim.
    The surrounding paragraph tells the owner that `operations.log` plus the
    authorizing grant is the undo script, which makes a fabricated scope a
    fabricated undo plan.

    The same render also pins the three other frozen claims the page carried
    under a header promising "Every number below was measured on your Mac".
    """
    doc = render_document(renderer, full_payload, tmp_path, monkeypatch)

    # 1. the unknown grant is not handed another grant's scope
    assert "G99" in doc
    unknown_heading = next(line for line in doc.splitlines() if "G99" in line and "<h4>" in line)
    assert G47_SCOPE not in unknown_heading
    assert renderer.SCOPE_NOT_RECORDED in unknown_heading
    # and the two grants the payload DOES record keep their own scopes
    assert G41_SCOPE in doc
    assert G47_SCOPE in doc

    # 2 + 3. neither frozen prose measurement survives.
    # Both blocks are gated (`if unprom:`, `if coll["qids_on_multiple"]:`), so
    # assert they RENDERED first — otherwise "the literal is absent" is true of
    # a page that simply omitted the section, which is the vacuity this whole
    # issue is about. Caught during the deliberate-break demonstration.
    assert "staging_acquisitions" in doc, "the unpromoted block did not render"
    assert "audit_duplicate_decisions.py" in doc, "the collisions block did not render"
    assert "A further 78 staging directories" not in doc
    assert "26 of 34 proposed quarantines" not in doc

    # 4. every issue number rendered in the filed-issues block was supplied
    supplied = {str(row["number"]) for row in full_payload["filed_issues"]["rows"]}
    block = doc[doc.index('id="issues"') : doc.index("</section>", doc.index('id="issues"'))]
    rendered = set(re.findall(rf"{re.escape(renderer.ISSUE_URL_BASE)}/(\d+)", block))
    assert rendered, "the filed-issues block rendered no issues at all"
    assert rendered <= supplied, f"rendered issue numbers not in the payload: {rendered - supplied}"


def test_filed_issues_block_is_omitted_when_the_payload_carries_none(
    renderer: ModuleType, full_payload: dict, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """No payload key, no invented table — the four literal rows cannot come back."""
    full_payload.pop("filed_issues")
    doc = render_document(renderer, full_payload, tmp_path, monkeypatch)

    assert "completeness issues" not in doc
    for number in ("406", "407", "408", "409"):
        assert f"{renderer.ISSUE_URL_BASE}/{number}" not in doc


def test_weekly_review_scripts_exist_in_repo() -> None:
    root = Path(__file__).resolve().parents[1]
    assert (root / "scripts/render_weekly_review.py").is_file()
    assert (root / "scripts/make_review_thumbs.py").is_file()
    render = (root / "scripts/render_weekly_review.py").read_text()
    assert "_ACTIVE_REL" in render
    assert "thumbs_{d}/" in render
