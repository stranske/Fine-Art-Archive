#!/usr/bin/env python3
"""Adopt a work's Wikidata creator (P170) as the artist for QID-less works.

Fixes works that carry a resolved work QID but a placeholder/junk ``artist.name``
(a mis-parsed caption token -- a date "1602", a place "_El_Jem", a period label
"British School, 16th century") by reading the real creator off the work entity's
P170. See :mod:`fine_art_archive.enrichment.artist_from_work` for the guards:
only touches works with no valid ``artist.wikidata_q``; only adopts a single,
concrete P170 creator (Wikidata ``somevalue`` anonymity and mis-resolved work
QIDs without P170 are declined, not guessed); skips works already naming that
creator. The junk ``artist.name`` is replaced (never a real attribution) with the
original preserved in the provenance note -- lossless.

Dry-run by default; ``--apply`` writes, records ``field_provenance`` for
``artist_qid``, mirrors to Art/works, and appends operations.log. Idempotent.
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
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "src"))

from _paths import default_works_dir  # noqa: E402

from fine_art_archive import provenance, sidecar  # noqa: E402
from fine_art_archive.enrichment.artist_from_work import (  # noqa: E402
    CreatorAdoption,
    resolve_adoption,
)
from fine_art_archive.enrichment.source_resolver import JsonClient  # noqa: E402

DEFAULT_LIMIT = 100_000


@dataclass
class ArtistAdoptStats:
    attempted: int  # works considered (no valid artist QID + a work QID)
    resolved: int  # artists written (0 in dry-run)
    mirrored: int
    matches: list[dict[str, Any]] = field(default_factory=list)


def _sidecar_paths(staging_dir: Path) -> list[Path]:
    paths = set(staging_dir.rglob("meta.json"))
    paths.update(staging_dir.glob("*.json"))
    return sorted(path for path in paths if path.is_file())


def _needs_artist(meta: dict[str, Any]) -> bool:
    artist = meta.get("artist")
    qid = artist.get("wikidata_q") if isinstance(artist, dict) else None
    has_qid = isinstance(qid, str) and bool(qid)
    stable = meta.get("stable_identifiers")
    work_qid = stable.get("wikidata_q") if isinstance(stable, dict) else None
    return not has_qid and isinstance(work_qid, str) and bool(work_qid)


def _apply(meta: dict[str, Any], adoption: CreatorAdoption) -> str:
    artist = meta.setdefault("artist", {})
    old_name = artist.get("name")
    artist["name"] = adoption.display_name
    artist["wikidata_q"] = adoption.creator_qid
    if not artist.get("lifespan") and adoption.lifespan:
        artist["lifespan"] = adoption.lifespan
    artist.setdefault("relation", "self")
    canonical = artist.setdefault("canonical", {})
    canonical["wikidata_q"] = adoption.creator_qid
    canonical["display_name"] = adoption.display_name
    if adoption.lifespan:
        canonical["lifespan"] = adoption.lifespan
    canonical["method"] = "wikidata-p170"
    note = f"Artist adopted from work P170 -> {adoption.creator_qid}" + (
        f"; replaced placeholder name {old_name!r}" if old_name else ""
    )
    provenance.set(
        meta,
        "artist_qid",
        "available",
        "wikidata",
        source_ref=f"https://www.wikidata.org/wiki/{adoption.creator_qid}",
        note=note,
    )
    return note


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
    log_path: Path,
    meta: dict[str, Any],
    adoption: CreatorAdoption,
    note: str,
    staging_path: Path,
    mirror_paths: list[Path],
) -> None:
    entry = {
        "ts": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "actor": "backfill_artist_from_work_p170",
        "op": "artist_from_work_p170",
        "work_id": meta["work_id"],
        "creator_qid": adoption.creator_qid,
        "display_name": adoption.display_name,
        "note": note,
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
) -> tuple[ArtistAdoptStats, Counter[str]]:
    if limit < 1:
        raise ValueError("limit must be at least 1")
    stats = ArtistAdoptStats(attempted=0, resolved=0, mirrored=0)
    reasons: Counter[str] = Counter()
    for path in _sidecar_paths(staging_dir):
        meta = sidecar.load(path)
        if not _needs_artist(meta):
            continue
        stats.attempted += 1
        adoption, reason = resolve_adoption(meta, client=client)
        reasons[reason] += 1
        if adoption is None:
            if stats.attempted >= limit:
                break
            continue
        stats.matches.append(
            {
                "work_id": meta["work_id"],
                "creator_qid": adoption.creator_qid,
                "display_name": adoption.display_name,
                "old_name": (meta.get("artist") or {}).get("name"),
            }
        )
        if apply:
            note = _apply(meta, adoption)
            sidecar.validate(meta)
            sidecar.write(path, meta)
            mirror_paths = _write_existing_mirrors(meta, art_works_root, exclude=path)
            stats.resolved += 1
            stats.mirrored += len(mirror_paths)
            if operations_log is not None:
                _append_operation(operations_log, meta, adoption, note, path, mirror_paths)
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
        default=default_works_dir(),
    )
    parser.add_argument("--art-works-root", type=Path, default=_env_path("FAA_ART_WORKS_ROOT"))
    parser.add_argument("--operations-log", type=Path, default=_env_path("FAA_OPERATIONS_LOG"))
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--show-matches", action="store_true")
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
        f"artist-from-work-P170 ({mode}): attempted={stats.attempted} "
        f"matched={len(stats.matches)} written={stats.resolved} mirrored={stats.mirrored}"
    )
    if reasons:
        print("outcomes:", dict(reasons.most_common()))
    if args.show_matches or not args.apply:
        for m in stats.matches:
            print(
                f"  {m['old_name']!r} -> {m['display_name']!r} ({m['creator_qid']})  [{m['work_id']}]"
            )
    if not args.apply and stats.matches:
        print("(dry-run: no files written; re-run with --apply)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
