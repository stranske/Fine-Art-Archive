"""Store backed by the canonical works tree, manifest.csv, and the ratings event log.

This module owns API filesystem access, including manifest/sidecar reads and
ratings-log appends. The rest of the API consumes it.
"""

from __future__ import annotations

import csv
import json
import os
import re
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path
from typing import Any

from fine_art_archive.identity import build_alias_table, resolve_artist

from .config import DEFAULT_ART_WORKS_ROOT, REPO_ROOT, env_path


def _works_dir() -> Path:
    """Resolve the ONE sidecar tree: `<works>/<wid>/meta.json`.

    The archive used to keep sidecars in two trees — `staging_sidecars/` and
    `Art/works/` — with the second declared canonical and the first the one
    this store actually read. They drifted, and because every audit check read
    staging too, all of them reported clean while the canonical tree held real
    defects. The workspace collapsed them onto `Art/works` (its DECISIONS.md
    D020, 2026-08-10) and quarantined the other.

    `FAA_STAGING_DIR` is the retired name. It is still honoured so a deployment
    that sets it keeps starting — but it now names a tree that no longer exists,
    so anything still setting it is pointed at an empty directory and should
    move to `FAA_WORKS_DIR`.
    """
    if os.environ.get("FAA_WORKS_DIR"):
        return env_path("FAA_WORKS_DIR", DEFAULT_ART_WORKS_ROOT)
    return env_path("FAA_STAGING_DIR", DEFAULT_ART_WORKS_ROOT)


WORKS = _works_dir()
MANIFEST_CSV = env_path("FAA_MANIFEST_CSV", REPO_ROOT / "manifest.csv")
RATINGS_LOG = env_path("FAA_RATINGS_LOG", REPO_ROOT / "data" / "ratings_log.jsonl")
_WORK_ID_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_QID_RE = re.compile(r"^Q[0-9]+$")
_FileSignature = tuple[int, int]


def validate_work_id(work_id: str) -> str:
    """Validate a URL-supplied work_id before using it as a path segment."""
    if not work_id or work_id in {".", ".."}:
        raise ValueError("invalid work_id")
    if "/" in work_id or "\\" in work_id or "\x00" in work_id:
        raise ValueError("invalid work_id")
    if not _WORK_ID_RE.fullmatch(work_id):
        raise ValueError("invalid work_id")
    return work_id


def contained_work_path(root: Path, work_id: str, *parts: str) -> Path:
    """Return root/work_id/parts after proving the result stays under root."""
    safe_work_id = validate_work_id(work_id)
    root_path = root.resolve(strict=False)
    candidate = (root_path / safe_work_id).joinpath(*parts).resolve(strict=False)
    if not candidate.is_relative_to(root_path):
        raise ValueError("work_id path escapes archive root")
    return candidate


def sidecar_path(work_id: str) -> Path:
    return contained_work_path(WORKS, work_id, "meta.json")


# --------------------------------------------------------------------------
# Resolver — apply at read-time so split spellings merge in the UI even
# before the bulk sidecar update lands.
# --------------------------------------------------------------------------
@lru_cache(maxsize=1)
def _alias_table():
    return build_alias_table()


@lru_cache(maxsize=4096)
def _resolve_cached(raw: str) -> tuple[str | None, str | None]:
    """Returns (canonical_q, canonical_display_name) for a raw string,
    or (None, None) when unresolved. Cached for the process lifetime."""
    if not raw:
        return None, None
    r = resolve_artist(raw, _alias_table(), allow_wikidata=False)
    return r.q, r.display_name


# --------------------------------------------------------------------------
# Manifest + sidecars
# --------------------------------------------------------------------------
_MANIFEST_CACHE: list[dict] | None = None
_MANIFEST_SIGNATURE: _FileSignature | None = None


def _file_signature(path: Path) -> _FileSignature | None:
    try:
        stat = path.stat()
    except FileNotFoundError:
        return None
    return (stat.st_mtime_ns, stat.st_size)


