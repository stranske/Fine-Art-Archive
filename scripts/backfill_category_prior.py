#!/usr/bin/env python3
"""Backfill ``category`` for uncategorized works from a creator-occupation prior.

The residual uncategorized floor is works with a real artist + title but no work
QID and no usable medium -- neither P31 nor the medium heuristics can fire, and
the title diverges too much from Wikidata for a safe work-QID match. This fills
those using :mod:`fine_art_archive.enrichment.creator_category_prior`: when the
artist's Wikidata occupations resolve to exactly one art category, the work is
assigned that category with provenance status ``unverified`` (a hedged prior,
not per-work verification). Multi-medium artists (painter *and* printmaker *and*
draughtsman) are abstained on.

Only works that are uncategorized and have a creator QID are considered; the
category is written ``unverified`` so it is honestly distinguished from the
``available`` categories set from P31 / medium evidence.

Dry-run by default; ``--apply`` writes, records ``field_provenance`` for
``category`` (status ``unverified``), mirrors to Art/works, and logs.
"""

from __future__ import annotations

import argparse
import json
import os
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

from fine_art_archive import provenance, sidecar  # noqa: E402
from fine_art_archive.enrichment.creator_category_prior import (  # noqa: E402
    fetch_occupations,
    infer_prior,
)
from fine_art_archive.enrichment.holder import _creator_qid  # noqa: E402
from fine_art_archive.enrichment.source_resolver import JsonClient  # noqa: E402

DEFAULT_LIMIT = 100_000
_UNCATEGORIZED = (None, "", "(uncategorized)")


@dataclass
class PriorBackfillStats:
    attempted: int  # uncategorized works with a creator QID
    resolved: int  # works a single-category prior fired for
    updated_works: int  # sidecars written (0 in dry-run)
    mirrored: int  # canonical mirrors written


def _sidecar_paths(staging_dir: Path) -> list[Path]:
    paths = set(staging_dir.rglob("meta.json"))
    paths.update(staging_dir.glob("*.json"))
    return sorted(path for path in paths if path.is_file())


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
    category: str,
    creator_qid: str,
    note: str,
    staging_path: Path,
    mirror_paths: list[Path],
) -> None:
    entry = {
        "ts": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "actor": "backfill_category_prior",
        "op": "category_prior_backfill",
        "work_id": meta["work_id"],
        "category": category,
        "creator_qid": creator_qid,
        "status": "unverified",
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
) -> tuple[PriorBackfillStats, Counter[str]]:
    if limit < 1:
        raise ValueError("limit must be at least 1")
    attempted = resolved = updated = mirrored = 0
    by_category: Counter[str] = Counter()
    occupation_cache: dict[str, list[str]] = {}
    for path in _sidecar_paths(staging_dir):
        meta = sidecar.load(path)
        if meta.get("category") not in _UNCATEGORIZED:
            continue
        creator_qid = _creator_qid(meta)
        if not creator_qid:
            by_category["(no-creator)"] += 1
            continue
        attempted += 1
        if creator_qid not in occupation_cache:
            occupation_cache[creator_qid] = fetch_occupations(creator_qid, client=client)
        result = infer_prior(meta, occupation_cache[creator_qid])
        if result is None:
            by_category["(abstain)"] += 1
            if attempted >= limit:
                break
            continue
        category, note = result
        meta["category"] = category
        provenance.set(
            meta,
            "category",
            "unverified",
            "wikidata",
            source_ref=f"https://www.wikidata.org/wiki/{creator_qid}",
            note=note,
        )
        sidecar.validate(meta)
        resolved += 1
        by_category[category] += 1
        if apply:
            sidecar.write(path, meta)
            mirror_paths = _write_existing_mirrors(meta, art_works_root, exclude=path)
            updated += 1
            mirrored += len(mirror_paths)
            if operations_log is not None:
                _append_operation(
                    operations_log, meta, category, creator_qid, note, path, mirror_paths
                )
        if attempted >= limit:
            break
    return PriorBackfillStats(attempted, resolved, updated, mirrored), by_category


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
    args = parser.parse_args(argv)

    stats, by_category = backfill(
        args.staging_dir,
        client=JsonClient(timeout=args.timeout),
        art_works_root=args.art_works_root,
        operations_log=args.operations_log,
        limit=args.limit,
        apply=args.apply,
    )
    mode = "apply" if args.apply else "dry-run"
    print(
        f"category-prior backfill ({mode}): "
        f"attempted={stats.attempted} resolved={stats.resolved} "
        f"updated_works={stats.updated_works} mirrored={stats.mirrored}"
    )
    if by_category:
        print("by category:", dict(by_category.most_common()))
    if not args.apply and stats.resolved:
        print("(dry-run: no files written; categories would be status=unverified)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
