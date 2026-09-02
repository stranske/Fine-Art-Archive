"""Quarantine directories name their own expiry; something has to read it.

D02 names each quarantine `<date>__<reason>__purge-after-<date>`, and nothing
ever parsed that date. On 2026-09-02 eight directories were past it — the oldest
by 78 days — holding roughly 1.8 GB. A deletion deadline encoded in a filename
that no code reads is a gate whose drain does not exist, and it is silent by
construction: the directory just sits there looking like every other directory.

Reporting it is the durable fix. Purging stays a human decision, so these tests
pin two properties in particular: that the report can never block anything, and
that a tree it cannot read is never reported as clean.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fine_art_archive.api import main as api_main
from fine_art_archive.api import store as api_store
from fine_art_archive.api.main import _quarantine_report, app


@pytest.fixture
def quarantine(tmp_path: Path) -> Path:
    root = tmp_path / "quarantine"
    root.mkdir()
    for name in (
        "2026-05-17__purge-after-2026-06-16",
        "2026-06-29__dedup__purge-after-2026-07-29",
        "2026-08-01__dedup__purge-after-2026-08-31",
        "2026-12-01__dedup__purge-after-2027-01-01",
        "truncated-masters-2026-09-02",
        "2026-08-01__broken__purge-after-not-a-date",
    ):
        (root / name).mkdir()
    (root / "a-loose-file.txt").write_text("not a directory", encoding="utf-8")
    return root


def test_overdue_directories_are_reported_with_their_age(quarantine: Path) -> None:
    report = _quarantine_report(quarantine, today=date(2026, 9, 2))
    assert report is not None
    assert [row["name"] for row in report["overdue"]] == [
        "2026-05-17__purge-after-2026-06-16",
        "2026-06-29__dedup__purge-after-2026-07-29",
        "2026-08-01__dedup__purge-after-2026-08-31",
    ], "most overdue first"
    assert report["overdue"][0]["days_overdue"] == 78


def test_a_future_purge_date_is_not_overdue(quarantine: Path) -> None:
    report = _quarantine_report(quarantine, today=date(2026, 9, 2))
    assert report is not None
    names = {row["name"] for row in report["overdue"]}
    assert "2026-12-01__dedup__purge-after-2027-01-01" not in names


def test_a_quarantine_with_no_ttl_is_reported_separately(quarantine: Path) -> None:
    """A quarantine that never comes due is the same defect one step earlier.

    `truncated-masters-2026-09-02` was created without a `purge-after-` segment,
    so no deadline can ever pass. That is quieter than being overdue, not safer.
    """
    report = _quarantine_report(quarantine, today=date(2026, 9, 2))
    assert report is not None
    assert report["no_ttl"] == [
        "2026-08-01__broken__purge-after-not-a-date",
        "truncated-masters-2026-09-02",
    ]


def test_nothing_overdue_reports_an_empty_list_not_nothing(tmp_path: Path) -> None:
    """The drained state has to be reachable and distinguishable from failure."""
    root = tmp_path / "quarantine"
    root.mkdir()
    (root / "2026-12-01__dedup__purge-after-2027-01-01").mkdir()
    report = _quarantine_report(root, today=date(2026, 9, 2))
    assert report == {"overdue": [], "no_ttl": [], "total": 1}


def test_unreadable_root_is_none_not_clean(tmp_path: Path) -> None:
    """ "Cannot list the tree" must not render as "nothing is overdue"."""
    assert _quarantine_report(tmp_path / "does-not-exist", today=date(2026, 9, 2)) is None


def test_overdue_quarantine_never_blocks_health(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FYI only. An expired quarantine is disk housekeeping, not an outage.

    If this ever gated `ok`, a directory nobody had got round to deleting would
    take the operator UI's health red and train everyone to ignore it.
    """
    works = tmp_path / "works"
    works.mkdir()
    manifest = tmp_path / "manifest.csv"
    manifest.write_text("work_id,title\n", encoding="utf-8")
    quarantine = tmp_path / "quarantine"
    (quarantine / "2026-01-01__old__purge-after-2026-01-02").mkdir(parents=True)
    queues = tmp_path / "queues"
    queues.mkdir()

    monkeypatch.setattr(api_store, "WORKS", works)
    monkeypatch.setattr(api_store, "MANIFEST_CSV", manifest)
    monkeypatch.setattr(api_main, "ART_WORKS_ROOT", works)
    monkeypatch.setattr(api_main, "QUEUES_DIR", queues)
    monkeypatch.setattr(api_store, "RATINGS_LOG", tmp_path / "ratings.jsonl")
    api_store.invalidate_manifest_cache()
    api_store.invalidate_ratings_cache()

    body = TestClient(app).get("/healthz").json()
    assert body["quarantine"]["overdue"], "the overdue directory must be reported"
    assert body["ok"] is True, "an overdue quarantine must never fail health"

    api_store.invalidate_manifest_cache()
    api_store.invalidate_ratings_cache()
