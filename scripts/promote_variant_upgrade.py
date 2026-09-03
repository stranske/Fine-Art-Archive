#!/usr/bin/env python3
"""Apply accepted variant upgrades: swap a work's master for a better copy.

`/variant_upgrades/{wid}/decision` records an accept and tells the operator to
"add a per-decision grant in permissions.md and run
scripts/promote_variant_upgrade.py". That script did not exist. Accepting an
upgrade appended a line to `data/variant_upgrade_decisions.jsonl` and nothing
else ever happened -- a decision surface with no executor behind it, which is
the same shape as the manifest that had no producer.

Usage:

    promote_variant_upgrade.py                      # dry run: what would apply
    promote_variant_upgrade.py --apply --grant GNN  # actually swap
    promote_variant_upgrade.py --wid <work_id>      # one work

WHY THIS REFUSES MORE THAN IT APPLIES
-------------------------------------
The candidate list is produced by a detector this app does not own, and on
2026-09-02 three of its six rows were wrong in a way that would have destroyed
data: one 311 MB file was proposed as the upgrade for FOUR different works. Its
directory is named `342776b-thirty-six-views-of-mount-fuji-hokusai`, after the
SERIES, but its sidecar says it is *South Wind, Clear Sky* (Q3565037) -- Red
Fuji. Three of the four targets are *Under the Wave off Kanagawa*. Applying the
CSV as written would have replaced The Great Wave with Red Fuji, three times,
and the only surviving evidence would have been a `superseded-` file nobody was
looking for.

So a size ratio is not authority to overwrite a master. This verifies the
candidate IS the work it claims to upgrade, on Wikidata identity, and refuses
whatever it cannot prove. Both Q-IDs present and equal, or no swap. "Cannot
determine identity" is a refusal, never a pass -- an unverifiable swap and a
verified one must not look the same.

The replaced master is MOVED to `superseded-<sha7><ext>` beside its work, never
deleted, matching promote_reacquired.py. That makes a swap reversible, which is
what keeps this class R2 (`replace`) rather than R3.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "src"))

from fine_art_archive import sidecar  # noqa: E402
from fine_art_archive.api import store  # noqa: E402

# Imported, never re-derived: the containment roots and file locations are the
# API's, and a second copy of them here could drift from the ones the endpoint
# actually enforces.
from fine_art_archive.api.main import (  # noqa: E402
    ART_WORKS_ROOT,
    VARIANT_CANDIDATE_ROOTS,
    VARIANT_UPGRADE_CSV,
    VARIANT_UPGRADE_DECISIONS,
)

APPLIED_LOG = ROOT / "data" / "variant_upgrade_applied.jsonl"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _work_qid(meta: dict[str, Any]) -> str | None:
    stable = meta.get("stable_identifiers")
    qid = stable.get("wikidata_q") if isinstance(stable, dict) else None
    return qid if isinstance(qid, str) and qid.startswith("Q") else None


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def accepted_work_ids() -> set[str]:
    """Work IDs whose LATEST decision is `accept`.

    Latest wins: the log is append-only, so an accept followed by a reject is a
    reject. Reading it as "an accept appears anywhere" would resurrect a
    decision the operator had already changed their mind about.
    """
    latest: dict[str, str] = {}
    if not VARIANT_UPGRADE_DECISIONS.exists():
        return set()
    for line in VARIANT_UPGRADE_DECISIONS.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except ValueError:
            continue
        wid = event.get("existing_wid")
        decision = event.get("decision")
        if isinstance(wid, str) and isinstance(decision, str):
            latest[wid] = decision
    return {wid for wid, decision in latest.items() if decision == "accept"}


def evaluate(row: dict[str, str], claimed_by: Counter[str]) -> dict[str, Any]:
    """Decide whether this candidate may replace this work's master."""
    wid = (row.get("existing_wid") or "").strip()
    verdict: dict[str, Any] = {"wid": wid}
    try:
        store.validate_work_id(wid)
    except ValueError as exc:
        return {**verdict, "status": "REFUSED", "reason": f"unusable work_id: {exc}"}

    raw = (row.get("candidate_path") or "").strip()
    if not raw:
        return {**verdict, "status": "REFUSED", "reason": "no candidate_path recorded"}
    candidate = Path(raw).expanduser().resolve(strict=False)

    # The CSV is untrusted input; this is the same containment the read-only
    # candidate_image endpoint enforces, applied before a WRITE.
    if not any(
        candidate.is_relative_to(root.resolve(strict=False)) for root in VARIANT_CANDIDATE_ROOTS
    ):
        return {**verdict, "status": "REFUSED", "reason": "candidate outside permitted roots"}
    if not candidate.is_file():
        return {**verdict, "status": "REFUSED", "reason": f"candidate not on disk: {candidate}"}

    # One file cannot be the better copy of two different paintings. This is the
    # check that would have caught the Hokusai rows.
    if claimed_by[str(candidate)] > 1:
        return {
            **verdict,
            "status": "REFUSED",
            "reason": f"candidate is proposed for {claimed_by[str(candidate)]} different "
            "works; at most one of them can be right",
        }

    work_dir = ART_WORKS_ROOT / wid
    masters = sorted(p for p in work_dir.glob("master.*") if p.is_file())
    if not masters:
        return {**verdict, "status": "REFUSED", "reason": "work has no master in the archive"}
    target_meta = _load_json(work_dir / "meta.json")
    if target_meta is None:
        return {**verdict, "status": "REFUSED", "reason": "work has no readable sidecar"}

    candidate_meta = _load_json(candidate.parent / "meta.json")
    target_q, candidate_q = _work_qid(target_meta), _work_qid(candidate_meta or {})
    if target_q is None or candidate_q is None:
        missing = "target" if target_q is None else "candidate"
        return {
            **verdict,
            "status": "REFUSED",
            "reason": f"cannot verify identity: {missing} has no work Q-ID",
        }
    if target_q != candidate_q:
        return {
            **verdict,
            "status": "REFUSED",
            "reason": f"different works: target {target_q} vs candidate {candidate_q}",
        }

    return {
        **verdict,
        "status": "READY",
        "candidate": str(candidate),
        "master": str(masters[0]),
        "work_qid": target_q,
        "reason": f"identity confirmed ({target_q})",
    }


