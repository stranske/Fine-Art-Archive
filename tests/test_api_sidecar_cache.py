"""`_all_sidecars` — the cache the API reads every work through.

It scans the works tree once and reuses the result until a cheap signature changes. Two ways to be
wrong, both silent:

  * invalidation too weak -> the API serves STALE sidecars after an edit, indefinitely, with no
    error anywhere;
  * one bad file aborting the scan -> works that are perfectly readable vanish from the archive
    because a neighbour has malformed JSON.

The signature exists because per-directory mtimes are not enough: rewriting an existing
`<works>/<wid>/meta.json` in place moves neither the works root's mtime nor the work directory's.
`store._dossier_signature`'s own docstring records that, and this file pins the consequence.
"""

from __future__ import annotations

import json

import pytest

from fine_art_archive.api import main as api_main
from fine_art_archive.api import store


@pytest.fixture()
def works(tmp_path, monkeypatch):
    """Point the store at a tree this test owns, and clear the module-level cache."""
    root = tmp_path / "works"
    root.mkdir()
    monkeypatch.setattr(store, "WORKS", root)
    monkeypatch.setattr(api_main, "_sidecars_cache", None, raising=False)
    return root


def _work(root, wid: str, **meta) -> None:
    d = root / wid
    d.mkdir(parents=True, exist_ok=True)
    (d / "meta.json").write_text(json.dumps(meta or {"id": wid}), encoding="utf-8")


def test_an_empty_tree_is_an_empty_list(works):
    assert api_main._all_sidecars() == []


def test_a_missing_works_root_is_empty_rather_than_an_error(tmp_path, monkeypatch):
    """A fresh install has no works directory. Raising here takes down every route at once."""
    monkeypatch.setattr(store, "WORKS", tmp_path / "does-not-exist")
    monkeypatch.setattr(api_main, "_sidecars_cache", None, raising=False)
    assert api_main._all_sidecars() == []


def test_each_work_is_returned_with_its_id_and_sidecar(works):
    _work(works, "w1", title="A")
    _work(works, "w2", title="B")
    got = dict(api_main._all_sidecars())
    assert got["w1"]["title"] == "A"
    assert got["w2"]["title"] == "B"


def test_results_are_ordered_so_the_archive_does_not_reshuffle(works):
    """Directory iteration order is not stable across filesystems; the API would list works in a
    different order on every deploy."""
    for wid in ("w3", "w1", "w2"):
        _work(works, wid)
    assert [wid for wid, _ in api_main._all_sidecars()] == ["w1", "w2", "w3"]


def test_a_directory_without_a_sidecar_is_skipped(works):
    _work(works, "w1")
    (works / "w2").mkdir()
    assert [wid for wid, _ in api_main._all_sidecars()] == ["w1"]


def test_one_malformed_sidecar_does_not_take_its_neighbours_with_it(works):
    """The whole archive must not disappear because one file is broken.

    Aborting the scan is the silent version of this: every OTHER work vanishes from the API and
    nothing says why.
    """
    _work(works, "w1", title="A")
    (works / "w2").mkdir()
    (works / "w2" / "meta.json").write_text("{not json", encoding="utf-8")
    _work(works, "w3", title="C")
    got = [wid for wid, _ in api_main._all_sidecars()]
    assert got == ["w1", "w3"]


# ---------------------------------------------------------------------------------------------
# The cache. Serving stale data is the failure that never announces itself.
# ---------------------------------------------------------------------------------------------


def test_an_edited_sidecar_is_picked_up(works):
    """The reason the signature hashes FILE mtimes rather than directory ones.

    Rewriting a meta.json in place moves neither the works root's mtime nor the work directory's,
    so a directory-only signature would serve the old title forever.
    """
    _work(works, "w1", title="before")
    assert dict(api_main._all_sidecars())["w1"]["title"] == "before"

    _work(works, "w1", title="after")
    assert dict(api_main._all_sidecars())["w1"]["title"] == "after"


def test_a_new_work_is_picked_up(works):
    _work(works, "w1")
    assert len(api_main._all_sidecars()) == 1
    _work(works, "w2")
    assert len(api_main._all_sidecars()) == 2


def test_a_removed_work_disappears(works):
    _work(works, "w1")
    _work(works, "w2")
    assert len(api_main._all_sidecars()) == 2
    (works / "w2" / "meta.json").unlink()
    (works / "w2").rmdir()
    assert [wid for wid, _ in api_main._all_sidecars()] == ["w1"]


def test_an_unchanged_tree_is_not_rescanned(works, monkeypatch):
    """The cache must actually cache — otherwise every request walks the whole archive.

    Asserted by counting reads of the tree rather than by timing, which would be flaky.
    """
    _work(works, "w1")
    api_main._all_sidecars()

    calls = {"n": 0}
    real_iterdir = type(works).iterdir

    def counting_iterdir(self):
        if self == works:
            calls["n"] += 1
        return real_iterdir(self)

    monkeypatch.setattr(type(works), "iterdir", counting_iterdir)
    api_main._all_sidecars()
    assert calls["n"] == 0, "a second call with an unchanged signature must not walk the tree"
