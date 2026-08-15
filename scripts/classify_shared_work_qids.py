#!/usr/bin/env python3
"""Classify shared work QIDs and migrate proven series identities.

The report is versioned with code. Operational sidecars remain outside this
repository and are touched only when ``--apply-series-migration`` is explicit.
"""

from __future__ import annotations

import argparse
import json
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

from fine_art_archive import sidecar
from fine_art_archive.known_works.artwork_classes import (
    USER_AGENT,
    series_qid_evidence,
)

SCROVEGNI_FRESCO_QID = "Q547923"


def _qid_sort_key(qid: str) -> tuple[int, str]:
    digits = qid[1:] if qid.startswith("Q") else ""
    return (int(digits) if digits.isdigit() else 0, qid)


def _claim_qids(entity: object, property_id: str) -> set[str]:
    if not isinstance(entity, dict):
        return set()
    claims = entity.get("claims")
    if not isinstance(claims, dict):
        return set()
    found: set[str] = set()
    for statement in claims.get(property_id) or []:
        if not isinstance(statement, dict):
            continue
        snak = statement.get("mainsnak")
        if not isinstance(snak, dict):
            continue
        value = (snak.get("datavalue") or {}).get("value")
        if isinstance(value, dict) and isinstance(value.get("id"), str):
            found.add(value["id"])
    return found


def _fetch_entities(qids: set[str], *, timeout: int = 30) -> dict[str, object]:
    if not qids:
        return {}
    query = urllib.parse.urlencode(
        {
            "action": "wbgetentities",
            "format": "json",
            "props": "claims|labels",
            "languages": "en",
            "ids": "|".join(sorted(qids, key=_qid_sort_key)),
        }
    )
    request = urllib.request.Request(
        f"https://www.wikidata.org/w/api.php?{query}", headers={"User-Agent": USER_AGENT}
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read())
    entities = payload.get("entities") if isinstance(payload, dict) else None
    if not isinstance(entities, dict):
        raise RuntimeError("Wikidata response did not contain an entities object")
    return entities


def fetch_classification_graph(qids: set[str]) -> dict[str, object]:
    """Fetch candidates, their P31 classes, and the classes' P279 ancestry."""
    entities = _fetch_entities(qids)
    pending: set[str] = set()
    for qid in qids:
        pending.update(_claim_qids(entities.get(qid), "P31"))
    # A positive series result needs only one path to a group class. Cap the
    # broad ontology walk: Wikidata's upper taxonomy is deep and irrelevant
    # after the concrete artwork classes have been traversed.
    for _depth in range(12):
        pending.difference_update(entities)
        if not pending:
            break
        fetched = _fetch_entities(pending)
        entities.update(fetched)
        pending = set()
        for entity in fetched.values():
            pending.update(_claim_qids(entity, "P279"))
    return entities


def scan_holders(root: Path) -> tuple[dict[str, list[str]], dict[str, Path]]:
    holders: dict[str, list[str]] = defaultdict(list)
    paths: dict[str, Path] = {}
    for path in sorted(root.glob("*/meta.json")):
        meta = sidecar.load(path)
        work_id = str(meta.get("work_id") or path.parent.name)
        paths[work_id] = path
        stable = meta.get("stable_identifiers")
        qid = stable.get("wikidata_q") if isinstance(stable, dict) else None
        if isinstance(qid, str) and qid:
            holders[qid].append(work_id)
    return dict(holders), paths


def _label(entity: object) -> str | None:
    if not isinstance(entity, dict):
        return None
    labels = entity.get("labels")
    if not isinstance(labels, dict):
        return None
    english = labels.get("en")
    return english.get("value") if isinstance(english, dict) else None


def build_report(root: Path) -> dict[str, object]:
    holders, _paths = scan_holders(root)
    shared_qids = {qid for qid, work_ids in holders.items() if len(work_ids) > 1}
    candidates = set(shared_qids)
    if SCROVEGNI_FRESCO_QID in holders:
        candidates.add(SCROVEGNI_FRESCO_QID)
    entities = fetch_classification_graph(candidates)

    records: list[dict[str, object]] = []
    for qid in sorted(shared_qids, key=_qid_sort_key):
        evidence = series_qid_evidence(qid, entities)
        records.append(
            {
                "qid": qid,
                "label": _label(entities.get(qid)),
                "classification": "series-qid" if evidence["is_series"] else "duplicate-candidate",
                "holder_count": len(holders[qid]),
                "work_ids": sorted(holders[qid]),
                "evidence": {
                    "p31": evidence["p31"],
                    "matched_group_classes": evidence["matched_group_classes"],
                    "source": f"https://www.wikidata.org/wiki/Special:EntityData/{qid}.json",
                },
            }
        )

    adjudications: list[dict[str, object]] = []
    if SCROVEGNI_FRESCO_QID in holders:
        evidence = series_qid_evidence(SCROVEGNI_FRESCO_QID, entities)
        adjudications.append(
            {
                "qid": SCROVEGNI_FRESCO_QID,
                "label": _label(entities.get(SCROVEGNI_FRESCO_QID)),
                "classification": "single-work" if not evidence["is_series"] else "series-qid",
                "work_ids": sorted(holders[SCROVEGNI_FRESCO_QID]),
                "part_of_q": "Q29353420",
                "decision": "preserve wikidata_q; it identifies one fresco, not the cycle",
                "evidence": {
                    "p31": evidence["p31"],
                    "matched_group_classes": evidence["matched_group_classes"],
                    "source": (
                        "https://www.wikidata.org/wiki/"
                        f"Special:EntityData/{SCROVEGNI_FRESCO_QID}.json"
                    ),
                },
            }
        )

    return {
        "format_version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "source": "local operational sidecar corpus",
        "shared_qid_count": len(records),
        "records": records,
        "adjudications": adjudications,
    }


