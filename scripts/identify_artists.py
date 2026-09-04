#!/usr/bin/env python3
"""Set verified ``artist.wikidata_q`` for works the name-based resolver can't reach.

Some uncategorized-floor works carry an artist the automatic resolver
(``backfill_artist_qids.py``) misses -- because the name is in a form its search
can't match (family-first, diacritics, surname-only), or because the artist field
holds the *sitter*, a *medium*, or a *place* instead of the creator. Those cannot
be fixed by loosening a gate; they need identification.

:data:`ARTIST_IDS` is a hand-verified table: each work's creator was identified
from its master image + title and confirmed against Wikidata (label + occupation
+ era). Where the artist field held junk (a medium, "Glass plate collodion
negative"), the corrected name is written too. QIDs are load-bearing (a wrong one
corrupts P170-based enrichment), so only high-confidence identifications are
listed; ambiguous or Wikidata-absent artists are left for the needs-research
report.

Dry-run by default; ``--apply`` writes ``artist.wikidata_q`` (+ corrected
``artist.name``), records ``field_provenance`` for ``artist_qid`` (status
``available``), mirrors to Art/works, and logs. Only touches works that lack an
artist QID; a guard skips any whose artist QID is already set.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "src"))

from _paths import default_works_dir  # noqa: E402
from _sidecar_io import script_env_path as _env_path  # noqa: E402
from _sidecar_io import sidecar_paths as _sidecar_paths  # noqa: E402
from _sidecar_io import write_existing_mirrors as _write_existing_mirrors  # noqa: E402

from fine_art_archive import provenance, sidecar  # noqa: E402
from fine_art_archive.enrichment.holder import _creator_qid  # noqa: E402


@dataclass(frozen=True)
class ArtistId:
    qid: str  # verified person QID (P106 artist, era-consistent)
    name: str | None  # corrected artist name, or None to keep the existing one
    note: str


# Verified 2026-08-01 (image + title identification, confirmed vs Wikidata
# label + occupation + lifespan). Keyed by work_id.
ARTIST_IDS: dict[str, ArtistId] = {
    "4a067a9-aeneas-taken-by-the-sibyl-to": ArtistId(
        "Q984173",
        None,
        "Jacob van Swanenburgh (painter, 1571-1638); infernal scene matches his oeuvre.",
    ),
    "817dc64-aeneas-taken-by-the-sibyl-to": ArtistId(
        "Q984173",
        None,
        "Jacob van Swanenburgh (painter, 1571-1638); duplicate of the Aeneas underworld work.",
    ),
    "118b36a-the-butcher-los-gauchos-series-cesareo": ArtistId(
        "Q5065617", "Cesáreo Bernaldo de Quirós", "Argentine painter; 'Los Gauchos' series is his."
    ),
    "b0b3ea6-papa-mama-and-their-children-shoji": ArtistId(
        "Q3107892",
        "Shōji Ueda",
        "Japanese photographer (1913-2000); 'Papa, Mama and the Children' is his.",
    ),
    "ebe2cb4-birds-eye-view-of-the-village-teiko": ArtistId(
        "Q5620694", "Teikō Shiotani", "Japanese pictorialist photographer (1899-1988)."
    ),
    "5da94a9-mishima-morning-mist-mishima-asagiri-hiroshige-print": ArtistId(
        "Q200798",
        "Utagawa Hiroshige",
        "Ukiyo-e artist; Mishima is a Tōkaidō station print. (was medium text)",
    ),
    "3e0f4cf-marxism-will-give-health-to-the-masonite": ArtistId(
        "Q5588",
        "Frida Kahlo",
        "'Marxism Will Give Health to the Ill' is a Kahlo painting. (was medium text)",
    ),
    "acc7461-ulysses-simpson-grant-mathew-brady-studio-negative": ArtistId(
        "Q187850", "Mathew Brady", "Civil-War studio portrait of Grant. (was medium text)"
    ),
    "6aacb85-calvin-coolidge-hopkinson": ArtistId(
        "Q5079125", None, "Charles Hopkinson (American painter, 1869-1962); Coolidge portrait."
    ),
}


@dataclass
class IdentifyStats:
    matched: int  # table entries whose sidecar was found
    changed: int  # sidecars written / would be written
    skipped_existing: int  # already had an artist QID (guard)
    mirrored: int


def _apply(meta: dict[str, Any], ident: ArtistId) -> None:
    artist = meta.setdefault("artist", {})
    if not isinstance(artist, dict):  # pragma: no cover - malformed guard
        raise ValueError("artist must be an object")
    artist["wikidata_q"] = ident.qid
    if ident.name is not None:
        artist["name"] = ident.name
    provenance.set(
        meta,
        "artist_qid",
        "available",
        "research",
        source_ref=f"https://www.wikidata.org/wiki/{ident.qid}",
        note=ident.note,
    )


def _append_operation(
    log_path: Path, meta: dict[str, Any], ident: ArtistId, staging_path: Path, mirrors: list[Path]
) -> None:
    entry = {
        "ts": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "actor": "identify_artists",
        "op": "artist_identify",
        "work_id": meta["work_id"],
        "artist_qid": ident.qid,
        "note": ident.note,
        "staging_path": str(staging_path),
        "mirror_paths": [str(path) for path in mirrors],
    }
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")


def identify(
    staging_dir: Path,
    *,
    artist_ids: dict[str, ArtistId] = ARTIST_IDS,
    art_works_root: Path | None = None,
    operations_log: Path | None = None,
    apply: bool = False,
) -> tuple[IdentifyStats, list[str]]:
    matched = changed = skipped = mirrored = 0
    outcomes: list[str] = []
    for path in _sidecar_paths(staging_dir):
        meta = sidecar.load(path)
        work_id = str(meta.get("work_id") or "")
        ident = artist_ids.get(work_id)
        if ident is None:
            continue
        matched += 1
        if _creator_qid(meta):
            skipped += 1
            outcomes.append(f"SKIP  {work_id}: artist QID already set")
            continue
        _apply(meta, ident)
        sidecar.validate(meta)
        changed += 1
        outcomes.append(f"OK    {work_id}: artist -> {ident.qid}")
        if apply:
            sidecar.write(path, meta)
            mirrors = _write_existing_mirrors(meta, art_works_root, exclude=path)
            mirrored += len(mirrors)
            if operations_log is not None:
                _append_operation(operations_log, meta, ident, path, mirrors)
    return IdentifyStats(matched, changed, skipped, mirrored), outcomes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write changes (default: dry-run)")
    parser.add_argument(
        "--staging-dir",
        type=Path,
        default=default_works_dir(),
    )
    parser.add_argument("--art-works-root", type=Path, default=_env_path("FAA_ART_WORKS_ROOT"))
    parser.add_argument("--operations-log", type=Path, default=_env_path("FAA_OPERATIONS_LOG"))
    args = parser.parse_args(argv)

    stats, outcomes = identify(
        args.staging_dir,
        art_works_root=args.art_works_root,
        operations_log=args.operations_log,
        apply=args.apply,
    )
    mode = "apply" if args.apply else "dry-run"
    for line in outcomes:
        print(line)
    print(
        f"\nartist identify ({mode}): matched={stats.matched} changed={stats.changed} "
        f"skipped_existing={stats.skipped_existing} mirrored={stats.mirrored}"
    )
    unseen = sorted(set(ARTIST_IDS) - {ln.split()[1].rstrip(":") for ln in outcomes})
    if unseen:
        print("WARNING: table entries with no matching sidecar:", unseen)
    if not args.apply and stats.changed:
        print("(dry-run: no files written; re-run with --apply)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
