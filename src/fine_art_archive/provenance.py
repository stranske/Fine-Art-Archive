"""Helpers for the additive per-field sidecar research ledger."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

STATUSES = frozenset({"not_researched", "available", "not_available", "unverified", "conflicting"})
FILENAME_BACKFILLED_FIELDS = ("medium", "category", "dimensions_original")


def get(sidecar: dict[str, Any], field: str) -> dict[str, Any] | None:
    """Return a field's provenance entry, if one has been recorded."""
    provenance = sidecar.get("field_provenance")
    if not isinstance(provenance, dict):
        return None
    entry = provenance.get(field)
    return entry if isinstance(entry, dict) else None


def set(
    sidecar: dict[str, Any],
    field: str,
    status: str,
    source: str | None = None,
    source_ref: str | None = None,
    checked_at: str | None = None,
    note: str | None = None,
) -> dict[str, Any]:
    """Record and return provenance for ``field``, stamping ``checked_at`` by default."""
    if status not in STATUSES:
        raise ValueError(f"unsupported provenance status: {status}")

    provenance = sidecar.setdefault("field_provenance", {})
    if not isinstance(provenance, dict):
        raise ValueError("field_provenance must be an object")

    entry = {
        "status": status,
        "source": source,
        "source_ref": source_ref,
        "checked_at": checked_at or _utc_now(),
        "note": note,
    }
    provenance[field] = entry
    return entry


def needs_research(sidecar: dict[str, Any], field: str) -> bool:
    """Return whether ``field`` lacks research or has unresolved/unverified evidence."""
    entry = get(sidecar, field)
    return entry is None or entry.get("status") in {
        "not_researched",
        "unverified",
        "conflicting",
    }


def mark_filename_backfilled_fields(sidecar: dict[str, Any]) -> list[str]:
    """Mark present filename-backfilled values unverified without changing their values.

    This is the one-time migration helper for the 2026-07-24 filename backfill.
    Existing provenance is retained because a later authoritative source must not be
    downgraded merely because the value was once filename-derived.
    """
    marked: list[str] = []
    for field in FILENAME_BACKFILLED_FIELDS:
        if field in sidecar and sidecar[field] is not None and get(sidecar, field) is None:
            set(
                sidecar,
                field,
                "unverified",
                "filename_backfill",
                note="Value was backfilled from a filename; verify against an authoritative source.",
            )
            marked.append(field)
    return marked


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
