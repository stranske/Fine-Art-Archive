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
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parents[1]
RENDERER = ROOT / "scripts" / "render_weekly_review.py"

DATE = "2099-01-01"
MASTER = "/archive/works/wid-001/master.tif"
ABS_THUMB = f"/repo/docs/reports/thumbs_{DATE}/abc123.jpg"


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


def test_weekly_review_scripts_exist_in_repo() -> None:
    root = Path(__file__).resolve().parents[1]
    assert (root / "scripts/render_weekly_review.py").is_file()
    assert (root / "scripts/make_review_thumbs.py").is_file()
    render = (root / "scripts/render_weekly_review.py").read_text()
    assert "_ACTIVE_REL" in render
    assert "thumbs_{d}/" in render
