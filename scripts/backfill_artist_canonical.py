#!/usr/bin/env python3
"""Backfill ``artist.canonical`` identity for works that have an artist QID.

An artist QID is the bridge from the raw ``artist.name`` (a source string, kept
verbatim for provenance) to the resolved *identity* -- the canonical display name
and lifespan the UI uses to group spelling/relation variants of one artist. Many
works carry a resolved ``artist.wikidata_q`` but were never given that identity:
``artist.canonical`` is missing its ``display_name``.

This fills it using :func:`fine_art_archive.enrichment.wikidata_identity.fetch_identity`
(Wikidata label + P569/P570 lifespan), populating ``artist.canonical`` and, when
empty, ``artist.lifespan``. It only touches works whose canonical lacks a
``display_name``; an existing canonical display name is respected (a lifespan is
still added if missing). Fetches are cached per QID, so the cost scales with the
number of distinct artists, not works.

Dry-run by default; ``--apply`` writes, mirrors to Art/works, and logs. Idempotent.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "src"))

from _paths import default_works_dir  # noqa: E402
from _sidecar_io import script_env_path as _env_path  # noqa: E402
from _sidecar_io import sidecar_paths as _sidecar_paths  # noqa: E402
from _sidecar_io import write_existing_mirrors as _write_existing_mirrors  # noqa: E402

from fine_art_archive import sidecar  # noqa: E402
from fine_art_archive.enrichment.source_resolver import JsonClient  # noqa: E402
from fine_art_archive.enrichment.wikidata_identity import fetch_identity  # noqa: E402
from fine_art_archive.identity.artist_resolver import fold_name  # noqa: E402

DEFAULT_LIMIT = 1_000_000


@dataclass
class CanonicalStats:
    candidates: int  # works with a QID but no canonical display_name
    resolved: int  # works a display_name was fetched for
    updated_works: int  # sidecars written (0 in dry-run)
    mirrored: int
    distinct_artists: int  # unique QIDs fetched


def _artist_qid(meta: dict[str, Any]) -> str | None:
    artist = meta.get("artist")
    if isinstance(artist, dict):
        qid = artist.get("wikidata_q")
        return qid if isinstance(qid, str) and qid else None
    return None


def _needs_canonical(meta: dict[str, Any]) -> bool:
    artist = meta.get("artist")
    if not isinstance(artist, dict) or not _artist_qid(meta):
        return False
    canonical = artist.get("canonical")
    if not isinstance(canonical, dict):
        return True
    # identity is display_name + lifespan; fill either when missing
    return not (canonical.get("display_name") and canonical.get("lifespan"))


def _apply_canonical(
    meta: dict[str, Any], display_name: str | None, lifespan: str | None, *, now: str
) -> bool:
    """Fill missing canonical fields from the fetched identity. Returns True if changed.

    Never overwrites an existing ``display_name``/``lifespan``; only adds what is
    missing, so a re-run that finds nothing new writes nothing (idempotent).
    """
    artist = meta["artist"]
    qid = artist["wikidata_q"]
    canonical = artist.get("canonical")
    if not isinstance(canonical, dict):
        canonical = {}
    changed = False
    if canonical.get("wikidata_q") != qid:
        canonical["wikidata_q"] = qid
        changed = True
    if not canonical.get("display_name") and display_name:
        canonical["display_name"] = display_name
        changed = True
    if not canonical.get("lifespan") and lifespan:
        canonical["lifespan"] = lifespan
        changed = True
    if not canonical.get("family_key") and canonical.get("display_name"):
        canonical["family_key"] = fold_name(str(canonical["display_name"]))
        changed = True
    if not changed:
        return False
    canonical.setdefault("method", "wikidata")
    canonical["confidence"] = 0.9
    canonical["resolved_at"] = now
    artist["canonical"] = canonical
    if lifespan and not artist.get("lifespan"):
        artist["lifespan"] = lifespan
    return True


def _append_operation(
    log_path: Path, meta: dict[str, Any], qid: str, staging_path: Path, mirrors: list[Path]
) -> None:
    entry = {
        "ts": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "actor": "backfill_artist_canonical",
        "op": "artist_canonical_backfill",
        "work_id": meta["work_id"],
        "artist_qid": qid,
        "staging_path": str(staging_path),
        "mirror_paths": [str(path) for path in mirrors],
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
    now: str | None = None,
) -> tuple[CanonicalStats, Counter[str]]:
    if limit < 1:
        raise ValueError("limit must be at least 1")
    stamp = now or datetime.now(UTC).isoformat().replace("+00:00", "Z")
    candidates = resolved = updated = mirrored = 0
    reasons: Counter[str] = Counter()
    cache: dict[str, tuple[str | None, str | None]] = {}
    for path in _sidecar_paths(staging_dir):
        meta = sidecar.load(path)
        if not _needs_canonical(meta):
            continue
        candidates += 1
        qid = _artist_qid(meta)
        assert qid is not None  # guaranteed by _needs_canonical
        if qid not in cache:
            cache[qid] = fetch_identity(qid, client=client)
        display_name, lifespan = cache[qid]
        if not display_name and not lifespan:
            reasons["unresolved"] += 1
            if candidates >= limit:
                break
            continue
        if not _apply_canonical(meta, display_name, lifespan, now=stamp):
            reasons["no_change"] += 1  # nothing new to add (e.g. artist has no WD dates)
            if candidates >= limit:
                break
            continue
        sidecar.validate(meta)
        resolved += 1
        reasons["resolved"] += 1
        if apply:
            sidecar.write(path, meta)
            mirror_paths = _write_existing_mirrors(meta, art_works_root, exclude=path)
            updated += 1
            mirrored += len(mirror_paths)
            if operations_log is not None:
                _append_operation(operations_log, meta, qid, path, mirror_paths)
        if candidates >= limit:
            break
    return (
        CanonicalStats(candidates, resolved, updated, mirrored, len(cache)),
        reasons,
    )


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
        f"artist-canonical backfill ({mode}): candidates={stats.candidates} "
        f"resolved={stats.resolved} updated_works={stats.updated_works} "
        f"mirrored={stats.mirrored} distinct_artists={stats.distinct_artists}"
    )
    if reasons:
        print("outcomes:", dict(reasons.most_common()))
    if not args.apply and stats.resolved:
        print("(dry-run: no files written; re-run with --apply)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