def load_manifest() -> list[dict]:
    """Load the flat manifest CSV, reloading when the file changes."""
    global _MANIFEST_CACHE, _MANIFEST_SIGNATURE
    signature = _file_signature(MANIFEST_CSV)
    if signature is None:
        _MANIFEST_CACHE = []
        _MANIFEST_SIGNATURE = None
        return []
    if _MANIFEST_CACHE is not None and signature == _MANIFEST_SIGNATURE:
        return _MANIFEST_CACHE
    try:
        with open(MANIFEST_CSV) as f:
            rows = list(csv.DictReader(f))
    except FileNotFoundError:
        _MANIFEST_CACHE = []
        _MANIFEST_SIGNATURE = None
        return []
    _MANIFEST_CACHE = rows
    _MANIFEST_SIGNATURE = signature
    return rows


def invalidate_manifest_cache() -> None:
    global _MANIFEST_CACHE, _MANIFEST_SIGNATURE
    _MANIFEST_CACHE = None
    _MANIFEST_SIGNATURE = None


def _matches_query(row: dict, ql: str) -> bool:
    """Search match over the title and every name the archive knows for the artist.

    Four passes, widening: the raw title, the raw `artist_name`, the canonical display
    name, and a folded comparison of both so accents do not have to be typed (`durer`
    finds `Dürer`).

    The last pass resolves the QUERY through the same curated alias table the rows go
    through, and matches when both land on the same Wikidata Q-ID. Without it, a name
    this repository explicitly asserts is the same painter finds nothing: `CURATED_ALIASES`
    lists `Pieter Brueghel` and `Pieter Bruegel I` under Q43270, the works are catalogued
    as `Pieter Bruegel the Elder` under Q43270, and searching either alias returned an
    empty archive because no substring of one appears in the other.

    This cannot over-match. It fires only where the curated table already says two
    spellings are one person, so it unifies exactly the variants somebody chose to
    record — and a bare surname like `Brueghel`, which resolves to nothing, still
    matches nothing.
    """
    raw_artist = row.get("artist_name", "") or ""
    cq, cname = _resolve_cached(raw_artist)
    if ql in (row.get("title", "") or "").lower():
        return True
    if ql in raw_artist.lower():
        return True
    if cname and ql in cname.lower():
        return True
    # Also try a folded-name comparison so accent / spelling variants hit
    from fine_art_archive.identity.artist_resolver import fold_name

    qf = fold_name(ql)
    if qf and (qf in fold_name(raw_artist) or (cname and qf in fold_name(cname))):
        return True
    # Finally, an alias the curated table maps to the same artist as this row.
    query_q, _ = _resolve_cached(ql)
    return bool(query_q and cq and query_q == cq)


def list_works(
    *, q: str | None = None, artist: str | None = None, limit: int = 50, offset: int = 0
) -> dict:
    rows = load_manifest()
    if q:
        ql = q.lower().strip()
        rows = [r for r in rows if _matches_query(r, ql)]
    if artist:
        al = artist.lower().strip()
        # Artist filter: match either raw artist_name OR canonical Q-ID
        rows_out = []
        for r in rows:
            raw = r.get("artist_name", "") or ""
            cq, cname = _resolve_cached(raw)
            if al in raw.lower():
                rows_out.append(r)
                continue
            if cq and (al == cq.lower() or (cname and al in cname.lower())):
                rows_out.append(r)
                continue
        rows = rows_out
    # Attach the most recent rating's value(s) + the canonical artist.
    # Events may be on either schema: two-axis (quality+fit) or legacy
    # single-axis (rating). Expose all three so the UI can decide.
    by_work = _ratings_by_work()
    out = []
    for r in rows[offset : offset + limit]:
        latest = by_work.get(r.get("work_id"), [])  # type: ignore[arg-type]
        last_ev = latest[-1] if latest else None
        raw = r.get("artist_name", "") or ""
        cq, cname = _resolve_cached(raw)
        out.append(
            {
                **r,
                "_last_rating": (last_ev or {}).get("rating"),  # legacy axis
                "_last_quality": (last_ev or {}).get("quality"),  # two-axis
                "_last_fit": (last_ev or {}).get("fit"),  # two-axis
                "_n_ratings": len(latest),
                "_canonical_q": cq,
                "_canonical_name": cname,
            }
        )
    return {"total": len(rows), "offset": offset, "limit": limit, "works": out}


