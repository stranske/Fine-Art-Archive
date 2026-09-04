#!/usr/bin/env python3
"""Resolve ``conflicting`` metadata fields with a deterministic, zero-touch policy.

Run this after ``complete_metadata.py`` to work through the conflicts it records.

Policy (uniform, auditable, reversible -- every discarded value is kept in the
provenance note):

  * ``medium`` -- parse the curated original and the source value into canonical
    ``(mediums, supports)`` sets (see :mod:`fine_art_archive.enrichment.medium_vocab`).
    If they AGREE (or one is merely more complete) render one clean form
    ("Oil on canvas") and mark it ``available``. A genuine material disagreement
    (canvas vs panel, oil vs pastel) keeps the curated museum value as
    ``unverified`` and is listed for optional review.
  * ``year`` / ``dimensions_original`` / ``category`` -- the museum catalogue
    (curated original) is authoritative for the physical object, so keep it as
    ``unverified`` and record the source alternative. Range-vs-point and
    precision noise disappears because the curated value wins.

The curated original is recovered from the conflict note written by
``source_resolver`` (``... existing value <json>.``). Only ``conflicting`` fields
are touched; gap-fills and agreements are left alone.
"""

from __future__ import annotations

import argparse
import json
import sys
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
from fine_art_archive.enrichment import medium_vocab  # noqa: E402

DEFAULT_LIMIT = 100_000
CURATED_FIELDS = ("year", "dimensions_original", "category")
_NOTE_MARKER = "existing value "


@dataclass
class ResolutionStats:
    attempted_works: int
    resolved_fields: int
    reconciled_medium: int
    material_conflicts: int
    curated_kept: int
    updated_works: int
    mirrored: int


def _note_original(note: str) -> Any:
    """Recover the json-encoded pre-overwrite value from a conflict note."""
    idx = note.find(_NOTE_MARKER)
    if idx < 0:
        return None
    text = note[idx + len(_NOTE_MARKER) :].strip()
    if text.startswith('"'):
        end = 1
        while end < len(text):
            if text[end] == "\\":
                end += 2
                continue
            if text[end] == '"':
                break
            end += 1
        try:
            return json.loads(text[: end + 1])
        except ValueError:
            return None
    if text.startswith("{"):
        depth = 0
        for end, ch in enumerate(text):
            depth += (ch == "{") - (ch == "}")
            if depth == 0:
                try:
                    return json.loads(text[: end + 1])
                except ValueError:
                    return None
    return None


def _append_operation(
    log_path: Path,
    meta: dict[str, Any],
    staging_path: Path,
    mirror_paths: list[Path],
    outcomes: dict[str, str],
) -> None:
    entry = {
        "ts": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "actor": "resolve_conflicts",
        "op": "conflict_resolution",
        "work_id": meta["work_id"],
        "fields": dict(sorted(outcomes.items())),
        "staging_path": str(staging_path),
        "mirror_paths": [str(path) for path in mirror_paths],
    }
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")


def resolve_field(meta: dict[str, Any], field: str) -> tuple[str, list[str]]:
    """Apply the policy to one ``conflicting`` field. Returns ``(outcome, review)``
    where outcome is one of ``skip``/``reconciled``/``material_conflict``/``curated``.
    ``review`` collects human-readable notes for material conflicts."""
    entry = provenance.get(meta, field)
    if entry is None or entry.get("status") != "conflicting":
        return "skip", []
    original = _note_original(entry.get("note") or "")
    if original is None:
        return "skip", []
    current = meta.get(field)
    review: list[str] = []

    if field == "medium":
        kind, canonical = medium_vocab.reconcile(current, original)
        if kind == "agree" and canonical:
            meta["medium"] = canonical
            provenance.set(
                meta,
                "medium",
                "available",
                "reconciled",
                note="Conflict resolved: curated and source agree; canonical medium form.",
            )
            return "reconciled", review
        # unparsed or genuine material conflict -> keep curated museum value
        meta["medium"] = original
        provenance.set(
            meta,
            "medium",
            "unverified",
            "curated",
            note=f"Conflict resolved: kept curated museum value; source alternative was {current!r}.",
        )
        if kind == "conflict":
            review.append(f"{meta.get('work_id')}: medium curated={original!r} source={current!r}")
            return "material_conflict", review
        return "curated", review

    # museum catalogue authoritative for physical-object facts
    meta[field] = original
    provenance.set(
        meta,
        field,
        "unverified",
        "curated",
        note=f"Conflict resolved: kept curated museum value; source alternative was {current!r}.",
    )
    return "curated", review


def resolve_sidecars(
    staging_dir: Path,
    *,
    art_works_root: Path | None = None,
    operations_log: Path | None = None,
    limit: int = DEFAULT_LIMIT,
) -> tuple[ResolutionStats, list[str]]:
    if limit < 1:
        raise ValueError("limit must be at least 1")
    attempted = resolved = reconciled = conflicts = curated = updated = mirrored = 0
    review: list[str] = []
    for path in _sidecar_paths(staging_dir):
        meta = sidecar.load(path)
        fp = meta.get("field_provenance") or {}
        conflicting = [
            f
            for f in ("medium", *CURATED_FIELDS)
            if (fp.get(f) or {}).get("status") == "conflicting"
        ]
        if not conflicting:
            continue
        attempted += 1
        outcomes: dict[str, str] = {}
        for field in conflicting:
            outcome, notes = resolve_field(meta, field)
            review.extend(notes)
            if outcome == "skip":
                continue
            resolved += 1
            outcomes[field] = outcome
            reconciled += outcome == "reconciled"
            conflicts += outcome == "material_conflict"
            curated += outcome in {"curated", "material_conflict"}
        if outcomes:
            sidecar.validate(meta)
            sidecar.write(path, meta)
            mirror_paths = _write_existing_mirrors(meta, art_works_root, exclude=path)
            updated += 1
            mirrored += len(mirror_paths)
            if operations_log is not None:
                _append_operation(operations_log, meta, path, mirror_paths, outcomes)
        if attempted >= limit:
            break
    stats = ResolutionStats(attempted, resolved, reconciled, conflicts, curated, updated, mirrored)
    return stats, review


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument(
        "--staging-dir",
        type=Path,
        default=default_works_dir(),
    )
    parser.add_argument("--art-works-root", type=Path, default=_env_path("FAA_ART_WORKS_ROOT"))
    parser.add_argument("--operations-log", type=Path, default=_env_path("FAA_OPERATIONS_LOG"))
    parser.add_argument(
        "--show-conflicts", action="store_true", help="Print the material-conflict review list."
    )
    args = parser.parse_args(argv)

    stats, review = resolve_sidecars(
        args.staging_dir,
        art_works_root=args.art_works_root,
        operations_log=args.operations_log,
        limit=args.limit,
    )
    print(
        "conflict resolution: "
        f"attempted_works={stats.attempted_works} resolved_fields={stats.resolved_fields} "
        f"reconciled_medium={stats.reconciled_medium} material_conflicts={stats.material_conflicts} "
        f"curated_kept={stats.curated_kept} updated_works={stats.updated_works} "
        f"mirrored={stats.mirrored}"
    )
    if args.show_conflicts and review:
        print(f"\n{len(review)} material conflicts kept curated (review optional):")
        for line in review:
            print(f"  {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