def write_report(path: Path, report: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def apply_series_migration(root: Path, report: dict[str, object], *, timestamp: str) -> int:
    _holders, paths = scan_holders(root)
    changed = 0
    for record in report.get("records", []):
        if not isinstance(record, dict) or record.get("classification") != "series-qid":
            continue
        qid = record.get("qid")
        work_ids = record.get("work_ids")
        if not isinstance(qid, str) or not isinstance(work_ids, list):
            raise ValueError("malformed series record")
        for work_id in work_ids:
            if not isinstance(work_id, str) or work_id not in paths:
                raise ValueError(f"report references missing work_id: {work_id!r}")
            path = paths[work_id]
            meta = sidecar.load(path)
            stable = meta.setdefault("stable_identifiers", {})
            if not isinstance(stable, dict):
                raise ValueError(f"{work_id}: stable_identifiers is not an object")
            current = stable.get("wikidata_q")
            part_of = stable.get("part_of_q")
            if current is None and part_of == qid:
                continue
            if current != qid:
                raise ValueError(f"{work_id}: expected wikidata_q={qid}, found {current!r}")
            if part_of not in (None, qid):
                raise ValueError(f"{work_id}: part_of_q conflict: {part_of!r} versus {qid}")
            stable.pop("wikidata_q")
            stable["part_of_q"] = qid
            sidecar.merge_history(
                meta,
                {
                    "ts": timestamp,
                    "actor": "codex",
                    "op": "migrate-series-qid",
                    "notes": (
                        f"Fine-Art-Archive#542; moved proven group identity {qid} "
                        "from wikidata_q to part_of_q"
                    ),
                },
            )
            sidecar.write(path, meta)
            changed += 1
    return changed


def check_report(report: dict[str, object], root: Path | None = None) -> None:
    records = report.get("records")
    if not isinstance(records, list) or report.get("shared_qid_count") != len(records):
        raise ValueError("report record count is inconsistent")
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("report contains a non-object record")
        if record.get("classification") not in {"series-qid", "duplicate-candidate"}:
            raise ValueError(f"{record.get('qid')}: unresolved classification")
        evidence = record.get("evidence")
        if not isinstance(evidence, dict) or not isinstance(evidence.get("p31"), list):
            raise ValueError(f"{record.get('qid')}: missing P31 evidence")
    if root is None:
        return

    _holders, paths = scan_holders(root)
    for record in records:
        qid = record["qid"]
        for work_id in record["work_ids"]:
            meta = sidecar.load(paths[work_id])
            stable = meta.get("stable_identifiers") or {}
            if record["classification"] == "series-qid":
                if stable.get("wikidata_q") == qid or stable.get("part_of_q") != qid:
                    raise ValueError(f"{work_id}: series migration for {qid} is incomplete")
            elif stable.get("wikidata_q") != qid:
                raise ValueError(f"{work_id}: duplicate candidate {qid} was mutated")

    for decision in report.get("adjudications", []):
        if not isinstance(decision, dict) or decision.get("qid") != SCROVEGNI_FRESCO_QID:
            continue
        for work_id in decision.get("work_ids", []):
            stable = sidecar.load(paths[work_id]).get("stable_identifiers") or {}
            if stable.get("wikidata_q") != SCROVEGNI_FRESCO_QID:
                raise ValueError(f"{work_id}: single-work fresco identity was mutated")
            if stable.get("part_of_q") != decision.get("part_of_q"):
                raise ValueError(f"{work_id}: Scrovegni cycle relationship changed")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, help="operational or snapshot works directory")
    parser.add_argument("--report", type=Path, default=Path("docs/reports/shared_work_qids.json"))
    parser.add_argument("--fetch-wikidata", action="store_true", help="regenerate the report")
    parser.add_argument("--apply-series-migration", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--timestamp", help="ISO timestamp for migration history")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report: dict[str, object]
    if args.fetch_wikidata:
        if args.root is None:
            raise SystemExit("--fetch-wikidata requires --root")
        report = build_report(args.root)
        write_report(args.report, report)
    else:
        report = json.loads(args.report.read_text(encoding="utf-8"))

    changed = 0
    if args.apply_series_migration:
        if args.root is None:
            raise SystemExit("--apply-series-migration requires --root")
        timestamp = args.timestamp or datetime.now(UTC).replace(microsecond=0).isoformat()
        changed = apply_series_migration(args.root, report, timestamp=timestamp)
    if args.check:
        check_report(report, args.root)
    print(json.dumps({"report": str(args.report), "migrated_sidecars": changed, "ok": True}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