_dossier_cache: dict[str, object] = {"sig": None, "ids": frozenset()}


def _dossier_signature() -> tuple[int, int, int, int] | None:
    """Cheap change-detector for the staging tree.

    Aggregates the mtime and size of each *meta.json*, plus WORKS's own
    mtime. Per-work directory mtimes alone are not enough: rewriting an
    existing <works>/<wid>/meta.json in place changes neither
    WORKS's mtime nor the work directory's — only the file's own mtime
    moves, and that is the common case (dossier/subject passes rewrite
    existing sidecars). WORKS's mtime is still required so directory
    rename/move/add/remove operations invalidate the cache even when the
    individual meta.json mtime+size aggregates would otherwise match.

    Costs one stat per sidecar (~0.02 s for 3.4k works) against ~0.7 s to
    re-read them all, so it is cheap enough to run per request.
    """
    try:
        staging_mtime = WORKS.stat().st_mtime_ns
        mtimes = sizes = count = 0
        for entry in os.scandir(WORKS):
            try:
                st = os.stat(os.path.join(entry.path, "meta.json"))
            except OSError:
                continue
            mtimes += st.st_mtime_ns
            sizes += st.st_size
            count += 1
        return staging_mtime, mtimes, sizes, count
    except OSError:
        return None


def work_ids_with_dossier() -> frozenset[str]:
    """Return the set of work_ids whose sidecar has a populated dossier.

    Result is cached against `_dossier_signature()`, so edits to existing
    sidecars are picked up without a restart. Uses a cheap substring probe
    (avoids parsing every sidecar) — a dossier is "populated" when it carries a
    viewer_summary, key_facts, or references.
    """
    sig = _dossier_signature()
    if sig is None:
        return frozenset()
    if _dossier_cache["sig"] == sig:
        return _dossier_cache["ids"]  # type: ignore[return-value]
    ids: set[str] = set()
    for meta in WORKS.glob("*/meta.json"):
        try:
            text = meta.read_text(encoding="utf-8")
        except OSError:
            continue
        if '"dossier"' not in text:
            continue
        if not any(k in text for k in ('"viewer_summary"', '"key_facts"', '"references"')):
            continue
        ids.add(meta.parent.name)
    frozen = frozenset(ids)
    _dossier_cache["sig"] = sig
    _dossier_cache["ids"] = frozen
    return frozen


# --------------------------------------------------------------------------
# Acquisition review — the FYI surface behind grant G55.
#
# G55 makes Track A growth standing (200 works/month, promoted with no human in
# the loop). Tim's approval was explicitly conditional: he must be able to see
# what was acquired and mark it reviewed. This is that list.
#
# It is a VIEW, never a queue. Promotion does not wait for review, nothing
# expires, and an unread list has no consequence — so no backlog can form.
# --------------------------------------------------------------------------
OWNER_REVIEW_OP = "owner-review"

# Everything before this was hand-driven and already seen; the surface exists
# for the autonomous era only. Override for tests or a re-baseline.
AUTOMATION_EPOCH = os.environ.get("FAA_AUTOMATION_EPOCH", "2026-08-09")

_acq_cache: dict[str, Any] = {"sig": None, "rows": []}


def _first_history_ts(meta: dict) -> str:
    """Timestamp of a work's earliest history event, or "" if it has none."""
    stamps = [str(e.get("ts") or "") for e in (meta.get("history") or [])]
    stamps = [s for s in stamps if s]
    return min(stamps) if stamps else ""


def _owner_review_event(meta: dict) -> dict | None:
    """The most recent owner-review event on a work, if any."""
    seen = [e for e in (meta.get("history") or []) if e.get("op") == OWNER_REVIEW_OP]
    return max(seen, key=lambda e: str(e.get("ts") or "")) if seen else None


