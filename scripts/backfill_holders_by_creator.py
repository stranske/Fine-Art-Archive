#!/usr/bin/env python3
"""Backfill holders for no-holder works via SPARQL by-creator + title match.

Run after artist QIDs are resolved (``backfill_artist_qids.py``): for each work
that still lacks a holder but has a creator QID, enumerate the creator's works on
Wikidata and match the title under strict guards (see
:mod:`fine_art_archive.enrichment.holder_by_creator`), then record the matched
work's collection as the holder. Never touches works that already have a holder.

Dry-run by default; ``--apply`` writes. Records provenance + mirrors + logs.
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
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "src"))

from fine_art_archive import provenance, sidecar  # noqa: E402
from fine_art_archive.enrichment import holder as holdermod  # noqa: E402
from fine_art_archive.enrichment.holder import _creator_qid  # noqa: E402
from fine_art_archive.enrichment.holder_by_creator import (  # noqa: E402
    IMMOVABLE_CATEGORIES,
    HolderMatch,
    resolve_holder,
    year_of,
)

DEFAULT_LIMIT = 100_000
SPARQL_ENDPOINT = "https://query.wikidata.org/sparql"
USER_AGENT = "Fine-Art-Archive/0.1 (https://github.com/stranske/Fine-Art-Archive)"


class SparqlClient:
    """Throttled, retrying Wikidata Query Service transport."""

    def __init__(self, *, endpoint: str = SPARQL_ENDPOINT, timeout: float = 45.0,
                 throttle: float = 0.3, max_retries: int = 4) -> None:
        self.endpoint = endpoint
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
        url = f"{self.endpoint}?{urllib.parse.urlencode({'query': sparql, 'format': 'json'})}"
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
class HolderBackfillStats:
    attempted: int
    resolved: int
    updated_works: int
    mirrored: int


def _sidecar_paths(staging_dir: Path) -> list[Path]:
    paths = set(staging_dir.rglob("meta.json"))
    paths.update(staging_dir.glob("*.json"))
    return sorted(path for path in paths if path.is_file())


def _has_holder(meta: dict[str, Any]) -> bool:
    return meta.get("holder") not in (None, "", {}, [])


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


def _apply_match(meta: dict[str, Any], match: HolderMatch) -> None:
    work = match.work
    entry = holdermod._registry_entry(match.holder_qid)
    meta["holder"] = {
        "name": match.holder_label or (entry.name if entry else None),
        "wikidata_q": match.holder_qid,
        "ror": match.holder_ror or (entry.ror if entry else None),
        "url": match.holder_url or (entry.homepage if entry else None),
        "accession": work.accession,
    }
    stable = meta.setdefault("stable_identifiers", {})
    stable["wikidata_q"] = work.work_qid
    if work.accession:
        stable["museum_accession"] = work.accession
    kind = "location (P276)" if match.kind == "location" else "collection (P195)"
    provenance.set(
        meta, "holder", "available", "wikidata",
        source_ref=f"https://www.wikidata.org/wiki/{work.work_qid}",
        note=f"Holder via SPARQL creator-work match ({match.score:.2f}), {kind}; "
             f"work {work.work_qid} matched by creator+title.",
    )


def _append_operation(log_path: Path, meta: dict[str, Any], match: HolderMatch,
                      staging_path: Path, mirror_paths: list[Path]) -> None:
    entry = {
        "ts": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "actor": "backfill_holders_by_creator",
        "op": "holder_by_creator_backfill",
        "work_id": meta["work_id"],
        "matched_work_qid": match.work.work_qid,
        "holder_qid": match.holder_qid,
        "holder_kind": match.kind,
        "score": round(match.score, 3),
        "staging_path": str(staging_path),
        "mirror_paths": [str(path) for path in mirror_paths],
    }
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")


def backfill(staging_dir: Path, *, client: Any, art_works_root: Path | None = None,
             operations_log: Path | None = None, limit: int = DEFAULT_LIMIT,
             ) -> tuple[HolderBackfillStats, Counter[str]]:
    if limit < 1:
        raise ValueError("limit must be at least 1")
    attempted = resolved = updated = mirrored = 0
    reasons: Counter[str] = Counter()
    for path in _sidecar_paths(staging_dir):
        meta = sidecar.load(path)
        if _has_holder(meta):
            continue
        creator = _creator_qid(meta)
        if not creator:
            continue
        attempted += 1
        allow_location = str(meta.get("category") or "") in IMMOVABLE_CATEGORIES
        match, reason = resolve_holder(
            str(meta.get("title") or ""), year_of(meta.get("year")), creator,
            client=client, allow_location=allow_location,
        )
        if match is None:
            reasons[reason] += 1
            continue
        _apply_match(meta, match)
        sidecar.validate(meta)
        sidecar.write(path, meta)
        mirror_paths = _write_existing_mirrors(meta, art_works_root, exclude=path)
        resolved += 1
        updated += 1
        mirrored += len(mirror_paths)
        if operations_log is not None:
            _append_operation(operations_log, meta, match, path, mirror_paths)
        if attempted >= limit:
            break
    return HolderBackfillStats(attempted, resolved, updated, mirrored), reasons


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
    args = parser.parse_args(argv)

    stats, reasons = backfill(
        args.staging_dir, client=SparqlClient(),
        art_works_root=args.art_works_root, operations_log=args.operations_log, limit=args.limit,
    )
    print(
        "holder-by-creator backfill: "
        f"attempted={stats.attempted} resolved={stats.resolved} "
        f"updated_works={stats.updated_works} mirrored={stats.mirrored}"
    )
    if reasons:
        print("unresolved reasons:", dict(reasons))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
