#!/usr/bin/env python3
"""Rebuild `manifest.csv`, the operator UI's only navigation index, from sidecars.

The Companion App never walks the works tree to browse: `store.list_works()`
reads manifest rows and nothing else, and `store.get_manifest_row()` is the
fallback `/works/{id}` uses when a sidecar is missing. A work absent from the
manifest is served and rendered perfectly well but cannot be reached, so it can
never be rated and never enters the curation loop.

Nothing wrote this file. Promotion creates `<works>/<work_id>/` with a master
and a `meta.json` and stops there, so the manifest could only ever drift
downward: by 18 works on 2026-08-05, and by 2026-09-01 by all 3499, the file
having never existed at all. `/healthz` reported that drift correctly and had
no producer to clear it. This script is the producer.

Usage:

    python3 scripts/build_manifest.py            # rebuild in place
    python3 scripts/build_manifest.py --check    # report staleness, write nothing
    python3 scripts/build_manifest.py --works-root DIR --out FILE

Run it after anything that adds, removes, or retitles a work -- see the
"Manifest" section of README.md for where that lives. A full rebuild over the
3499-work archive costs about 0.7 s, so there is no incremental append path to
keep in step with this one; the whole file is rewritten every time.

Exit codes: 0 current or written, 1 `--check` found it stale, 2 the works root
could not be read.
"""

from __future__ import annotations

import argparse
import csv
import io
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "src"))

from fine_art_archive.api import store  # noqa: E402

#: The manifest columns, each with a live consumer. `store.list_works()` splats
#: whole rows into its response, so every column here ships to the UI on every
#: browse request -- add one only when something reads it.
#:
#:   work_id            `store.get_manifest_row()`, and the key `list_works()`
#:                      joins ratings on. Always the DIRECTORY name: every path
#:                      the API builds comes from `store.sidecar_path()`, so a
#:                      sidecar whose `work_id` field disagrees with its own
#:                      directory is navigable only under the directory name.
#:   title              searched by `store._matches_query()`; the list and
#:                      gallery cells in `ui/index.html`.
#:   artist_name        searched by `store._matches_query()` and folded onto
#:                      canonical Q-IDs by `store.list_artists()`. The RAW
#:                      source spelling, not the canonical name: the resolver
#:                      runs at read time, and `list_artists()` counts distinct
#:                      raw spellings to show how many merged.
#:   artist_wikidata_q  the Q-ID chip in `ui/index.html`, and the placeholder in
#:                      `main._manifest_placeholder_work()`.
#:   year               the Year column, and the same placeholder.
#:   medium             `main._manifest_placeholder_work()`.
#:   n_variants         the Variants column in `ui/index.html`.
COLUMNS = (
    "work_id",
    "title",
    "artist_name",
    "artist_wikidata_q",
    "year",
    "medium",
    "n_variants",
)


@dataclass(frozen=True)
class Skip:
    """One work directory that could not be turned into a manifest row."""

    work_id: str
    reason: str


@dataclass(frozen=True)
class BuildResult:
    rows: list[dict[str, str]]
    skipped: list[Skip]


