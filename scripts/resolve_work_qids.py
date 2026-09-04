#!/usr/bin/env python3
"""Exhaustive work-QID search with a versioned research ledger.

Runs a pipeline of increasingly-broad-but-still-precise search strategies against
each QID-less work, and records the outcome in ``field_provenance.work_qid`` so a
work is never searched twice needlessly -- yet is automatically re-opened when
the search itself improves.

Strategies (this build = search-plan v5):
  1. **by-creator** -- the guarded match in the creator's Wikidata oeuvre
     (alias + normalized-title match), disambiguating a same-title cluster by, in
     order, the holder (P195), the year, the **medium** (P31: a painting vs its
     own print edition -- a routine collision, e.g. Benton's "Aaron" as both a
     painting and a lithograph), then the work's dimensions (P2048/P2049); needs
     a creator QID.
  2. **title-search** -- creator-independent Wikidata title search, gated to
     ``P31=artwork`` with a strong title match and year agreement; accepts a work
     by the creator, else a globally-unique artwork match even without a
     confirmed creator (see :mod:`fine_art_archive.enrichment.work_qid_search`).
  3. **title-variants** -- the creator's oeuvre again, but with ALL-language
     labels and a small set of normalizations (an archive copy number, a label
     disambiguator, ordered token containment), because 358 of the 466 works v4
     retired failed as ``by-creator:below-threshold`` -- the oeuvre was there and
     the two strings differed structurally rather than in which work they meant.
     Guards are tighter than strategy 1's, never looser (see
     :mod:`fine_art_archive.enrichment.work_qid_title_variants`).

A work whose retirement records a DECISION rather than an exhausted search
(``faa:identity-anchor``, ``duplicate-adjudication`` -- 101 sidecars) is never
re-opened by a plan bump. A decision is re-litigated by revisiting the decision,
not by running the search again.

A further strategy -- cross-referencing ``known_works`` (Wikipedia "List of
paintings by X" + Met) -- was evaluated and rejected: for a work whose creator's
Wikidata P170 oeuvre is empty (the only bucket strategy 1 can't cover), the only
QID-bearing ``known_works`` source is that same empty P170, so it recovered 0 of
a 9-work probe. Do not re-add it without a source that carries Wikidata QIDs.

Ledger states written for ``work_qid``:
  * ``available`` -- a QID was found (never searched again);
  * ``not_available @ vN`` -- creator known, all strategies exhausted, none found
    (terminal until the plan version rises);
  * ``unverified @ vN`` -- no creator QID, creator-independent search exhausted
    (re-searched once a creator QID appears, or when the plan rises).

Eligibility re-opens a retired work when the current plan version exceeds the one
it was retired under -- so raising ``SEARCH_PLAN_VERSION`` (i.e. adding a strategy)
re-searches every previously-retired work automatically. "Give up" is never final
until the search can't improve.

The terminal labels are written ONLY with ``--retire`` -- run it after the plan is
complete, never mid-build, so nothing is retired before it has really been
searched. Without it, unresolved works are left ``not_researched`` and re-tried.
Dry-run by default; ``--apply`` writes; mirrors + operations.log as usual.
"""

from __future__ import annotations

import argparse
import json
import re
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
from _sidecar_io import script_env_path as _env_path  # noqa: E402
from _sidecar_io import sidecar_paths as _sidecar_paths  # noqa: E402
from _sidecar_io import write_existing_mirrors as _write_existing_mirrors  # noqa: E402
from jsonschema import ValidationError as _ValidationError  # noqa: E402

from fine_art_archive import provenance, sidecar  # noqa: E402
from fine_art_archive.enrichment.holder import _creator_qid  # noqa: E402
from fine_art_archive.enrichment.source_resolver import JsonClient  # noqa: E402
from fine_art_archive.enrichment.work_qid_by_creator import resolve_work_qid, year_of  # noqa: E402
from fine_art_archive.enrichment.work_qid_search import resolve_by_title_search  # noqa: E402
from fine_art_archive.enrichment.work_qid_title_variants import (  # noqa: E402
    resolve_by_title_variants,
)
from fine_art_archive.identity.variants import VariantLinks  # noqa: E402
from fine_art_archive.identity.work_qid_uniqueness import (  # noqa: E402
    WorkQidClaims,
    collision_note,
)

DEFAULT_LIMIT = 100_000
SEARCH_PLAN_VERSION = 5  # bump when a strategy is added -> re-opens retired works
_PLAN_REF_RE = re.compile(r"faa:work-qid-search/v(\d+)")
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
class ResolveStats:
    attempted: int
    resolved: int
    retired_not_available: int
    retired_blocked: int
    mirrored: int
    matches: list[dict[str, Any]] = field(default_factory=list)


