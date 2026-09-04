#!/usr/bin/env python3
"""Repair mis-resolved ``stable_identifiers.wikidata_q`` values.

An earlier free-text title resolver attached work QIDs that point at the wrong
entity -- a person, a place, an article -- for ~110 works. This checks each work
QID's live Wikidata type and, for the ones that are NOT artworks, either:

  * **un-swaps** a title/artist reversal when the QID is the *artist's* person QID
    (P106 art occupation) and the title holds that artist's name -- setting the
    artist from the person, moving the real title out of the ``artist`` field,
    and dropping the person QID so the by-creator pass can re-resolve the real
    work QID; or
  * **clears** the wrong QID (place / sitter / other) -- removing a value that
    poisoned P170-artist and P31-category resolution.

Real artwork QIDs are never touched. See
:mod:`fine_art_archive.enrichment.misresolved_work_qid` for the guards.

Run afterwards, in order: ``backfill_work_qids_by_creator.py --apply`` (re-resolve
the real work QID for un-swapped works), ``backfill_categories.py --apply``.
Dry-run by default; ``--apply`` writes, records provenance, mirrors, logs.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "src"))

from _paths import default_works_dir  # noqa: E402

from fine_art_archive import provenance, sidecar  # noqa: E402
from fine_art_archive.enrichment.misresolved_work_qid import (  # noqa: E402
    Repair,
    classify_qids,
    decide_repair,
)

DEFAULT_LIMIT = 100_000
SPARQL_ENDPOINT = "https://query.wikidata.org/sparql"
USER_AGENT = "Fine-Art-Archive/0.1 (https://github.com/stranske/Fine-Art-Archive)"


class SparqlClient:
    """Throttled, retrying WDQS transport (mirrors the by-creator passes)."""

    def __init__(self, *, timeout: float = 45.0, throttle: float = 0.25, max_retries: int = 4):
        self.timeout = timeout
        self.throttle = throttle
        self.max_retries = max_retries
        self._cache: dict[str, dict[str, Any] | None] = {}
        self._last = 0.0

    def _wait(self) -> None:
        gap = self.throttle - (time.monotonic() - self._last)
        if gap > 0:
            time.sleep(gap)
        self._last = time.monotonic()

    def query(self, sparql: str) -> dict[str, Any] | None:
        if sparql in self._cache:
            return self._cache[sparql]
        url = f"{SPARQL_ENDPOINT}?{urllib.parse.urlencode({'query': sparql, 'format': 'json'})}"
        request = urllib.request.Request(
            url, headers={"User-Agent": USER_AGENT, "Accept": "application/sparql-results+json"}
        )
        result: dict[str, Any] | None = None
        for attempt in range(self.max_retries):
            self._wait()
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    result = json.loads(response.read())
                break
            except urllib.error.HTTPError as exc:
                if exc.code in (429, 503) and attempt < self.max_retries - 1:
                    time.sleep(min(2.0**attempt, 20.0))
                    continue
                break
            except (urllib.error.URLError, TimeoutError, OSError, json.JSONDecodeError):
                break
        self._cache[sparql] = result
        return result


@dataclass
class RepairStats:
    attempted: int  # works with a work QID considered
    unswapped: int
    cleared: int
    mirrored: int
    matches: list[dict[str, Any]] = field(default_factory=list)


def _sidecar_paths(staging_dir: Path) -> list[Path]:
    paths = set(staging_dir.rglob("meta.json"))
    paths.update(staging_dir.glob("*.json"))
    return sorted(path for path in paths if path.is_file())


def _work_qid(meta: dict[str, Any]) -> str | None:
    stable = meta.get("stable_identifiers")
    if isinstance(stable, dict):
        qid = stable.get("wikidata_q")
        return qid if isinstance(qid, str) and qid else None
    return None


def _apply(meta: dict[str, Any], repair: Repair) -> None:
    stable = meta.get("stable_identifiers")
    if isinstance(stable, dict):
        stable.pop("wikidata_q", None)
    provenance.set(meta, "work_qid", "not_available", "wikidata", note=repair.note)
    if repair.action == "unswap":
        meta["title"] = repair.new_title
        artist = meta.setdefault("artist", {})
        artist["name"] = repair.artist_name
        artist["wikidata_q"] = repair.artist_qid
        artist.setdefault("relation", "self")
        canonical = artist.setdefault("canonical", {})
        canonical["wikidata_q"] = repair.artist_qid
        canonical["display_name"] = repair.artist_name
        canonical["method"] = "unswap-misresolved"
        provenance.set(
            meta,
            "artist_qid",
            "available",
            "wikidata",
            source_ref=f"https://www.wikidata.org/wiki/{repair.artist_qid}",
            note=repair.note,
        )


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
    repair: Repair,
    staging_path: Path,
    mirror_paths: list[Path],
) -> None:
    entry = {
        "ts": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "actor": "fix_misresolved_work_qids",
        "op": f"misresolved_work_qid_{repair.action}",
        "work_id": meta["work_id"],
        "note": repair.note,
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
) -> tuple[RepairStats, Counter[str]]:
    if limit < 1:
        raise ValueError("limit must be at least 1")
    stats = RepairStats(attempted=0, unswapped=0, cleared=0, mirrored=0)
    reasons: Counter[str] = Counter()
    # Load each sidecar once (Dropbox reads are slow), keep only those with a
    # work QID, then batch-classify every distinct QID up front (one WDQS query
    # per ~80) before deciding per work.
    loaded: list[tuple[Path, dict[str, Any], str]] = []
    for path in _sidecar_paths(staging_dir):
        meta = sidecar.load(path)
        work_qid = _work_qid(meta)
        if work_qid is not None:
            loaded.append((path, meta, work_qid))
    # Bound the network work by `limit` BEFORE classifying: this used to
    # classify the whole corpus and only then break per-item, so `--limit`
    # never bounded WDQS spend and a bad query day hit every work.
    loaded = loaded[:limit]
    type_cache = classify_qids([wq for _, _, wq in loaded], client=client)
    for path, meta, work_qid in loaded:
        stats.attempted += 1
        qtype = type_cache.get(work_qid)
        if qtype is None:
            reasons["classify-failed"] += 1
            if stats.attempted >= limit:
                break
            continue
        if qtype.is_artwork:
            reasons["artwork-ok"] += 1
            if stats.attempted >= limit:
                break
            continue
        repair = decide_repair(meta, qtype)
        if repair is None:  # defensive: is_artwork already filtered
            reasons["artwork-ok"] += 1
            continue
        reasons[repair.action] += 1
        stats.matches.append(
            {
                "work_id": meta["work_id"],
                "action": repair.action,
                "work_qid": work_qid,
                "note": repair.note,
            }
        )
        if repair.action == "unverifiable":
            # Counted and reported, never written: the query did not answer, so
            # there is nothing to act on. Skipping the apply block is the whole
            # point — a transient WDQS condition must not erase an identifier.
            if stats.attempted >= limit:
                break
            continue
        if apply:
            _apply(meta, repair)
            sidecar.validate(meta)
            sidecar.write(path, meta)
            mirror_paths = _write_existing_mirrors(meta, art_works_root, exclude=path)
            if repair.action == "unswap":
                stats.unswapped += 1
            else:
                stats.cleared += 1
            stats.mirrored += len(mirror_paths)
            if operations_log is not None:
                _append_operation(operations_log, meta, repair, path, mirror_paths)
        if stats.attempted >= limit:
            break
    return stats, reasons


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
    parser.add_argument("--timeout", type=float, default=45.0)
    args = parser.parse_args(argv)

    stats, reasons = backfill(
        args.staging_dir,
        client=SparqlClient(timeout=args.timeout),
        art_works_root=args.art_works_root,
        operations_log=args.operations_log,
        limit=args.limit,
        apply=args.apply,
    )
    mode = "apply" if args.apply else "dry-run"
    print(
        f"fix-misresolved-work-qids ({mode}): attempted={stats.attempted} "
        f"unswapped={stats.unswapped} cleared={stats.cleared} mirrored={stats.mirrored} "
        f"(proposed: {len(stats.matches)})"
    )
    if reasons:
        print("outcomes:", dict(reasons.most_common()))
    if not args.apply:
        for m in stats.matches:
            print(f"  [{m['action']}] {m['work_qid']}  {m['work_id']}\n      {m['note']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
