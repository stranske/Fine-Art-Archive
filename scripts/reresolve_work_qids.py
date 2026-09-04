#!/usr/bin/env python3
"""Re-resolve (or clear) mis-resolved work QIDs for a known set of works.

A minority of works carry a ``stable_identifiers.wikidata_q`` that points at
something that is *not* the artwork -- a country, a person, a scholarly article,
a scrapped chemical tanker, a generic "type of building". These were surfaced
during the 2026-07-31 category backfill (PR #361): the backfill's strict P31
allowlist let most fall through harmlessly, but the wrong QID still corrupts any
P31/Wikidata-based enrichment and must be corrected.

Unlike the heuristic backfills, this pass works from a **hand-verified table**
(:data:`RESOLUTIONS`): each work's correct Wikidata entity was confirmed by
title+entity match (label + P31) against Wikidata, or the QID was cleared to
``null`` when no confident work entity exists. Because each entity is verified,
the category is written directly from it (with a Wikidata source_ref) rather
than left to the coarse allowlist -- this also lets us correct the one work
(``Ancient_Temple``) whose category was mis-written ``painting`` from a
mis-resolved QID, which ``backfill_categories`` would never revisit (it only
touches uncategorized works).

Dry-run by default (reports what *would* change); ``--apply`` writes. On write
it records ``field_provenance`` for ``stable_identifiers.wikidata_q`` (and
``category`` when set), mirrors to the canonical Art/works tree, and appends to
operations.log.
"""

from __future__ import annotations

import argparse
import json
import os
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

from fine_art_archive import provenance, sidecar  # noqa: E402

QID_PROV_FIELD = "stable_identifiers.wikidata_q"


@dataclass(frozen=True)
class Resolution:
    """A hand-verified correction for one work's stable Wikidata identifier."""

    old_qid: str  # the mis-resolved QID currently on the sidecar (guard value)
    old_entity: str  # what old_qid actually is, for the audit note
    new_qid: str | None  # verified work QID, or None to clear
    new_entity: str | None  # label/description of the verified entity (None when cleared)
    category: str | None  # category to write from the verified entity, or None to leave as-is
    note: str  # human-readable justification recorded in provenance + log