def _text(value: object) -> str:
    """Render a sidecar value as a CSV cell.

    `title`, `year`, `medium` and `artist.name` are all nullable in
    `schemas/meta.schema.json` -- `artist.name` deliberately so, as the
    transient state a debris-repair pass leaves behind. None becomes an empty
    cell rather than the string "None", which the UI would render as a work by
    an artist of that name.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    return str(value)


def _row(work_id: str, meta: dict[str, Any]) -> dict[str, str]:
    artist = meta.get("artist")
    artist_name = artist.get("name") if isinstance(artist, dict) else None
    files = meta.get("files")
    variants = files.get("variants") if isinstance(files, dict) else None
    return {
        "work_id": work_id,
        "title": _text(meta.get("title")),
        "artist_name": _text(artist_name),
        "artist_wikidata_q": store.artist_qid(meta) or "",
        "year": _text(meta.get("year")),
        "medium": _text(meta.get("medium")),
        "n_variants": str(len(variants) if isinstance(variants, list) else 0),
    }


def build(works_root: Path) -> BuildResult:
    """Read every `<works_root>/<work_id>/meta.json` into a manifest row.

    Rows are sorted by work_id, so a rerun over an unchanged tree reproduces the
    file byte for byte and a real change diffs to just that change.

    A sidecar that cannot be read is named and skipped, never raised: one
    corrupt file must not cost navigation to the other 3498. A missing or
    unreadable `works_root` is the opposite case and does raise, because
    "cannot measure the tree" is not "the tree is empty" -- treating it as
    empty would truncate a good manifest to nothing.

    Only `artist.name` being absent is tolerated within a row, because a work
    whose attribution is mid-repair still has to be reachable; it is exactly the
    work someone needs to open.
    """
    if not works_root.is_dir():
        raise NotADirectoryError(f"works root not found: {works_root}")

    rows: list[dict[str, str]] = []
    skipped: list[Skip] = []
    with os.scandir(works_root) as entries:
        names = sorted(entry.name for entry in entries if entry.is_dir())

    for work_id in names:
        try:
            store.validate_work_id(work_id)
        except ValueError as exc:
            skipped.append(Skip(work_id, f"unusable work_id: {exc}"))
            continue
        meta_path = works_root / work_id / "meta.json"
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            skipped.append(Skip(work_id, "no meta.json"))
            continue
        except OSError as exc:
            skipped.append(Skip(work_id, f"unreadable meta.json: {exc}"))
            continue
        except ValueError as exc:
            skipped.append(Skip(work_id, f"invalid JSON in meta.json: {exc}"))
            continue
        if not isinstance(meta, dict):
            skipped.append(Skip(work_id, "meta.json is not a JSON object"))
            continue
        rows.append(_row(work_id, meta))

    return BuildResult(rows=rows, skipped=skipped)


def _write_rows(handle: TextIO, rows: list[dict[str, str]]) -> None:
    writer = csv.DictWriter(handle, fieldnames=list(COLUMNS), lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)


def render(rows: list[dict[str, str]]) -> str:
    """The exact manifest text for `rows`, so `--check` compares like with like."""
    buffer = io.StringIO()
    _write_rows(buffer, rows)
    return buffer.getvalue()


def write_manifest(rows: list[dict[str, str]], out_path: Path) -> None:
    """Write the manifest atomically.

    A half-written manifest is the same outage as a missing one -- the UI would
    browse whatever prefix survived -- so the file is built whole and moved into
    place, never truncated where the API can read it.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = out_path.with_name(f"{out_path.name}.tmp{os.getpid()}")
    try:
        tmp_path.write_text(render(rows), encoding="utf-8", newline="")
        os.replace(tmp_path, out_path)
    finally:
        tmp_path.unlink(missing_ok=True)


def _previous_row_count(out_path: Path) -> int | None:
    """Rows in the manifest on disk, or None when there is no manifest.

    None and 0 are different facts and are reported differently: "there was no
    index" against "the index was empty".
    """
    try:
        with open(out_path, encoding="utf-8", newline="") as handle:
            return sum(1 for _ in csv.DictReader(handle))
    except (OSError, ValueError):
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--works-root",
        type=Path,
        default=store.WORKS,
        help="sidecar tree to read (default: the API's, %(default)s)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=store.MANIFEST_CSV,
        help="manifest to write (default: the API's, %(default)s)",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="report whether the manifest is current and exit 1 if not; write nothing",
    )
    args = parser.parse_args(argv)

    try:
        result = build(args.works_root)
    except NotADirectoryError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    for skip in result.skipped:
        print(f"skipped {skip.work_id}: {skip.reason}", file=sys.stderr)

    # Say what was skipped even when nothing was, so a clean run is legibly
    # clean rather than merely quiet.
    tally = f"{len(result.rows)} works, {len(result.skipped)} skipped"

    if args.check:
        try:
            current = args.out.read_text(encoding="utf-8")
        except OSError:
            print(f"stale: {args.out} does not exist ({tally} on disk)")
            return 1
        if current == render(result.rows):
            print(f"current: {args.out} matches the works tree ({tally})")
            return 0
        print(f"stale: {args.out} does not match the works tree ({tally})")
        return 1

    previous = _previous_row_count(args.out)
    write_manifest(result.rows, args.out)
    was = "new" if previous is None else f"was {previous}"
    print(f"wrote {args.out}: {tally} ({was})")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
