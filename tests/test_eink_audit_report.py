"""The e-ink divergence audit must stay reproducible against the code.

The audit in ``docs/reports/eink_surface_divergence_audit.md`` is the
record that preview, saved-feed and export surfaces share one selection
contract. It is only worth keeping if it cannot silently drift from the
production ``PlaylistSpec`` inventory or lose the saved-feed preview
classification (#883), so this test pins both.
"""

from __future__ import annotations

import re
from pathlib import Path

from fine_art_archive.eink import PlaylistSpec

REPORT = Path(__file__).resolve().parents[1] / "docs/reports/eink_surface_divergence_audit.md"

DISPOSITIONS = (
    "already-correct",
    "confirmed-bug",
    "needs-investigation",
    "intentionally-unsupported",
)


def _report() -> str:
    return REPORT.read_text(encoding="utf-8")


def _field_rows(text: str) -> dict[str, str]:
    rows: dict[str, str] = {}
    for line in text.splitlines():
        match = re.match(r"\| `([a-z_]+)` \| ([a-z-]+) \|", line)
        if match:
            assert match.group(1) not in rows, f"duplicate audit row for {match.group(1)}"
            rows[match.group(1)] = match.group(2)
    return rows


def test_audit_report_matrix_and_classification_are_reproducible():
    text = _report()

    # One inspected revision anchors every source claim in the report.
    assert "Inspected source revision: `" in text

    # Every PlaylistSpec field has exactly one matrix row (the duplicate-row
    # assertion in _field_rows fires otherwise), with exactly one valid
    # disposition and no retired shorthand.
    rows = _field_rows(text)
    assert set(rows) == set(PlaylistSpec.__dataclass_fields__)
    assert len(rows) == 17
    for field, disposition in rows.items():
        assert disposition in DISPOSITIONS, f"{field}: unknown disposition {disposition!r}"

    # Saved-setting precedence is classified separately per surface: the
    # preview row must not borrow the export row's already-correct verdict.
    s1_row = text.split("| S1 |", 1)[1].splitlines()[0]
    s2_row = text.split("| S2 |", 1)[1].splitlines()[0]
    assert "needs-investigation" in s1_row
    assert "already-correct" in s2_row

    # The banner/parity-caption conflict and its dedup boundary stay recorded.
    assert "filters above are ignored" in text
    assert "same fit, range compression and dither as the card" in text
    for candidate in ("#825", "#826", "#827", "#883"):
        assert candidate in text

    # Historical receipts are labelled historical, never current validation.
    assert "## Historical receipts (historical, not current validation)" in text