def _work_qid(meta: dict[str, Any]) -> str | None:
    stable = meta.get("stable_identifiers")
    if isinstance(stable, dict):
        qid = stable.get("wikidata_q")
        return qid if isinstance(qid, str) and qid else None
    return None


def _retired_plan_version(meta: dict[str, Any]) -> int | None:
    """The search-plan version a work was last retired under, or None."""
    entry = (meta.get("field_provenance") or {}).get("work_qid")
    if not isinstance(entry, dict):
        return None
    if entry.get("status") not in ("not_available", "unverified"):
        return None
    match = _PLAN_REF_RE.search(str(entry.get("source_ref") or ""))
    return int(match.group(1)) if match else 0


def _is_derived(meta: dict[str, Any]) -> bool:
    """True for a detail/capture that inherits identity from a parent work."""
    return bool(meta.get("derived_from"))


def _adjudicated(meta: dict[str, Any]) -> str | None:
    """The source of a deliberate "this work has no Q-ID" decision, if any.

    ``_retired_plan_version`` reads a retirement whose ``source_ref`` carries no
    plan version as version 0, so raising the plan re-opens it. That is right
    for a work the SEARCH gave up on and wrong for a work some pass DECIDED
    about. The archive holds 101 of the latter -- 72 ``faa:identity-anchor`` and
    29 ``duplicate-adjudication``, the second group cleared on evidence that
    item dimensions and the P18 image put the work on another sidecar. Searching
    them again proposes the same Q-ID straight back, so bumping the plan would
    silently overturn every one of them.

    A decision is not re-litigated by a search. It is re-litigated by revisiting
    the decision.
    """
    entry = (meta.get("field_provenance") or {}).get("work_qid")
    if not isinstance(entry, dict) or entry.get("status") != "not_available":
        return None
    if _PLAN_REF_RE.search(str(entry.get("source_ref") or "")):
        return None
    return str(entry.get("source") or "adjudicated")


def _eligible(meta: dict[str, Any]) -> bool:
    if _is_derived(meta):
        # A derived item has no identity of its own: the schema invariant is
        # `derived_from set => stable_identifiers.wikidata_q is null`, and
        # audit_checks.derived_identity reports any violation as BROKEN.
        # Resolving one here does not merely add a wrong field, it starts an
        # OSCILLATION: this pass sets a Q-ID, the invariant repair clears it,
        # the next run sets it again. Observed flipping five times in 70
        # minutes on 8d8f6ab-the-birth-of-venus-botticelli (2026-08-09).
        return False
    if _work_qid(meta) is not None:
        return False  # already resolved
    if _adjudicated(meta) is not None:
        return False
    entry = (meta.get("field_provenance") or {}).get("work_qid")
    status = entry.get("status") if isinstance(entry, dict) else None
    if status not in ("not_available", "unverified"):
        return True  # never retired -> search
    # Retired: re-open when the plan improved, or (for artist-blocked works) when
    # a creator QID has since appeared so the by-creator strategy can now run.
    retired_at = _retired_plan_version(meta) or 0
    if retired_at < SEARCH_PLAN_VERSION:
        return True
    return status == "unverified" and _creator_qid(meta) is not None


def _search(
    meta: dict[str, Any], *, sparql: SparqlClient, json_client: JsonClient
) -> tuple[str | None, str, list[str]]:
    """Run the strategy pipeline. Returns (work_qid, method, tried-reasons)."""
    title = str(meta.get("title") or "")
    year = year_of(meta.get("year"))
    creator = _creator_qid(meta)
    tried: list[str] = []

    if creator:
        holder_qid = (meta.get("holder") or {}).get("wikidata_q")
        dims = meta.get("dimensions_original") or {}
        match, reason = resolve_work_qid(
            title,
            year,
            creator,
            client=sparql,
            holder_qid=holder_qid,
            dimensions=(dims.get("h_cm"), dims.get("w_cm")),
            category=meta.get("category"),
        )
        tried.append(f"by-creator:{reason}")
        if match is not None:
            return match.work_qid, "by-creator", tried

    qid, reason = resolve_by_title_search(
        title, year, creator, json_client=json_client, sparql_client=sparql
    )
    tried.append(f"title-search:{reason}")
    if qid is not None:
        return qid, "title-search", tried

    if creator:
        candidate, reason = resolve_by_title_variants(title, year, creator, client=sparql)
        tried.append(f"title-variants:{reason}")
        if candidate is not None:
            return candidate.work_qid, f"title-variants:{candidate.kind}", tried
    return None, "", tried


