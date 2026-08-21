"""Remove owner-approved false ``files.variants`` links without touching Q-IDs."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fine_art_archive import sidecar
from fine_art_archive.identity.variant_identity import work_qid_of

__all__ = [
    "ReciprocalUnlinkPlan",
    "ReciprocalUnlinkResult",
    "ReciprocalUnlinkStats",
    "plan_reciprocal_unlink",
    "remediate_reciprocal_false_variants",
]


@dataclass(frozen=True)
class ReciprocalUnlinkPlan:
    """One directed unlink in a reciprocal false-variant pair."""

    work_id: str
    sidecar_path: Path
    target_work_id: str
    target_rel_path: str
    qid_before: str | None
    variant_count_before: int


@dataclass(frozen=True)
class ReciprocalUnlinkResult:
    """Outcome for one sidecar after remediation."""

    work_id: str
    removed_rel_path: str | None
    qid_after: str | None
    variant_count_after: int
    wrote: bool


@dataclass(frozen=True)
class ReciprocalUnlinkStats:
    planned: int
    removed: int
    wrote: int


def _sidecar_path(art_works_root: Path, work_id: str) -> Path:
    candidates = (
        art_works_root / "works" / work_id / "meta.json",
        art_works_root / work_id / "meta.json",
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    raise FileNotFoundError(f"no meta.json found for {work_id!r} under {art_works_root}")


def _variant_rel_path(target_work_id: str) -> str:
    return f"works/{target_work_id}/master.jpeg"


def _remove_variant_entry(meta: dict[str, Any], target_work_id: str) -> str | None:
    files = meta.get("files")
    if not isinstance(files, Mapping):
        return None
    variants = files.get("variants")
    if not isinstance(variants, list):
        return None
    rel_path = _variant_rel_path(target_work_id)
    kept: list[Any] = []
    removed: str | None = None
    for variant in variants:
        if isinstance(variant, Mapping) and variant.get("rel_path") == rel_path:
            removed = rel_path
            continue
        kept.append(variant)
    if removed is None:
        return None
    if kept:
        files["variants"] = kept
    else:
        files.pop("variants", None)
    return removed


def plan_reciprocal_unlink(
    art_works_root: Path, work_id_a: str, work_id_b: str
) -> list[ReciprocalUnlinkPlan]:
    """Plan reciprocal unlink operations for two linked works."""
    plans: list[ReciprocalUnlinkPlan] = []
    for owner_id, target_id in ((work_id_a, work_id_b), (work_id_b, work_id_a)):
        path = _sidecar_path(art_works_root, owner_id)
        meta = sidecar.load(path)
        files = meta.get("files")
        variants = files.get("variants") if isinstance(files, Mapping) else None
        variant_count = len(variants) if isinstance(variants, list) else 0
        plans.append(
            ReciprocalUnlinkPlan(
                work_id=owner_id,
                sidecar_path=path,
                target_work_id=target_id,
                target_rel_path=_variant_rel_path(target_id),
                qid_before=work_qid_of(meta),
                variant_count_before=variant_count,
            )
        )
    return plans


def remediate_reciprocal_false_variants(
    art_works_root: Path,
    work_id_a: str,
    work_id_b: str,
    *,
    grant: str,
    actor: str,
    apply: bool = False,
    operations_log: Path | None = None,
) -> tuple[ReciprocalUnlinkStats, list[ReciprocalUnlinkResult]]:
    """Remove reciprocal ``files.variants`` entries while preserving work Q-IDs."""
    plans = plan_reciprocal_unlink(art_works_root, work_id_a, work_id_b)
    results: list[ReciprocalUnlinkResult] = []
    removed = wrote = 0
    ts = datetime.now(UTC).isoformat().replace("+00:00", "Z")

    for plan in plans:
        meta = sidecar.load(plan.sidecar_path)
        qid_before = work_qid_of(meta)
        removed_rel = _remove_variant_entry(meta, plan.target_work_id)
        if removed_rel is not None:
            removed += 1
            sidecar.merge_history(
                meta,
                {
                    "ts": ts,
                    "actor": actor,
                    "op": "remove-false-variant-link",
                    "to": plan.target_rel_path,
                    "notes": (
                        f"{grant}; removed mistaken reciprocal variant link to "
                        f"{plan.target_work_id}; preserved work Q-ID {qid_before!r}"
                    ),
                },
            )
        qid_after = work_qid_of(meta)
        if qid_before != qid_after:
            raise ValueError(
                f"{plan.work_id}: Q-ID changed during unlink "
                f"({qid_before!r} -> {qid_after!r}); aborting"
            )
        files = meta.get("files")
        variants = files.get("variants") if isinstance(files, Mapping) else None
        variant_count_after = len(variants) if isinstance(variants, list) else 0
        did_write = False
        if apply and removed_rel is not None:
            sidecar.write(plan.sidecar_path, meta)
            did_write = True
            wrote += 1
            if operations_log is not None:
                _append_operation(
                    operations_log,
                    work_id=plan.work_id,
                    actor=actor,
                    grant=grant,
                    removed_rel_path=removed_rel,
                    qid_preserved=qid_after,
                    sidecar_path=plan.sidecar_path,
                )
        results.append(
            ReciprocalUnlinkResult(
                work_id=plan.work_id,
                removed_rel_path=removed_rel,
                qid_after=qid_after,
                variant_count_after=variant_count_after,
                wrote=did_write,
            )
        )
    stats = ReciprocalUnlinkStats(planned=len(plans), removed=removed, wrote=wrote)
    return stats, results


def _append_operation(
    log_path: Path,
    *,
    work_id: str,
    actor: str,
    grant: str,
    removed_rel_path: str,
    qid_preserved: str | None,
    sidecar_path: Path,
) -> None:
    entry = {
        "ts": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "actor": actor,
        "op": "remove_false_variant_link",
        "work_id": work_id,
        "grant": grant,
        "removed_rel_path": removed_rel_path,
        "qid_preserved": qid_preserved,
        "sidecar_path": str(sidecar_path),
    }
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")