def _image_pixels(path: Path) -> tuple[int, int] | None:
    """Master dimensions, or None when they cannot be read.

    None means "could not measure". It is never rendered as a size, because a
    missing number that looks like a small number is how a transfer failure
    came to read as a low-quality picture.
    """
    try:
        import warnings

        from PIL import Image

        with warnings.catch_warnings():
            # Header read only, no decode. The bomb warning would otherwise
            # fire on every gigapixel master and bury real log lines.
            warnings.simplefilter("ignore", Image.DecompressionBombWarning)
            with Image.open(path) as im:
                return int(im.width), int(im.height)
    except Exception:  # noqa: BLE001 - unreadable, truncated, or no PIL
        return None


def _master_health(path: Path) -> str:
    """ "ok" | "truncated" | "unchecked" for an archived master.

    A JPEG marker pair is only a cheap hint: a marker-only file is not an
    image, while a master missing its final marker can still decode perfectly.
    Decode every readable master so both cases receive the truthful result.

    "unchecked" is returned when neither stage could run, and is never
    collapsed into "ok" -- not looking is not a clean bill.
    """
    try:
        with open(path, "rb") as fh:
            fh.read(1)
    except OSError:
        return "unchecked"

    try:
        import warnings

        from PIL import Image

        with warnings.catch_warnings():
            warnings.simplefilter("ignore", Image.DecompressionBombWarning)
            # This corpus is full of gigapixel museum scans that we fetched
            # ourselves, so Pillow's bomb ceiling is a false alarm here --
            # `_serve_resized`, `_image_dims` and the dedup cascade all lift it
            # for the same reason. Leaving it in place made a PERFECTLY GOOD
            # file report as damaged: Leonardo's *Virgin and Child with Saint
            # Anne* is 13295x17828 (237 MP), decodes cleanly, is byte-identical
            # to a fresh download of its source -- and was reported "truncated"
            # because DecompressionBombError landed in the except below. The
            # review card then told the owner not to judge a picture that was
            # never damaged.
            prev_max = Image.MAX_IMAGE_PIXELS
            try:
                Image.MAX_IMAGE_PIXELS = None
                with Image.open(path) as im:
                    im.load()
            finally:
                Image.MAX_IMAGE_PIXELS = prev_max
        return "ok"
    except Exception:  # noqa: BLE001 - any decode failure means unusable
        return "truncated"


def master_health(work_id: str) -> str:
    """ "ok" | "truncated" | "unchecked" for a work's archived master."""
    try:
        work_dir = contained_work_path(WORKS, work_id)
    except (ValueError, OSError):
        return "unchecked"
    master = _find_master(work_dir)
    return _master_health(master) if master else "unchecked"


def _find_master(work_dir: Path) -> Path | None:
    for name in ("master.jpeg", "master.jpg", "master.png", "master.tif", "master.tiff"):
        cand = work_dir / name
        if cand.exists():
            return cand
    return None


#: Per-file facts, memoised on the file's own identity rather than on the
#: sidecar cache below.
#:
#: `acquisitions_since_epoch` is invalidated whenever ANY sidecar changes, which
#: the growth tick does constantly. Before this, that re-opened every acquired
#: master to re-derive facts that had not moved: 132 files on a Dropbox-synced
#: volume, where every open() goes through the sync provider. /review took 28
#: seconds cold and paid it again after each tick — on the page whose whole
#: purpose is to be glanced at.
#:
#: Keyed on (path, mtime_ns, size), so a master that is genuinely replaced is
#: recomputed and one that is merely re-listed is not.
_MASTER_FACTS: dict[tuple[str, int, int], tuple[tuple[int, int] | None, float | None, str]] = {}