def _apply_found(meta: dict[str, Any], qid: str, method: str) -> None:
    meta.setdefault("stable_identifiers", {})["wikidata_q"] = qid
    provenance.set(
        meta,
        "work_qid",
        "available",
        "wikidata",
        source_ref=f"https://www.wikidata.org/wiki/{qid}",
        note=f"Work QID via {method} (search plan v{SEARCH_PLAN_VERSION}).",
    )


def _apply_retire(meta: dict[str, Any], tried: list[str]) -> str:
    """Retire an unresolved work; return the status written."""
    blocked = _creator_qid(meta) is None
    status = "unverified" if blocked else "not_available"
    detail = "blocked on artist QID; " if blocked else ""
    provenance.set(
        meta,
        "work_qid",
        status,
        "wikidata",
        source_ref=f"faa:work-qid-search/v{SEARCH_PLAN_VERSION}",
        note=f"No work QID found ({detail}search plan v{SEARCH_PLAN_VERSION}); tried: {tried}.",
    )
    return status


def _apply_collision_retire(meta: dict[str, Any], qid: str, holder: str) -> str:
    """Record a search hit refused because another work already holds that QID.

    Not `_apply_retire`: the search did not come up empty, it came up with an
    identifier that is already spoken for. See ``work_qid_uniqueness`` for why
    refusing is the conservative move.
    """
    provenance.set(
        meta,
        "work_qid",
        "unverified",
        "wikidata",
        source_ref=f"faa:work-qid-search/v{SEARCH_PLAN_VERSION}",
        note=collision_note(qid, holder, plan=f"search plan v{SEARCH_PLAN_VERSION}"),
    )
    return "unverified"


def _append_operation(
    log_path: Path,
    meta: dict[str, Any],
    op: str,
    detail: dict[str, Any],
    staging_path: Path,
    mirror_paths: list[Path],
) -> None:
    entry = {
        "ts": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "actor": "resolve_work_qids",
        "op": op,
        "work_id": meta["work_id"],
        **detail,
        "staging_path": str(staging_path),
        "mirror_paths": [str(path) for path in mirror_paths],
    }
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")


