#!/usr/bin/env python3
"""Remove owner-approved false reciprocal ``files.variants`` links.

Dry-run by default. ``--apply`` writes sidecars and appends to operations.log.
Issue #560 (2026-08-21 owner decision): unlink only the reciprocal Scream pair
``0ba0ac6-the-scream-munch`` ↔ ``94de558-the-scream-munch`` while preserving
all work Q-IDs.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fine_art_archive.identity.variant_identity import classify_variant_links  # noqa: E402
from fine_art_archive.identity.variant_remediation import (  # noqa: E402
    remediate_reciprocal_false_variants,
)
from fine_art_archive import sidecar  # noqa: E402

SCREAM_PAIR = (
    "0ba0ac6-the-scream-munch",
    "94de558-the-scream-munch",
)
GRANT_560 = "grant=issue-560-scream-false-variant-unlink"


def _env_path(name: str) -> Path | None:
    raw = os.environ.get(name)
    return Path(raw).expanduser() if raw else None


def _load_pair_metas(root: Path, work_id_a: str, work_id_b: str) -> list[dict]:
    metas = []
    for work_id in (work_id_a, work_id_b):
        for candidate in (
            root / "works" / work_id / "meta.json",
            root / work_id / "meta.json",
        ):
            if candidate.is_file():
                metas.append(sidecar.load(candidate))
                break
        else:
            raise FileNotFoundError(f"missing sidecar for {work_id} under {root}")
    return metas


def _audit_summary(root: Path, work_id_a: str, work_id_b: str) -> dict:
    metas = _load_pair_metas(root, work_id_a, work_id_b)
    findings = classify_variant_links(metas)
    return {
        "pair": [work_id_a, work_id_b],
        "finding_count": len(findings),
        "findings": [
            {
                "owner_work_id": item.owner_work_id,
                "holding_work_id": item.holding_work_id,
                "owner_qid": item.owner_qid,
                "holding_qid": item.holding_qid,
                "verdict": item.verdict.value,
            }
            for item in findings
        ],
        "qids": {
            meta["work_id"]: meta.get("stable_identifiers", {}).get("wikidata_q") for meta in metas
        },
        "variant_counts": {
            meta["work_id"]: len(meta.get("files", {}).get("variants") or []) for meta in metas
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pair",
        choices=("scream-560",),
        default="scream-560",
        help="Predefined owner-approved remediation pair",
    )
    parser.add_argument("--apply", action="store_true", help="write sidecars and log")
    parser.add_argument(
        "--art-works-root",
        type=Path,
        default=_env_path("FAA_ART_WORKS_ROOT")
        or Path.home() / "Library/CloudStorage/Dropbox/Pictures/Art/works",
    )
    parser.add_argument(
        "--operations-log",
        type=Path,
        default=_env_path("FAA_OPERATIONS_LOG")
        or Path.home() / "Library/CloudStorage/Dropbox/Pictures/Art/operations.log",
    )
    parser.add_argument(
        "--report-out",
        type=Path,
        help="write before/after JSON audit summary to this path",
    )
    args = parser.parse_args(argv)

    if args.pair != "scream-560":
        raise SystemExit(f"unsupported pair {args.pair!r}")
    work_id_a, work_id_b = SCREAM_PAIR

    before = _audit_summary(args.art_works_root, work_id_a, work_id_b)
    stats, results = remediate_reciprocal_false_variants(
        args.art_works_root,
        work_id_a,
        work_id_b,
        grant=GRANT_560,
        actor="remediate_false_variant_links",
        apply=args.apply,
        operations_log=args.operations_log if args.apply else None,
    )
    after = _audit_summary(args.art_works_root, work_id_a, work_id_b)

    payload = {
        "grant": GRANT_560,
        "apply": args.apply,
        "art_works_root": str(args.art_works_root),
        "before": before,
        "after": after,
        "stats": {
            "planned": stats.planned,
            "removed": stats.removed,
            "wrote": stats.wrote,
        },
        "results": [
            {
                "work_id": item.work_id,
                "removed_rel_path": item.removed_rel_path,
                "qid_after": item.qid_after,
                "variant_count_after": item.variant_count_after,
                "wrote": item.wrote,
            }
            for item in results
        ],
    }
    text = json.dumps(payload, indent=2, sort_keys=True)
    print(text)
    if args.report_out is not None:
        args.report_out.parent.mkdir(parents=True, exist_ok=True)
        args.report_out.write_text(text + "\n", encoding="utf-8")

    mode = "apply" if args.apply else "dry-run"
    print(
        f"\nfalse-variant unlink ({mode}): "
        f"planned={stats.planned} removed={stats.removed} wrote={stats.wrote}",
        file=sys.stderr,
    )
    if not args.apply and stats.removed:
        print("(dry-run: no files written; re-run with --apply)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
