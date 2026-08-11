#!/usr/bin/env python3
"""Backfill ``stable_identifiers.wikidata_q`` for QID-less uncategorized works.

The uncategorized bucket's remaining floor is works that carry a real artist and
title but no work QID -- so the categoriser's P31 path can't fire. When the
creator QID is known, this enumerates the creator's Wikidata works and matches
the title under the strict guards in
:mod:`fine_art_archive.enrichment.work_qid_by_creator` (best score, unambiguous,
year agreement), then writes the matched work QID. Because candidates come from
the creator's oeuvre, a match is by construction an artwork; a wrong creator QID
simply fails to match rather than writing a wrong work QID.

Scope guard: only touches works that are (a) uncategorized, (b) missing a work
QID, and (c) have a creator QID. Works needing artist resolution first are left
to ``backfill_artist_qids.py`` and reported, not guessed at.

Run ``backfill_categories.py --apply`` afterwards: the freshly written QIDs let
its P31 path assign categories. Dry-run by default; ``--apply`` writes, records
``field_provenance`` for ``work_qid``, mirrors to Art/works, and logs.
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
sys.path.insert(0, str(ROOT / "src"))

from jsonschema import ValidationError as _ValidationError  # noqa: E402

from fine_art_archive import provenance, sidecar  # noqa: E402
from fine_art_archive.enrichment.holder import _creator_qid  # noqa: E402
from fine_art_archive.enrichment.work_qid_by_creator import (  # noqa: E402
    WorkQidMatch,
    resolve_work_qid,
    year_of,
)
from fine_art_archive.identity.work_qid_uniqueness import (  # noqa: E402
    WorkQidClaims,
    collision_note,
)

DEFAULT_LIMIT = 100_000
SPARQL_ENDPOINT = "https://query.wikidata.org/sparql"
USER_AGENT = "Fine-Art-Archive/0.1 (https://github.com/stranske/Fine-Art-Archive)"
_UNCATEGORIZED = (None, "", "(uncategorized)")


class SparqlClient:
    """Throttled, retrying Wikidata Query Service transport.

    Mirrors ``backfill_holders_by_creator.SparqlClient`` (same endpoint contract:
    ``.query(str) -> dict | None``).
    """

    def __init__(
        self,
        *,
        endpoint: str = SPARQL_ENDPOINT,
        timeout: float = 45.0,
        throttle: float = 0.3,
        max_retries: int = 4,
    ) -> None:
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
class WorkQidBackfillStats:
    attempted: int  # eligible works considered
    resolved: int  # work QIDs written (0 in dry-run)
    mirrored: int  # canonical mirrors written
    needs_artist: int = 0  # uncategorized + no work QID but no creator QID (reported, skipped)
    matches: list[dict[str, Any]] = field(default_factory=list)  # for dry-run visibility
    # Matches refused because another sidecar already asserts that work QID.
    # Reported, never written -- silently dropping them would read as "nothing
    # to do here" when the truth is "two works claim one identity".
    collisions: list[dict[str, Any]] = field(default_factory=list)


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


def _eligible(meta: dict[str, Any], *, include_categorized: bool = False) -> bool:
    if _work_qid(meta) is not None:
        return False
    # By default only the uncategorized floor (a work QID unlocks its P31
    # category). With --include-categorized, also resolve the work QID for
    # already-categorized works so downstream holder / IIIF resolution can use
    # it -- e.g. the works whose artist was just un-swapped from a person QID.
    return include_categorized or meta.get("category") in _UNCATEGORIZED


def _apply_match(meta: dict[str, Any], match: WorkQidMatch) -> None:
    stable = meta.setdefault("stable_identifiers", {})
    stable["wikidata_q"] = match.work_qid
    provenance.set(
        meta,
        "work_qid",
        "available",
        "wikidata",
        source_ref=f"https://www.wikidata.org/wiki/{match.work_qid}",
        note=f"Work QID via SPARQL creator-work title match ({match.score:.2f}); "
        f"matched Wikidata label {match.label!r}.",
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
    match: WorkQidMatch,
    staging_path: Path,
    mirror_paths: list[Path],
) -> None:
    entry = {
        "ts": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "actor": "backfill_work_qids_by_creator",
        "op": "work_qid_by_creator_backfill",
        "work_id": meta["work_id"],
        "matched_work_qid": match.work_qid,
        "matched_label": match.label,
        "score": round(match.score, 3),
        "staging_path": str(staging_path),
        "mirror_paths": [str(path) for path in mirror_paths],
    }
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")


def _append_collision_operation(
    log_path: Path,
    meta: dict[str, Any],
    match: WorkQidMatch,
    collided_with: str,
    staging_path: Path,
    mirror_paths: list[Path],
) -> None:
    entry = {
        "ts": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "actor": "backfill_work_qids_by_creator",
        "op": "work_qid_by_creator_collision",
        "work_id": meta["work_id"],
        "proposed_work_qid": match.work_qid,
        "proposed_label": match.label,
        "score": round(match.score, 3),
        "collided_with": collided_with,
        "staging_path": str(staging_path),
        "mirror_paths": [str(path) for path in mirror_paths],
    }
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")


def _work_qid_holders(staging_dir: Path) -> dict[str, list[str]]:
    """work Q-ID -> the work_ids already asserting it."""
    holders: dict[str, list[str]] = {}
    for path in _sidecar_paths(staging_dir):
        try:
            meta = sidecar.load(path)
        except Exception:  # noqa: BLE001 - an unreadable sidecar cannot own a QID
            continue
        qid = _work_qid(meta)
        if qid:
            holders.setdefault(qid, []).append(str(meta.get("work_id") or path.parent.name))
    return holders


def backfill(
    staging_dir: Path,
    *,
    client: Any,
    art_works_root: Path | None = None,
    operations_log: Path | None = None,
    limit: int = DEFAULT_LIMIT,
    apply: bool = False,
    include_categorized: bool = False,
) -> tuple[WorkQidBackfillStats, Counter[str]]:
    if limit < 1:
        raise ValueError("limit must be at least 1")
    stats = WorkQidBackfillStats(attempted=0, resolved=0, mirrored=0)
    reasons: Counter[str] = Counter()
    paths = _sidecar_paths(staging_dir)
    # A work QID denotes one work: refuse a match already held by another
    # sidecar rather than asserting the two are the same work. This pass was
    # the source of 58 of the 60 collisions in the archive's own history.
    claims = WorkQidClaims.from_sidecars(paths, load=sidecar.load)
    for path in paths:
        meta = sidecar.load(path)
        if not _eligible(meta, include_categorized=include_categorized):
            continue
        creator = _creator_qid(meta)
        if not creator:
            stats.needs_artist += 1
            reasons["no-creator-qid"] += 1
            continue
        stats.attempted += 1
        match, reason = resolve_work_qid(
            str(meta.get("title") or ""),
            year_of(meta.get("year")),
            creator,
            client=client,
            holder_qid=(meta.get("holder") or {}).get("wikidata_q"),
            dimensions=(
                (meta.get("dimensions_original") or {}).get("h_cm"),
                (meta.get("dimensions_original") or {}).get("w_cm"),
            ),
            category=meta.get("category"),
        )
        if match is None:
            reasons[reason] += 1
            if stats.attempted >= limit:
                break
            continue
        collided_with = claims.collides(match.work_qid, str(meta.get("work_id")))
        if collided_with is not None:
            reasons["declined:collision"] += 1
            stats.collisions.append(
                {
                    "work_id": meta["work_id"],
                    "title": meta.get("title"),
                    "work_qid": match.work_qid,
                    "label": match.label,
                    "score": round(match.score, 3),
                    "held_by": [collided_with],
                }
            )
            if apply:
                provenance.set(
                    meta,
                    "work_qid",
                    "unverified",
                    "wikidata",
                    source_ref="faa:work-qid-by-creator",
                    note=collision_note(match.work_qid, collided_with, plan="by-creator backfill"),
                )
                try:
                    sidecar.validate(meta)
                except _ValidationError:
                    # A collision must be reported, but an unrelated invalid
                    # sidecar must not turn that report into a failed batch.
                    reasons["skipped-invalid-sidecar"] += 1
                    if stats.attempted >= limit:
                        break
                    continue
                sidecar.write(path, meta)
                mirror_paths = _write_existing_mirrors(meta, art_works_root, exclude=path)
                stats.mirrored += len(mirror_paths)
                if operations_log is not None:
                    _append_collision_operation(
                        operations_log, meta, match, collided_with, path, mirror_paths
                    )
            if stats.attempted >= limit:
                break
            continue
        reasons["match"] += 1
        stats.matches.append(
            {
                "work_id": meta["work_id"],
                "title": meta.get("title"),
                "work_qid": match.work_qid,
                "label": match.label,
                "score": round(match.score, 3),
            }
        )
        if apply:
            _apply_match(meta, match)
            try:
                sidecar.validate(meta)
            except _ValidationError as exc:
                # The sidecar was already schema-invalid for a reason this pass
                # did not introduce (e.g. an out-of-tree field). Skip it rather
                # than abort the whole run; report so it can be repaired.
                reasons["skipped-invalid-sidecar"] += 1
                stats.matches.pop()
                if "part_of_q" in str(exc):
                    reasons["skipped-part_of_q"] += 1
                if stats.attempted >= limit:
                    break
                continue
            sidecar.write(path, meta)
            mirror_paths = _write_existing_mirrors(meta, art_works_root, exclude=path)
            stats.resolved += 1
            stats.mirrored += len(mirror_paths)
            if operations_log is not None:
                _append_operation(operations_log, meta, match, path, mirror_paths)
        # Only a simulated dry-run or a successfully validated assignment may
        # reserve the Q-ID for later sidecars in this pass.  A rejected write
        # must not block a valid candidate that follows it.
        claims.claim(match.work_qid, str(meta.get("work_id") or path.parent.name))
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
        default=_env_path("FAA_STAGING_DIR") or ROOT / "staging_sidecars",
    )
    parser.add_argument("--art-works-root", type=Path, default=_env_path("FAA_ART_WORKS_ROOT"))
    parser.add_argument("--operations-log", type=Path, default=_env_path("FAA_OPERATIONS_LOG"))
    parser.add_argument("--show-matches", action="store_true", help="print each proposed match")
    parser.add_argument(
        "--include-categorized",
        action="store_true",
        help="also resolve the work QID for already-categorized works (for holder/IIIF)",
    )
    args = parser.parse_args(argv)

    stats, reasons = backfill(
        args.staging_dir,
        client=SparqlClient(),
        art_works_root=args.art_works_root,
        operations_log=args.operations_log,
        limit=args.limit,
        apply=args.apply,
        include_categorized=args.include_categorized,
    )
    mode = "apply" if args.apply else "dry-run"
    print(
        f"work-qid-by-creator backfill ({mode}): "
        f"eligible={stats.attempted} matched={len(stats.matches)} "
        f"written={stats.resolved} mirrored={stats.mirrored} "
        f"needs_artist_resolution={stats.needs_artist} "
        f"refused_collision={len(stats.collisions)}"
    )
    for c in stats.collisions:
        print(
            f"  REFUSED {c['work_id']}: {c['work_qid']} ({c['label']!r}, "
            f"score {c['score']}) is already held by {', '.join(c['held_by'])} "
            f"-- one Q-ID cannot denote two works"
        )
    if reasons:
        print("outcomes:", dict(reasons.most_common()))
    if args.show_matches or not args.apply:
        for m in stats.matches:
            print(
                f"  {m['score']:.2f}  {m['work_id']}  {m['title']!r} -> "
                f"{m['work_qid']} ({m['label']!r})"
            )
    if not args.apply and stats.matches:
        print("(dry-run: no files written; re-run with --apply)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
