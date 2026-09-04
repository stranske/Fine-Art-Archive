#!/usr/bin/env python3
"""Emit a read-only "needs research" report for still-uncategorized works.

Stage 3 of the uncategorized-bucket cleanup. After the heuristic categoriser
(``backfill_categories.py``), the keyword waves, and the creator+title work-QID
resolver (``backfill_work_qids_by_creator.py``) have run, a residual floor
remains that no automated pass can categorise. This surfaces that floor as an
FYI list -- what is stuck and, more usefully, *what single thing would unblock
each work* -- so it can be triaged (or ignored) at a glance. It is deliberately
read-only and never blocks: no queue, no per-work approval.

Each uncategorised work is bucketed by its primary blocker (offline signals
only -- no network), most-actionable first:

- ``needs_artist_qid``  -- no creator QID, so the work-QID resolver can't even
  try; resolve the artist first (``backfill_artist_qids.py``).
- ``needs_title_fix``   -- the title is a photo-caption / filename / enumerated
  scan name, not the work's real title; normalise it first.
- ``needs_work_qid``    -- has a creator QID and a plausible title, but no work
  QID resolved: the work is likely absent from / divergently labelled on
  Wikidata. Needs a manual QID or is a genuine dead end.

Writes a dated CSV + Markdown to ``--output-dir`` (default: current directory).
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import sys
from collections import Counter
from datetime import date
from pathlib import Path
from typing import Any, TextIO

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "src"))

from _paths import default_works_dir  # noqa: E402

from fine_art_archive import sidecar  # noqa: E402
from fine_art_archive.enrichment.holder import _creator_qid  # noqa: E402

_UNCATEGORIZED = (None, "", "(uncategorized)")
_ENUMERATED = re.compile(r"^\s*\d+[.)]\s")  # "34. Dwight Eisenhower, June 1956"

BLOCKERS = ("needs_artist_qid", "needs_title_fix", "needs_work_qid")


def _artist_name(meta: dict[str, Any]) -> str:
    artist = meta.get("artist")
    return str(artist.get("name") or "").strip() if isinstance(artist, dict) else ""


def is_junk_title(title: str, artist_name: str = "") -> bool:
    """Heuristic: does the title look like a caption/filename rather than a work title?"""
    text = (title or "").strip()
    if not text:
        return True
    if _ENUMERATED.search(text):  # enumerated scan/caption
        return True
    if "_" in text:  # filename-derived ("Castillo_de_Zafra")
        return True
    # a title that is just the artist name carries no work information
    return bool(artist_name and text.casefold() == artist_name.casefold())


def classify_blocker(meta: dict[str, Any]) -> str:
    """Return the primary blocker for an uncategorized work (offline signals only)."""
    if not _creator_qid(meta):
        return "needs_artist_qid"
    if is_junk_title(str(meta.get("title") or ""), _artist_name(meta)):
        return "needs_title_fix"
    return "needs_work_qid"


def _sidecar_paths(staging_dir: Path) -> list[Path]:
    paths = set(staging_dir.rglob("meta.json"))
    paths.update(staging_dir.glob("*.json"))
    return sorted(path for path in paths if path.is_file())


def _has_work_qid(meta: dict[str, Any]) -> bool:
    stable = meta.get("stable_identifiers")
    return isinstance(stable, dict) and bool(stable.get("wikidata_q"))


def collect(staging_dir: Path) -> list[dict[str, Any]]:
    """Return one row per still-uncategorized work, with its blocker classification."""
    if not staging_dir.is_dir():
        raise FileNotFoundError(f"staging directory not found: {staging_dir}")
    rows: list[dict[str, Any]] = []
    for path in _sidecar_paths(staging_dir):
        meta = sidecar.load(path)
        if meta.get("category") not in _UNCATEGORIZED:
            continue
        rows.append(
            {
                "work_id": str(meta.get("work_id") or path.parent.name),
                "artist": _artist_name(meta),
                "artist_qid": _creator_qid(meta) or "",
                "title": str(meta.get("title") or ""),
                "medium": str(meta.get("medium") or ""),
                "year": str(meta.get("year") or ""),
                "has_work_qid": _has_work_qid(meta),
                "blocker": classify_blocker(meta),
            }
        )
    rows.sort(key=lambda r: (BLOCKERS.index(r["blocker"]), r["artist"], r["title"]))
    return rows


_COLUMNS = ("work_id", "blocker", "artist", "artist_qid", "title", "medium", "year")


def _write_csv(rows: list[dict[str, Any]], handle: TextIO) -> None:
    writer = csv.DictWriter(handle, fieldnames=_COLUMNS, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)


def _render_markdown(rows: list[dict[str, Any]], *, report_date: date) -> str:
    counts = Counter(r["blocker"] for r in rows)
    hints = {
        "needs_artist_qid": "resolve the artist first (backfill_artist_qids.py)",
        "needs_title_fix": "title is a caption/filename; normalise it",
        "needs_work_qid": "no Wikidata work match; manual QID or dead end",
    }
    lines = [
        f"# Needs-research report ({report_date.isoformat()})",
        "",
        f"{len(rows)} works remain uncategorized after all automated passes. "
        "This is an FYI triage list, not a work queue.",
        "",
        "| Blocker | Count | What unblocks it |",
        "|---|---:|---|",
    ]
    for blocker in BLOCKERS:
        lines.append(f"| {blocker} | {counts.get(blocker, 0)} | {hints[blocker]} |")
    lines += ["", "## Works", "", "| Blocker | Artist | Title | Year |", "|---|---|---|---|"]
    for row in rows:
        title = row["title"].replace("|", "\\|")[:70]
        artist = row["artist"].replace("|", "\\|")[:28]
        lines.append(f"| {row['blocker']} | {artist} | {title} | {row['year']} |")
    return "\n".join(lines) + "\n"


def write_report(
    staging_dir: Path, output_dir: Path, *, report_date: date | None = None
) -> tuple[Path, Path, list[dict[str, Any]]]:
    rows = collect(staging_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    day = report_date or date.today()
    stem = f"needs_research_{day.isoformat()}"
    csv_path = output_dir / f"{stem}.csv"
    markdown_path = output_dir / f"{stem}.md"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        _write_csv(rows, handle)
    markdown_path.write_text(_render_markdown(rows, report_date=day), encoding="utf-8")
    return csv_path, markdown_path, rows


def _env_path(name: str) -> Path | None:
    raw = os.environ.get(name)
    return Path(raw).expanduser() if raw else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--staging-dir",
        type=Path,
        default=default_works_dir(),
    )
    parser.add_argument("--output-dir", type=Path, default=Path.cwd())
    args = parser.parse_args(argv)

    csv_path, markdown_path, rows = write_report(args.staging_dir, args.output_dir)
    counts = Counter(r["blocker"] for r in rows)
    print(
        f"needs-research report: uncategorized={len(rows)} "
        + " ".join(f"{b}={counts.get(b, 0)}" for b in BLOCKERS)
    )
    print(f"csv={csv_path} markdown={markdown_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