#: Where the memo survives a restart. Keeping it only in memory meant every
#: server start re-opened all 132 acquired masters before the first /review
#: could answer -- 29 seconds, on a Dropbox-synced volume where each open()
#: goes through the sync provider. The runner restarts the server routinely, so
#: that cost was paid far more often than the archive actually changed.
MASTER_FACTS_CACHE = env_path(
    "FAA_MASTER_FACTS_CACHE", REPO_ROOT / "data" / "master_facts_cache.json"
)
_MASTER_FACTS_LOADED = False
_MASTER_FACTS_DIRTY = False
#: Bounded, so neither the process nor the file grows without limit. The
#: working set is the acquisition list, which is small.
_MASTER_FACTS_MAX = 4096


def _load_master_facts() -> None:
    """Warm the memo from disk, once, and never fail because of it.

    A cache that cannot be read is a cache miss, not an error: every entry is
    recomputable from the file it describes. It is also never trusted blindly --
    each key carries the file's mtime and size, so a master that has actually
    changed misses and is re-examined.
    """
    global _MASTER_FACTS_LOADED
    if _MASTER_FACTS_LOADED:
        return
    _MASTER_FACTS_LOADED = True
    try:
        raw = json.loads(MASTER_FACTS_CACHE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if not isinstance(raw, dict):
        return
    for key, value in list(raw.get("entries", {}).items())[:_MASTER_FACTS_MAX]:
        try:
            path, mtime, size = key.rsplit("\u0000", 2)
            px, size_mb, health = value
            pixels = (int(px[0]), int(px[1])) if px else None
            # "unchecked" means we could not look. Persisting it would turn one
            # transient read failure into a permanent verdict, so it is dropped
            # and recomputed instead.
            if health not in {"ok", "truncated"}:
                continue
            _MASTER_FACTS[(path, int(mtime), int(size))] = (pixels, size_mb, str(health))
        except (ValueError, TypeError, IndexError):
            continue


def flush_master_facts() -> None:
    """Persist newly computed facts. Best effort: a failure costs only speed."""
    global _MASTER_FACTS_DIRTY
    if not _MASTER_FACTS_DIRTY:
        return
    _MASTER_FACTS_DIRTY = False
    entries = {
        "\u0000".join((path, str(mtime), str(size))): [list(px) if px else None, mb, health]
        for (path, mtime, size), (px, mb, health) in _MASTER_FACTS.items()
        if health in {"ok", "truncated"}
    }
    try:
        MASTER_FACTS_CACHE.parent.mkdir(parents=True, exist_ok=True)
        tmp = MASTER_FACTS_CACHE.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({"entries": entries}), encoding="utf-8")
        # Atomic, so a torn write cannot replace a good cache.
        tmp.replace(MASTER_FACTS_CACHE)
    except OSError:
        return


def _master_facts(
    master: Path | None,
) -> tuple[tuple[int, int] | None, float | None, str, bool]:
    """(pixels, size_mb, health, stat_failed) for a master, cached by file identity."""
    global _MASTER_FACTS_DIRTY
    if master is None:
        return None, None, "unchecked", False
    try:
        st = master.stat()
    except OSError:
        # A master can disappear between _find_master() and here. Keep the row
        # useful and make the uncertainty explicit rather than reporting zero.
        return None, None, "unchecked", True
    _load_master_facts()
    key = (str(master), st.st_mtime_ns, st.st_size)
    hit = _MASTER_FACTS.get(key)
    if hit is None:
        hit = (_image_pixels(master), round(st.st_size / 1e6, 1), _master_health(master))
        if len(_MASTER_FACTS) > _MASTER_FACTS_MAX:
            _MASTER_FACTS.clear()
        _MASTER_FACTS[key] = hit
        _MASTER_FACTS_DIRTY = True
    return hit[0], hit[1], hit[2], False


