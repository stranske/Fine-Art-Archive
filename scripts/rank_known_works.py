#!/usr/bin/env python3
"""Rank an artist's known works by display-worthiness (collection priority).

Answers "for this artist, which works should be collected first?" -- the ones
people typically want to *display* -- so a prolific oeuvre is prioritised rather
than swept in wholesale. Fetches the artist's works from the configured sources
(:mod:`fine_art_archive.known_works.fetchers`), merges them, and orders them by
:func:`display_score` (sitelinks demand proxy + image + public-collection +
multi-source corroboration; studies/sketches demoted). Scored per work, never
per artist, so there is no volume bias and no artificial per-artist cap.

Read-only: prints a ranked table (or ``--csv``); writes nothing. Sources that
are offline/rate-limited are skipped silently, so it degrades to whatever is
reachable.

    rank_known_works.py --artist-qid Q5582 --top 20
    rank_known_works.py --artist-qid Q5582 --artist-name "Vincent van Gogh" --csv
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "src"))

from fine_art_archive.known_works.fetchers import (  # noqa: E402
    KnownWork,
    _norm_title,
    display_score,
    fetch_met,
    fetch_wikidata_sparql,
    fetch_wikipedia_list,
    merge_works,
    rank_by_display_worthiness,
)


def gather(artist_qid: str | None, artist_name: str | None) -> list[KnownWork]:
    sources: list[list[KnownWork]] = []
    if artist_qid:
        sources.append(fetch_wikidata_sparql(artist_qid))
    if artist_name:
        sources.append(fetch_wikipedia_list(artist_name))
        sources.append(fetch_met(artist_name))
    return merge_works(*sources) if sources else []


def load_held(staging_dir: Path) -> tuple[set[str], set[str]]:
    """Return (held work QIDs, held folded titles) from the archive's sidecars.

    Used to compute a want-list: which of an artist's works are NOT yet held.
    Matches on the work QID first (exact), folded title as a fallback.
    """
    qids: set[str] = set()
    titles: set[str] = set()
    if not staging_dir.is_dir():
        return qids, titles
    for path in staging_dir.rglob("meta.json"):
        try:
            meta = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        stable = meta.get("stable_identifiers")
        if isinstance(stable, dict) and isinstance(stable.get("wikidata_q"), str):
            qids.add(stable["wikidata_q"])
        if isinstance(meta.get("title"), str):
            folded = _norm_title(meta["title"])
            if folded:
                titles.add(folded)
    return qids, titles


def is_held(work: KnownWork, held_qids: set[str], held_titles: set[str]) -> bool:
    wq = work.source_ids.get("wikidata")
    if wq and wq in held_qids:
        return True
    return _norm_title(work.title) in held_titles


def _print_table(works: list[KnownWork]) -> None:
    print(f"{'score':>5}  {'year':>4}  {'img':>3}  {'sl':>3}  title")
    for w in works:
        img = "yes" if w.image_url else "-"
        print(
            f"{display_score(w):>5.2f}  {str(w.year or ''):>4}  {img:>3}  "
            f"{w.sitelinks:>3}  {w.title}"
        )


def _write_csv(works: list[KnownWork]) -> None:
    writer = csv.writer(sys.stdout)
    writer.writerow(
        ["display_score", "title", "year", "has_image", "sitelinks", "holder", "sources"]
    )
    for w in works:
        writer.writerow(
            [
                display_score(w),
                w.title,
                w.year or "",
                bool(w.image_url),
                w.sitelinks,
                w.holder or "",
                "|".join(w.sources),
            ]
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artist-qid", help="Wikidata QID (enables the Wikidata source)")
    parser.add_argument("--artist-name", help="artist name (enables Wikipedia-list + Met sources)")
    parser.add_argument("--top", type=int, default=0, help="show only the top N (0 = all)")
    parser.add_argument("--csv", action="store_true", help="emit CSV instead of a table")
    parser.add_argument(
        "--missing-only",
        action="store_true",
        help="acquisition want-list: drop works already in the archive",
    )
    parser.add_argument(
        "--staging-dir",
        type=Path,
        default=(Path(os.environ["FAA_STAGING_DIR"]).expanduser() if os.environ.get("FAA_STAGING_DIR") else None),
        help="archive sidecar root for --missing-only (default: $FAA_STAGING_DIR)",
    )
    args = parser.parse_args(argv)

    if not args.artist_qid and not args.artist_name:
        parser.error("provide --artist-qid and/or --artist-name")

    works = gather(args.artist_qid, args.artist_name)
    if args.missing_only:
        if args.staging_dir is None:
            parser.error("--missing-only needs --staging-dir or $FAA_STAGING_DIR")
        held_qids, held_titles = load_held(args.staging_dir)
        works = [w for w in works if not is_held(w, held_qids, held_titles)]

    ranked = rank_by_display_worthiness(works)
    if args.top > 0:
        ranked = ranked[: args.top]

    if args.csv:
        _write_csv(ranked)
    else:
        _print_table(ranked)
        print(f"\n{len(ranked)} works (most display-worthy first)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