# Verified 2026-07-31 (title+entity confirmed against Wikidata label + P31).
# Keyed by work_id. `new_qid=None` means no confident work entity exists.
RESOLUTIONS: dict[str, Resolution] = {
    "037f7eb-castillo-de-zafra-campillodeduenas": Resolution(
        old_qid="Q83568274",
        old_entity="scrapped chemical tanker",
        new_qid="Q3571719",
        new_entity="Castle of Zafra (castle in Guadalajara, Spain)",
        category="architecture",
        note="Re-resolved to Q3571719 (Castle of Zafra); the castle depicted. "
        "P31 castle is off the category allowlist, so architecture is set directly.",
    ),
    "0fa11af-model-soapstone": Resolution(
        old_qid="Q4610556",
        old_entity="profession (fashion/artist's model)",
        new_qid=None,
        new_entity=None,
        category=None,
        note="Cleared: title 'Model' has no confident work entity on Wikidata "
        "(old Q4610556 was the profession, not an artwork).",
    ),
    "56d4631-going-back-to-the-roots-jb": Resolution(
        old_qid="Q30668804",
        old_entity="scholarly article",
        new_qid=None,
        new_entity=None,
        category=None,
        note="Cleared: 'Going back to the roots' (JB Maingi) has no work entity "
        "on Wikidata (old Q30668804 was a scientific article).",
    ),
    "71b26c7-the-standard-of-ur-bce": Resolution(
        old_qid="Q26777058",
        old_entity="scholarly article",
        new_qid="Q524447",
        new_entity="Standard of Ur (Sumerian artefact; P31 archaeological artefact, mosaic)",
        category="mosaic",
        note="Re-resolved to Q524447 (Standard of Ur); P31 includes mosaic, so "
        "category is set to mosaic.",
    ),
    "903dc4f-bullfight-varas": Resolution(
        old_qid="Q1193438",
        old_entity="bullring (type of building)",
        new_qid="Q20178241",
        new_entity="Bullfight, Suerte de Varas (painting by Francisco de Goya)",
        category="painting",
        note="Re-resolved to Q20178241 (Goya, 'Bullfight, Suerte de Varas'); P31 painting.",
    ),
    "93a3835-mikhail-larionov-baker": Resolution(
        old_qid="Q38785",
        old_entity="human (Mikhail Larionov, the artist)",
        new_qid="Q21711795",
        new_entity="The Baker (painting by Mikhail Larionov)",
        category="painting",
        note="Re-resolved to Q21711795 (Larionov, 'The Baker'); the sidecar had "
        "title/artist swapped and the QID pointed at the artist person. P31 painting.",
    ),
    "9785f08-luxe-volupte": Resolution(
        old_qid="Q32",
        old_entity="Luxembourg (country)",
        new_qid="Q3268045",
        new_entity="Luxe, Calme et Volupté (oil painting by Henri Matisse, 1904)",
        category="painting",
        note="Re-resolved to Q3268045 (Matisse, 'Luxe, Calme et Volupté'); P31 painting.",
    ),
    "b15fc61-caucasus-ingushetia": Resolution(
        old_qid="Q18869",
        old_entity="region (the Caucasus)",
        new_qid=None,
        new_entity=None,
        category=None,
        note="Cleared: title 'Caucasus' has no confident work entity on Wikidata "
        "(old Q18869 was the geographic region).",
    ),
    "cf87988-spring-de": Resolution(
        old_qid="Q124714",
        old_entity="feature type (spring, a water source)",
        new_qid=None,
        new_entity=None,
        category=None,
        note="Cleared: no confident work entity for 'Spring' (Adriaen van de Venne) "
        "on Wikidata (old Q124714 was the water-source feature type).",
    ),
    "fc92485-helvoetsluys-sea": Resolution(
        old_qid="Q136894027",
        old_entity="visual artwork (Helvoetsluys by J. M. W. Turner) -- already correct",
        new_qid="Q136894027",
        new_entity="Helvoetsluys (painting by J. M. W. Turner)",
        category="painting",
        note="Confirmed existing QID Q136894027 is correct (Turner, 'Helvoetsluys'); "
        "its P31 'visual artwork' is off the allowlist, so category painting is set directly.",
    ),
    "7aa8b3d-ancient-temple-naranag": Resolution(
        old_qid="Q19609386",
        old_entity="painting ('Ancient Temple' by Hubert Robert) -- not this work",
        new_qid="Q18394457",
        new_entity="Wangath Temple complex, Naranag (Hindu temple complex, Jammu & Kashmir)",
        category="architecture",
        note="Re-resolved to Q18394457 (Wangath/Naranag temple complex); corrects the "
        "category mis-written 'painting' from the mis-resolved QID to architecture.",
    ),
}


@dataclass
class ReresolveStats:
    matched: int  # sidecars whose work_id is in the table
    changed: int  # sidecars that would be / were written
    skipped_guard: int  # sidecars skipped because the current QID did not match old_qid
    mirrored: int  # canonical mirrors written


def _sidecar_paths(staging_dir: Path) -> list[Path]:
    paths = set(staging_dir.rglob("meta.json"))
    paths.update(staging_dir.glob("*.json"))
    return sorted(path for path in paths if path.is_file())


def _current_qid(meta: dict[str, Any]) -> str | None:
    stable = meta.get("stable_identifiers")
    if isinstance(stable, dict):
        qid = stable.get("wikidata_q")
        return qid if isinstance(qid, str) and qid else None
    return None


def _qid_ref(qid: str | None) -> str | None:
    return f"https://www.wikidata.org/wiki/{qid}" if qid else None


def _apply_resolution(meta: dict[str, Any], res: Resolution) -> None:
    stable = meta.setdefault("stable_identifiers", {})
    if not isinstance(stable, dict):  # pragma: no cover - malformed input guard
        raise ValueError("stable_identifiers must be an object")
    stable["wikidata_q"] = res.new_qid
    if res.new_qid is not None:
        provenance.set(
            meta,
            QID_PROV_FIELD,
            "available",
            "wikidata",
            source_ref=_qid_ref(res.new_qid),
            note=res.note,
        )
    else:
        provenance.set(
            meta,
            QID_PROV_FIELD,
            "not_available",
            "wikidata",
            source_ref=None,
            note=res.note,
        )
    if res.category is not None:
        meta["category"] = res.category
        provenance.set(
            meta,
            "category",
            "available",
            "wikidata",
            source_ref=_qid_ref(res.new_qid),
            note=res.note,
        )


