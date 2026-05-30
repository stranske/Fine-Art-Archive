#!/usr/bin/env python3
"""Propose subject-matter tags for fine-art works.

v1 implementation per `subject_taxonomy_design.md`. Two tiers:

  Tier 1 — Wikidata structured data (P136 genre, P180 depicts) when the
           sidecar has stable_identifiers.wikidata_q. Most works don't.

  Tier 2 — Title keyword heuristics. Works on every sidecar.

Outputs:

  - DEFAULT (no --apply): writes `subject_tags_v1_preview.csv` next to
    the project root. One row per work with proposed genre + tags.
  - --apply: writes the `subject` block into each sidecar's meta.json.
    Existing reviewer-confirmed tags are preserved; proposed tags from a
    prior v1 run are replaced.

Filtering args:

  --rated-only        Only tag works Tim has rated (uses ratings_log.jsonl).
  --limit N           Cap to N works.
  --random N          Sample N works at random.
  --wid <wid>         A specific work_id.

Reviewer workflow: after this runs, the Companion App's detail view
surfaces the proposed tags with accept/reject controls (separate UI task).
For now this just emits the preview CSV so Tim can react to the v1
quality before we wire the reviewer UI or run on all 3,301 works.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
import re
import sys
import urllib.error
import urllib.request
from datetime import UTC
from pathlib import Path

# Operational data root (the Cowork workspace). Overridable so the committed
# script isn't pinned to one machine's absolute path.
ROOT = Path(
    os.environ.get(
        "FAA_WORKSPACE", "/Users/teacher/Library/CloudStorage/Dropbox/Pictures/Claude Project"
    )
)
STAGING = ROOT / "staging_sidecars"
RATINGS_LOG = ROOT / "data" / "ratings_log.jsonl"
PREVIEW_CSV = ROOT / "subject_tags_v1_preview.csv"
TAG_METHOD_VERSION = "v1.0"


# --------------------------------------------------------------------------
# Tier 1: Wikidata mappings. Curated, intentionally small to start; expand
# as we encounter Q-ids that matter. Each Q-id maps to (genre_or_None, [tags]).
# --------------------------------------------------------------------------
WIKIDATA_P136_TO_GENRE: dict[str, str] = {
    "Q134307": "painting/portrait",  # portrait
    "Q191163": "painting/landscape",  # landscape art
    "Q158607": "painting/seascape",  # marine art
    "Q170571": "painting/still-life",  # still life
    "Q1047337": "painting/genre-scene",  # genre art
    "Q2864737": "painting/religious",  # religious art
    "Q15145782": "painting/mythological",  # mythological painting
    "Q1406161": "painting/history",  # history painting
    "Q188361": "painting/nude",  # nude
    "Q128115": "painting/abstract",  # abstract art
    "Q3305213": "painting/portrait",  # painting (generic) — fallback
    "Q3863891": "painting/animal",  # animal painting
    "Q1014157": "painting/cityscape",  # cityscape
    "Q11629": "drawing/sketch",  # drawing
}

# P180 (depicts) → list of content tags. Sample of common values; expand as needed.
WIKIDATA_P180_TO_TAGS: dict[str, list[str]] = {
    "Q302": ["filter:religious", "subject:single-figure", "subject:male"],  # Jesus Christ
    "Q345": ["filter:religious", "subject:single-figure", "subject:female"],  # Mary
    "Q35501": ["filter:religious", "theme:religious-narrative"],  # Annunciation
    "Q5": ["subject:single-figure"],  # human
    "Q467": ["subject:female"],  # woman
    "Q8441": ["subject:male"],  # man
    "Q7569": ["subject:child"],  # child
    "Q11891": ["subject:horse"],  # horse
    "Q144": ["subject:dog"],  # dog
    "Q5113": ["subject:bird"],  # bird
    "Q11446": ["subject:ship"],  # ship
    "Q22746": ["subject:flower"],  # flower
    "Q10884": ["subject:tree"],  # tree
    "Q41176": ["subject:building"],  # building
    "Q16970": ["subject:church", "filter:religious"],  # church
}


# --------------------------------------------------------------------------
# Tier 2: Title keyword heuristics. Order matters — the first match wins
# for genre; tags from all matches accumulate.
# --------------------------------------------------------------------------
# Each entry: (regex pattern, optional_genre, [tags], confidence)
TITLE_RULES: list[tuple[re.Pattern, str | None, list[str], float]] = [
    # Religious — strong signal. mother-and-child only added when title
    # explicitly mentions the child (madonna alone in coronation, etc.,
    # may not include the child).
    (
        re.compile(
            r"\b(madonna\s+and\s+child|virgin\s+and\s+child|holy\s+family|nativity|adoration\s+of\s+the\s+(magi|kings|shepherds))\b",
            re.I,
        ),
        "painting/religious",
        ["filter:religious", "theme:religious-narrative", "subject:mother-and-child"],
        0.92,
    ),
    (
        re.compile(r"\b(madonna|virgin\s+(of|with|in)|annunciation)\b", re.I),
        "painting/religious",
        ["filter:religious", "theme:religious-narrative"],
        0.88,
    ),
    (
        re.compile(
            r"\b(crucifixion|piet[àa]|lamentation|deposition|entombment|descent\s+from\s+the\s+cross|burial\s+of\s+christ)\b",
            re.I,
        ),
        "painting/religious",
        [
            "filter:religious",
            "filter:violence",
            "filter:blood",
            "filter:death",
            "theme:religious-narrative",
        ],
        0.95,
    ),
    (
        re.compile(r"\becce\s+homo\b", re.I),
        "painting/religious",
        [
            "filter:religious",
            "filter:violence",
            "filter:blood",
            "theme:religious-narrative",
            "subject:single-figure",
        ],
        0.95,
    ),
    # "Saint X" is a weaker signal than other religious patterns ("Saint"
    # can be a place, e.g. Saint-Lazare, Saint-Tropez). Lower confidence;
    # the reviewer can confirm. Word-boundary keeps it from matching
    # "Saint-Lazare" (Monet's Gare Saint-Lazare).
    (
        re.compile(r"\b(saint|st\.)\s+(?!lazare|tropez|petersburg|moritz)\w+\b", re.I),
        "painting/religious",
        ["filter:religious"],
        0.55,
    ),
    (
        re.compile(r"\b(christ|jesus|gospel|apostle|baptism\s+of|last\s+supper)\b", re.I),
        "painting/religious",
        ["filter:religious", "theme:religious-narrative"],
        0.85,
    ),
    (
        re.compile(r"\b(jonah|moses|david\s+and\s+goliath|samson|judith|salom[eé])\b", re.I),
        "painting/religious",
        ["filter:religious", "theme:religious-narrative"],
        0.80,
    ),
    # Mythological
    (
        re.compile(
            r"\b(venus|aphrodite|diana|artemis|apollo|bacchus|dionysus|mars|cupid|psyche|narcissus|orpheus)\b",
            re.I,
        ),
        "painting/mythological",
        ["theme:mythological"],
        0.75,
    ),
    (
        re.compile(r"\b(judgement\s+of\s+paris|rape\s+of\s+europa|abduction\s+of)\b", re.I),
        "painting/mythological",
        ["theme:mythological", "filter:violence"],
        0.85,
    ),
    # Nude
    (
        re.compile(r"\b(nude|naked)\b", re.I),
        "painting/nude",
        ["filter:nudity-full", "subject:single-figure"],
        0.85,
    ),
    (re.compile(r"\b(bather|bathers|the\s+bath)\b", re.I), None, ["filter:nudity-partial"], 0.65),
    (
        re.compile(r"\b(odalisque)\b", re.I),
        "painting/nude",
        ["filter:nudity-full", "subject:female"],
        0.90,
    ),
    # Violence / war
    (
        re.compile(r"\b(battle\s+of|battle|massacre|martyrdom)\b", re.I),
        "painting/history",
        ["filter:violence", "theme:war"],
        0.80,
    ),
    (
        re.compile(r"\b(execution|beheading|torture)\b", re.I),
        None,
        ["filter:violence", "filter:death", "filter:disturbing"],
        0.90,
    ),
    # Genre
    (
        re.compile(r"\b(portrait\s+of|self.?portrait)\b", re.I),
        "painting/portrait",
        ["subject:single-figure"],
        0.85,
    ),
    (
        re.compile(r"\b(landscape|view\s+of|valley\s+of|mountains?|forest)\b", re.I),
        "painting/landscape",
        ["setting:landscape-natural", "setting:outdoor"],
        0.80,
    ),
    (
        re.compile(
            r"\b(seascape|marine|ship\s+at\s+sea|shipwreck|the\s+wave|storm\s+at\s+sea)\b", re.I
        ),
        "painting/seascape",
        ["setting:water", "subject:ship", "setting:outdoor"],
        0.85,
    ),
    (re.compile(r"\b(still\s+life|vanitas)\b", re.I), "painting/still-life", [], 0.90),
    (re.compile(r"\bvanitas\b", re.I), None, ["filter:death", "theme:death"], 0.85),
    (
        re.compile(r"\b(cityscape|view\s+of\s+(paris|london|new\s+york|rome|venice))\b", re.I),
        "painting/cityscape",
        ["setting:urban", "setting:outdoor"],
        0.80,
    ),
    # Catches works titled to evoke a city even without "cityscape"/"view"
    # e.g. "The Voice of the City of New York Interpreted", "Lower Manhattan", etc.
    (
        re.compile(r"\bnew\s+york|manhattan|chicago|los\s+angeles\b", re.I),
        "painting/cityscape",
        ["setting:urban", "setting:outdoor"],
        0.70,
    ),
    (re.compile(r"\bcity\b", re.I), None, ["setting:urban"], 0.65),
    (re.compile(r"\b(allegory|allegorical)\b", re.I), "painting/allegory", [], 0.75),
    (re.compile(r"\b(garland\s+of\s+flowers|wreath)\b", re.I), None, ["subject:flower"], 0.85),
    (
        re.compile(r"\b(composition\s+(no\.|number|[0-9ivx]+)|no\.\s+\d+\s+composition)\b", re.I),
        "painting/abstract",
        [],
        0.85,
    ),
    # Setting / season
    (re.compile(r"\b(winter|snow)\b", re.I), None, ["setting:winter", "palette:cool-toned"], 0.75),
    (re.compile(r"\b(summer)\b", re.I), None, ["setting:summer"], 0.70),
    (re.compile(r"\bautumn|\bfall\b", re.I), None, ["setting:autumn"], 0.70),
    # "harvest" implies an outdoor agricultural scene; pair theme + setting + tentative genre
    (
        re.compile(r"\bharvest\b", re.I),
        "painting/genre-scene",
        ["theme:labor", "setting:rural", "setting:outdoor"],
        0.65,
    ),
    # \bnight\w*\b catches "nightlife", "nighthawks", etc. that \bnight\b misses
    (re.compile(r"\b(night\w*|nocturne|twilight)\b", re.I), None, ["setting:night"], 0.80),
    # Subject objects
    (
        re.compile(r"\b(train|locomotive|railway|station)\b", re.I),
        None,
        ["subject:train", "subject:industrial-machinery", "era-depicted:industrial-era"],
        0.85,
    ),
    (re.compile(r"\b(ship|boat|vessel|sail)\b", re.I), None, ["subject:ship"], 0.75),
    (re.compile(r"\b(horse|equestrian)\b", re.I), None, ["subject:horse"], 0.80),
    (
        re.compile(r"\b(dance|ball|festival)\b", re.I),
        None,
        ["theme:leisure", "theme:celebration", "subject:group"],
        0.75,
    ),
    (
        re.compile(r"\b(family|mother\s+and\s+child)\b", re.I),
        None,
        ["theme:motherhood", "subject:mother-and-child"],
        0.80,
    ),
    # Folio / manuscript
    (re.compile(r"\b(folio|manuscript|jami\s+al)\b", re.I), "manuscript-illumination", [], 0.85),
    # Bosch's "Cutting the Stone" / "Stone of Folly" — satirical medieval
    # allegory, not "disturbing" in the modern body-horror sense. Per Tim
    # 2026-05-25 review feedback: title-tagger can't reliably distinguish
    # Bosch's satirical-grotesque from Bacon's body-horror; leave the
    # disturbing flag to vision (Tier 3) / reviewer. Just set the genre.
    (
        re.compile(r"\bcutting\s+the\s+stone\b", re.I),
        "painting/allegory",
        ["theme:contemporary-life"],
        0.85,
    ),
    # Bacon-specific (Figure with Meat is one of the few title-only cases
    # where modern body-horror is reliably implied — title pairs "figure"
    # with "meat" in a 20th-century portraitist's oeuvre)
    (
        re.compile(r"\bfigure\s+with\s+meat\b", re.I),
        "painting/portrait",
        ["filter:disturbing", "subject:single-figure"],
        0.85,
    ),
]


# --------------------------------------------------------------------------
# Wikidata fetcher — for the rare work with a stable_identifiers.wikidata_q.
# Uses Special:EntityData which is more reliable than WDQS SPARQL.
# --------------------------------------------------------------------------
def fetch_wikidata_claims(q: str, timeout: int = 15) -> dict | None:
    """Return {P136: [Q...], P180: [Q...], P462: [Q...]} or None on failure."""
    url = f"https://www.wikidata.org/wiki/Special:EntityData/{q}.json"
    req = urllib.request.Request(url, headers={"User-Agent": "FAA-subject-tagger/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read())
    except Exception as e:
        print(f"  WD fetch failed for {q}: {e}", file=sys.stderr)
        return None
    ent = (data.get("entities") or {}).get(q) or {}
    claims = ent.get("claims") or {}
    out: dict[str, list[str]] = {}
    for prop in ("P136", "P180", "P462"):
        vals = []
        for c in claims.get(prop, []):
            try:
                vid = c["mainsnak"]["datavalue"]["value"]["id"]
                vals.append(vid)
            except (KeyError, TypeError):
                continue
        if vals:
            out[prop] = vals
    return out


# --------------------------------------------------------------------------
# Tagger
# --------------------------------------------------------------------------
def tag_work(sidecar: dict, fetch_wd: bool = True) -> dict:
    """Apply Tier 1 + Tier 2 to a single sidecar dict; return subject block."""
    title = sidecar.get("title") or ""

    # Collect all (genre_candidate, confidence, tags, source, evidence) results
    genre_candidates: list[tuple[str, float, str, str]] = []  # (genre, conf, source, evidence)
    tag_set: dict[str, dict] = {}  # tag_id → {"state":"proposed", "source", "evidence"}

    # ---- Tier 1: Wikidata
    wid_q = (sidecar.get("stable_identifiers") or {}).get("wikidata_q")
    if wid_q and fetch_wd:
        claims = fetch_wikidata_claims(wid_q)
        if claims:
            for p136_q in claims.get("P136", []):
                if p136_q in WIKIDATA_P136_TO_GENRE:
                    genre_candidates.append(
                        (WIKIDATA_P136_TO_GENRE[p136_q], 0.90, "wikidata:P136", p136_q)
                    )
            for p180_q in claims.get("P180", []):
                if p180_q in WIKIDATA_P180_TO_TAGS:
                    for t in WIKIDATA_P180_TO_TAGS[p180_q]:
                        tag_set[t] = {
                            "state": "proposed",
                            "source": "wikidata:P180",
                            "evidence": p180_q,
                        }

    # ---- Tier 2: title heuristics
    for pat, genre, tags, conf in TITLE_RULES:
        if pat.search(title):
            if genre:
                genre_candidates.append((genre, conf, "title-heuristic", pat.pattern[:40]))
            for t in tags:
                if t not in tag_set:
                    tag_set[t] = {
                        "state": "proposed",
                        "source": "title-heuristic",
                        "evidence": pat.pattern[:40],
                    }

    # ---- Genre pick: highest confidence wins; tie → first-seen
    if genre_candidates:
        genre_candidates.sort(key=lambda x: -x[1])
        g, gconf, gsrc, gev = genre_candidates[0]
    else:
        # Genre fallbacks from the tag pattern. Useful when title doesn't
        # name a genre directly but the content tags imply one.
        tag_ids = set(tag_set.keys())
        if {"subject:group", "theme:leisure"} & tag_ids and {
            "subject:group",
            "theme:leisure",
        }.issubset(tag_ids):
            g, gconf, gsrc, gev = "painting/genre-scene", 0.55, "tag-fallback", "group+leisure"
        elif "subject:train" in tag_ids:
            g, gconf, gsrc, gev = "painting/cityscape", 0.50, "tag-fallback", "train"
        elif "setting:landscape-natural" in tag_ids:
            g, gconf, gsrc, gev = "painting/landscape", 0.55, "tag-fallback", "landscape-tags"
        else:
            g, gconf, gsrc, gev = "unknown", 0.0, "none", ""

    content_tags = [
        {
            "id": tid,
            "state": meta["state"],
            "source": meta["source"],
            **({"evidence": meta["evidence"]} if meta.get("evidence") else {}),
        }
        for tid, meta in sorted(tag_set.items())
    ]
    return {
        "genre": g,
        "genre_confidence": round(gconf, 2),
        "genre_source": gsrc,
        "genre_evidence": gev,
        "content_tags": content_tags,
        "tag_method_version": TAG_METHOD_VERSION,
        "last_tagged_at": _now(),
        "needs_review": bool(content_tags) or g != "unknown",
    }


def _now() -> str:
    from datetime import datetime

    return datetime.now(UTC).isoformat(timespec="seconds")


# --------------------------------------------------------------------------
# Driver
# --------------------------------------------------------------------------
def rated_work_ids() -> set[str]:
    if not RATINGS_LOG.exists():
        return set()
    out = set()
    for line in RATINGS_LOG.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            e = json.loads(line)
            if (e.get("notes") or "").startswith("smoke"):
                continue
            wid = e.get("work_id")
            if wid:
                out.add(wid)
        except json.JSONDecodeError:
            continue
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rated-only", action="store_true", help="Tag only works Tim has rated")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--random", type=int, default=None, help="Random sample of N works")
    ap.add_argument("--wid", default=None, help="Single work_id")
    ap.add_argument(
        "--apply", action="store_true", help="Write tags into sidecars (default: preview CSV only)"
    )
    ap.add_argument(
        "--no-wikidata", action="store_true", help="Skip Tier 1 (faster, for large dry-runs)"
    )
    args = ap.parse_args()

    # Choose work_ids
    if args.wid:
        wids = [args.wid]
    elif args.rated_only:
        wids = sorted(rated_work_ids())
    else:
        wids = sorted(p.name for p in STAGING.iterdir() if p.is_dir())
        if args.random:
            random.seed(42)
            wids = random.sample(wids, min(args.random, len(wids)))
        if args.limit:
            wids = wids[: args.limit]

    print(
        f"Tagging {len(wids)} work(s)... (apply={args.apply}, "
        f"fetch_wikidata={not args.no_wikidata})",
        file=sys.stderr,
    )

    rows = []
    for i, wid in enumerate(wids, 1):
        sc_path = STAGING / wid / "meta.json"
        if not sc_path.exists():
            print(f"  [{i}/{len(wids)}] MISSING SIDECAR: {wid}", file=sys.stderr)
            continue
        try:
            sc = json.loads(sc_path.read_text())
        except Exception as e:
            print(f"  [{i}/{len(wids)}] load failed {wid}: {e}", file=sys.stderr)
            continue
        subj = tag_work(sc, fetch_wd=not args.no_wikidata)
        title = (sc.get("title") or "")[:60]
        artist = (sc.get("artist") or {}).get("name", "")[:30]
        print(
            f"  [{i}/{len(wids)}] {wid[:38]:<40} {title!r:<62}  "
            f"genre={subj['genre']:<24}  tags={len(subj['content_tags'])}"
        )
        rows.append(
            {
                "work_id": wid,
                "title": title,
                "artist": artist,
                "genre": subj["genre"],
                "genre_confidence": subj["genre_confidence"],
                "genre_source": subj["genre_source"],
                "n_tags": len(subj["content_tags"]),
                "tags": ";".join(t["id"] for t in subj["content_tags"]),
                "filters": ";".join(
                    t["id"] for t in subj["content_tags"] if t["id"].startswith("filter:")
                ),
            }
        )
        if args.apply:
            sc["subject"] = subj
            sc_path.write_text(json.dumps(sc, indent=2, ensure_ascii=False))

    # Always emit preview CSV
    if rows:
        with open(PREVIEW_CSV, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        print(f"\nPreview written: {PREVIEW_CSV.relative_to(ROOT)}", file=sys.stderr)
        # Quick stats
        warn_count = sum(1 for r in rows if r["filters"])
        print(f"  {warn_count}/{len(rows)} works have at least one warning", file=sys.stderr)
        if args.apply:
            print(f"  Applied to {len(rows)} sidecar(s).", file=sys.stderr)
        else:
            print("  DRY RUN — pass --apply to write to sidecars.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
