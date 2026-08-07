"""Playlist selection: turn a filter spec into an ordered list of works.

This is the "prepare a card by artist, period, mood, theme, rating" layer. It
reads the sidecar metadata the tagger produces plus the ratings log, and is
deliberately a pure query over what already exists rather than a new tagging
scheme.

On "mood": there is no mood tag family in the taxonomy, and inventing one would
mean 3,411 works with no values in it. What DOES exist is `palette:*` (43 tag
instances), `theme:*` (338) and `setting:*` (459). So a mood here is a NAMED
QUERY over those — `MOODS` below — which means moods work today on real data and
improve automatically as palette coverage grows. Each mood states which tags it
is built from, so a user can see why a work qualified.

On rating: the log is two-axis (quality, fit). `fit` is the right signal for a
rotation playlist — it literally asks "how much do I want to see this now" —
so `min_fit` filters on that, and `min_quality` is separate for when the point
is to show the best work rather than the most wanted.

Coverage honesty: filters over tags can only ever select from tagged works.
`PlaylistResult.coverage` reports how many candidates were excluded for having
no value on a filtered field, so a thin result reads as thin METADATA rather
than as a thin archive.
"""
from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

SortKey = Literal["fit", "quality", "year", "artist", "title", "random", "as-filtered"]

# A mood is a named query over tags that actually exist. `any_tags` means at
# least one must be present; `all_tags` means every one must be.
MOODS: dict[str, dict[str, Any]] = {
    "quiet-interior": {
        "label": "Quiet interior",
        "any_tags": ["setting:interior"],
        "not_tags": ["filter:violence", "filter:death", "theme:war"],
        "genres": ["painting/genre-scene", "painting/still-life"],
    },
    "open-air": {
        "label": "Open air",
        "any_tags": ["setting:outdoor", "setting:landscape-natural", "setting:rural"],
        "not_tags": ["setting:night"],
    },
    "winter-light": {
        "label": "Winter light",
        "any_tags": ["setting:winter"],
    },
    "nocturne": {
        "label": "Nocturne",
        "any_tags": ["setting:night", "palette:predominantly-dark"],
    },
    "cool-and-still": {
        "label": "Cool and still",
        "any_tags": ["palette:cool-toned", "palette:monochrome"],
    },
    "warm-and-bright": {
        "label": "Warm and bright",
        "any_tags": ["palette:warm-toned", "palette:predominantly-light"],
    },
    "festive": {
        "label": "Festive",
        "any_tags": ["theme:celebration", "theme:leisure"],
    },
    "labour": {
        "label": "Work and labour",
        "any_tags": ["theme:labor", "subject:industrial-machinery", "era-depicted:industrial-era"],
    },
    "sea-and-ships": {
        "label": "Sea and ships",
        "any_tags": ["subject:ship", "setting:water"],
        "genres": ["painting/seascape"],
    },
    "faces": {
        "label": "Faces",
        "genres": ["painting/portrait"],
        "any_tags": ["subject:single-figure"],
    },
}

# Periods as inclusive year ranges. Named rather than free-form because "period"
# in the request means something like "Dutch Golden Age", not "1600-1700".
PERIODS: dict[str, tuple[str, int, int]] = {
    "medieval": ("Medieval", 500, 1400),
    "renaissance": ("Renaissance", 1400, 1600),
    "golden-age": ("17th century / Golden Age", 1600, 1700),
    "18th-century": ("18th century", 1700, 1800),
    "19th-century": ("19th century", 1800, 1900),
    "modern": ("20th century onward", 1900, 2100),
}

_YEAR_RE = re.compile(r"\b(\d{3,4})\b")


def parse_year(value: Any) -> int | None:
    """Best-effort year from the messy strings real records carry."""
    if isinstance(value, (int, float)) and value:
        return int(value)
    if isinstance(value, str):
        m = _YEAR_RE.search(value)
        if m:
            y = int(m.group(1))
            if 300 <= y <= 2100:
                return y
    return None


@dataclass
class PlaylistSpec:
    """Everything a user can ask for. All filters are AND-ed together."""

    artists: list[str] = field(default_factory=list)
    genres: list[str] = field(default_factory=list)
    moods: list[str] = field(default_factory=list)
    periods: list[str] = field(default_factory=list)
    year_from: int | None = None
    year_to: int | None = None
    any_tags: list[str] = field(default_factory=list)
    all_tags: list[str] = field(default_factory=list)
    not_tags: list[str] = field(default_factory=list)
    exclude_filters: list[str] = field(default_factory=list)
    min_fit: int | None = None
    min_quality: int | None = None
    require_dossier: bool = False
    limit: int | None = None
    sort: SortKey = "fit"
    seed: int = 42

    @classmethod
    def from_dict(cls, d: dict) -> PlaylistSpec:
        known = set(cls.__dataclass_fields__)
        unknown = set(d) - known
        if unknown:
            # Fail loudly: a typo'd facet that is silently ignored produces a
            # playlist that looks filtered and is not.
            raise ValueError(f"unknown playlist field(s): {sorted(unknown)}")
        return cls(**d)


