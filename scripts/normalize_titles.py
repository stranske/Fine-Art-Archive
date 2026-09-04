#!/usr/bin/env python3
"""Normalize corrupted ``title`` values for a fixed set of hand-reviewed works.

A small cluster of works carry titles that are photo-caption fragments,
Wikimedia filenames, or catalogue lines with the artist, the year, and/or a
leading list number folded into the title string ("30. Calvin Coolidge, 1919",
"Baturraden_overview_from_ridge", "... - Friederich"). These strings are wrong
as *titles*: they defeat human browsing and every downstream match that keys on
the title (work-QID resolution, medium lookup, categorisation).

Rather than a fuzzy rule-based stripper -- which would mangle legitimate titles
that happen to contain a dash, a parenthetical, or a trailing name -- this pass
applies an explicit, reviewed correction **keyed by work_id**. The correct work
title for each entry was recovered by hand from the slug, the resolved artist,
and the visible catalogue noise; every entry records the exact ``expected``
current title so the pass refuses to touch a sidecar whose title has since
drifted. Nothing outside the map is ever modified.

Scope is deliberately ``title`` only. The artist-resolution pipeline owns the
``artist`` object (several of these works additionally have junk in
``artist.name`` -- e.g. "1907-1908Oil on canvas", "_Ingushetia" -- which is left
for :mod:`backfill_artist_qids` and is reported, not fixed, here).

Dry-run by default (reports what *would* change); ``--apply`` writes. On write it
records ``field_provenance`` for ``title`` (status ``available`` + source
``curated``), mirrors to the canonical Art/works tree, and appends to
operations.log -- the same pass shape as :mod:`backfill_categories`.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "src"))

from _paths import default_works_dir  # noqa: E402
from _sidecar_io import script_env_path as _env_path  # noqa: E402
from _sidecar_io import write_existing_mirrors as _write_existing_mirrors  # noqa: E402

from fine_art_archive import provenance, sidecar  # noqa: E402

DEFAULT_LIMIT = 100_000


@dataclass(frozen=True)
class TitleFix:
    """One reviewed title correction, guarded by the title it replaces."""

    expected: str  # current (corrupted) title; a drifted title is skipped, not clobbered
    title: str  # the corrected work title to write
    note: str  # what was removed/reconstructed, for the provenance ledger


# work_id -> reviewed correction. Only works whose title actually changes are
# listed; the other uncategorised works in this cluster already have clean
# titles (e.g. "An Old Woman Cooking Eggs") and are intentionally absent.
TITLE_CORRECTIONS: dict[str, TitleFix] = {
    "0a005ef-the-shipbuilder-and-his-wife-jan": TitleFix(
        expected="Griet Jans -",
        title="The Shipbuilder and His Wife",
        note="Reconstructed Rembrandt work title from caption fragment 'Griet Jans -'.",
    ),
    "20f8c49-19-rutherford-b-hayes": TitleFix(
        expected="19. Rutherford B. Hayes",
        title="Rutherford B. Hayes",
        note="Removed leading list number '19. '.",
    ),
    "3e0f4cf-marxism-will-give-health-to-the-masonite": TitleFix(
        expected="Marxism Will Give Health to the Ill, Kahlo, 1954",
        title="Marxism Will Give Health to the Ill",
        note="Removed embedded artist/year ', Kahlo, 1954'.",
    ),
    "4a067a9-aeneas-taken-by-the-sibyl-to": TitleFix(
        expected="Aeneas taken by the Sibyl to the Underworld (Swanenburgh)",
        title="Aeneas taken by the Sibyl to the Underworld",
        note="Removed trailing artist '(Swanenburgh)'.",
    ),
    "79b8431-sharing-the-cake-bertiers": TitleFix(
        expected="Sharing the cake - Bertiers",
        title="Sharing the cake",
        note="Removed trailing artist ' - Bertiers'.",
    ),
    "7a54bbd-rembrandt-laughing-about-1628": TitleFix(
        expected="Rembrandt Laughing, about 1628",
        title="Rembrandt Laughing",
        note="Removed embedded date ', about 1628'.",
    ),
    "817dc64-aeneas-taken-by-the-sibyl-to": TitleFix(
        expected="Aeneas taken by the Sibyl to the Underworld (Swanenburgh)",
        title="Aeneas taken by the Sibyl to the Underworld",
        note="Removed trailing artist '(Swanenburgh)'.",
    ),
    "887c6d2-baturraden-overview-from-ridge-purwokerto": TitleFix(
        expected="Baturraden_overview_from_ridge",
        title="Baturraden overview from ridge",
        note="Replaced Wikimedia-filename underscores with spaces.",
    ),
    "a518eab-ulysses-companions-meet-the-daughter-of-292": TitleFix(
        expected="Ulysses companions meet the daughter of the King of the Laestrygonians (left)",
        title="Ulysses companions meet the daughter of the King of the Laestrygonians",
        note="Removed panel marker ' (left)'.",
    ),
    "acc7461-ulysses-simpson-grant-mathew-brady-studio-negative": TitleFix(
        expected="Ulysses Simpson Grant, Mathew Brady Studio, 1860-70",
        title="Ulysses Simpson Grant",
        note="Removed embedded studio/date ', Mathew Brady Studio, 1860-70'.",
    ),
    "b44ff28-pennsylvania-station-excavation-george-wesley-bellows-canvas": TitleFix(
        expected="Pennsylvania Station Excavation George Wesley Bellows",
        title="Pennsylvania Station Excavation",
        note="Removed trailing artist ' George Wesley Bellows'.",
    ),
    "bd7244f-30-calvin-coolidge-1919": TitleFix(
        expected="30. Calvin Coolidge, 1919",
        title="Calvin Coolidge",
        note="Removed leading list number '30. ' and trailing year ', 1919'.",
    ),
    "be762ad-kitchen-still-life-with-a-maid": TitleFix(
        expected="Kitchen Still Life with a Maid and Young Boy, mid-17th century",
        title="Kitchen Still Life with a Maid and Young Boy",
        note="Removed embedded date ', mid-17th century'.",
    ),
    "d3f98c4-37-richard-nixon-1973": TitleFix(
        expected="37. Richard Nixon, 1973",
        title="Richard Nixon",
        note="Removed leading list number '37. ' and trailing year ', 1973'.",
    ),
    "d7869c2-34-dwight-eisenhower-june-1956": TitleFix(
        expected="34. Dwight Eisenhower, June 1956",
        title="Dwight Eisenhower",
        note="Removed leading list number '34. ' and trailing date ', June 1956'.",
    ),
    "d9f625c-rocky-landscape-in-the-elbe-sandstone": TitleFix(
        expected="Rocky Landscape in the Elbe Sandstone Mountains - Friederich",
        title="Rocky Landscape in the Elbe Sandstone Mountains",
        note="Removed trailing artist ' - Friederich' (Caspar David Friedrich).",
    ),
    "eda2a3e-portrait-of-a-young-man-16th": TitleFix(
        expected="Portrait of a Young Man (16th-17th Century)",
        title="Portrait of a Young Man",
        note="Removed trailing date range ' (16th-17th Century)'.",
    ),
}


@dataclass
class TitleNormalizeStats:
    attempted: int  # works in the correction map found on disk
    updated: int  # sidecars whose title was rewritten (0 in dry-run)
    mirrored: int  # canonical mirrors written
    missing: list[str] = field(default_factory=list)  # work_ids not found on disk
    skipped_drift: list[str] = field(default_factory=list)  # title != expected


def _staging_path(staging_dir: Path, work_id: str) -> Path | None:
    """Locate the staging sidecar for ``work_id`` (nested dir or flat file)."""
    for candidate in (staging_dir / work_id / "meta.json", staging_dir / f"{work_id}.json"):
        if candidate.is_file():
            return candidate
    return None


def _apply_fix(meta: dict[str, Any], fix: TitleFix) -> None:
    meta["title"] = fix.title
    provenance.set(meta, "title", "available", "curated", note=fix.note)


def _append_operation(
    log_path: Path,
    meta: dict[str, Any],
    fix: TitleFix,
    staging_path: Path,
    mirror_paths: list[Path],
) -> None:
    entry = {
        "ts": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "actor": "normalize_titles",
        "op": "title_normalization",
        "work_id": meta["work_id"],
        "old_title": fix.expected,
        "new_title": fix.title,
        "note": fix.note,
        "staging_path": str(staging_path),
        "mirror_paths": [str(path) for path in mirror_paths],
    }
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")


def normalize_titles(
    staging_dir: Path,
    *,
    corrections: dict[str, TitleFix] = TITLE_CORRECTIONS,
    art_works_root: Path | None = None,
    operations_log: Path | None = None,
    limit: int = DEFAULT_LIMIT,
    apply: bool = False,
) -> TitleNormalizeStats:
    if limit < 1:
        raise ValueError("limit must be at least 1")
    stats = TitleNormalizeStats(attempted=0, updated=0, mirrored=0)
    for work_id, fix in corrections.items():
        if stats.attempted >= limit:
            break
        path = _staging_path(staging_dir, work_id)
        if path is None:
            stats.missing.append(work_id)
            continue
        meta = sidecar.load(path)
        current = meta.get("title")
        if current != fix.expected:
            # Data drifted since review (already normalised, or changed elsewhere).
            # Refuse to clobber -- only touch a sidecar we still recognise.
            if current != fix.title:
                stats.skipped_drift.append(work_id)
            continue
        stats.attempted += 1
        _apply_fix(meta, fix)
        sidecar.validate(meta)  # title has minLength 1; reject an empty result loudly
        if apply:
            sidecar.write(path, meta)
            mirror_paths = _write_existing_mirrors(meta, art_works_root, exclude=path)
            stats.updated += 1
            stats.mirrored += len(mirror_paths)
            if operations_log is not None:
                _append_operation(operations_log, meta, fix, path, mirror_paths)
    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write changes (default: dry-run)")
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument(
        "--staging-dir",
        type=Path,
        default=default_works_dir(),
    )
    parser.add_argument("--art-works-root", type=Path, default=_env_path("FAA_ART_WORKS_ROOT"))
    parser.add_argument("--operations-log", type=Path, default=_env_path("FAA_OPERATIONS_LOG"))
    args = parser.parse_args(argv)

    stats = normalize_titles(
        args.staging_dir,
        art_works_root=args.art_works_root,
        operations_log=args.operations_log,
        limit=args.limit,
        apply=args.apply,
    )
    mode = "apply" if args.apply else "dry-run"
    print(
        f"title normalization ({mode}): "
        f"eligible={stats.attempted} updated={stats.updated} mirrored={stats.mirrored}"
    )
    if stats.skipped_drift:
        print(f"skipped (title drifted from expected): {sorted(stats.skipped_drift)}")
    if stats.missing:
        print(f"not found on disk: {sorted(stats.missing)}")
    if not args.apply and stats.attempted:
        print("(dry-run: no files written; re-run with --apply)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
