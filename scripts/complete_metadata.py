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

import jsonschema

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "src"))

from _paths import default_works_dir  # noqa: E402
from _sidecar_io import script_env_path as _env_path  # noqa: E402
from _sidecar_io import sidecar_paths as _sidecar_paths  # noqa: E402
from _sidecar_io import write_existing_mirrors as _write_existing_mirrors  # noqa: E402

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
    skipped_invalid: int = 0


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
    attempted_works = attempted_fields = updated_works = updated_fields = mirrored = (
        skipped_invalid
    ) = 0
    for path in _sidecar_paths(staging_dir):
        work_id = path.parent.name
        try:
            meta = sidecar.load(path)
            work_id = str(meta.get("work_id", work_id))
            sidecar.validate(meta)
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
        except jsonschema.ValidationError as error:
            skipped_invalid += 1
            _record_invalid_sidecar(operations_log, path, work_id, error)

    return CompletionStats(
        attempted_works,
        attempted_fields,
        updated_works,
        updated_fields,
        mirrored,
        skipped_invalid,
    )


def _eligible_fields(meta: dict[str, Any]) -> list[str]:
    fields: list[str] = []
    for field in FIELD_ORDER:
        entry = provenance.get(meta, field)
        status = entry.get("status") if entry is not None else "not_researched"
        if status in {"not_researched", "unverified"}:
            fields.append(field)
    return fields


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


def _record_invalid_sidecar(
    log_path: Path | None, path: Path, work_id: str, error: jsonschema.ValidationError
) -> None:
    message = f"skipping invalid sidecar work_id={work_id}: {error.message}"
    print(message, file=sys.stderr)
    if log_path is None:
        return
    entry = {
        "ts": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "actor": "complete_metadata",
        "op": "invalid_sidecar_skipped",
        "work_id": work_id,
        "staging_path": str(path),
        "validation_error": error.message,
    }
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")


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
        default=default_works_dir(),
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
        f"mirrored={stats.mirrored} "
        f"skipped_invalid={stats.skipped_invalid}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
