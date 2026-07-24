#!/usr/bin/env python3
"""Emit a read-only field-provenance completeness report for staged sidecars."""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from datetime import date
from pathlib import Path
from typing import Any, TextIO

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "src"))

from fine_art_archive import provenance, sidecar  # noqa: E402


def build_report(staging_dir: Path) -> provenance.CompletenessReport:
    """Load staged sidecars and return a read-only completeness aggregate."""
    if not staging_dir.is_dir():
        raise FileNotFoundError(f"staging directory not found: {staging_dir}")
    sidecars = [sidecar.load(path) for path in _sidecar_paths(staging_dir)]
    return provenance.completeness_report(sidecars)


def write_report(
    staging_dir: Path,
    output_dir: Path,
    *,
    report_date: date | None = None,
) -> tuple[Path, Path, provenance.CompletenessReport]:
    """Write CSV and Markdown reports and return their paths and aggregate."""
    report = build_report(staging_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    day = report_date or date.today()
    stem = f"completeness_report_{day.isoformat()}"
    csv_path = output_dir / f"{stem}.csv"
    markdown_path = output_dir / f"{stem}.md"

    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        _write_csv(report, handle)
    markdown_path.write_text(
        _render_markdown(report, report_date=day),
        encoding="utf-8",
    )
    return csv_path, markdown_path, report


def _sidecar_paths(staging_dir: Path) -> list[Path]:
    paths = set(staging_dir.rglob("meta.json"))
    paths.update(staging_dir.glob("*.json"))
    return sorted(path for path in paths if path.is_file())


def _write_csv(report: provenance.CompletenessReport, handle: TextIO) -> None:
    header = ["field", "total_works"]
    for status in provenance.STATUS_ORDER:
        header.extend((f"{status}_count", f"{status}_pct"))
    writer = csv.DictWriter(handle, fieldnames=header)
    writer.writeheader()
    for field_row in report.fields:
        row: dict[str, str | int] = {
            "field": field_row.field,
            "total_works": field_row.total_works,
        }
        for status in provenance.STATUS_ORDER:
            row[f"{status}_count"] = field_row.count(status)
            row[f"{status}_pct"] = f"{field_row.percentage(status):.2f}"
        writer.writerow(row)


def _render_markdown(
    report: provenance.CompletenessReport,
    *,
    report_date: date,
) -> str:
    lines = [
        f"# Metadata Completeness Report — {report_date.isoformat()}",
        "",
        f"Scanned {report.total_works} sidecars across {len(report.fields)} fields.",
        "",
        "| Field | Not researched | Available | Not available | Unverified | Conflicting |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for row in report.fields:
        cells = [_markdown_cell(row.field)]
        cells.extend(
            f"{row.count(status)} ({row.percentage(status):.2f}%)"
            for status in provenance.STATUS_ORDER
        )
        lines.append(f"| {' | '.join(cells)} |")

    lines.extend(
        [
            "",
            "## Conflicting works",
            "",
            f"{len(report.conflicts)} conflicts are listed for optional operator review.",
            "",
        ]
    )
    if report.conflicts:
        lines.extend(
            [
                "| Work ID | Field | Kept value | Kept source | Losing value | "
                "Losing source | Provenance note |",
                "|---|---|---|---|---|---|---|",
            ]
        )
        for conflict in report.conflicts:
            values = (
                conflict.work_id,
                conflict.field,
                _display_value(conflict.kept_value),
                conflict.kept_source or "not recorded",
                _display_value(conflict.losing_value),
                conflict.losing_source or "not recorded",
                conflict.note or "",
            )
            lines.append(f"| {' | '.join(_markdown_cell(value) for value in values)} |")
    else:
        lines.append("No conflicting works were found.")
    lines.append("")
    return "\n".join(lines)


def _display_value(value: Any) -> str:
    if value is None:
        return "not recorded"
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _markdown_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def _env_path(name: str) -> Path | None:
    raw = os.environ.get(name)
    return Path(raw).expanduser() if raw else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--staging-dir",
        type=Path,
        default=_env_path("FAA_STAGING_DIR") or ROOT / "staging_sidecars",
        help="Sidecar corpus root (default: FAA_STAGING_DIR or ./staging_sidecars).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path.cwd(),
        help="Directory for the dated CSV and Markdown files (default: current directory).",
    )
    args = parser.parse_args(argv)

    csv_path, markdown_path, report = write_report(args.staging_dir, args.output_dir)
    print(
        f"completeness report: works={report.total_works} fields={len(report.fields)} "
        f"conflicts={len(report.conflicts)} csv={csv_path} markdown={markdown_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