def _acquisition_evidence(meta: dict, work_dir: Path) -> dict:
    prov = meta.get("acquisition_provenance") or {}
    rights = meta.get("rights") or {}
    holder = meta.get("holder") or {}
    master = _find_master(work_dir)
    px, size_mb, health, stat_failed = _master_facts(master)
    return {
        "holder_name": holder.get("name") or "",
        "source": prov.get("source") or "",
        "source_filename": prov.get("commons_filename") or "",
        "source_url": prov.get("image_url") or "",
        "scaled_rendition": bool(prov.get("scaled_rendition")),
        "wikidata_q": (meta.get("stable_identifiers") or {}).get("wikidata_q") or "",
        "rights_status": rights.get("status") or "",
        "rights_evidence_url": rights.get("evidence_url") or "",
        # Absent, not zero. `pixels_measured` says which.
        "pixels_measured": px is not None,
        "width_px": px[0] if px else None,
        "height_px": px[1] if px else None,
        "megapixels": round(px[0] * px[1] / 1e6, 1) if px else None,
        "master_mb": size_mb,
        # "ok" | "truncated" | "unchecked". Never collapse the last into the
        # first: not looking is not a clean bill.
        "file_health": health,
    }


def acquisitions_since_epoch(epoch: str | None = None) -> list[dict]:
    """Works acquired in the autonomous era, newest first, with review state.

    Membership is decided by the FIRST history event's timestamp, NOT by
    matching acquisition op names. That is deliberate. `op` is a free-form
    string and has already drifted in this archive (`batch-acquire-v3`,
    `phase3-bulk-move`, `staging-sidecar-build`, ...), so a list defined by
    op-name matching would silently omit anything acquired by a future writer
    that spelled its op differently. A review surface that silently omits works
    is worse than no review surface at all: it reads as "nothing to see" when
    the truth is "we did not look". Every sidecar has a first history event, so
    this criterion cannot drift.
    """
    cutoff = epoch if epoch is not None else AUTOMATION_EPOCH
    sig = (_dossier_signature(), cutoff)
    if _acq_cache["sig"] == sig:
        return list(_acq_cache["rows"])

    rows: list[dict] = []
    for meta_path in WORKS.glob("*/meta.json"):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        acquired_at = _first_history_ts(meta)
        if not acquired_at or acquired_at < cutoff:
            continue
        reviewed = _owner_review_event(meta)
        rows.append(
            {
                "work_id": meta_path.parent.name,
                "title": meta.get("title", ""),
                "artist_name": (meta.get("artist") or {}).get("name", ""),
                "year": meta.get("year", ""),
                "acquired_at": acquired_at,
                "acquired_by": next(
                    (
                        e.get("actor", "")
                        for e in (meta.get("history") or [])
                        if e.get("ts") == acquired_at
                    ),
                    "",
                ),
                "reviewed": reviewed is not None,
                "reviewed_at": (reviewed or {}).get("ts"),
                "reviewed_by": (reviewed or {}).get("actor"),
                "review_note": (reviewed or {}).get("notes"),
                # The evidence a person needs to say "yes, that is the picture
                # I meant to acquire". The list used to carry a title, a name
                # and a 68 px icon -- which cannot show that a work titled
                # "Poppy Field near ARGENTEUIL" was filled from a file named
                # "Poppy Field in a Hollow near GIVERNY". The source filename
                # and URL are the only place that disagreement is visible.
                **_acquisition_evidence(meta, meta_path.parent),
            }
        )
    rows.sort(key=lambda r: str(r["acquired_at"]), reverse=True)
    _acq_cache["sig"] = sig
    _acq_cache["rows"] = rows
    # Persist whatever this pass had to compute, so the NEXT process start does
    # not re-open every master. Written once per rebuild rather than per file:
    # one write for a scan that touched up to 132 of them.
    flush_master_facts()
    return list(rows)


def invalidate_acquisitions_cache() -> None:
    _acq_cache["sig"] = None
    _acq_cache["rows"] = []


_artist_qid_cache: dict[str, Any] = {"sig": None, "qids": frozenset()}


