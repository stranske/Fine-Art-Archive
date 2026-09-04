#!/usr/bin/env python3
"""Complete holder metadata for a bounded set of eligible sidecars."""

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
from fine_art_archive.enrichment.holder import (  # noqa: E402
    HolderClient,
    WikidataClient,
    complete_holder,
)

DEFAULT_LIMIT = 100


@dataclass(frozen=True)
class CompletionStats:
    attempted: int
    updated: int
    mirrored: int
    skipped_invalid: int = 0


def complete_sidecars(
    staging_dir: Path,
    *,
    art_works_root: Path | None = None,
    operations_log: Path | None = None,
    limit: int = DEFAULT_LIMIT,
    client: HolderClient | None = None,
) -> CompletionStats:
    """Complete at most ``limit`` eligible sidecars and return run counts."""
    if limit < 1:
        raise ValueError("limit must be at least 1")

    active_client = client if client is not None else WikidataClient()
    attempted = updated_count = mirrored_count = skipped_invalid = 0
    for path in _sidecar_paths(staging_dir):
        work_id = path.parent.name
        try:
            meta = sidecar.load(path)
            work_id = str(meta.get("work_id", work_id))
            sidecar.validate(meta)
            if not _eligible(meta):
                continue
            attempted += 1
            before = deepcopy(meta)
            completed = complete_holder(meta, client=active_client)
            if completed != before:
                sidecar.validate(completed)
                sidecar.write(path, completed)
                mirror_paths = _write_existing_mirrors(completed, art_works_root, exclude=path)
                updated_count += 1
                mirrored_count += len(mirror_paths)
                if operations_log is not None:
                    _append_operation(operations_log, completed, path, mirror_paths)
            if attempted >= limit:
                break
        except jsonschema.ValidationError as error:
            skipped_invalid += 1
            _record_invalid_sidecar(operations_log, path, work_id, error)
    return CompletionStats(attempted, updated_count, mirrored_count, skipped_invalid)


def _eligible(meta: dict[str, Any]) -> bool:
    return provenance.needs_research(meta, "holder")


def _append_operation(
    log_path: Path,
    meta: dict[str, Any],
    staging_path: Path,
    mirror_paths: list[Path],
) -> None:
    holder_provenance = provenance.get(meta, "holder")
    if holder_provenance is None:
        raise ValueError("holder completion did not record provenance")
    entry = {
        "ts": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "actor": "complete_holders",
        "op": "holder_completion",
        "work_id": meta["work_id"],
        "status": holder_provenance["status"],
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
        "actor": "complete_holders",
        "op": "invalid_sidecar_skipped",
        "work_id": work_id,
        "staging_path": str(path),
        "validation_error": error.message,
    }
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")


def _default_limit() -> int:
    raw = os.environ.get("FAA_HOLDER_LIMIT")
    return int(raw) if raw else DEFAULT_LIMIT


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--limit",
        type=int,
        default=_default_limit(),
        help=f"Maximum eligible sidecars to attempt (default: {DEFAULT_LIMIT}).",
    )
    args = parser.parse_args(argv)

    staging_dir = default_works_dir()
    stats = complete_sidecars(
        staging_dir,
        art_works_root=_env_path("FAA_ART_WORKS_ROOT"),
        operations_log=_env_path("FAA_OPERATIONS_LOG"),
        limit=args.limit,
    )
    print(
        f"holder completion: attempted={stats.attempted} "
        f"updated={stats.updated} mirrored={stats.mirrored} "
        f"skipped_invalid={stats.skipped_invalid}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
