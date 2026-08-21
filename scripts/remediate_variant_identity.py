#!/usr/bin/env python3
"""Apply the owner-approved, evidence-pinned variant-identity repair.

The July crop linker connected two distinct versions of *The Scream* as display
variants.  Their independently evidenced work Q-IDs prove they are not the
same artwork.  This command removes only those reciprocal relationship entries;
it deliberately preserves both Q-IDs and does not touch missing-identity or
unresolved records.

The command is dry-run by default.  ``--apply`` validates both sidecars before
writing and appends a complete preimage to ``operations.log`` for recovery.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "src"))

from fine_art_archive import sidecar  # noqa: E402

ISSUE_NUMBER = 560
APPROVED_FALSE_VARIANT_PAIR = (
    ("0ba0ac6-the-scream-munch", "Q18891156"),
    ("94de558-the-scream-munch", "Q18891158"),
)


@dataclass(frozen=True)
class RemediationPlan:
    paths: tuple[Path, Path]
    before: tuple[dict[str, Any], dict[str, Any]]
    after: tuple[dict[str, Any], dict[str, Any]]
    removed: tuple[dict[str, Any], dict[str, Any]]


def _qid(meta: dict[str, Any]) -> str | None:
    stable = meta.get("stable_identifiers")
    value = stable.get("wikidata_q") if isinstance(stable, dict) else None
    return value if isinstance(value, str) and value else None


def _meta_path(sidecar_root: Path, work_id: str) -> Path:
    return sidecar_root / work_id / "meta.json"


def _remove_exact_variant(meta: dict[str, Any], target_id: str) -> dict[str, Any]:
    files = meta.get("files")
    variants = files.get("variants") if isinstance(files, dict) else None
    if not isinstance(variants, list):
        raise ValueError(f"{meta.get('work_id')} has no variant list")
    expected = f"works/{target_id}/master.jpeg"
    matched = [item for item in variants if isinstance(item, dict) and item.get("rel_path") == expected]
    if len(matched) != 1:
        raise ValueError(
            f"{meta.get('work_id')} expected exactly one link to {target_id}; found {len(matched)}"
        )
    files["variants"] = [item for item in variants if item is not matched[0]]
    return matched[0]


def build_plan(sidecar_root: Path) -> RemediationPlan | None:
    """Return the exact reciprocal unlink plan, or ``None`` if already applied."""
    (left_id, left_qid), (right_id, right_qid) = APPROVED_FALSE_VARIANT_PAIR
    left_path, right_path = _meta_path(sidecar_root, left_id), _meta_path(sidecar_root, right_id)
    left_before, right_before = sidecar.load(left_path), sidecar.load(right_path)
    for meta, work_id, qid in ((left_before, left_id, left_qid), (right_before, right_id, right_qid)):
        if meta.get("work_id") != work_id or _qid(meta) != qid:
            raise ValueError(f"{work_id} no longer matches the approved identity evidence")

    def has_link(meta: dict[str, Any], target: str) -> bool:
        files = meta.get("files")
        variants = files.get("variants") if isinstance(files, dict) else []
        return any(isinstance(item, dict) and item.get("rel_path") == f"works/{target}/master.jpeg" for item in variants)

    left_link, right_link = has_link(left_before, right_id), has_link(right_before, left_id)
    if not left_link and not right_link:
        return None
    if left_link != right_link:
        raise ValueError("reciprocal variant link is only partially present; refusing asymmetric repair")

    left_after, right_after = copy.deepcopy(left_before), copy.deepcopy(right_before)
    removed_left = _remove_exact_variant(left_after, right_id)
    removed_right = _remove_exact_variant(right_after, left_id)
    sidecar.validate(left_after)
    sidecar.validate(right_after)
    return RemediationPlan(
        paths=(left_path, right_path),
        before=(left_before, right_before),
        after=(left_after, right_after),
        removed=(removed_left, removed_right),
    )


def _digest(meta: dict[str, Any]) -> str:
    payload = json.dumps(meta, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(payload).hexdigest()


def _append_operation(log_path: Path, plan: RemediationPlan) -> None:
    entry = {
        "ts": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "actor": "remediate_variant_identity",
        "op": "unlink_false_variant",
        "issue": ISSUE_NUMBER,
        "work_ids": [meta["work_id"] for meta in plan.before],
        "before_sha256": [_digest(meta) for meta in plan.before],
        "after_sha256": [_digest(meta) for meta in plan.after],
        "removed_variants": list(plan.removed),
        "preimage": list(plan.before),
    }
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")


def remediate(sidecar_root: Path, *, operations_log: Path, apply: bool = False) -> RemediationPlan | None:
    """Validate and optionally apply the sole approved false-variant unlink."""
    plan = build_plan(sidecar_root)
    if plan is None or not apply:
        return plan
    for path, meta in zip(plan.paths, plan.after, strict=True):
        sidecar.write(path, meta)
    _append_operation(operations_log, plan)
    return plan


def _default_root() -> Path:
    return Path(
        os.environ.get(
            "FAA_ART_WORKS_ROOT",
            "~/Library/CloudStorage/Dropbox/Pictures/Art/works",
        )
    ).expanduser()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write the approved unlink (default: dry-run)")
    parser.add_argument("--sidecar-root", type=Path, default=_default_root())
    parser.add_argument("--operations-log", type=Path)
    args = parser.parse_args(argv)
    log_path = args.operations_log or args.sidecar_root.parent / "operations.log"
    plan = remediate(args.sidecar_root, operations_log=log_path, apply=args.apply)
    if plan is None:
        print("variant-identity remediation: already applied; no changes")
        return 0
    mode = "applied" if args.apply else "dry-run"
    print(
        f"variant-identity remediation ({mode}): unlink "
        f"{plan.before[0]['work_id']} <-> {plan.before[1]['work_id']}; qids preserved"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
