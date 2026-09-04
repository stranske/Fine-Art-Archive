#!/usr/bin/env python3
"""Complete attribution + holder for the identified/anonymous floor works.

Two jobs, from a single hand-verified table:

1. **Cascade** the canonical identity for works whose artist QID is known (the
   ``identify_artists`` set and a few new identifications): fetch the Wikidata
   label + lifespan and populate ``artist.canonical`` + ``artist.lifespan`` -- the
   derived data that should accompany a resolved ``artist.wikidata_q``.

2. **Catalogue the unidentified works** by professional convention (CCO/CDWA):
   - a named individual where scholarship attributes one (with a QID when it
     exists, e.g. George Bellows for 'Pennsylvania Station Excavation'; a plain
     name where Wikidata has no entity, e.g. John Thornton);
   - ``relation='anonymous'`` + ``attribution_anchor=Q4233718`` + a ``nationality``
     culture for securely-dated ancient works (Ravenna mosaics, Roman frescoes,
     the Neo-Assyrian obelisk); ``relation='unknown'`` for modern works whose
     maker is merely unrecorded (official portrait photos);
   - the **holder** (site / institution) as the identifying anchor for in-situ
     works -- the church, mausoleum, or museum that holds them.

Every artist QID and holder QID was verified against Wikidata (label +
occupation/type + era). Dry-run by default; ``--apply`` writes, records
``field_provenance``, mirrors, and logs.
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
from fine_art_archive.enrichment.holder_by_creator import fold_name  # noqa: E402
from fine_art_archive.enrichment.source_resolver import JsonClient  # noqa: E402
from fine_art_archive.enrichment.wikidata_identity import fetch_identity  # noqa: E402

ANONYMOUS_ANCHOR = "Q4233718"


@dataclass(frozen=True)
class Attribution:
    qid: str | None = None  # verified artist person QID (fills canonical)
    name: str | None = None  # corrected artist display name (None = keep existing)
    relation: str | None = None  # 'self' | 'anonymous' | 'unknown'
    anchor: str | None = None  # attribution_anchor (Q4233718 for anonymous)
    nationality: str | None = None  # culture/nationality (e.g. 'Byzantine')
    confidence: str | None = None  # attribution_confidence
    holder_qid: str | None = None
    holder_name: str | None = None
    note: str = ""


_CONSENSUS = "scholarly_consensus"

# work_id -> Attribution. Verified 2026-08-01.
ATTRIBUTIONS: dict[str, Attribution] = {
    # --- canonical cascade for the already-identified artists (relation self) ---
    "4a067a9-aeneas-taken-by-the-sibyl-to": Attribution(
        qid="Q984173", relation="self", confidence=_CONSENSUS, note="Jacob van Swanenburgh."
    ),
    "817dc64-aeneas-taken-by-the-sibyl-to": Attribution(
        qid="Q984173", relation="self", confidence=_CONSENSUS, note="Jacob van Swanenburgh."
    ),
    "118b36a-the-butcher-los-gauchos-series-cesareo": Attribution(
        qid="Q5065617", relation="self", confidence=_CONSENSUS, note="Cesáreo Bernaldo de Quirós."
    ),
    "b0b3ea6-papa-mama-and-their-children-shoji": Attribution(
        qid="Q3107892", relation="self", confidence=_CONSENSUS, note="Shōji Ueda."
    ),
    "ebe2cb4-birds-eye-view-of-the-village-teiko": Attribution(
        qid="Q5620694", relation="self", confidence=_CONSENSUS, note="Teikō Shiotani."
    ),
    "5da94a9-mishima-morning-mist-mishima-asagiri-hiroshige-print": Attribution(
        qid="Q200798", relation="self", confidence=_CONSENSUS, note="Utagawa Hiroshige."
    ),
    "3e0f4cf-marxism-will-give-health-to-the-masonite": Attribution(
        qid="Q5588", relation="self", confidence=_CONSENSUS, note="Frida Kahlo."
    ),
    "acc7461-ulysses-simpson-grant-mathew-brady-studio-negative": Attribution(
        qid="Q187850", relation="self", confidence=_CONSENSUS, note="Mathew Brady."
    ),
    "6aacb85-calvin-coolidge-hopkinson": Attribution(
        qid="Q5079125", relation="self", confidence=_CONSENSUS, note="Charles Hopkinson."
    ),
    # --- new individual identifications (name + QID + holder) ---
    "b44ff28-pennsylvania-station-excavation-george-wesley-bellows-canvas": Attribution(
        qid="Q167132",
        name="George Bellows",
        relation="self",
        confidence=_CONSENSUS,
        holder_qid="Q632682",
        holder_name="Brooklyn Museum",
        note="George Bellows, 'Pennsylvania Station Excavation'. Artist field held a medium string.",
    ),
    "1d182e8-after-the-battle-of-curupayti-lopez": Attribution(
        qid="Q2533231",
        name="Cándido López",
        relation="self",
        confidence=_CONSENSUS,
        holder_qid="Q1848918",
        holder_name="National Museum of Fine Arts, Argentina",
        note="Cándido López (Argentine soldier-painter); Curupaytí is his signature subject.",
    ),
    "0b0b44a-quire-ceiling-cathedral": Attribution(
        qid="Q8005615",
        name="William Blake Richmond",
        relation="self",
        confidence=_CONSENSUS,
        holder_qid="Q173882",
        holder_name="St Paul's Cathedral",
        note="W. B. Richmond designed the St Paul's quire ceiling mosaics.",
    ),
    "8b7faad-paliotto-altar-frontal-novella": Attribution(
        qid="Q122935244",
        name="Jacopo di Cambio",
        relation="self",
        confidence=_CONSENSUS,
        holder_qid="Q51175",
        holder_name="Basilica of Santa Maria Novella",
        note="Jacopo di Cambio (textile artist); embroidered altar frontal, 1336.",
    ),
    "2ddc608-the-cathedral-and-metropolitical-church-of-1296": Attribution(
        name="John Thornton",
        relation="self",
        confidence="attributed",
        holder_qid="Q252575",
        holder_name="York Minster",
        note="Great East Window, traditionally attributed to glazier John Thornton (no Wikidata entity); held by York Minster.",
    ),
    # --- named makers with no Wikidata entity (keep/correct name; holder where known) ---
    "8e96b64-russian-cavalry-on-the-attack-in-yuriyevich": Attribution(
        name="Alexander Averyanov",
        relation="self",
        confidence="attributed",
        note="Contemporary Russian battle painter Alexander Yur'evich Averyanov (no Wikidata entity).",
    ),
    # --- anonymous, securely-dated: relation anonymous + culture + holder site ---
    "995d564-the-mausoleum-of-galla-placidia-3-ce": Attribution(
        relation="anonymous",
        anchor=ANONYMOUS_ANCHOR,
        nationality="Early Christian",
        confidence=_CONSENSUS,
        holder_qid="Q644288",
        holder_name="Mausoleum of Galla Placidia",
        note="Anonymous Early Christian mosaics, Ravenna, c. 425-450.",
    ),
    "d7f07f4-the-mausoleum-of-galla-placidia-2-ce": Attribution(
        relation="anonymous",
        anchor=ANONYMOUS_ANCHOR,
        nationality="Early Christian",
        confidence=_CONSENSUS,
        holder_qid="Q644288",
        holder_name="Mausoleum of Galla Placidia",
        note="Anonymous Early Christian mosaics, Ravenna, c. 425-450.",
    ),
    "f8fc50e-the-mausoleum-of-galla-placidia-ce": Attribution(
        relation="anonymous",
        anchor=ANONYMOUS_ANCHOR,
        nationality="Early Christian",
        confidence=_CONSENSUS,
        holder_qid="Q644288",
        holder_name="Mausoleum of Galla Placidia",
        note="Anonymous Early Christian mosaics, Ravenna, c. 425-450.",
    ),
    "4800c69-sant-apollinare-nuovo-built-by-the-chapel": Attribution(
        relation="anonymous",
        anchor=ANONYMOUS_ANCHOR,
        nationality="Byzantine",
        confidence=_CONSENSUS,
        holder_qid="Q832278",
        holder_name="Basilica of Sant'Apollinare Nuovo",
        note="Anonymous Byzantine mosaics, Ravenna, 6th c.",
    ),
    "a518eab-ulysses-companions-meet-the-daughter-of-292": Attribution(
        relation="anonymous",
        anchor=ANONYMOUS_ANCHOR,
        nationality="Roman",
        confidence=_CONSENSUS,
        holder_qid="Q213678",
        holder_name="Vatican Library",
        note="Anonymous Roman 'Odyssey Landscapes' wall frescoes, 1st c. BC.",
    ),
    "5ce16da-the-black-obelisk-of-shalmaneser-iii-neoassyrian": Attribution(
        relation="anonymous",
        anchor=ANONYMOUS_ANCHOR,
        nationality="Assyrian",
        confidence=_CONSENSUS,
        holder_qid="Q6373",
        holder_name="British Museum",
        note="Anonymous Neo-Assyrian relief obelisk, c. 825 BC.",
    ),
    "b15fc61-caucasus-ingushetia": Attribution(
        relation="anonymous",
        anchor=ANONYMOUS_ANCHOR,
        nationality="Ingush",
        confidence=_CONSENSUS,
        note="Anonymous medieval Ingush (Vainakh) tower architecture, in situ.",
    ),
    # --- modern works, maker merely unrecorded: relation unknown ---
    "0fa11af-model-soapstone": Attribution(
        relation="unknown", note="Sculptor unrecorded; artist field held the medium ('Soapstone')."
    ),
    "20f8c49-19-rutherford-b-hayes": Attribution(
        relation="unknown", note="Portrait painter unrecorded; artist field held the sitter."
    ),
    "61735c8-cascada-dynjandi-vestfirir": Attribution(
        relation="unknown", note="Landscape photograph, photographer unrecorded."
    ),
    "887c6d2-baturraden-overview-from-ridge-purwokerto": Attribution(
        relation="unknown", note="Landscape photograph, photographer unrecorded."
    ),
    "bd7244f-30-calvin-coolidge-1919": Attribution(
        relation="unknown",
        note="Official portrait photograph, photographer unrecorded; field held the sitter.",
    ),
    "d3f98c4-37-richard-nixon-1973": Attribution(
        relation="unknown",
        note="Press/portrait photograph, photographer unrecorded; field held the sitter.",
    ),
    "d7869c2-34-dwight-eisenhower-june-1956": Attribution(
        relation="unknown",
        note="Official portrait photograph, photographer unrecorded; field held the sitter.",
    ),
    "e6494c8-32-2-anna-eleanor-roosevelt-portrait": Attribution(
        relation="unknown",
        note="Portrait photograph, photographer unrecorded; field held a caption.",
    ),
}


@dataclass
class CatalogStats:
    matched: int
    changed: int
    holders_set: int
    mirrored: int


def _sidecar_paths(staging_dir: Path) -> list[Path]:
    paths = set(staging_dir.rglob("meta.json"))
    paths.update(staging_dir.glob("*.json"))
    return sorted(path for path in paths if path.is_file())


def _qid_ref(qid: str | None) -> str | None:
    return f"https://www.wikidata.org/wiki/{qid}" if qid else None


def _apply(meta: dict[str, Any], attr: Attribution, *, client: Any, now: str) -> bool:
    """Apply one attribution. Returns True if a holder was set."""
    artist = meta.setdefault("artist", {})
    if not isinstance(artist, dict):  # pragma: no cover - malformed guard
        raise ValueError("artist must be an object")
    if attr.name:
        artist["name"] = attr.name
    elif attr.relation in ("anonymous", "unknown"):
        # controlled display for an unknown maker; the sitter/subject lives in title
        artist["name"] = f"Unknown ({attr.nationality})" if attr.nationality else "Unknown"
    if attr.relation:
        artist["relation"] = attr.relation
    if attr.nationality:
        artist["nationality"] = attr.nationality
    if attr.confidence:
        artist["attribution_confidence"] = attr.confidence
    if attr.anchor:
        artist["attribution_anchor"] = attr.anchor

    if attr.qid:
        artist["wikidata_q"] = attr.qid
        display_name, lifespan = fetch_identity(attr.qid, client=client)
        artist["canonical"] = {
            "wikidata_q": attr.qid,
            "display_name": display_name,
            "lifespan": lifespan,
            "family_key": fold_name(display_name) if display_name else None,
            "method": "manual_research",
            "confidence": 0.95,
            "resolved_at": now,
            "notes": attr.note,
        }
        if lifespan and not artist.get("lifespan"):
            artist["lifespan"] = lifespan
        provenance.set(
            meta,
            "artist_qid",
            "available",
            "research",
            source_ref=_qid_ref(attr.qid),
            note=attr.note,
        )
    elif attr.relation in ("anonymous", "unknown"):
        artist["wikidata_q"] = None
        provenance.set(meta, "artist_qid", "not_available", "research", note=attr.note)

    holder_set = False
    if attr.holder_qid:
        meta["holder"] = {
            "name": attr.holder_name,
            "wikidata_q": attr.holder_qid,
            "ror": None,
            "accession": None,
            "url": None,
        }
        provenance.set(
            meta,
            "holder",
            "available",
            "research",
            source_ref=_qid_ref(attr.holder_qid),
            note=f"In-situ / holding institution: {attr.holder_name}.",
        )
        holder_set = True
    return holder_set


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
    log_path: Path, meta: dict[str, Any], attr: Attribution, staging_path: Path, mirrors: list[Path]
) -> None:
    entry = {
        "ts": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "actor": "catalog_floor_attribution",
        "op": "floor_attribution",
        "work_id": meta["work_id"],
        "artist_qid": attr.qid,
        "relation": attr.relation,
        "holder_qid": attr.holder_qid,
        "note": attr.note,
        "staging_path": str(staging_path),
        "mirror_paths": [str(path) for path in mirrors],
    }
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")


def catalog(
    staging_dir: Path,
    *,
    client: Any,
    attributions: dict[str, Attribution] = ATTRIBUTIONS,
    art_works_root: Path | None = None,
    operations_log: Path | None = None,
    apply: bool = False,
    now: str | None = None,
) -> tuple[CatalogStats, list[str]]:
    stamp = now or datetime.now(UTC).isoformat().replace("+00:00", "Z")
    matched = changed = holders = mirrored = 0
    outcomes: list[str] = []
    for path in _sidecar_paths(staging_dir):
        meta = sidecar.load(path)
        work_id = str(meta.get("work_id") or "")
        attr = attributions.get(work_id)
        if attr is None:
            continue
        matched += 1
        holder_set = _apply(meta, attr, client=client, now=stamp)
        sidecar.validate(meta)
        changed += 1
        holders += int(holder_set)
        label = attr.qid or attr.relation or "?"
        outcomes.append(f"OK    {work_id}: {label}{' +holder' if holder_set else ''}")
        if apply:
            sidecar.write(path, meta)
            mirrors = _write_existing_mirrors(meta, art_works_root, exclude=path)
            mirrored += len(mirrors)
            if operations_log is not None:
                _append_operation(operations_log, meta, attr, path, mirrors)
    return CatalogStats(matched, changed, holders, mirrored), outcomes


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
    parser.add_argument("--timeout", type=float, default=15.0)
    args = parser.parse_args(argv)

    stats, outcomes = catalog(
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
        f"\nfloor attribution ({mode}): matched={stats.matched} changed={stats.changed} "
        f"holders_set={stats.holders_set} mirrored={stats.mirrored}"
    )
    unseen = sorted(set(ATTRIBUTIONS) - {ln.split()[1].rstrip(":") for ln in outcomes})
    if unseen:
        print("WARNING: table entries with no matching sidecar:", unseen)
    if not args.apply and stats.changed:
        print("(dry-run: no files written; re-run with --apply)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
