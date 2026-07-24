"""Helpers for the additive per-field sidecar research ledger."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

STATUS_ORDER = (
    "not_researched",
    "available",
    "not_available",
    "unverified",
    "conflicting",
)
STATUSES = frozenset(STATUS_ORDER)
FILENAME_BACKFILLED_FIELDS = ("medium", "category", "dimensions_original")
COMPLETENESS_FIELDS = (
    "holder",
    "year",
    "medium",
    "category",
    "dimensions_original",
    "artist_qid",
)
_LOSING_VALUE_MARKER = "Higher-tier source replaced lower-tier existing value "


@dataclass(frozen=True)
class FieldCompleteness:
    """Status counts for one field across the whole sidecar corpus."""

    field: str
    total_works: int
    counts: Mapping[str, int]

    def count(self, status: str) -> int:
        """Return the count for a supported provenance status."""
        if status not in STATUSES:
            raise ValueError(f"unsupported provenance status: {status}")
        return self.counts[status]

    def percentage(self, status: str) -> float:
        """Return this status' percentage of all scanned works."""
        if self.total_works == 0:
            return 0.0
        return self.count(status) * 100 / self.total_works


@dataclass(frozen=True)
class Conflict:
    """One unresolved source disagreement exposed for optional review."""

    work_id: str
    field: str
    kept_value: Any
    kept_source: str | None
    losing_value: Any
    losing_source: str | None
    note: str | None


@dataclass(frozen=True)
class CompletenessReport:
    """Read-only aggregate of field coverage and source conflicts."""

    total_works: int
    fields: tuple[FieldCompleteness, ...]
    conflicts: tuple[Conflict, ...]


def completeness_report(
    sidecars: Iterable[Mapping[str, Any]],
    *,
    baseline_fields: Iterable[str] = COMPLETENESS_FIELDS,
) -> CompletenessReport:
    """Aggregate per-field coverage without modifying any input sidecar.

    The initiative's holder and five resolver fields are always included so a
    corpus with no ledger entries still reports them as ``not_researched``.
    Any additional fields found in ``field_provenance`` are included as well.
    """
    corpus = tuple(sidecars)
    fields = {*baseline_fields}
    for meta in corpus:
        ledger = meta.get("field_provenance")
        if isinstance(ledger, Mapping):
            fields.update(str(field) for field in ledger)

    ordered_fields = [field for field in COMPLETENESS_FIELDS if field in fields]
    ordered_fields.extend(sorted(fields.difference(ordered_fields)))
    counts_by_field = {field: dict.fromkeys(STATUS_ORDER, 0) for field in ordered_fields}
    conflicts: list[Conflict] = []

    for meta in corpus:
        ledger = meta.get("field_provenance")
        entries = ledger if isinstance(ledger, Mapping) else {}
        for field in ordered_fields:
            raw_entry = entries.get(field)
            entry = raw_entry if isinstance(raw_entry, Mapping) else None
            raw_status = entry.get("status") if entry is not None else None
            status = raw_status if isinstance(raw_status, str) else "not_researched"
            if status not in STATUSES:
                work_id = str(meta.get("work_id") or "<unknown>")
                raise ValueError(f"unsupported provenance status {status!r} for {work_id}.{field}")
            counts_by_field[field][status] += 1
            if status == "conflicting" and entry is not None:
                conflicts.append(_conflict(meta, field, entry))

    field_rows = tuple(
        FieldCompleteness(field, len(corpus), counts_by_field[field]) for field in ordered_fields
    )
    return CompletenessReport(
        total_works=len(corpus),
        fields=field_rows,
        conflicts=tuple(sorted(conflicts, key=lambda item: (item.work_id, item.field))),
    )


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


def _conflict(
    sidecar: Mapping[str, Any],
    field: str,
    entry: Mapping[str, Any],
) -> Conflict:
    note = entry.get("note")
    note_text = note if isinstance(note, str) else None
    losing_value = _losing_value(note_text)
    source = entry.get("source")
    return Conflict(
        work_id=str(sidecar.get("work_id") or "<unknown>"),
        field=field,
        kept_value=_field_value(sidecar, field),
        kept_source=source if isinstance(source, str) else None,
        losing_value=losing_value,
        # The current ledger schema records only the kept source. Do not guess
        # the overwritten source when older conflict notes do not contain it.
        losing_source=None,
        note=note_text,
    )


def _field_value(sidecar: Mapping[str, Any], field: str) -> Any:
    if field == "artist_qid":
        artist = sidecar.get("artist")
        return artist.get("wikidata_q") if isinstance(artist, Mapping) else None
    return sidecar.get(field)


def _losing_value(note: str | None) -> Any:
    if note is None:
        return None
    marker_at = note.find(_LOSING_VALUE_MARKER)
    if marker_at < 0:
        return None
    encoded = note[marker_at + len(_LOSING_VALUE_MARKER) :]
    try:
        value, _ = json.JSONDecoder().raw_decode(encoded)
    except json.JSONDecodeError:
        return None
    return value


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")