def _write_existing_mirrors(
    meta: dict[str, Any], art_works_root: Path | None, *, exclude: Path
) -> list[Path]:
    if art_works_root is None:
        return []
    work_id = str(meta["work_id"])
    candidates = {
        art_works_root / "works" / work_id / "meta.json",
        art_works_root / work_id / "meta.json",
    }
    written: list[Path] = []
    for candidate in sorted(candidates):
        if candidate.is_file() and candidate.resolve() != exclude.resolve():
            sidecar.write(candidate, meta)
            written.append(candidate)
    return written


def _append_operation(
    log_path: Path,
    meta: dict[str, Any],
    res: Resolution,
    staging_path: Path,
    mirror_paths: list[Path],
) -> None:
    entry = {
        "ts": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "actor": "reresolve_work_qids",
        "op": "work_qid_reresolve",
        "work_id": meta["work_id"],
        "old_wikidata_q": res.old_qid,
        "new_wikidata_q": res.new_qid,
        "category": res.category,
        "note": res.note,
        "staging_path": str(staging_path),
        "mirror_paths": [str(path) for path in mirror_paths],
    }
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")


def reresolve(
    staging_dir: Path,
    *,
    resolutions: dict[str, Resolution] = RESOLUTIONS,
    art_works_root: Path | None = None,
    operations_log: Path | None = None,
    apply: bool = False,
) -> tuple[ReresolveStats, list[str]]:
    """Apply the verified QID corrections to the staging corpus.

    Returns aggregate stats and a list of human-readable per-work outcome lines.
    """
    matched = changed = skipped = mirrored = 0
    outcomes: list[str] = []
    for path in _sidecar_paths(staging_dir):
        meta = sidecar.load(path)
        work_id = str(meta.get("work_id") or "")
        res = resolutions.get(work_id)
        if res is None:
            continue
        matched += 1
        current = _current_qid(meta)
        if current != res.old_qid:
            skipped += 1
            outcomes.append(
                f"SKIP  {work_id}: current QID {current!r} != expected {res.old_qid!r} "
                "(data changed since audit; not touched)"
            )
            continue
        _apply_resolution(meta, res)
        sidecar.validate(meta)  # reject any schema violation before writing
        changed += 1
        target = res.new_qid if res.new_qid else "null"
        cat = f", category={res.category}" if res.category else ""
        outcomes.append(f"OK    {work_id}: {res.old_qid} -> {target}{cat}")
        if apply:
            sidecar.write(path, meta)
            mirror_paths = _write_existing_mirrors(meta, art_works_root, exclude=path)
            mirrored += len(mirror_paths)
            if operations_log is not None:
                _append_operation(operations_log, meta, res, path, mirror_paths)
    return ReresolveStats(matched, changed, skipped, mirrored), outcomes


def _env_path(name: str) -> Path | None:
    raw = os.environ.get(name)
    return Path(raw).expanduser() if raw else None


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

    stats, outcomes = reresolve(
        args.staging_dir,
        art_works_root=args.art_works_root,
        operations_log=args.operations_log,
        apply=args.apply,
    )
    mode = "apply" if args.apply else "dry-run"
    for line in outcomes:
        print(line)
    print(
        f"\nwork-qid reresolve ({mode}): "
        f"matched={stats.matched} changed={stats.changed} "
        f"skipped_guard={stats.skipped_guard} mirrored={stats.mirrored}"
    )
    unseen = sorted(set(RESOLUTIONS) - {ln.split()[1].rstrip(":") for ln in outcomes})
    if unseen:
        print("WARNING: table entries with no matching sidecar:", unseen)
    if not args.apply and stats.changed:
        print("(dry-run: no files written; re-run with --apply)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