def artist_qid(meta: dict) -> str | None:
    """The artist Q-ID a sidecar carries, or None when it carries none.

    Prefers the resolver's canonical Q-ID and falls back to the raw one, so an
    artist whose name is spelled two ways still resolves to a single Q-ID.

    Shared by `known_artist_qids()` and `scripts/build_manifest.py` so the
    screener's idea of which Q-ID a work carries cannot drift from the one the
    manifest publishes to the UI.
    """
    artist = meta.get("artist")
    if not isinstance(artist, dict):
        return None
    canonical = artist.get("canonical")
    canonical_qid = canonical.get("wikidata_q") if isinstance(canonical, dict) else None
    raw_qid = artist.get("wikidata_q")
    qid = (
        canonical_qid
        if isinstance(canonical_qid, str) and _QID_RE.fullmatch(canonical_qid)
        else raw_qid
    )
    return qid if isinstance(qid, str) and _QID_RE.fullmatch(qid) else None


def known_artist_qids() -> frozenset[str]:
    """Artist Q-IDs the archive already holds at least one work by.

    Read from sidecars rather than the manifest because this set decides what
    the acquisition screener treats as "already represented", and the screener
    reads sidecars.
    """
    sig = _dossier_signature()
    if _artist_qid_cache["sig"] == sig:
        return _artist_qid_cache["qids"]

    qids: set[str] = set()
    for meta_path in WORKS.glob("*/meta.json"):
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(meta, dict):
            continue
        qid = artist_qid(meta)
        if qid is not None:
            qids.add(qid)
    frozen = frozenset(qids)
    _artist_qid_cache["sig"] = sig
    _artist_qid_cache["qids"] = frozen
    return frozen


def invalidate_artist_qid_cache() -> None:
    _artist_qid_cache["sig"] = None
    _artist_qid_cache["qids"] = frozenset()


def get_manifest_row(work_id: str) -> dict | None:
    """Return a manifest row, or None when unknown.

    Raises ValueError for malformed work IDs.
    """
    safe_work_id = validate_work_id(work_id)
    for row in load_manifest():
        if row.get("work_id") == safe_work_id:
            return row
    return None


def get_work(work_id: str) -> dict | None:
    """Return a sidecar payload, or raise ValueError for malformed work IDs."""
    path = sidecar_path(work_id)
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


def list_artists(*, limit: int = 100) -> list[dict]:
    """Return artists sorted by work count, descending.

    Grouped by canonical Wikidata Q-ID where the resolver maps; raw
    strings without a canonical mapping group on themselves. Each entry
    shows how many raw strings folded together so Tim can see the
    deduplication at a glance.
    """
    counts: dict[str, dict] = {}
    for r in load_manifest():
        raw = (r.get("artist_name") or "").strip()
        if not raw:
            continue
        cq, cname = _resolve_cached(raw)
        key = cq or f"raw:{raw}"
        display = cname or raw
        entry = counts.setdefault(
            key,
            {
                "key": key,
                "canonical_q": cq,
                "name": display,
                "n_works": 0,
                "_raw_strings": Counter(),
            },
        )
        entry["n_works"] += 1
        entry["_raw_strings"][raw] += 1
    out = []
    for e in sorted(counts.values(), key=lambda x: -x["n_works"])[:limit]:
        raws = e.pop("_raw_strings")
        e["n_raw_strings_merged"] = len(raws)
        # Show the top 3 raw spellings for context
        e["raw_examples"] = [r for r, _ in raws.most_common(3)]
        out.append(e)
    return out


# --------------------------------------------------------------------------
# Ratings event log
# --------------------------------------------------------------------------
_RATINGS_CACHE: list[dict] | None = None
_RATINGS_BY_WORK: dict[str, list[dict]] | None = None
_RATINGS_SIGNATURE: _FileSignature | None = None
_RATINGS_CORRUPT_LINES = 0