@dataclass
class PlaylistResult:
    work_ids: list[str]
    total_candidates: int
    matched: int
    coverage: dict[str, Any]
    facets: dict[str, list[tuple[str, int]]]
    spec: dict


def _tags_of(sc: dict) -> set[str]:
    subj = sc.get("subject") or {}
    out = {
        str(t.get("id"))
        for t in (subj.get("content_tags") or [])
        if isinstance(t, dict) and t.get("id")
    }
    g = subj.get("genre")
    if g and g != "unknown":
        out.add(f"genre:{g}")
    return out


def _genre_of(sc: dict) -> str | None:
    g = (sc.get("subject") or {}).get("genre")
    return g if g and g != "unknown" else None


def _artist_of(sc: dict) -> str:
    """Preferred display name for the artist.

    `artist.canonical` is a resolver RECORD, not a string — it carries
    wikidata_q, display_name, lifespan, confidence and method. Treating it as
    a name raises AttributeError on the first work with a resolved artist,
    which is most of them.
    """
    a = sc.get("artist") or {}
    canon = a.get("canonical")
    if isinstance(canon, dict):
        name = canon.get("display_name") or ""
        if isinstance(name, str) and name.strip():
            return name.strip()
    elif isinstance(canon, str) and canon.strip():
        return canon.strip()
    name = a.get("name")
    return name.strip() if isinstance(name, str) else ""


def load_ratings(path: Path) -> dict[str, dict[str, int]]:
    """work_id -> best-known {quality, fit}. Last event per work wins."""
    out: dict[str, dict[str, int]] = {}
    if not path.exists():
        return out
    for line in path.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except ValueError:
            continue          # a corrupt line must not sink the whole playlist
        wid = ev.get("work_id")
        if not wid:
            continue
        rec = out.setdefault(wid, {})
        for axis in ("quality", "fit"):
            v = ev.get(axis)
            if isinstance(v, (int, float)) and v == v:      # v == v rejects NaN
                rec[axis] = int(v)
    return out


def _mood_ok(mood: str, tags: set[str], genre: str | None) -> bool:
    spec = MOODS.get(mood)
    if spec is None:
        raise KeyError(f"unknown mood {mood!r}; have {sorted(MOODS)}")
    if spec.get("not_tags") and tags & set(spec["not_tags"]):
        return False
    hits = []
    if spec.get("any_tags"):
        hits.append(bool(tags & set(spec["any_tags"])))
    if spec.get("genres"):
        hits.append(genre in spec["genres"])
    # A mood with several positive clauses matches on ANY of them, so
    # "Sea and ships" catches both a ship tag and the seascape genre.
    return any(hits) if hits else False


