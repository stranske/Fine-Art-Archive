#!/usr/bin/env python3
"""Build reviewable series-position sidecars from an explicit mapping.

The command never mutates the operational corpus. ``--check`` validates and
reports only; otherwise candidates are written beneath ``--output-dir``.
"""

from __future__ import annotations

import argparse
import copy
import json
from collections import defaultdict
from pathlib import Path
from typing import Any

from fine_art_archive import sidecar


def load_mapping(path: Path) -> list[dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    records = raw.get("records") if isinstance(raw, dict) else raw
    if not isinstance(records, list) or not all(isinstance(item, dict) for item in records):
        raise ValueError("mapping must be a list of records or an object with a records list")
    return records


def validate_mapping(records: list[dict[str, Any]]) -> None:
    by_qid: dict[str, list[tuple[str, int]]] = defaultdict(list)
    seen_work_ids: set[str] = set()
    for record in records:
        work_id = record.get("work_id")
        qid = record.get("qid")
        position = record.get("position")
        source = record.get("source")
        if not isinstance(work_id, str) or not work_id:
            raise ValueError("every mapping record requires a work_id")
        if work_id in seen_work_ids:
            raise ValueError(f"duplicate work_id in mapping: {work_id}")
        seen_work_ids.add(work_id)
        if not isinstance(qid, str) or not qid.startswith("Q") or not qid[1:].isdigit():
            raise ValueError(f"{work_id}: qid must be a Wikidata Q-ID")
        if isinstance(position, bool) or not isinstance(position, int) or position < 1:
            raise ValueError(f"{work_id}: position must be a positive integer")
        if not isinstance(source, str) or not source.strip():
            raise ValueError(f"{work_id}: source is required")
        by_qid[qid].append((work_id, position))

    for qid, members in by_qid.items():
        by_position: dict[int, list[str]] = defaultdict(list)
        for work_id, position in members:
            by_position[position].append(work_id)
        duplicates = {p: ids for p, ids in by_position.items() if len(ids) > 1}
        if duplicates:
            raise ValueError(f"{qid}: duplicate positions: {duplicates}")
        expected = set(range(1, max(by_position) + 1))
        missing = sorted(expected - set(by_position))
        if missing:
            raise ValueError(f"{qid}: missing positions: {missing}")


def build_candidates(
    root: Path, records: list[dict[str, Any]]
) -> tuple[list[tuple[str, dict[str, Any]]], dict[str, Any]]:
    validate_mapping(records)
    candidates: list[tuple[str, dict[str, Any]]] = []
    changes: list[dict[str, Any]] = []
    for record in records:
        work_id = str(record["work_id"])
        path = root / work_id / "meta.json"
        if not path.exists():
            raise ValueError(f"{work_id}: sidecar not found at {path}")
        original = sidecar.load(path)
        stable = original.get("stable_identifiers")
        if not isinstance(stable, dict) or stable.get("part_of_q") != record["qid"]:
            raise ValueError(
                f"{work_id}: stable_identifiers.part_of_q does not match {record['qid']}"
            )
        candidate = copy.deepcopy(original)
        old_value = candidate.get("series")
        new_value: dict[str, Any] = {
            "position": record["position"],
            "source": record["source"],
        }
        if record.get("position_label") is not None:
            new_value["position_label"] = record["position_label"]
        candidate["series"] = new_value
        sidecar.validate(candidate)
        candidates.append((work_id, candidate))
        changes.append(
            {
                "work_id": work_id,
                "qid": record["qid"],
                "old_value": old_value,
                "new_position": record["position"],
                "evidence_source": record["source"],
            }
        )
    return candidates, {"change_count": len(changes), "changes": changes}


def write_candidates(output_dir: Path, candidates: list[tuple[str, dict[str, Any]]]) -> None:
    for work_id, candidate in candidates:
        sidecar.write(output_dir / work_id / "meta.json", candidate)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True, help="source sidecar root")
    parser.add_argument("--mapping", type=Path, required=True, help="explicit JSON mapping")
    parser.add_argument("--output-dir", type=Path, help="candidate output root")
    parser.add_argument("--report", type=Path, help="optional report JSON path")
    parser.add_argument("--check", action="store_true", help="validate without writing candidates")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.check and args.output_dir is None:
        raise SystemExit("--output-dir is required unless --check is used")
    records = load_mapping(args.mapping)
    candidates, report = build_candidates(args.root, records)
    if not args.check:
        write_candidates(args.output_dir, candidates)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