def _load_ratings() -> list[dict]:
    """Load all rating events, reloading when the log file changes."""
    global _RATINGS_CACHE, _RATINGS_BY_WORK, _RATINGS_SIGNATURE, _RATINGS_CORRUPT_LINES
    signature = _file_signature(RATINGS_LOG)
    if signature is None:
        _RATINGS_CACHE = []
        _RATINGS_BY_WORK = None
        _RATINGS_SIGNATURE = None
        _RATINGS_CORRUPT_LINES = 0
        return []
    if _RATINGS_CACHE is not None and signature == _RATINGS_SIGNATURE:
        return _RATINGS_CACHE
    events: list[dict] = []
    corrupt_lines = 0
    try:
        with open(RATINGS_LOG) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    corrupt_lines += 1
    except FileNotFoundError:
        _RATINGS_CACHE = []
        _RATINGS_BY_WORK = None
        _RATINGS_SIGNATURE = None
        _RATINGS_CORRUPT_LINES = 0
        return []
    _RATINGS_CACHE = events
    _RATINGS_BY_WORK = None
    _RATINGS_SIGNATURE = signature
    _RATINGS_CORRUPT_LINES = corrupt_lines
    return events


def _ratings_by_work() -> dict[str, list[dict]]:
    global _RATINGS_BY_WORK
    _load_ratings()
    if _RATINGS_BY_WORK is not None:
        return _RATINGS_BY_WORK
    out: dict[str, list[dict]] = defaultdict(list)
    for ev in _load_ratings():
        wid = ev.get("work_id")
        if wid:
            out[wid].append(ev)
    # Keep per-work lists sorted by ts so [-1] is the latest
    for wid in out:
        out[wid].sort(key=lambda e: e.get("ts", ""))
    _RATINGS_BY_WORK = out
    return out


def invalidate_ratings_cache() -> None:
    global _RATINGS_CACHE, _RATINGS_BY_WORK, _RATINGS_SIGNATURE, _RATINGS_CORRUPT_LINES
    _RATINGS_CACHE = None
    _RATINGS_BY_WORK = None
    _RATINGS_SIGNATURE = None
    _RATINGS_CORRUPT_LINES = 0


def append_rating(event: dict) -> None:
    """Append a rating event and invalidate cached rating reads."""
    payload = json.dumps(event, ensure_ascii=False, allow_nan=False)
    RATINGS_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(RATINGS_LOG, "a", encoding="utf-8") as handle:
        handle.write(payload + "\n")
    invalidate_ratings_cache()


def ratings_corrupt_line_count() -> int:
    _load_ratings()
    return _RATINGS_CORRUPT_LINES


def latest_rating(work_id: str) -> dict | None:
    events = _ratings_by_work().get(work_id) or []
    return events[-1] if events else None


def list_ratings_for(work_id: str) -> list[dict]:
    return list(_ratings_by_work().get(work_id) or [])


def count_ratings_for(work_id: str) -> int:
    return len(_ratings_by_work().get(work_id) or [])


def count_ratings() -> int:
    return len(_load_ratings())


def recent_ratings(*, limit: int = 20) -> list[dict]:
    return sorted(_load_ratings(), key=lambda e: e.get("ts", ""), reverse=True)[:limit]


def _numeric_distribution(dist: Counter) -> dict[str, int]:
    return {str(k): dist[k] for k in sorted(dist)}


def ratings_summary() -> dict:
    events = _load_ratings()
    dist = Counter(e.get("rating") for e in events if e.get("rating") is not None)
    quality_dist = Counter(e.get("quality") for e in events if e.get("quality") is not None)
    fit_dist = Counter(e.get("fit") for e in events if e.get("fit") is not None)
    by_surface = Counter(e.get("surface") for e in events)
    by_work = _ratings_by_work()
    return {
        "n_events": len(events),
        "corrupt_line_count": _RATINGS_CORRUPT_LINES,
        "n_works_rated": len(by_work),
        "rating_distribution": _numeric_distribution(dist),
        "quality_distribution": _numeric_distribution(quality_dist),
        "fit_distribution": _numeric_distribution(fit_dist),
        "by_surface": dict(by_surface),
        "most_rated_works": [
            {
                "work_id": w,
                "n_ratings": len(evs),
                "last_rating": evs[-1].get("rating"),
                "last_quality": evs[-1].get("quality"),
                "last_fit": evs[-1].get("fit"),
            }
            for w, evs in sorted(by_work.items(), key=lambda kv: -len(kv[1]))[:10]
        ],
    }