def apply_swap(verdict: dict[str, Any], grant: str) -> dict[str, Any]:
    """Supersede the master and move the candidate in. Never deletes."""
    master = Path(verdict["master"])
    candidate = Path(verdict["candidate"])
    superseded = master.parent / f"superseded-{_sha256(master)[:7]}{master.suffix}"
    shutil.move(str(master), str(superseded))
    new_master = master.parent / f"master{candidate.suffix}"
    shutil.move(str(candidate), str(new_master))

    meta_path = master.parent / "meta.json"
    meta = _load_json(meta_path) or {}
    files = meta.setdefault("files", {})
    entry = files.setdefault("master", {})
    entry.update(
        {
            "filename": new_master.name,
            "sha256": _sha256(new_master),
            "size_bytes": new_master.stat().st_size,
            "ingested_at": datetime.now(UTC).isoformat(timespec="seconds"),
        }
    )
    meta.setdefault("history", []).append(
        {
            "ts": datetime.now(UTC).isoformat(timespec="seconds"),
            "actor": "promote_variant_upgrade",
            "op": "variant-upgrade",
            "notes": (
                f"grant={grant}; master replaced from {candidate}; previous kept as "
                f"{superseded.name}; identity confirmed {verdict['work_qid']}"
            ),
        }
    )
    # Validate BEFORE writing, so a swap cannot leave an invalid sidecar behind.
    sidecar.write(meta_path, meta)
    return {
        **verdict,
        "status": "APPLIED",
        "superseded": superseded.name,
        "new_master": new_master.name,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--apply", action="store_true", help="perform the swap (needs --grant)")
    parser.add_argument("--grant", help="permissions.md grant ID authorising the replace")
    parser.add_argument(
        "--wid",
        action="append",
        default=[],
        help="limit to these work IDs (default: every accepted decision)",
    )
    args = parser.parse_args(argv)

    if args.apply and not args.grant:
        print(
            "--apply requires --grant: replacing a master is R2 under permissions.md",
            file=sys.stderr,
        )
        return 2
    if not VARIANT_UPGRADE_CSV.exists():
        print(f"no candidate list at {VARIANT_UPGRADE_CSV}", file=sys.stderr)
        return 2

    with open(VARIANT_UPGRADE_CSV, encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    # Counted over the WHOLE list, not the selection: a candidate claimed by
    # four works is ambiguous even when you ask about only one of them.
    claimed_by = Counter(
        str(Path((r.get("candidate_path") or "").strip()).expanduser().resolve(strict=False))
        for r in rows
        if (r.get("candidate_path") or "").strip()
    )

    accepted = set(args.wid) if args.wid else accepted_work_ids()
    selected = [r for r in rows if (r.get("existing_wid") or "").strip() in accepted]
    if not selected:
        print(f"{len(rows)} candidates on file, none accepted for application.")
        print("Accept one on the Variant upgrades screen first, or pass --wid.")
        return 0

    verdicts = [evaluate(row, claimed_by) for row in selected]
    ready = [v for v in verdicts if v["status"] == "READY"]

    for v in verdicts:
        print(f"  {v['status']:8} {v['wid'][:46]:46} {v['reason']}")
    print(f"\n{len(ready)} ready, {len(verdicts) - len(ready)} refused")

    if not args.apply:
        print("\nDRY RUN — nothing changed. Re-run with --apply --grant <ID>.")
        return 0

    applied = [apply_swap(v, args.grant) for v in ready]
    if applied:
        APPLIED_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(APPLIED_LOG, "a", encoding="utf-8") as fh:
            for record in applied:
                fh.write(
                    json.dumps(
                        {
                            **record,
                            "grant": args.grant,
                            "ts": datetime.now(UTC).isoformat(timespec="seconds"),
                        }
                    )
                    + "\n"
                )
    for record in applied:
        print(
            f"  APPLIED  {record['wid']}: {record['new_master']} "
            f"(previous kept as {record['superseded']})"
        )
    print(f"\napplied {len(applied)} upgrade(s) under {args.grant}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
