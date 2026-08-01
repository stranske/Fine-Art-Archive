#!/usr/bin/env python3
"""Populate ``artist.relation`` for attribution-qualifier works + fix the reference QID.

Works whose ``artist.name`` carries an art-historical qualifier -- "Workshop of X",
"Circle of X", "After X", "Attributed to X", "Style of X" -- are NOT autograph works
by X. The schema models this: keep the qualifier phrase in ``artist.name``, set
``artist.relation`` (workshop/circle/after/follower/attributed), and point
``artist.wikidata_q`` (+ canonical) at the *reference* artist so the work sorts near
their oeuvre without claiming they made it.

That layer was never populated -- all 32 such works had ``relation`` unset (defaulting
to self), and several had a badly mis-resolved reference QID sitting in the
load-bearing ``artist.wikidata_q`` (e.g. "Workshop of Rogier van der Weyden" pointed at
*Titian*; "Circle of Jacques-Louis David" at *Julien Hudson*; "Attributed to Marco
d'Oggiono" at *Eva Gonzalès*). Both problems corrupt P170-based enrichment and
artist grouping.

:data:`ATTRIBUTIONS` is a hand-verified table (relation parsed from the source name;
reference artist re-resolved + confirmed against Wikidata label + occupation + era).
On apply the reference identity is rebuilt from the correct QID; ``artist.name`` is
left verbatim. The lone anonymous case (a Persian manuscript "Attributed to Iran")
gets ``relation=anonymous`` + ``attribution_anchor=Q4233718`` + a culture.

Dry-run by default; ``--apply`` writes, records ``field_provenance`` for
``artist_qid``, mirrors, and logs.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "src"))

from fine_art_archive import provenance, sidecar  # noqa: E402
from fine_art_archive.enrichment.source_resolver import JsonClient  # noqa: E402
from fine_art_archive.enrichment.wikidata_identity import fetch_identity  # noqa: E402
from fine_art_archive.identity.artist_resolver import fold_name  # noqa: E402

ANONYMOUS_ANCHOR = "Q4233718"


@dataclass(frozen=True)
class Attr:
    relation: str  # workshop | circle | after | follower | attributed | anonymous
    ref_qid: str | None  # verified reference-artist QID (None for anonymous)
    confidence: str  # attribution_confidence
    nationality: str | None = None  # culture, for the anonymous case
    note: str = field(default="")


# work_id -> Attr. Relation parsed from artist.name; reference QID re-resolved +
# verified against Wikidata (2026-08-01). The comment is the source name.
ATTRIBUTIONS: dict[str, Attr] = {
    "00edba3-jonah-and-the-whale-folio-probably-iran": Attr(
        "anonymous", None, "scholarly_consensus", nationality="Persian"
    ),  # Unknown artist, Attributed to Iran
    "07bbd4c-portrait-of-isabella-of-portugal-weyden": Attr(
        "workshop", "Q68631", "scholarly_consensus"
    ),  # Workshop of Rogier van der Weyden
    "0fac326-pentecost-workshop": Attr(
        "workshop", "Q7814", "scholarly_consensus"
    ),  # Giotto and Workshop
    "1c9bd73-christ-carrying-the-cross-follower": Attr(
        "follower", "Q130531", "attributed"
    ),  # Bosch (follower)
    "1f3a87b-a-lovely-garland-tamakazura-from-the-mitsuyoshi": Attr(
        "circle", "Q3532590", "attributed"
    ),  # circle of Tosa Mitsuyoshi
    "33a9f2a-a-city-on-a-rock-goya": Attr("follower", "Q5432", "uncertain"),  # Style of Goya
    "40245d0-portrait-of-a-woman-possibly-ginevra-pane": Attr(
        "attributed", "Q21285511", "attributed"
    ),  # Attributed to the Maestro delle Storie del Pane
    "409d160-girl-with-a-flute-vermeer": Attr(
        "attributed", "Q41264", "attributed"
    ),  # Attributed to Johannes Vermeer
    "463d0f5-an-old-woman-peeling-pears-younger": Attr(
        "follower", "Q335022", "attributed"
    ),  # Follower of David Teniers the Younger
    "49a9466-illustrated-kabuki-performance-mitsuhiro": Attr(
        "attributed", "Q11567199", "attributed"
    ),  # Traditionally attributed to Karasumaru Mitsuhiro
    "4a03c73-portrait-of-pope-julius-ii-workshop": Attr(
        "workshop", "Q5597", "scholarly_consensus"
    ),  # Raphael and workshop
    "4e3565c-bon-bock-cafe-manet": Attr(
        "follower", "Q40599", "uncertain"
    ),  # Style of Edouard Manet
    "55391c1-a-boy-with-a-bird-titian": Attr(
        "workshop", "Q47551", "uncertain"
    ),  # Titian or workshop of Titian
    "5891c1a-girl-with-cherries-doggiono": Attr(
        "attributed", "Q982274", "attributed"
    ),  # Attributed to Marco d'Oggiono
    "63a8a82-portrait-of-a-young-woman-in-david": Attr(
        "circle", "Q83155", "attributed"
    ),  # Circle of Jacques-Louis David
    "7855e65-judith-with-the-head-of-holofernes-campagnola": Attr(
        "follower", "Q5681", "uncertain"
    ),  # Andrea Mantegna or Follower (Possibly Giulio Campagnola)
    "799abd4-the-conjurer-workshop": Attr(
        "workshop", "Q130531", "scholarly_consensus"
    ),  # Hieronymus Bosch and workshop
    "7a84b74-landscape-with-the-death-of-procris-claude": Attr(
        "workshop", "Q214074", "scholarly_consensus"
    ),  # Studio of Claude
    "7e81f08-tobias-and-the-angel-verrocchio": Attr(
        "workshop", "Q183458", "scholarly_consensus"
    ),  # Workshop of Andrea del Verrocchio
    "86a89fb-still-life-gauguin": Attr("follower", "Q37693", "uncertain"),  # Style of Paul Gauguin
    "8f254e7-the-deposition-weyden": Attr(
        "follower", "Q68631", "attributed"
    ),  # Follower of Rogier van der Weyden
    "967f2ca-salome-receiving-the-head-of-john-rijn": Attr(
        "circle", "Q5598", "attributed"
    ),  # circle of Rembrandt van Rijn
    "a520581-lucrezia-tornabuoni-to": Attr(
        "attributed", "Q191423", "attributed"
    ),  # Domenico Ghirlandaio (Attributed to)
    "aef7188-old-woman-cutting-her-nails-dutch": Attr(
        "follower", "Q5598", "uncertain"
    ),  # Style of Rembrandt (Dutch
    "b157f38-lamentation-of-christ-workshop": Attr(
        "workshop", "Q68631", "scholarly_consensus"
    ),  # Rogier van der Weyden (and workshop)
    "b732bed-study-of-an-old-woman-after": Attr(
        "after", "Q5598", "scholarly_consensus"
    ),  # Rembrandt van Rijn (after)
    "b9b121c-st-augustine-sacrificing-to-a-manichaean-follower": Attr(
        "follower", "Q68631", "attributed"
    ),  # Rogier van der Weyden (follower)
    "bd0e60e-saint-jerome-and-the-lion-predella-workshop": Attr(
        "workshop", "Q205148", "scholarly_consensus"
    ),  # Fra Filippo Lippi and workshop
    "c1b7808-christ-carrying-the-cross-of": Attr(
        "follower", "Q130531", "attributed"
    ),  # Hieronymus Bosch (a follower of)
    "ca8b23b-david-meeting-abigail-workshop": Attr(
        "workshop", "Q5599", "scholarly_consensus"
    ),  # Rubens Workshop
    "d4a4c28-madonna-and-child-bellini": Attr(
        "workshop", "Q17169", "scholarly_consensus"
    ),  # Workshop of Giovanni Bellini
    "ea5e072-portrait-of-a-young-man-to": Attr(
        "attributed", "Q5594", "attributed"
    ),  # Antonello da Messina (Attributed to)
}


@dataclass
class FixStats:
    matched: int
    changed: int
    reference_fixed: int  # works whose artist QID changed to a different value
    mirrored: int


def _sidecar_paths(staging_dir: Path) -> list[Path]:
    paths = set(staging_dir.rglob("meta.json"))
    paths.update(staging_dir.glob("*.json"))
    return sorted(path for path in paths if path.is_file())


def _qid_ref(qid: str | None) -> str | None:
    return f"https://www.wikidata.org/wiki/{qid}" if qid else None


def _apply(meta: dict[str, Any], attr: Attr, *, client: Any, now: str) -> bool:
    """Apply one attribution correction. Returns True if the reference QID changed."""
    artist = meta.setdefault("artist", {})
    if not isinstance(artist, dict):  # pragma: no cover - malformed guard
        raise ValueError("artist must be an object")
    prior_qid = artist.get("wikidata_q")
    artist["relation"] = attr.relation
    artist["attribution_confidence"] = attr.confidence

    if attr.relation == "anonymous":
        artist["wikidata_q"] = None
        artist["attribution_anchor"] = ANONYMOUS_ANCHOR
        artist["canonical"] = None
        if attr.nationality:
            artist["nationality"] = attr.nationality
        provenance.set(
            meta,
            "artist_qid",
            "not_available",
            "research",
            note="Anonymous; source attributes only a culture, not a person.",
        )
        return prior_qid is not None

    qid = attr.ref_qid
    assert qid is not None  # only anonymous has ref_qid=None
    artist["wikidata_q"] = qid
    display_name, lifespan = fetch_identity(qid, client=client)
    artist["canonical"] = {
        "wikidata_q": qid,
        "display_name": display_name,
        "lifespan": lifespan,
        "family_key": fold_name(display_name) if display_name else None,
        "method": "manual_research",
        "confidence": 0.95,
        "resolved_at": now,
        "notes": f"Reference artist for a '{attr.relation}' attribution.",
    }
    provenance.set(
        meta,
        "artist_qid",
        "available",
        "research",
        source_ref=_qid_ref(qid),
        note=(
            f"relation={attr.relation}; artist.name is the source qualifier, "
            f"wikidata_q re-resolved to the reference artist {display_name}."
        ),
    )
    return prior_qid != qid


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
    log_path: Path, meta: dict[str, Any], attr: Attr, staging_path: Path, mirrors: list[Path]
) -> None:
    entry = {
        "ts": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "actor": "fix_attribution_relations",
        "op": "attribution_relation_fix",
        "work_id": meta["work_id"],
        "relation": attr.relation,
        "reference_qid": attr.ref_qid,
        "staging_path": str(staging_path),
        "mirror_paths": [str(path) for path in mirrors],
    }
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")


def fix(
    staging_dir: Path,
    *,
    client: Any,
    attributions: dict[str, Attr] = ATTRIBUTIONS,
    art_works_root: Path | None = None,
    operations_log: Path | None = None,
    apply: bool = False,
    now: str | None = None,
) -> tuple[FixStats, list[str]]:
    stamp = now or datetime.now(UTC).isoformat().replace("+00:00", "Z")
    matched = changed = fixed = mirrored = 0
    outcomes: list[str] = []
    for path in _sidecar_paths(staging_dir):
        meta = sidecar.load(path)
        work_id = str(meta.get("work_id") or "")
        attr = attributions.get(work_id)
        if attr is None:
            continue
        matched += 1
        ref_changed = _apply(meta, attr, client=client, now=stamp)
        sidecar.validate(meta)
        changed += 1
        fixed += int(ref_changed)
        ref = attr.ref_qid or "anonymous"
        outcomes.append(
            f"OK    {work_id}: relation={attr.relation} ref={ref}{' (QID fixed)' if ref_changed else ''}"
        )
        if apply:
            sidecar.write(path, meta)
            mirrors = _write_existing_mirrors(meta, art_works_root, exclude=path)
            mirrored += len(mirrors)
            if operations_log is not None:
                _append_operation(operations_log, meta, attr, path, mirrors)
    return FixStats(matched, changed, fixed, mirrored), outcomes


def _env_path(name: str) -> Path | None:
    raw = os.environ.get(name)
    return Path(raw).expanduser() if raw else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="write changes (default: dry-run)")
    parser.add_argument(
        "--staging-dir",
        type=Path,
        default=_env_path("FAA_STAGING_DIR") or ROOT / "staging_sidecars",
    )
    parser.add_argument("--art-works-root", type=Path, default=_env_path("FAA_ART_WORKS_ROOT"))
    parser.add_argument("--operations-log", type=Path, default=_env_path("FAA_OPERATIONS_LOG"))
    parser.add_argument("--timeout", type=float, default=15.0)
    args = parser.parse_args(argv)

    stats, outcomes = fix(
        args.staging_dir,
        client=JsonClient(timeout=args.timeout),
        art_works_root=args.art_works_root,
        operations_log=args.operations_log,
        apply=args.apply,
    )
    mode = "apply" if args.apply else "dry-run"
    for line in outcomes:
        print(line)
    print(
        f"\nattribution-relation fix ({mode}): matched={stats.matched} changed={stats.changed} "
        f"reference_qid_fixed={stats.reference_fixed} mirrored={stats.mirrored}"
    )
    unseen = sorted(set(ATTRIBUTIONS) - {ln.split()[1].rstrip(":") for ln in outcomes})
    if unseen:
        print("WARNING: table entries with no matching sidecar:", unseen)
    if not args.apply and stats.changed:
        print("(dry-run: no files written; re-run with --apply)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
