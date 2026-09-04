#!/usr/bin/env python3
"""Repair ``field_provenance`` entries carrying keys the schema forbids.

The sidecar schema pins each ``field_provenance`` entry to
``additionalProperties: false`` over ``{status, source, source_ref, checked_at,
note}``. An out-of-tree repair pass (``source: fix_corrupt_artist_qids``) wrote
extra ``prior_canonical`` / ``prior_mirror`` keys into ``artist_qid_repair``
entries, leaving 86 sidecars schema-invalid -- which fails ``sidecar.validate``
and blocks every validation-gated pass.

This strips any non-schema key from every provenance entry and folds ``key=value``
into that entry's ``note`` first (lossless -- for the known case the values were
already restated in the note, so nothing changes there), then re-validates and
writes. Idempotent: a clean sidecar is left untouched.

Dry-run by default; ``--apply`` writes, mirrors to Art/works, and logs.
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

_ALLOWED_KEYS = frozenset({"status", "source", "source_ref", "checked_at", "note"})


@dataclass
class RepairStats:
    scanned: int
    repaired: int  # sidecars with >=1 stripped key
    entries_fixed: int  # provenance entries touched
    keys_stripped: int
    mirrored: int


def strip_nonschema_keys(meta: dict[str, Any]) -> tuple[int, int]:
    """Strip non-schema keys from every provenance entry, folding them into note.

    Returns ``(entries_fixed, keys_stripped)``. Mutates ``meta`` in place.
    """
    provenance = meta.get("field_provenance")
    if not isinstance(provenance, dict):
        return 0, 0
    entries_fixed = keys_stripped = 0
    for entry in provenance.values():
        if not isinstance(entry, dict):
            continue
        extra = sorted(set(entry) - _ALLOWED_KEYS)
        if not extra:
            continue
        note = str(entry.get("note") or "")
        folded = "; ".join(f"{key}={entry[key]}" for key in extra)
        for key in extra:
            del entry[key]
        if folded and folded not in note:
            entry["note"] = f"{note} [{folded}]".strip() if note else f"[{folded}]"
        entries_fixed += 1
        keys_stripped += len(extra)
    return entries_fixed, keys_stripped


def _append_operation(
    log_path: Path, meta: dict[str, Any], keys: int, staging_path: Path, mirrors: list[Path]
) -> None:
    entry = {
        "ts": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "actor": "repair_provenance_keys",
        "op": "provenance_key_repair",
        "work_id": meta["work_id"],
        "keys_stripped": keys,
        "staging_path": str(staging_path),
        "mirror_paths": [str(path) for path in mirrors],
    }
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")


def repair(
    staging_dir: Path,
    *,
    art_works_root: Path | None = None,
    operations_log: Path | None = None,
    apply: bool = False,
) -> tuple[RepairStats, Counter[str]]:
    scanned = repaired = entries = keys = mirrored = 0
    sources: Counter[str] = Counter()
    for path in _sidecar_paths(staging_dir):
        meta = sidecar.load(path)
        scanned += 1
        entries_fixed, keys_stripped = strip_nonschema_keys(meta)
        if not keys_stripped:
            continue
        for name, entry in (meta.get("field_provenance") or {}).items():
            if isinstance(entry, dict) and name == "artist_qid_repair":
                sources[str(entry.get("source"))] += 1
        sidecar.validate(meta)  # must now be schema-valid
        repaired += 1
        entries += entries_fixed
        keys += keys_stripped
        if apply:
            sidecar.write(path, meta)
            mirrors = _write_existing_mirrors(meta, art_works_root, exclude=path)
            mirrored += len(mirrors)
            if operations_log is not None:
                _append_operation(operations_log, meta, keys_stripped, path, mirrors)
    return RepairStats(scanned, repaired, entries, keys, mirrored), sources


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write changes (default: dry-run)")
    parser.add_argument(
        "--staging-dir",
        type=Path,
        default=default_works_dir(),
    )
    parser.add_argument("--art-works-root", type=Path, default=_env_path("FAA_ART_WORKS_ROOT"))
    parser.add_argument("--operations-log", type=Path, default=_env_path("FAA_OPERATIONS_LOG"))
    args = parser.parse_args(argv)

    stats, sources = repair(
        args.staging_dir,
        art_works_root=args.art_works_root,
        operations_log=args.operations_log,
        apply=args.apply,
    )
    mode = "apply" if args.apply else "dry-run"
    print(
        f"provenance-key repair ({mode}): scanned={stats.scanned} repaired={stats.repaired} "
        f"entries_fixed={stats.entries_fixed} keys_stripped={stats.keys_stripped} "
        f"mirrored={stats.mirrored}"
    )
    if sources:
        print("offending sources:", dict(sources))
    if not args.apply and stats.repaired:
        print("(dry-run: no files written; re-run with --apply)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