def build(
    sidecars: Iterable[tuple[str, dict]],
    spec: PlaylistSpec,
    *,
    ratings: dict[str, dict[str, int]] | None = None,
    dossier_ids: set[str] | None = None,
) -> PlaylistResult:
    ratings = ratings or {}
    dossier_ids = dossier_ids or set()

    period_ranges = [PERIODS[p][1:] for p in spec.periods] if spec.periods else []
    for p in spec.periods:
        if p not in PERIODS:
            raise KeyError(f"unknown period {p!r}; have {sorted(PERIODS)}")
    artists_lc = {a.strip().lower() for a in spec.artists if a.strip()}

    total = 0
    rows: list[dict] = []
    skipped: Counter[str] = Counter()
    facet_artist: Counter = Counter()
    facet_genre: Counter = Counter()
    facet_mood: Counter = Counter()

    for wid, sc in sidecars:
        total += 1
        tags = _tags_of(sc)
        genre = _genre_of(sc)
        artist = _artist_of(sc)
        year = parse_year(sc.get("year"))
        r = ratings.get(wid, {})

        if artists_lc:
            if not artist:
                skipped["no artist"] += 1
                continue
            if artist.lower() not in artists_lc:
                continue
        if spec.genres:
            if genre is None:
                skipped["no genre"] += 1
                continue
            if genre not in spec.genres:
                continue
        if period_ranges or spec.year_from or spec.year_to:
            if year is None:
                skipped["no year"] += 1
                continue
            if period_ranges and not any(lo <= year <= hi for lo, hi in period_ranges):
                continue
            if spec.year_from is not None and year < spec.year_from:
                continue
            if spec.year_to is not None and year > spec.year_to:
                continue
        if spec.any_tags and not (tags & set(spec.any_tags)):
            continue
        if spec.all_tags and not set(spec.all_tags) <= tags:
            continue
        if spec.not_tags and (tags & set(spec.not_tags)):
            continue
        if spec.exclude_filters and (tags & {f"filter:{f}" if not f.startswith("filter:") else f
                                             for f in spec.exclude_filters}):
            continue
        if spec.moods and not any(_mood_ok(m, tags, genre) for m in spec.moods):
            continue
        if spec.min_fit is not None:
            if "fit" not in r:
                skipped["unrated (fit)"] += 1
                continue
            if r["fit"] < spec.min_fit:
                continue
        if spec.min_quality is not None:
            if "quality" not in r:
                skipped["unrated (quality)"] += 1
                continue
            if r["quality"] < spec.min_quality:
                continue
        if spec.require_dossier and wid not in dossier_ids:
            continue

        rows.append({
            "work_id": wid, "artist": artist, "genre": genre, "year": year,
            "title": sc.get("title") or "",
            "fit": r.get("fit"), "quality": r.get("quality"),
        })
        if artist:
            facet_artist[artist] += 1
        if genre:
            facet_genre[genre] += 1
        for m in MOODS:
            if _mood_ok(m, tags, genre):
                facet_mood[m] += 1

    def sort_value(row: dict):
        if spec.sort == "fit":
            return (-(row["fit"] if row["fit"] is not None else -1), row["title"])
        if spec.sort == "quality":
            return (-(row["quality"] if row["quality"] is not None else -1), row["title"])
        if spec.sort == "year":
            return (row["year"] if row["year"] is not None else 9999, row["title"])
        if spec.sort == "artist":
            return (row["artist"].lower(), row["year"] or 9999)
        if spec.sort == "title":
            return (row["title"].lower(),)
        return (0,)

    if spec.sort == "random":
        import random
        rnd = random.Random(spec.seed)   # seeded so a card is reproducible
        rnd.shuffle(rows)
    elif spec.sort != "as-filtered":
        rows.sort(key=sort_value)

    matched = len(rows)
    if spec.limit:
        rows = rows[: spec.limit]

    return PlaylistResult(
        work_ids=[r["work_id"] for r in rows],
        total_candidates=total,
        matched=matched,
        coverage={
            "excluded_for_missing_metadata": dict(skipped),
            "note": "Tag filters can only select from tagged works; these "
                    "counts say how many were dropped for having no value on a "
                    "filtered field, so a small result is legible.",
        },
        facets={
            "artist": facet_artist.most_common(25),
            "genre": facet_genre.most_common(),
            "mood": facet_mood.most_common(),
        },
        spec=spec.__dict__.copy(),
    )

def discover_facets(sidecars: Iterable[tuple[str, dict]]) -> dict:
    """Enumerate every filterable value that actually exists in the corpus.

    The filter surface must be DERIVED, not declared. A hardcoded control list
    silently stops matching the archive the moment tagging improves: the tagger
    took genre coverage from 3% to 65% in one session and added `theme:` and
    `era-depicted:` families that no UI knew about, so any fixed list of
    dropdowns would have been wrong within a day.

    So this returns the families and values present right now, with counts, and
    the UI renders controls from it. A family that gains its first value appears
    on the next page load; a family that is still empty (palette has one value
    today) shows its real count rather than pretending to be a rich filter.
    """
    families: dict[str, Counter] = {}
    artists: Counter = Counter()
    years: list[int] = []
    total = 0
    for _wid, sc in sidecars:
        total += 1
        subj = sc.get("subject") or {}
        g = subj.get("genre")
        if g and g != "unknown":
            families.setdefault("genre", Counter())[g] += 1
        for t in subj.get("content_tags") or []:
            # Mirror _tags_of: non-dict entries must not break /eink/facets.
            if not isinstance(t, dict):
                continue
            tid = str(t.get("id") or "")
            if ":" in tid:
                fam, val = tid.split(":", 1)
                families.setdefault(fam, Counter())[val] += 1
        a = _artist_of(sc)
        if a:
            artists[a] += 1
        y = parse_year(sc.get("year"))
        if y is not None:
            years.append(y)

    return {
        "total_works": total,
        "families": {
            fam: {
                "count": sum(c.values()),
                "values": [{"value": v, "tag": f"{fam}:{v}", "count": n}
                           for v, n in c.most_common()],
            }
            for fam, c in sorted(families.items(),
                                 key=lambda kv: -sum(kv[1].values()))
        },
        "artists": [{"value": a, "count": n} for a, n in artists.most_common(400)],
        "year_range": [min(years), max(years)] if years else None,
        "years_known": len(years),
        # Moods and periods stay curated because they are EDITORIAL groupings,
        # not data: "nocturne" is a judgement that night scenes and dark palettes
        # belong together. Each still reports which underlying tags it uses, so a
        # mood whose tags have no coverage reads as empty rather than broken.
        "moods": [
            {"key": k, "label": v["label"],
             "uses": sorted(set(v.get("any_tags", []) + v.get("genres", [])))}
            for k, v in MOODS.items()
        ],
        "periods": [{"key": k, "label": lbl, "from": lo, "to": hi}
                    for k, (lbl, lo, hi) in PERIODS.items()],
    }
