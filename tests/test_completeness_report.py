"""Tests for the read-only field provenance completeness report."""

from __future__ import annotations

import csv
import json
from datetime import date
from pathlib import Path
from typing import Any

from scripts.completeness_report import write_report


def _write_sidecar(staging_dir: Path, work_id: str, data: dict[str, Any]) -> Path:
    work_dir = staging_dir / work_id
    work_dir.mkdir(parents=True)
    path = work_dir / "meta.json"
    path.write_text(json.dumps({"work_id": work_id, **data}), encoding="utf-8")
    return path


def test_fixture_corpus_counts_statuses_and_lists_exact_conflicts(tmp_path: Path) -> None:
    staging_dir = tmp_path / "staging"
    first = _write_sidecar(
        staging_dir,
        "aaa0001-first",
        {
            "title": "Kept title",
            "medium": "Oil on canvas",
            "year": None,
            "field_provenance": {
                "medium": {"status": "available", "source": "museum:first"},
                "year": {"status": "not_available", "source": "museum:first"},
                "title": {
                    "status": "conflicting",
                    "source": "museum:first",
                    "note": (
                        "Higher-tier source replaced lower-tier existing value " '"Filename title".'
                    ),
                },
            },
        },
    )
    second = _write_sidecar(
        staging_dir,
        "bbb0002-second",
        {
            "title": "Confirmed title",
            "year": "1888",
            "field_provenance": {
                "medium": {"status": "not_researched"},
                "year": {"status": "unverified", "source": "filename_parse"},
                "title": {"status": "available", "source": "museum:second"},
            },
        },
    )
    third = _write_sidecar(
        staging_dir,
        "ccc0003-third",
        {
            "year": "1901",
            "field_provenance": {
                "year": {
                    "status": "conflicting",
                    "source": "museum:third",
                    "note": ("Higher-tier source replaced lower-tier existing value " '"1900".'),
                }
            },
        },
    )
    before = {path: path.read_bytes() for path in (first, second, third)}

    csv_path, markdown_path, report = write_report(
        staging_dir,
        tmp_path / "reports",
        report_date=date(2026, 7, 24),
    )

    rows = {
        row["field"]: row
        for row in csv.DictReader(csv_path.read_text(encoding="utf-8").splitlines())
    }
    assert rows["medium"] == {
        "field": "medium",
        "total_works": "3",
        "not_researched_count": "2",
        "not_researched_pct": "66.67",
        "available_count": "1",
        "available_pct": "33.33",
        "not_available_count": "0",
        "not_available_pct": "0.00",
        "unverified_count": "0",
        "unverified_pct": "0.00",
        "conflicting_count": "0",
        "conflicting_pct": "0.00",
    }
    assert rows["year"] == {
        "field": "year",
        "total_works": "3",
        "not_researched_count": "0",
        "not_researched_pct": "0.00",
        "available_count": "0",
        "available_pct": "0.00",
        "not_available_count": "1",
        "not_available_pct": "33.33",
        "unverified_count": "1",
        "unverified_pct": "33.33",
        "conflicting_count": "1",
        "conflicting_pct": "33.33",
    }
    assert rows["title"]["not_researched_count"] == "1"
    assert rows["title"]["available_count"] == "1"
    assert rows["title"]["conflicting_count"] == "1"

    assert [
        (
            conflict.work_id,
            conflict.field,
            conflict.kept_value,
            conflict.kept_source,
            conflict.losing_value,
            conflict.losing_source,
        )
        for conflict in report.conflicts
    ] == [
        (
            "aaa0001-first",
            "title",
            "Kept title",
            "museum:first",
            "Filename title",
            None,
        ),
        ("ccc0003-third", "year", "1901", "museum:third", "1900", None),
    ]
    markdown = markdown_path.read_text(encoding="utf-8")
    assert "| aaa0001-first | title | Kept title | museum:first | Filename title |" in markdown
    assert "| ccc0003-third | year | 1901 | museum:third | 1900 |" in markdown
    assert csv_path.name == "completeness_report_2026-07-24.csv"
    assert markdown_path.name == "completeness_report_2026-07-24.md"
    assert {path: path.read_bytes() for path in (first, second, third)} == before


def test_empty_ledgers_still_report_initiative_fields_as_not_researched(
    tmp_path: Path,
) -> None:
    staging_dir = tmp_path / "staging"
    _write_sidecar(staging_dir, "aaa0001-first", {"title": "First"})
    _write_sidecar(staging_dir, "bbb0002-second", {"title": "Second"})

    _, _, report = write_report(
        staging_dir,
        tmp_path / "reports",
        report_date=date(2026, 7, 24),
    )

    assert {row.field for row in report.fields} >= {
        "holder",
        "year",
        "medium",
        "category",
        "dimensions_original",
        "artist_qid",
    }
    assert all(
        row.count("not_researched") == 2
        for row in report.fields
        if row.field
        in {"holder", "year", "medium", "category", "dimensions_original", "artist_qid"}
    )
    assert report.conflicts == ()
