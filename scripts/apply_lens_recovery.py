#!/usr/bin/env python3
"""Apply Google Lens image-search recoveries to sidecars (resumable).

Image search identifies a work from its picture when the *text* metadata is
corrupt -- recovering the correct artist and title, and sometimes a Wikidata QID
outright. This applies those findings conservatively:

  * corrects ``artist.name`` and/or ``title`` from the Lens identification
    (keeping the prior value in the provenance note);
  * when a Wikidata work QID is supplied, VERIFIES it is an artwork
    (P31/P279* -> Q838948) before setting ``stable_identifiers.wikidata_q``;
  * stamps ``field_provenance`` with ``source="google-lens"`` and the
    corroborating museum/Wikidata source, so every change is auditable.

It does NOT itself resolve artist/work QIDs from the corrected text -- that is
left to the tested ``resolve_creators`` / ``resolve_work_qids`` passes, which run
afterwards on the now-correct text. Resumable: a record whose sidecar already
carries a ``google-lens`` provenance for that value is skipped.

Input: a JSONL file, one finding per line:
  {"work_id": "...", "artist_name": "...", "title": "...",
   "wikidata_q": "Q...", "source": "NGA/Wikidata/...", "note": "..."}
Dry-run by default; ``--apply`` writes + mirrors + logs.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from _paths import default_works_dir  # noqa: E402
from _sidecar_io import script_env_path as _env_path  # noqa: E402
from _sidecar_io import write_existing_mirrors as _write_existing_mirrors  # noqa: E402
from jsonschema import ValidationError as _ValidationError  # noqa: E402
from scripts.resolve_work_qids import SparqlClient  # noqa: E402

from fine_art_archive import provenance, sidecar  # noqa: E402

LENS_REF_PREFIX = "faa:google-lens"
# Terminal state written when image search CONFIRMS there is no individual artist
# to recover (a place / architecture photo, or a genuinely anonymous work). This
# is what lets a null artist become FINAL -- only after image search has looked.
REF_IMAGE_CONFIRMED = "faa:image-search/confirmed"
_NO_ARTIST_VERDICTS = {"confirmed-anonymous", "anonymous", "site", "place", "no-artist"}


def _find_sidecar(staging: Path, work_id: str) -> Path | None:
    exact = staging / work_id / "meta.json"
    if exact.is_file():
        return exact
    for p in staging.glob(f"{work_id}*/meta.json"):
        return p
    return None


def _is_artwork(qid: str, *, client: SparqlClient) -> bool:
    r = client.query(f"ASK {{ wd:{qid} wdt:P31/wdt:P279* wd:Q838948 }}")
    return bool(isinstance(r, dict) and r.get("boolean"))


def _already_lens(meta: dict[str, Any], field: str) -> bool:
    entry = (meta.get("field_provenance") or {}).get(field)
    if not isinstance(entry, dict):
        return False
    source_ref = str(entry.get("source_ref") or "")
    if source_ref.startswith(LENS_REF_PREFIX):
        return True
    # The operator guide records manual reverse-image research as a result URL.
    # Treat that form as complete only when its source explicitly identifies the
    # same research method; arbitrary URL provenance must remain eligible.
    return entry.get("source") == "reverse_image_search" and source_ref.startswith(
        ("https://", "http://")
    )


def apply_finding(
    meta: dict[str, Any], finding: dict[str, Any], *, client: SparqlClient
) -> list[str]:
    """Mutate ``meta`` from a Lens finding; return list of changes applied."""
    changes: list[str] = []
    source = str(finding.get("source") or "google-lens")
    artist_name = (finding.get("artist_name") or "").strip()
    title = (finding.get("title") or "").strip()
    work_qid = (finding.get("wikidata_q") or "").strip()
    verdict = str(finding.get("verdict") or "").strip().lower()

    # Image search CONFIRMED there is no individual artist to recover (a place /
    # architecture photo, or a genuinely anonymous work). Finalize the pending
    # null: null is now a searched, terminal outcome -- not a silent gap.
    if verdict in _NO_ARTIST_VERDICTS:
        if title:
            meta["title"] = title
        category = (finding.get("category") or "").strip()
        if category:
            meta["category"] = category
        provenance.set(
            meta,
            "artist_qid",
            "not_available",
            "google-lens",
            source_ref=REF_IMAGE_CONFIRMED,
            note=(
                finding.get("note")
                or "Image search confirms no individual artist "
                f"(verdict={verdict}); null attribution is correct. Source: {source}."
            ),
        )
        return [f"confirmed-no-artist ({verdict})"]

    if title:
        old = str(meta.get("title") or "")
        if old.strip().lower() != title.lower():
            meta["title"] = title
            changes.append(f"title {old!r}->{title!r}")

    if artist_name:
        artist = meta.setdefault("artist", {})
        if isinstance(artist, dict):
            old = str(artist.get("name") or "")
            if old.strip().lower() != artist_name.lower():
                artist["name"] = artist_name
                # a corrected name invalidates any stale relation catch-all
                if str(artist.get("relation") or "").lower() in ("unknown", "anonymous"):
                    artist.pop("relation", None)
                changes.append(f"artist {old!r}->{artist_name!r}")

    if work_qid:
        if not _is_artwork(work_qid, client=client):
            changes.append(f"REJECTED work_qid {work_qid} (not an artwork on Wikidata)")
        else:
            stable = meta.setdefault("stable_identifiers", {})
            if stable.get("wikidata_q") != work_qid:
                stable["wikidata_q"] = work_qid
                provenance.set(
                    meta,
                    "work_qid",
                    "available",
                    "google-lens",
                    source_ref=f"{LENS_REF_PREFIX}/{work_qid}",
                    note=f"Work QID via Google Lens image match; corroborated by {source}.",
                )
                changes.append(f"work_qid={work_qid}")

    if changes and (artist_name or title):
        # Record that the text was image-corrected (so resolve_creators trusts it).
        provenance.set(
            meta,
            "artist_qid",
            "not_researched",
            "google-lens",
            source_ref=f"{LENS_REF_PREFIX}/text",
            note=f"artist/title corrected from Google Lens ({source}); re-resolve QIDs.",
        )
        # A corrected TITLE re-opens the work-QID search (the retire ledger locked
        # it under the OLD, wrong title). Skip if Lens already gave the QID.
        if (
            title
            and not work_qid
            and (meta.get("stable_identifiers") or {}).get("wikidata_q") is None
        ):
            provenance.set(
                meta,
                "work_qid",
                "not_researched",
                "google-lens",
                source_ref=f"{LENS_REF_PREFIX}/title-corrected",
                note="Title corrected from image search; re-open work-QID search.",
            )
            changes.append("reopened work_qid search")
    return changes


def _log(log_path: Path, meta: dict[str, Any], finding: dict[str, Any], changes: list[str]) -> None:
    entry = {
        "ts": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "actor": "apply_lens_recovery",
        "op": "lens_recovery",
        "work_id": meta["work_id"],
        "changes": changes,
        "source": finding.get("source"),
    }
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("a", encoding="utf-8") as h:
        h.write(json.dumps(entry, ensure_ascii=False, sort_keys=True) + "\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("findings", type=Path, help="JSONL of Lens findings")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument(
        "--staging-dir",
        type=Path,
        default=default_works_dir(),
    )
    ap.add_argument("--art-works-root", type=Path, default=_env_path("FAA_ART_WORKS_ROOT"))
    ap.add_argument("--operations-log", type=Path, default=_env_path("FAA_OPERATIONS_LOG"))
    args = ap.parse_args(argv)

    client = SparqlClient()
    counts: Counter[str] = Counter()
    for line in args.findings.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        finding = json.loads(line)
        wid = finding["work_id"]
        path = _find_sidecar(args.staging_dir, wid)
        if path is None:
            counts["sidecar-not-found"] += 1
            print(f"  ! {wid}: sidecar not found")
            continue
        meta = sidecar.load(path)
        if _already_lens(meta, "work_qid") or _already_lens(meta, "artist_qid"):
            counts["already-applied"] += 1
            continue
        changes = apply_finding(meta, finding, client=client)
        if not changes:
            counts["no-change"] += 1
            continue
        counts["changed"] += 1
        print(f"  {wid}: {changes}")
        if args.apply:
            try:
                sidecar.validate(meta)
            except _ValidationError as exc:
                counts["skipped-invalid"] += 1
                print(f"  ! {wid}: invalid after edit: {str(exc)[:120]}")
                continue
            sidecar.write(path, meta)
            mirrored = _write_existing_mirrors(meta, args.art_works_root, exclude=path)
            counts["mirrored"] += len(mirrored)
            if args.operations_log:
                _log(args.operations_log, meta, finding, changes)
    print(f"\nlens-recovery ({'apply' if args.apply else 'dry-run'}):", dict(counts.most_common()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