def backfill(
    staging_dir: Path,
    *,
    sparql: SparqlClient,
    json_client: JsonClient,
    art_works_root: Path | None = None,
    operations_log: Path | None = None,
    limit: int = DEFAULT_LIMIT,
    apply: bool = False,
    retire: bool = False,
) -> tuple[ResolveStats, Counter[str]]:
    if limit < 1:
        raise ValueError("limit must be at least 1")
    stats = ResolveStats(0, 0, 0, 0, 0)
    outcomes: Counter[str] = Counter()
    paths = _sidecar_paths(staging_dir)
    # A work QID denotes one work. Seeded from the archive so an incumbent
    # blocks a new claimant, and updated as this run resolves so the run cannot
    # collide with itself — the 2026-08-09 regression was two writes 15 minutes
    # apart inside ONE pass.
    claims = WorkQidClaims.from_sidecars(paths, load=sidecar.load)
    # The same rule one field over: a sidecar named in another sidecar's
    # `files.variants[]` is a second HOLDING of a work, not a work. The schema
    # enforces this for `derived_from` and cannot for variants, because the
    # entry lives in the OWNER's sidecar and says nothing inside the holding's —
    # so this pass has to keep them out of the queue itself, or it restores the
    # shared identity the crop repair just cleared.
    links = VariantLinks.from_sidecars(paths, load=sidecar.load)
    for path in paths:
        meta = sidecar.load(path)
        if _is_derived(meta):
            outcomes["skipped:derived-item"] += 1
            continue
        reason = links.exclusion_reason(str(meta.get("work_id") or path.parent.name))
        if reason is not None:
            outcomes[f"skipped:{reason}"] += 1
            continue
        if not _eligible(meta):
            continue
        stats.attempted += 1
        qid, method, tried = _search(meta, sparql=sparql, json_client=json_client)
        collided_with = claims.collides(qid, str(meta.get("work_id")))
        if collided_with is not None:
            outcomes["declined:collision"] += 1
            tried.append(f"collision:held-by-{collided_with}")
            if apply:
                _apply_collision_retire(meta, str(qid), collided_with)
                sidecar.validate(meta)
                sidecar.write(path, meta)
                mirror_paths = _write_existing_mirrors(meta, art_works_root, exclude=path)
                stats.mirrored += len(mirror_paths)
                stats.retired_blocked += 1
                if operations_log is not None:
                    _append_operation(
                        operations_log,
                        meta,
                        "work_qid_collision_declined",
                        {"qid": qid, "held_by": collided_with, "method": method},
                        path,
                        mirror_paths,
                    )
            if stats.attempted >= limit:
                break
            continue
        if qid is not None:
            outcomes[f"resolved:{method}"] += 1
            stats.matches.append({"work_id": meta["work_id"], "qid": qid, "method": method})
            claims.claim(qid, str(meta.get("work_id") or path.parent.name))
            if apply:
                _apply_found(meta, qid, method)
        elif retire:
            status = _apply_retire(meta, tried)
            outcomes[f"retired:{status}"] += 1
        else:
            outcomes["unresolved:not-retired"] += 1

        if apply and (qid is not None or retire):
            op = "work_qid_resolved" if qid is not None else "work_qid_retired"
            detail = {"qid": qid, "method": method} if qid else {"tried": tried}
            try:
                sidecar.validate(meta)
            except _ValidationError:
                # The sidecar was already schema-invalid for a reason this pass
                # did not introduce; skip it rather than abort the whole run, and
                # undo this work's tallies so the report stays accurate.
                outcomes["skipped-invalid-sidecar"] += 1
                if qid is not None:
                    outcomes[f"resolved:{method}"] -= 1
                    stats.matches.pop()
                else:
                    outcomes[f"retired:{meta['field_provenance']['work_qid']['status']}"] -= 1
                if stats.attempted >= limit:
                    break
                continue
            sidecar.write(path, meta)
            mirror_paths = _write_existing_mirrors(meta, art_works_root, exclude=path)
            stats.mirrored += len(mirror_paths)
            if qid is not None:
                stats.resolved += 1
            elif meta["field_provenance"]["work_qid"]["status"] == "not_available":
                stats.retired_not_available += 1
            else:
                stats.retired_blocked += 1
            if operations_log is not None:
                _append_operation(operations_log, meta, op, detail, path, mirror_paths)
        if stats.attempted >= limit:
            break
    return stats, outcomes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write changes (default: dry-run)")
    parser.add_argument(
        "--retire",
        action="store_true",
        help="label exhausted works not_available/unverified (run only when the plan is complete)",
    )
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument(
        "--staging-dir",
        type=Path,
        default=default_works_dir(),
    )
    parser.add_argument("--art-works-root", type=Path, default=_env_path("FAA_ART_WORKS_ROOT"))
    parser.add_argument(
        "--no-mirror",
        action="store_true",
        help="write staging only, deliberately leaving the canonical archive stale",
    )
    parser.add_argument("--operations-log", type=Path, default=_env_path("FAA_OPERATIONS_LOG"))
    args = parser.parse_args(argv)

    # Refuse to write staging-only by accident. `_write_existing_mirrors`
    # returns [] when the root is None, so an unset FAA_ART_WORKS_ROOT used to
    # make every run report success while the canonical archive silently went
    # stale: 49 of 926 identity ops wrote a mirror without the variable set,
    # against 760 of 761 with it, leaving 142 works whose two sidecars
    # disagreed. Silence is the bug; make the caller say which it wants.
    if args.apply and args.art_works_root is None and not args.no_mirror:
        parser.error(
            "refusing to --apply without a canonical archive root: writes would "
            "land in staging only and the archive would drift silently. Set "
            "FAA_ART_WORKS_ROOT, pass --art-works-root, or pass --no-mirror to "
            "say you meant staging only."
        )

    stats, outcomes = backfill(
        args.staging_dir,
        sparql=SparqlClient(),
        json_client=JsonClient(timeout=15.0),
        # --no-mirror means staging-only, so the root must be dropped here and
        # not merely tolerated by the guard above: otherwise the flag silences
        # the error while still writing the mirrors it claims to suppress.
        art_works_root=None if args.no_mirror else args.art_works_root,
        operations_log=args.operations_log,
        limit=args.limit,
        apply=args.apply,
        retire=args.retire,
    )
    mode = "apply" if args.apply else "dry-run"
    print(
        f"resolve-work-qids ({mode}, plan v{SEARCH_PLAN_VERSION}, retire={args.retire}): "
        f"attempted={stats.attempted} resolved={stats.resolved} "
        f"retired_not_available={stats.retired_not_available} "
        f"retired_blocked={stats.retired_blocked} mirrored={stats.mirrored}"
    )
    if outcomes:
        print("outcomes:", dict(outcomes.most_common()))
    for m in stats.matches:
        print(f"  {m['method']:14} {m['qid']:10} {m['work_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
