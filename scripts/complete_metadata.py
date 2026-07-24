#!/usr/bin/env python3
"""Complete unresolved work metadata from tiered authoritative sources."""

from __future__ import annotations

import argparse
import json
import os
import sys
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "src"))

from fine_art_archive import provenance, sidecar  # noqa: E402
from fine_art_archive.enrichment.source_resolver import (  # noqa: E402
    Resolution,
    SourceResolver,
    apply_resolution,
)

DEFAULT_LIMIT = 100
FIELD_ORDER = ("year", "medium", "category", "dimensions_original", "artist_qid")


@dataclass(frozen=True)
class CompletionStats:
    """Counts from one bounded completion pass."""

    attempted_works: int
    attempted_fields: int
    updated_works: int
    updated_fields: int
    mirrored: int


def complete_sidecars(
    staging_dir: Path,
    *,
    art_works_root: Path | None = None,
    operations_log: Path | None = None,
    limit: int = DEFAULT_LIMIT,
    resolver: SourceResolver | None = None,
) -> CompletionStats:
    """Complete at most ``limit`` eligible works and mirror existing sidecars."""
    if limit < 1:
        raise ValueError("limit must be at least 1")

    active_resolver = resolver or SourceResolver()
    attempted_works = attempted_fields = updated_works = updated_fields = mirrored = 0
    for path in _sidecar_paths(staging_dir):
        meta = sidecar.load(path)
        fields = _eligible_fields(meta)
        if not fields:
            continue
        attempted_works += 1
        before = deepcopy(meta)
        outcomes: dict[str, Resolution] = {}
        for field in fields:
            attempted_fields += 1
            resolution = active_resolver.research(meta, field)
            if apply_resolution(meta, field, resolution):
                updated_fields += 1
                outcomes[field] = resolution

        if meta != before:
            sidecar.validate(meta)
            sidecar.write(path, meta)
            mirror_paths = _write_existing_mirrors(meta, art_works_root, exclude=path)
            updated_works += 1
            mirrored += len(mirror_paths)
            if operations_log is not None:
                _append_operation(operations_log, meta, path, mirror_paths, outcomes)
        if attempted_works >= limit:
            break

    return CompletionStats(
        attempted_works,
        attempted_fields,
        updated_works,
        updated_fields,
        mirrored,
    )


def _eligible_fields(meta: dict[str, Any]) -> list[str]:
    fields: list[str] = []
    for field in FIELD_ORDER:
        entry = provenance.get(meta, field)
        status = entry.get("status") if entry is not None else "not_researched"
        if status in {"not_researched", "unverified"}:
            fields.append(field)
    return fields


def _sidecar_paths(staging_dir: Path) -> list[Path]:
    paths = set(staging_dir.rglob("meta.json"))
    paths.update(staging_dir.glob("*.json"))
    return sorted(path for path in paths if path.is_file())


def _write_existing_mirrors(
    meta: dict[str, Any],
    art_works_root: Path | None,
    *,
    exclude: Path,
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
    staging_path: Path,
    mirror_paths: list[Path],
    outcomes: dict[str, Resolution],
) -> None:
    entry = {
        "ts": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "actor": "complete_metadata",
        "op": "metadata_completion",
        "work_id": meta["work_id"],
        "fields": {
            field: {
                "status": resolution.status,
                "source": resolution.source_id,
            }
            for field, resolution in sorted(outcomes.items())
        },
        "staging_path": str(staging_path),
        "mirror_paths": [str(path) for path in mirror_paths],
    }
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")


def _env_path(name: str) -> Path | None:
    raw = os.environ.get(name)
    return Path(raw).expanduser() if raw else None


def _default_limit() -> int:
    raw = os.environ.get("FAA_METADATA_LIMIT")
    return int(raw) if raw else DEFAULT_LIMIT


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--limit",
        type=int,
        default=_default_limit(),
        help=f"Maximum eligible works to attempt (default: {DEFAULT_LIMIT}).",
    )
    parser.add_argument(
        "--staging-dir",
        type=Path,
        default=_env_path("FAA_STAGING_DIR") or ROOT / "staging_sidecars",
    )
    parser.add_argument(
        "--art-works-root",
        type=Path,
        default=_env_path("FAA_ART_WORKS_ROOT"),
    )
    parser.add_argument(
        "--operations-log",
        type=Path,
        default=_env_path("FAA_OPERATIONS_LOG"),
    )
    args = parser.parse_args(argv)

    stats = complete_sidecars(
        args.staging_dir,
        art_works_root=args.art_works_root,
        operations_log=args.operations_log or args.staging_dir.parent / "operations.log",
        limit=args.limit,
    )
    print(
        "metadata completion: "
        f"attempted_works={stats.attempted_works} "
        f"attempted_fields={stats.attempted_fields} "
        f"updated_works={stats.updated_works} "
        f"updated_fields={stats.updated_fields} "
        f"mirrored={stats.mirrored}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
