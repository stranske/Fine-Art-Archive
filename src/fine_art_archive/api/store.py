"""Read-only store backed by staging_sidecars/, manifest.csv, and the
ratings event log.

This module is the only one in the api/ subpackage that touches the
filesystem. The rest of the API consumes it.
"""

from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from functools import lru_cache

from fine_art_archive.identity import build_alias_table, resolve_artist

from .config import REPO_ROOT, env_path

STAGING = env_path("FAA_STAGING_DIR", REPO_ROOT / "staging_sidecars")
MANIFEST_CSV = env_path("FAA_MANIFEST_CSV", REPO_ROOT / "manifest.csv")
RATINGS_LOG = env_path("FAA_RATINGS_LOG", REPO_ROOT / "data" / "ratings_log.jsonl")


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
@lru_cache(maxsize=1)
def load_manifest() -> list[dict]:
    """Load the flat manifest CSV. Cached for the process lifetime."""
    if not MANIFEST_CSV.exists():
        return []
    with open(MANIFEST_CSV) as f:
        return list(csv.DictReader(f))


def _matches_query(row: dict, ql: str) -> bool:
    """Search match. Includes raw title + raw artist_name + the
    canonical artist name + the canonical family_key. That last one is
    what makes searching 'Brueghel' return all 40 'Bruegel' works too."""
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

    return bool(ql in fold_name(raw_artist) or (cname and ql in fold_name(cname)))


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


def get_work(work_id: str) -> dict | None:
    sidecar_path = STAGING / work_id / "meta.json"
    if not sidecar_path.exists():
        return None
    with open(sidecar_path) as f:
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


def _load_ratings() -> list[dict]:
    """Load all rating events. Cached; call invalidate_ratings_cache()
    after appending."""
    global _RATINGS_CACHE
    if _RATINGS_CACHE is not None:
        return _RATINGS_CACHE
    events: list[dict] = []
    if RATINGS_LOG.exists():
        with open(RATINGS_LOG) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    _RATINGS_CACHE = events
    return events


def _ratings_by_work() -> dict[str, list[dict]]:
    global _RATINGS_BY_WORK
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
    global _RATINGS_CACHE, _RATINGS_BY_WORK
    _RATINGS_CACHE = None
    _RATINGS_BY_WORK = None


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


def ratings_summary() -> dict:
    events = _load_ratings()
    dist = Counter(e.get("rating") for e in events if e.get("rating") is not None)
    quality_dist = Counter(e.get("quality") for e in events if e.get("quality") is not None)
    fit_dist = Counter(e.get("fit") for e in events if e.get("fit") is not None)
    by_surface = Counter(e.get("surface") for e in events)
    by_work = _ratings_by_work()
    return {
        "n_events": len(events),
        "n_works_rated": len(by_work),
        "rating_distribution": {str(k): dist[k] for k in sorted(dist, key=str)},
        "quality_distribution": {str(k): quality_dist[k] for k in sorted(quality_dist, key=str)},
        "fit_distribution": {str(k): fit_dist[k] for k in sorted(fit_dist, key=str)},
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
