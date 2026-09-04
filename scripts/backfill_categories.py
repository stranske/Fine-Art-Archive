#!/usr/bin/env python3
"""Backfill the top-level ``category`` for works stuck in ``(uncategorized)``.

The uncategorized bucket has the worst field completeness in the archive and
drags every average down. This pass infers a category from the most reliable
evidence available for each work, via
:mod:`fine_art_archive.enrichment.category_infer` (medium technique keywords ->
Wikidata P31 allowlist -> paint/draw medium -> title hints), and leaves a work
uncategorized when no rule fires.

Only touches works whose ``category`` is missing; existing categories are left
alone. Every candidate is schema-validated before it is written, so a value
outside the ``category`` enum fails loudly instead of corrupting a sidecar.

Dry-run by default (reports what *would* change); ``--apply`` writes. On write it
records ``field_provenance`` for ``category`` (status ``available`` + source +
note), mirrors to the canonical Art/works tree, and appends to operations.log.
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

from fine_art_archive import provenance, sidecar  # noqa: E402
from fine_art_archive.enrichment.category_infer import (  # noqa: E402
    CategoryInference,
    fetch_p31_qids,
    infer_category,
    infer_from_medium_technique,
)
from fine_art_archive.enrichment.source_resolver import JsonClient  # noqa: E402

DEFAULT_LIMIT = 100_000
_UNCATEGORIZED = (None, "", "(uncategorized)")


@dataclass
class CategoryBackfillStats:
    attempted: int  # uncategorized works considered
    resolved: int  # works a rule fired on
    updated_works: int  # sidecars written (0 in dry-run)
    mirrored: int  # canonical mirrors written


def _is_uncategorized(meta: dict[str, Any]) -> bool:
    return meta.get("category") in _UNCATEGORIZED


def _work_qid(meta: dict[str, Any]) -> str | None:
    stable = meta.get("stable_identifiers")
    if isinstance(stable, dict):
        qid = stable.get("wikidata_q")
        return qid if isinstance(qid, str) and qid else None
    return None


def _infer(meta: dict[str, Any], *, client: Any) -> CategoryInference | None:
    """Infer a category, fetching P31 only when a cheaper rule has not fired."""
    if infer_from_medium_technique(meta.get("medium")) is not None:
        p31: list[str] | None = None  # technique wins; skip the network call
    else:
        qid = _work_qid(meta)
        p31 = fetch_p31_qids(qid, client=client) if qid else None
    return infer_category(meta, p31_qids=p31)


def _apply_inference(meta: dict[str, Any], inference: CategoryInference) -> None:
    meta["category"] = inference.category
    source_ref = None
    if inference.source == "wikidata":
        qid = _work_qid(meta)
        source_ref = f"https://www.wikidata.org/wiki/{qid}" if qid else None
    provenance.set(
        meta,
        "category",
        "available",
        inference.source,
        source_ref=source_ref,
        note=inference.note,
    )


def _append_operation(
    log_path: Path,
    meta: dict[str, Any],
    inference: CategoryInference,
    staging_path: Path,
    mirror_paths: list[Path],
) -> None:
    entry = {
        "ts": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "actor": "backfill_categories",
        "op": "category_backfill",
        "work_id": meta["work_id"],
        "category": inference.category,
        "source": inference.source,
        "note": inference.note,
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
) -> tuple[CategoryBackfillStats, Counter[str]]:
    if limit < 1:
        raise ValueError("limit must be at least 1")
    attempted = resolved = updated = mirrored = 0
    by_category: Counter[str] = Counter()
    for path in _sidecar_paths(staging_dir):
        meta = sidecar.load(path)
        if not _is_uncategorized(meta):
            continue
        attempted += 1
        inference = _infer(meta, client=client)
        if inference is None:
            by_category["(unresolved)"] += 1
            if attempted >= limit:
                break
            continue
        _apply_inference(meta, inference)
        sidecar.validate(meta)  # reject out-of-enum values in dry-run and apply
        resolved += 1
        by_category[inference.category] += 1
        if apply:
            sidecar.write(path, meta)
            mirror_paths = _write_existing_mirrors(meta, art_works_root, exclude=path)
            updated += 1
            mirrored += len(mirror_paths)
            if operations_log is not None:
                _append_operation(operations_log, meta, inference, path, mirror_paths)
        if attempted >= limit:
            break
    return CategoryBackfillStats(attempted, resolved, updated, mirrored), by_category


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
        f"category backfill ({mode}): "
        f"attempted={stats.attempted} resolved={stats.resolved} "
        f"updated_works={stats.updated_works} mirrored={stats.mirrored}"
    )
    if by_category:
        print("by category:", dict(by_category.most_common()))
    if not args.apply and stats.resolved:
        print("(dry-run: no files written; re-run with --apply)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
