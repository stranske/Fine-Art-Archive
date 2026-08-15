#!/usr/bin/env python3
"""Resolve / classify the CREATOR of works that lack a creator QID.

The work-QID ledger labels a work ``unverified`` when it has no creator QID, but
lumps three very different situations together: a genuinely anonymous work, a
work whose real creator simply is not resolved yet, and a corrupt record whose
creator is lost from the metadata entirely. This pass separates them
(:mod:`fine_art_archive.enrichment.creator_provenance`) and records the verdict
in ``field_provenance.artist_qid`` so each is treated honestly:

  * **resolved**       -- writes the recovered ``artist.wikidata_q`` (which also
    re-opens the work-QID by-creator search for that work).
  * **anonymous**      -- ``not_available`` @ ``faa:creator/anonymous`` -- a
    positive, terminal "no maker by nature"; never re-searched, NOT a gap.
  * **searched**       -- ``not_available`` @ ``faa:artist-search/v<N>`` -- a real
    name not found at plan v<N>; re-opens when the plan version rises.
  * **unattributable** -- ``not_available`` @ ``faa:creator/unattributable`` -- a
    corrupt record; distinct from anonymous (we do not claim the work has no
    maker), terminal until the record itself is repaired.

Name repair is conservative (occupation-gated, order-independent >= 0.90 match).
Dry-run by default; ``--apply`` writes, mirrors to the promoted-masters root, and
logs. Eligibility re-opens a ``searched`` work when ARTIST_SEARCH_PLAN_VERSION
rises; ``anonymous`` / ``unattributable`` are version-independent terminals.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "src"))

from jsonschema import ValidationError as _ValidationError  # noqa: E402

from fine_art_archive import provenance, sidecar  # noqa: E402
from fine_art_archive.enrichment.creator_provenance import (  # noqa: E402
    ARTIST_SEARCH_PLAN_VERSION,
    REF_ANONYMOUS,
    REF_IMAGE_NAME_RECOVERED,
    REF_IMAGE_PENDING,
    REF_SEARCH,
    REF_UNATTRIBUTABLE,
    CreatorOutcome,
    classify,
)
from fine_art_archive.enrichment.holder import _creator_qid  # noqa: E402
from fine_art_archive.enrichment.source_resolver import JsonClient  # noqa: E402

DEFAULT_LIMIT = 100_000
_SEARCH_REF_RE = re.compile(re.escape(REF_SEARCH) + r"(\d+)")


def _sidecar_paths(staging_dir: Path) -> list[Path]:
    paths = set(staging_dir.rglob("meta.json"))
    paths.update(staging_dir.glob("*.json"))
    return sorted(path for path in paths if path.is_file())


def _artist_entry(meta: dict[str, Any]) -> dict[str, Any] | None:
    entry = (meta.get("field_provenance") or {}).get("artist_qid")
    return entry if isinstance(entry, dict) else None


def _eligible(meta: dict[str, Any]) -> bool:
    if _creator_qid(meta) is not None:
        return False  # already has a creator
    entry = _artist_entry(meta)
    if entry is None:
        return True  # never classified -> classify
    if entry.get("status") == "available":
        return False  # resolved
    ref = str(entry.get("source_ref") or "")
    if ref == REF_ANONYMOUS:
        return False  # genuine anonymity (named, era/culture) -- terminal
    if ref.startswith("faa:image-search/"):
        return False  # pending -> image process owns it; confirmed -> terminal
    if ref == REF_UNATTRIBUTABLE:
        return True  # legacy terminal -> reopen to migrate it to image-search pending
    match = _SEARCH_REF_RE.search(ref)
    if match:  # THIS ledger's 'searched' state: re-open when the plan rises
        return int(match.group(1)) < ARTIST_SEARCH_PLAN_VERSION
    # Any other state -- incl. an OLD generic not_available with no/foreign
    # source_ref -- was not written by this ledger; reclassify it.
    return True


def _apply_outcome(meta: dict[str, Any], outcome: CreatorOutcome) -> str:
    """Mutate ``meta`` for the outcome; return the ledger bucket applied."""
    artist = meta.setdefault("artist", {})
    if not isinstance(artist, dict):
        artist = {}
        meta["artist"] = artist

    if outcome.kind == "resolved" and outcome.qid:
        artist["wikidata_q"] = outcome.qid
        if outcome.display:
            artist["name"] = outcome.display
        canonical = artist.get("canonical")
        if isinstance(canonical, dict):
            canonical["wikidata_q"] = outcome.qid
            if outcome.display:
                canonical["display_name"] = outcome.display
        provenance.set(
            meta,
            "artist_qid",
            "available",
            "wikidata",
            source_ref=f"https://www.wikidata.org/wiki/{outcome.qid}",
            note=outcome.note,
        )
        return "resolved"

    if outcome.kind == "anonymous":
        # Positively mark anonymity in the primary field, retiring any old
        # "unknown" catch-all so the verdict is visible, not just in provenance.
        artist["relation"] = "anonymous"
        provenance.set(
            meta,
            "artist_qid",
            "not_available",
            "catalogue",
            source_ref=REF_ANONYMOUS,
            note=outcome.note,
        )
        return "anonymous"

    prior_entry = _artist_entry(meta)
    prior_ref = str((prior_entry or {}).get("source_ref") or "")
    canonical = artist.get("canonical")
    recovered_name = str(artist.get("name") or "").strip() or (
        str(canonical.get("display_name") or "").strip() if isinstance(canonical, dict) else ""
    )
    if (
        outcome.kind in {"searched", "unattributable"}
        and recovered_name
        and prior_ref.startswith("faa:google-lens/")
    ):
        provenance.set(
            meta,
            "artist_qid",
            "not_available",
            "google-lens",
            source_ref=REF_IMAGE_NAME_RECOVERED,
            note=(
                f"Image search recovered {recovered_name!r}, but no safe single creator QID "
                f"was resolved. {outcome.note}"
            ),
        )
        return "image-search-name-recovered"

    if outcome.kind == "searched":
        provenance.set(
            meta,
            "artist_qid",
            "not_available",
            "wikidata",
            source_ref=f"{REF_SEARCH}{ARTIST_SEARCH_PLAN_VERSION}",
            note=outcome.note,
        )
        return "searched"

    # Corrupt / null-name: NOT final. Text search is exhausted, but image search
    # still owes this work a look before null/no-attribution is accepted.
    provenance.set(
        meta,
        "artist_qid",
        "not_available",
        "faa",
        source_ref=REF_IMAGE_PENDING,
        note=f"{outcome.note} Text exhausted; image search required before this is final.",
    )
    return "image-search-pending"


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
    bucket: str,
    outcome: CreatorOutcome,
    staging_path: Path,
    mirror_paths: list[Path],
) -> None:
    entry = {
        "ts": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "actor": "resolve_creators",
        "op": "creator_provenance",
        "work_id": meta["work_id"],
        "bucket": bucket,
        "artist_qid": outcome.qid,
        "method": outcome.method,
        "staging_path": str(staging_path),
        "mirror_paths": [str(path) for path in mirror_paths],
    }
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")


@dataclass
class Stats:
    attempted: int = 0
    written: int = 0
    mirrored: int = 0
    examples: list[dict[str, Any]] = field(default_factory=list)


def run(
    staging_dir: Path,
    *,
    client: Any,
    art_works_root: Path | None = None,
    operations_log: Path | None = None,
    limit: int = DEFAULT_LIMIT,
    apply: bool = False,
) -> tuple[Stats, Counter[str]]:
    if limit < 1:
        raise ValueError("limit must be at least 1")
    stats = Stats()
    buckets: Counter[str] = Counter()
    for path in _sidecar_paths(staging_dir):
        meta = sidecar.load(path)
        if not _eligible(meta):
            continue
        stats.attempted += 1
        outcome = classify(meta, client=client)
        bucket = _apply_outcome(meta, outcome)
        buckets[bucket] += 1
        if len(stats.examples) < 40 or bucket == "resolved":
            stats.examples.append(
                {
                    "work_id": meta["work_id"],
                    "bucket": bucket,
                    "qid": outcome.qid,
                    "display": outcome.display,
                    "method": outcome.method,
                }
            )
        if apply:
            try:
                sidecar.validate(meta)
            except _ValidationError:
                buckets["skipped-invalid-sidecar"] += 1
                buckets[bucket] -= 1
                if stats.attempted >= limit:
                    break
                continue
            sidecar.write(path, meta)
            mirror_paths = _write_existing_mirrors(meta, art_works_root, exclude=path)
            stats.written += 1
            stats.mirrored += len(mirror_paths)
            if operations_log is not None:
                _append_operation(operations_log, meta, bucket, outcome, path, mirror_paths)
        if stats.attempted >= limit:
            break
    return stats, buckets


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
        default=_env_path("FAA_STAGING_DIR") or ROOT / "staging_sidecars",
    )
    parser.add_argument("--art-works-root", type=Path, default=_env_path("FAA_ART_WORKS_ROOT"))
    parser.add_argument("--operations-log", type=Path, default=_env_path("FAA_OPERATIONS_LOG"))
    parser.add_argument("--show", action="store_true", help="print each classification")
    args = parser.parse_args(argv)

    stats, buckets = run(
        args.staging_dir,
        client=JsonClient(timeout=15.0),
        art_works_root=args.art_works_root,
        operations_log=args.operations_log,
        limit=args.limit,
        apply=args.apply,
    )
    mode = "apply" if args.apply else "dry-run"
    print(
        f"resolve-creators ({mode}, artist-plan v{ARTIST_SEARCH_PLAN_VERSION}): "
        f"attempted={stats.attempted} written={stats.written} mirrored={stats.mirrored}"
    )
    if buckets:
        print("buckets:", dict(buckets.most_common()))
    if args.show or not args.apply:
        for e in stats.examples:
            print(
                f"  {e['bucket']:15} {e['work_id']:40} "
                f"{(e['qid'] or ''):10} {e['display'] or ''} {e['method'] or ''}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
