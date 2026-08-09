#!/usr/bin/env python3
"""Repair title/artist swaps in works that have no work QID.

Extends the QID-based un-swap (:mod:`misresolved_work_qid`) to the works it
cannot see -- those with no work QID at all -- where the ``title`` holds the
artist's name and ``artist.name`` holds the real title (e.g. title
"George Wesley Bellows", artist "Love of Winter"). See
:mod:`fine_art_archive.enrichment.title_artist_swap` for the detection and guards
(the occupation-gated resolver on the title tells a painter-in-the-title-slot
from a sitter/real-title, and a subject-portrait guard avoids flipping a
"portrait of <artist>").

On a swap it sets ``artist`` (name + QID + canonical) from the resolved artist,
moves the real title into ``title``, and records provenance for ``title`` and
``artist_qid`` (the originals are preserved in the notes -- lossless). Afterwards
the by-creator pass can resolve the real work QID, since the work now has a
creator + a real title.

Dry-run by default; ``--apply`` writes, mirrors to Art/works, appends
operations.log. Idempotent (a resolved artist is never re-touched).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "src"))

from fine_art_archive import provenance, sidecar  # noqa: E402
from fine_art_archive.enrichment.source_resolver import JsonClient  # noqa: E402
from fine_art_archive.enrichment.title_artist_swap import Swap, detect_swap  # noqa: E402

DEFAULT_LIMIT = 100_000


@dataclass
class SwapStats:
    attempted: int  # works with no valid artist QID considered
    swapped: int
    mirrored: int
    matches: list[dict[str, Any]] = field(default_factory=list)


def _sidecar_paths(staging_dir: Path) -> list[Path]:
    paths = set(staging_dir.rglob("meta.json"))
    paths.update(staging_dir.glob("*.json"))
    return sorted(path for path in paths if path.is_file())


def _needs_artist(meta: dict[str, Any]) -> bool:
    artist = meta.get("artist")
    if not isinstance(artist, dict):
        return False
    if isinstance(artist.get("wikidata_q"), str) and artist["wikidata_q"]:
        return False
    canonical = artist.get("canonical")
    return not (isinstance(canonical, dict) and canonical.get("wikidata_q"))


def _apply(meta: dict[str, Any], swap: Swap) -> None:
    meta["title"] = swap.new_title
    artist = meta.setdefault("artist", {})
    artist["name"] = swap.artist_name
    artist["wikidata_q"] = swap.artist_qid
    if swap.lifespan and not artist.get("lifespan"):
        artist["lifespan"] = swap.lifespan
    artist.setdefault("relation", "self")
    canonical = artist.setdefault("canonical", {})
    canonical["wikidata_q"] = swap.artist_qid
    canonical["display_name"] = swap.artist_name
    if swap.lifespan:
        canonical["lifespan"] = swap.lifespan
    canonical["method"] = "title-artist-unswap"
    provenance.set(meta, "title", "available", "wikidata", note=swap.note)
    provenance.set(
        meta,
        "artist_qid",
        "available",
        "wikidata",
        source_ref=f"https://www.wikidata.org/wiki/{swap.artist_qid}",
        note=swap.note,
    )


def _write_existing_mirrors(
    meta: dict[str, Any], art_works_root: Path | None, *, exclude: Path
) -> list[Path]:
    if art_works_root is None:
        return []
    work_id = str(meta["work_id"])
    candidates = {
        art_works_root / "works" / work_id / "meta.json",
        art_works_root / work_id / "meta.json",
    }
    written: list[Path] = []
    for candidate in sorted(candidates):
        if candidate.is_file() and candidate.resolve() != exclude.resolve():
            sidecar.write(candidate, meta)
            written.append(candidate)
    return written


def _append_operation(
    log_path: Path, meta: dict[str, Any], swap: Swap, staging_path: Path, mirror_paths: list[Path]
) -> None:
    entry = {
        "ts": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "actor": "fix_title_artist_swap",
        "op": "title_artist_unswap",
        "work_id": meta["work_id"],
        "artist_qid": swap.artist_qid,
        "artist_name": swap.artist_name,
        "new_title": swap.new_title,
        "old_title": swap.old_title,
        "staging_path": str(staging_path),
        "mirror_paths": [str(path) for path in mirror_paths],
    }
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")


def backfill(
    staging_dir: Path,
    *,
    client: Any,
    art_works_root: Path | None = None,
    operations_log: Path | None = None,
    limit: int = DEFAULT_LIMIT,
    apply: bool = False,
) -> tuple[SwapStats, Counter[str]]:
    if limit < 1:
        raise ValueError("limit must be at least 1")
    stats = SwapStats(attempted=0, swapped=0, mirrored=0)
    reasons: Counter[str] = Counter()
    for path in _sidecar_paths(staging_dir):
        meta = sidecar.load(path)
        if not _needs_artist(meta):
            continue
        stats.attempted += 1
        swap = detect_swap(meta, client=client)
        if swap is None:
            reasons["no-swap"] += 1
            if stats.attempted >= limit:
                break
            continue
        reasons["swap"] += 1
        stats.matches.append(
            {
                "work_id": meta["work_id"],
                "artist": swap.artist_name,
                "qid": swap.artist_qid,
                "old_title": swap.old_title,
                "new_title": swap.new_title,
            }
        )
        if apply:
            _apply(meta, swap)
            sidecar.validate(meta)
            sidecar.write(path, meta)
            mirror_paths = _write_existing_mirrors(meta, art_works_root, exclude=path)
            stats.swapped += 1
            stats.mirrored += len(mirror_paths)
            if operations_log is not None:
                _append_operation(operations_log, meta, swap, path, mirror_paths)
        if stats.attempted >= limit:
            break
    return stats, reasons


def _env_path(name: str) -> Path | None:
    raw = os.environ.get(name)
    return Path(raw).expanduser() if raw else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write changes (default: dry-run)")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument(
        "--staging-dir",
        type=Path,
        default=_env_path("FAA_STAGING_DIR") or ROOT / "staging_sidecars",
    )
    parser.add_argument("--art-works-root", type=Path, default=_env_path("FAA_ART_WORKS_ROOT"))
    parser.add_argument("--operations-log", type=Path, default=_env_path("FAA_OPERATIONS_LOG"))
    parser.add_argument("--timeout", type=float, default=15.0)
    args = parser.parse_args(argv)

    stats, reasons = backfill(
        args.staging_dir,
        client=JsonClient(timeout=args.timeout),
        art_works_root=args.art_works_root,
        operations_log=args.operations_log,
        limit=args.limit,
        apply=args.apply,
    )
    mode = "apply" if args.apply else "dry-run"
    print(
        f"title-artist-unswap ({mode}): attempted={stats.attempted} "
        f"swapped={len(stats.matches)} written={stats.swapped} mirrored={stats.mirrored}"
    )
    if reasons:
        print("outcomes:", dict(reasons.most_common()))
    for m in stats.matches:
        print(
            f"  {m['old_title']!r} -> artist {m['artist']!r} ({m['qid']}); title -> {m['new_title']!r}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
