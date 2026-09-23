#!/usr/bin/env python3
"""Build ``weekly_review_<date>.json`` from current archive measurements.

The builder is read-only with respect to archive inputs.  Its only write is the
dated JSON report consumed by :mod:`render_weekly_review`.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from datetime import date, timedelta
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fine_art_archive.api.config import DEFAULT_ART_WORKS_ROOT, env_path  # noqa: E402
from fine_art_archive.identity.artist_qid import artist_qid  # noqa: E402
from fine_art_archive.identity.work_qid_collision_audit import (  # noqa: E402
    actionable_offenders,
    measure_work_qid_collisions,
    measures_as_dict,
)
from fine_art_archive.known_works.artwork_classes import ALLOWED_P31  # noqa: E402

REPORTS = ROOT / "docs" / "reports"
DRAWING_QID = "Q93184"
P31_LABELS = {
    "Q179700": "statue",
    "Q838948": "work of art",
    "Q860861": "sculpture",
    "Q93184": "drawing",
    "Q3305213": "painting",
    "Q4502142": "visual artwork",
    "Q11060274": "print",
    "Q15711026": "altarpiece",
    "Q15727816": "painting series",
    "Q18761202": "watercolor painting",
}


def _norm(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "")
    value = "".join(char for char in value if not unicodedata.combining(char)).lower()
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read JSON from {path}: {exc}") from exc


def _title(meta: Mapping[str, Any]) -> str:
    value = meta.get("title")
    if isinstance(value, Mapping):
        return str(value.get("canonical") or value.get("raw") or "")
    return str(value or "")


def _artist(meta: Mapping[str, Any]) -> str:
    value = meta.get("artist")
    if not isinstance(value, Mapping):
        return str(value or "")
    canonical = value.get("canonical")
    if isinstance(canonical, Mapping):
        return str(canonical.get("display_name") or canonical.get("name") or "")
    return str(value.get("name") or "")


def _artist_qid(meta: Mapping[str, Any]) -> str:
    return artist_qid(dict(meta)) or ""


def _master(work_dir: Path) -> Path | None:
    matches = sorted(work_dir.glob("master.*"))
    return matches[0] if matches else None


def _size_mb(path: Path | None) -> float | None:
    if path is None:
        return None
    try:
        return round(path.stat().st_size / 1_048_576, 1)
    except OSError:
        return None


def load_sidecars(works_root: Path) -> list[dict[str, Any]]:
    if not works_root.is_dir():
        raise ValueError(f"works root is not a readable directory: {works_root}")
    rows: list[dict[str, Any]] = []
    for work_dir in sorted(path for path in works_root.iterdir() if path.is_dir()):
        meta_path = work_dir / "meta.json"
        if not meta_path.is_file():
            continue
        raw = _read_json(meta_path)
        if not isinstance(raw, dict):
            raise ValueError(f"sidecar must be a JSON object: {meta_path}")
        meta = dict(raw)
        existing_id = meta.get("work_id")
        if existing_id not in (None, "", work_dir.name):
            raise ValueError(
                f"sidecar work_id {existing_id!r} does not match directory {work_dir.name!r}"
            )
        meta["work_id"] = work_dir.name
        meta["_work_dir"] = str(work_dir)
        rows.append(meta)
    return rows


def grant_authority_from_permissions(text: str) -> dict[str, Any]:
    promotion: set[str] = set()
    standing: set[str] = set()
    scopes: dict[str, str] = {}
    for raw in text.splitlines():
        if not raw.lstrip().startswith("|"):
            continue
        columns = [part.strip() for part in raw.strip().strip("|").split("|")]
        if len(columns) < 5 or not re.fullmatch(r"G[0-9]+[a-z]?", columns[0]):
            continue
        grant, scope, operation, term = columns[0], columns[2], columns[3], columns[4]
        scopes[grant] = scope
        operation_plain = re.sub(r"[*_~`]", "", operation)
        operation_lower = operation_plain.lower()
        scope_lower = re.sub(r"[*_~`]", "", scope).lower()
        direct_destination = bool(
            re.search(r"(?:→|->|\bto\b)\s*Art/works(?:/|\b)", operation_plain)
        )
        permitted = (
            "promot" in f"{scope_lower} {operation_lower}"
            or ("write-new" in operation_lower and "Art/works" in operation_plain)
            or (direct_destination and "restore" not in operation_lower)
        )
        if not permitted:
            continue
        promotion.add(grant)
        term_plain = re.sub(r"[*_~`]", "", term).lower()
        not_standing = bool(
            re.search(r"\b(?:not|never)\s+standing\b", term_plain)
            or "one-time" in term_plain
            or "one supervised run" in term_plain
        )
        if "standing" in term_plain and not not_standing:
            standing.add(grant)
    return {
        "promotion_authorized": sorted(promotion),
        "standing_acquisition": sorted(standing),
        "scopes": dict(sorted(scopes.items())),
    }


def collect_ops(path: Path, works_root: Path, since: str) -> dict[str, list[dict[str, str]]]:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        raise ValueError(f"cannot read operations log {path}: {exc}") from exc
    promotions: list[dict[str, str]] = []
    removals: list[dict[str, str]] = []
    restores: list[dict[str, str]] = []
    root_text = str(works_root.resolve())
    for raw in lines:
        if not raw.startswith("20"):
            continue
        parts = [part.strip() for part in raw.split("|")]
        if len(parts) < 5 or parts[0][:10] < since:
            continue
        timestamp, grant, operation, source, destination = parts[:5]
        note = parts[6] if len(parts) > 6 else ""
        source_live = source == root_text or source.startswith(f"{root_text}/")
        destination_live = destination == root_text or destination.startswith(f"{root_text}/")
        selected = destination if destination_live else source
        relative = selected[len(root_text) :].lstrip("/") if selected.startswith(root_text) else ""
        work_id = relative.split("/", 1)[0] if relative else ""
        record = {"ts": timestamp, "grant": grant, "wid": work_id, "note": note}
        if destination_live and not source_live:
            if "restored from quarantine" in note.lower():
                restores.append(record)
            elif not destination.endswith("meta.json") and (
                "master" in destination.lower()
                or "promot" in note.lower()
                or "promot" in operation.lower()
            ):
                promotions.append(record)
        elif source_live and not destination_live:
            removals.append(record)
    return {"promotions": promotions, "removals": removals, "restores": restores}


def collect_ungranted(
    promotions: Iterable[Mapping[str, str]],
    promotion_grants: set[str],
    works_root: Path,
    by_id: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for promotion in promotions:
        if promotion.get("grant") in promotion_grants:
            continue
        work_id = str(promotion.get("wid") or "")
        meta = by_id.get(work_id, {})
        master = _master(works_root / work_id)
        grouped[str(promotion.get("grant") or "unrecorded")].append(
            {
                "wid": work_id,
                "title": _title(meta) or work_id,
                "artist": _artist(meta),
                "master": str(master) if master else "",
                "size_mb": _size_mb(master),
                "batch": "operations.log",
            }
        )
    ordered = {grant: grouped[grant] for grant in sorted(grouped)}
    return {"by_grant": ordered, "total": sum(map(len, ordered.values()))}


def _frontier_rows(frontier: Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if isinstance(frontier, dict):
        candidates = frontier.get("candidates", [])
        if isinstance(candidates, dict):
            rows = [dict(value, qid=value.get("qid", key)) for key, value in candidates.items()]
        elif isinstance(candidates, list):
            rows = [dict(value) for value in candidates if isinstance(value, dict)]
        else:
            raise ValueError("frontier candidates must be a list or object")
        return rows, frontier
    if isinstance(frontier, list):
        return [dict(value) for value in frontier if isinstance(value, dict)], {}
    raise ValueError("frontier must be a JSON list or object")


def collect_candidates(
    frontier_path: Path, sidecars: Sequence[Mapping[str, Any]], limit: int = 25
) -> dict[str, Any]:
    rows, frontier = _frontier_rows(_read_json(frontier_path))
    held_by_artist: dict[str, list[str]] = defaultdict(list)
    for meta in sidecars:
        artist_qid = _artist_qid(meta)
        if artist_qid:
            held_by_artist[artist_qid].append(_title(meta) or str(meta["work_id"]))
    screened = [row for row in rows if row.get("status") == "screened"]
    screened.sort(key=lambda row: (-int(row.get("sitelinks") or 0), str(row.get("qid") or "")))
    top: list[dict[str, Any]] = []
    for row in screened[:limit]:
        qid = str(row.get("qid") or "")
        artist_qid = str(row.get("artist_qid") or "")
        held = sorted(held_by_artist.get(artist_qid, []))
        image_url = str(row.get("image_url") or row.get("thumb") or "")
        top.append(
            {
                "qid": qid,
                "title": str(row.get("title") or qid),
                "artist_qid": artist_qid,
                "artist": str(row.get("artist") or artist_qid or "not recorded"),
                "sitelinks": int(row.get("sitelinks") or 0),
                "generator": row.get("generator"),
                "thumb": image_url,
                "wikidata_url": f"https://www.wikidata.org/wiki/{qid}" if qid else "",
                "held_count": len(held),
                "held_titles": held[:12],
                "screen_scores": row.get("screen_scores") or {},
            }
        )
    latest = (frontier.get("runs") or [{}])[-1] if isinstance(frontier, dict) else {}
    merge = latest.get("merge") or {} if isinstance(latest, dict) else {}
    return {
        "top": top,
        "frontier_total": len(rows),
        "by_status": dict(
            sorted(Counter(str(row.get("status") or "unknown") for row in rows).items())
        ),
        "latest_run": {
            "ts": latest.get("ts") if isinstance(latest, dict) else None,
            "raw_by_generator": latest.get("per_generator_raw") or {},
            "admitted_by_generator": merge.get("per_generator") or {},
            "added": merge.get("added", 0),
            "capped": merge.get("capped", 0),
        },
    }


def collect_unpromoted(
    staging_root: Path,
    works_root: Path,
    sidecars: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    if not staging_root.is_dir():
        raise ValueError(f"staging root is not a readable directory: {staging_root}")
    held_titles = {_norm(_title(meta)): str(meta["work_id"]) for meta in sidecars if _title(meta)}
    rows: list[dict[str, Any]] = []
    for staged_dir in sorted(path for path in staging_root.iterdir() if path.is_dir()):
        if (works_root / staged_dir.name).is_dir():
            continue
        master = _master(staged_dir)
        if master is None:
            continue
        meta_path = staged_dir / "meta.json"
        raw = _read_json(meta_path) if meta_path.is_file() else {}
        meta = raw if isinstance(raw, dict) else {}
        title = _title(meta) or staged_dir.name
        collision = held_titles.get(_norm(title), "")
        collision_master = _master(works_root / collision) if collision else None
        rows.append(
            {
                "wid": staged_dir.name,
                "title": title,
                "artist": _artist(meta),
                "staged_master": str(master),
                "size_mb": _size_mb(master),
                "title_collision_with": collision,
                "collision_master": str(collision_master) if collision_master else "",
            }
        )
    return rows


def collect_collisions(
    sidecars: Sequence[Mapping[str, Any]], works_root: Path, limit: int = 6
) -> dict[str, Any]:
    measures = measure_work_qid_collisions(sidecars)
    all_actionable = actionable_offenders(sidecars, limit=max(len(sidecars), 1))
    actionable = dict(list(all_actionable.items())[:limit])
    by_id = {str(meta["work_id"]): meta for meta in sidecars}
    worst = []
    for qid, work_ids in actionable.items():
        worst.append(
            {
                "qid": qid,
                "label": "label not recorded",
                "n": len(work_ids),
                "wikidata_url": f"https://www.wikidata.org/wiki/{qid}",
                "examples": [
                    {
                        "wid": work_id,
                        "title": _title(by_id[work_id]) or work_id,
                        "master": str(_master(works_root / work_id) or ""),
                    }
                    for work_id in work_ids[:8]
                ],
            }
        )
    return {
        "worst": worst,
        "qids_on_multiple": measures.actionable_qids,
        "extra_assignments": sum(len(work_ids) - 1 for work_ids in all_actionable.values()),
        "raw_measures": measures_as_dict(measures),
    }


def collect_allowed_p31() -> dict[str, Any]:
    qids = sorted(ALLOWED_P31, key=lambda qid: int(qid[1:]))
    return {
        "definitions": [
            {
                "file": "fine_art_archive.known_works.artwork_classes.ALLOWED_P31",
                "classes": [
                    {"qid": qid, "label": P31_LABELS.get(qid, "label not recorded")} for qid in qids
                ],
            }
        ],
        "dropped": {"qid": DRAWING_QID, "label": P31_LABELS[DRAWING_QID]},
    }


def build_review(
    *,
    review_date: str,
    since: str,
    works_root: Path,
    staging_root: Path,
    frontier_path: Path,
    operations_log: Path,
    permissions_path: Path,
) -> dict[str, Any]:
    date.fromisoformat(review_date)
    date.fromisoformat(since)
    sidecars = load_sidecars(works_root)
    by_id = {str(meta["work_id"]): meta for meta in sidecars}
    try:
        permissions = permissions_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ValueError(f"cannot read grant ledger {permissions_path}: {exc}") from exc
    grants = grant_authority_from_permissions(permissions)
    ops = collect_ops(operations_log, works_root, since)
    return {
        "generated": review_date,
        "ops_window_start": since,
        "live_works": len(sidecars),
        "ops": ops,
        "grants": grants,
        "ungranted": collect_ungranted(
            ops["promotions"], set(grants["promotion_authorized"]), works_root, by_id
        ),
        "candidates": collect_candidates(frontier_path, sidecars),
        "unpromoted": collect_unpromoted(staging_root, works_root, sidecars),
        "collisions": collect_collisions(sidecars, works_root),
        "allowed_p31": collect_allowed_p31(),
    }


def write_review(payload: Mapping[str, Any], reports_dir: Path, review_date: str) -> Path:
    reports_dir.mkdir(parents=True, exist_ok=True)
    destination = reports_dir / f"weekly_review_{review_date}.json"
    temporary = destination.with_name(f".{destination.name}.tmp")
    serialized = json.dumps(payload, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    temporary.write_text(serialized, encoding="utf-8")
    temporary.replace(destination)
    return destination


def _default_staging_root(works_root: Path) -> Path:
    return env_path("FAA_STAGING_ROOT", works_root.parent / "staging_acquisitions")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--since")
    parser.add_argument(
        "--works-root", type=Path, default=env_path("FAA_WORKS_DIR", DEFAULT_ART_WORKS_ROOT)
    )
    parser.add_argument("--staging-root", type=Path)
    parser.add_argument("--frontier", type=Path, default=ROOT / "discovery_frontier.json")
    parser.add_argument("--operations-log", type=Path, default=ROOT / "operations.log")
    parser.add_argument("--permissions", type=Path, default=ROOT / "permissions.md")
    parser.add_argument("--reports-dir", type=Path, default=REPORTS)
    args = parser.parse_args(argv)
    try:
        review_day = date.fromisoformat(args.date)
        review_date = review_day.isoformat()
        since = (
            date.fromisoformat(args.since) if args.since else review_day - timedelta(days=7)
        ).isoformat()
        staging_root = args.staging_root or _default_staging_root(args.works_root)
        payload = build_review(
            review_date=review_date,
            since=since,
            works_root=args.works_root,
            staging_root=staging_root,
            frontier_path=args.frontier,
            operations_log=args.operations_log,
            permissions_path=args.permissions,
        )
        destination = write_review(payload, args.reports_dir, review_date)
    except (OSError, ValueError, TypeError) as exc:
        parser.error(str(exc))
    print(f"wrote {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
