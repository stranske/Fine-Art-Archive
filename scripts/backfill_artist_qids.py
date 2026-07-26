#!/usr/bin/env python3
"""Backfill ``artist.wikidata_q`` by resolving the artist NAME to a person QID.

Complements ``complete_metadata.py``: the source pass only fills ``artist_qid``
from a work entity's P170 (needs a work QID that title search often misses),
so obscure works are stranded even when the artist is famous. This resolves the
artist directly from ``artist.name`` via
:func:`fine_art_archive.identity.artist_lookup.resolve_artist_qid`, gated to real
artists. Only touches works lacking an artist QID; existing QIDs are left alone.

Dry-run by default; ``--apply`` writes. Records provenance + mirrors + logs.
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
sys.path.insert(0, str(ROOT / "src"))

from fine_art_archive import provenance, sidecar  # noqa: E402
from fine_art_archive.enrichment.source_resolver import JsonClient  # noqa: E402
from fine_art_archive.identity.artist_lookup import resolve_artist_qid  # noqa: E402

DEFAULT_LIMIT = 100_000


@dataclass
class BackfillStats:
    attempted: int
    resolved: int
    updated_works: int
    mirrored: int


def _sidecar_paths(staging_dir: Path) -> list[Path]:
    paths = set(staging_dir.rglob("meta.json"))
    paths.update(staging_dir.glob("*.json"))
    return sorted(path for path in paths if path.is_file())


def _existing_qid(meta: dict[str, Any]) -> str | None:
    artist = meta.get("artist")
    return artist.get("wikidata_q") if isinstance(artist, dict) else None


def _artist_name(meta: dict[str, Any]) -> str:
    artist = meta.get("artist")
    return str(artist.get("name") or "").strip() if isinstance(artist, dict) else ""


def _write_existing_mirrors(meta: dict[str, Any], art_works_root: Path | None, *, exclude: Path) -> list[Path]:
    if art_works_root is None:
        return []
    work_id = str(meta["work_id"])
    candidates = {art_works_root / "works" / work_id / "meta.json", art_works_root / work_id / "meta.json"}
    written: list[Path] = []
    for candidate in sorted(candidates):
        if candidate.is_file() and candidate.resolve() != exclude.resolve():
            sidecar.write(candidate, meta)
            written.append(candidate)
    return written


def _append_operation(log_path: Path, meta: dict[str, Any], qid: str, method: str,
                      staging_path: Path, mirror_paths: list[Path]) -> None:
    entry = {
        "ts": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "actor": "backfill_artist_qids",
        "op": "artist_qid_backfill",
        "work_id": meta["work_id"],
        "artist_qid": qid,
        "method": method,
        "staging_path": str(staging_path),
        "mirror_paths": [str(path) for path in mirror_paths],
    }
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")


def backfill(staging_dir: Path, *, client: Any, art_works_root: Path | None = None,
             operations_log: Path | None = None, limit: int = DEFAULT_LIMIT,
             ) -> tuple[BackfillStats, Counter[str]]:
    if limit < 1:
        raise ValueError("limit must be at least 1")
    attempted = resolved = updated = mirrored = 0
    reasons: Counter[str] = Counter()
    for path in _sidecar_paths(staging_dir):
        meta = sidecar.load(path)
        if _existing_qid(meta):
            continue
        name = _artist_name(meta)
        if not name:
            continue
        attempted += 1
        qid, method = resolve_artist_qid(name, client=client)
        if qid is None:
            reasons[method or "unresolved"] += 1
            continue
        meta.setdefault("artist", {})["wikidata_q"] = qid
        provenance.set(
            meta, "artist_qid", "available", "wikidata",
            source_ref=f"https://www.wikidata.org/wiki/{qid}",
            note=f"Resolved from artist name {name!r} ({method}).",
        )
        sidecar.validate(meta)
        sidecar.write(path, meta)
        mirror_paths = _write_existing_mirrors(meta, art_works_root, exclude=path)
        resolved += 1
        updated += 1
        mirrored += len(mirror_paths)
        if operations_log is not None:
            _append_operation(operations_log, meta, qid, method or "", path, mirror_paths)
        if attempted >= limit:
            break
    return BackfillStats(attempted, resolved, updated, mirrored), reasons


def _env_path(name: str) -> Path | None:
    raw = os.environ.get(name)
    return Path(raw).expanduser() if raw else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--staging-dir", type=Path,
                        default=_env_path("FAA_STAGING_DIR") or ROOT / "staging_sidecars")
    parser.add_argument("--art-works-root", type=Path, default=_env_path("FAA_ART_WORKS_ROOT"))
    parser.add_argument("--operations-log", type=Path, default=_env_path("FAA_OPERATIONS_LOG"))
    parser.add_argument("--timeout", type=float, default=15.0)
    args = parser.parse_args(argv)

    stats, reasons = backfill(
        args.staging_dir, client=JsonClient(timeout=args.timeout),
        art_works_root=args.art_works_root, operations_log=args.operations_log,
        limit=args.limit,
    )
    print(
        "artist_qid backfill: "
        f"attempted={stats.attempted} resolved={stats.resolved} "
        f"updated_works={stats.updated_works} mirrored={stats.mirrored}"
    )
    if reasons:
        print("unresolved reasons:", dict(reasons))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
