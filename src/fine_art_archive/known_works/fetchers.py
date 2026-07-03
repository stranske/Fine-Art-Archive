"""Pluggable per-source fetchers for an artist's known works.

Three sources implemented:
  - Wikidata SPARQL (canonical LOD; offline when WDQS is down)
  - Wikipedia "List of paintings by X" (table-parsing the article)
  - Met Open Access API (artist-name search → CC0 records)

Each fetcher returns a list of KnownWork records in normalized shape.
The caller passes them to `merge_works` to dedupe across sources.
"""

from __future__ import annotations

import json
import logging
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field

LOG = logging.getLogger(__name__)
USER_AGENT = "FineArtArchive/0.3 (tim@stranskemo.com)"
SPARQL_ENDPOINT = "https://query.wikidata.org/sparql"
MEDIAWIKI_API = "https://en.wikipedia.org/w/api.php"
MET_SEARCH = "https://collectionapi.metmuseum.org/public/collection/v1/search"
MET_OBJECT = "https://collectionapi.metmuseum.org/public/collection/v1/objects"


# --------------------------------------------------------------------------
@dataclass
class KnownWork:
    title: str
    year: int | None = None
    image_url: str | None = None
    holder: str | None = None
    sources: list[str] = field(default_factory=list)
    source_ids: dict[str, str] = field(default_factory=dict)


def _http_json(url: str, *, timeout: int = 25) -> dict:
    req = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def _http_text(url: str, *, timeout: int = 25) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def _norm_title(s: str) -> str:
    """Fold for dedup: lower, strip punct, collapse spaces."""
    if not s:
        return ""
    s = re.sub(r"[^\w\s]+", " ", s.lower())
    return re.sub(r"\s+", " ", s).strip()


# --------------------------------------------------------------------------
# Source 1: Wikidata SPARQL
# --------------------------------------------------------------------------
def _wd_sparql_query(artist_q: str) -> str:
    return f"""
SELECT DISTINCT ?work ?workLabel ?inception ?image WHERE {{
  ?work wdt:P170 wd:{artist_q} .
  VALUES ?cls {{ wd:Q3305213 wd:Q4502142 wd:Q11086742 wd:Q15727816
                  wd:Q15711026 wd:Q11060274 wd:Q18761202 wd:Q860861 }}
  ?work wdt:P31 ?cls .
  OPTIONAL {{ ?work wdt:P571 ?inception . }}
  OPTIONAL {{ ?work wdt:P18 ?image . }}
  SERVICE wikibase:label {{ bd:Language "en". }}
}}
LIMIT 500
"""


def fetch_wikidata_sparql(artist_q: str, *, timeout: int = 60) -> list[KnownWork]:
    """Returns [] silently on outage / rate limit; doesn't block other sources."""
    q = _wd_sparql_query(artist_q)
    url = SPARQL_ENDPOINT + "?query=" + urllib.parse.quote(q) + "&format=json"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/sparql-results+json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read())
    except (
        TimeoutError,
        json.JSONDecodeError,
        urllib.error.HTTPError,
        urllib.error.URLError,
    ) as e:
        LOG.warning("[wikidata] FAIL: %s: %s", type(e).__name__, str(e)[:90])
        return []
    out: dict[str, KnownWork] = {}
    for r in data.get("results", {}).get("bindings", []):
        wq = r.get("work", {}).get("value", "").rsplit("/", 1)[-1]
        if not wq:
            continue
        entry = out.setdefault(
            wq,
            KnownWork(
                title=r.get("workLabel", {}).get("value", ""),
                sources=["wikidata"],
                source_ids={"wikidata": wq},
            ),
        )
        if "inception" in r and entry.year is None:
            m = re.search(r"(\d{4})", r["inception"]["value"])
            if m:
                entry.year = int(m.group(1))
        if "image" in r and entry.image_url is None:
            entry.image_url = r["image"]["value"]
    LOG.info("[wikidata] %s works", len(out))
    return list(out.values())


# --------------------------------------------------------------------------
# Source 2: Wikipedia "List of paintings by X"
# --------------------------------------------------------------------------
def fetch_wikipedia_list(artist_name: str) -> list[KnownWork]:
    """Look up the 'List of {paintings|works} by <X>' article and parse it.

    Strategy: search MediaWiki for 'List of <kind> by <artist>',
    take the first hit, fetch the wikitext, parse rows. Tolerant of
    title-only rows when other fields are missing.
    """
    article_title = None
    for kind in ("paintings", "works"):
        search_q = f"List of {kind} by {artist_name}"
        search_url = (
            f"{MEDIAWIKI_API}?action=query&list=search&srlimit=3"
            f"&format=json&srsearch=" + urllib.parse.quote(search_q)
        )
        try:
            sr = _http_json(search_url)
        except (
            TimeoutError,
            json.JSONDecodeError,
            urllib.error.HTTPError,
            urllib.error.URLError,
        ) as e:
            LOG.warning("[wikipedia] search FAIL: %s", e)
            return []
        for h in sr.get("query", {}).get("search", []) or []:
            t = h.get("title", "")
            if t.lower().startswith(f"list of {kind} by"):
                article_title = t
                break
        if article_title:
            break
    if not article_title:
        LOG.info("[wikipedia] no list-page found for %r", artist_name)
        return []
    # Fetch wikitext
    parse_url = (
        f"{MEDIAWIKI_API}?action=parse&prop=wikitext&format=json"
        f"&page=" + urllib.parse.quote(article_title)
    )
    try:
        pr = _http_json(parse_url)
    except (
        TimeoutError,
        json.JSONDecodeError,
        urllib.error.HTTPError,
        urllib.error.URLError,
    ) as e:
        LOG.warning("[wikipedia] parse FAIL: %s", e)
        return []
    wikitext = pr.get("parse", {}).get("wikitext", {}).get("*", "")
    if not wikitext:
        return []
    # Extract every {{Painting list ...}} template or table row.
    # Many list pages use simple wikitables with {| / |} markers.
    works: list[KnownWork] = []
    seen_titles: set[str] = set()
    # Heuristic A: italicized titles in wikitables — ''Title'' or [[Title]]
    # The most common shape is row-per-painting with the title in italics
    # or as a link. We scan for italicized strings inside table rows.
    for m in re.finditer(r"\|\s*''(\[\[([^\]|]+)(?:\|[^\]]+)?\]\]|[^'\n]+?)''", wikitext):
        title_inner = m.group(2) if m.group(2) else m.group(1)
        title = title_inner.strip()
        if not title or len(title) > 200:
            continue
        nt = _norm_title(title)
        if nt in seen_titles:
            continue
        seen_titles.add(nt)
        # Try to find a 4-digit year in the next 300 chars
        tail = wikitext[m.end() : m.end() + 400]
        year = None
        ym = re.search(r"\b(1[2-9]\d{2}|20[0-2]\d)\b", tail)
        if ym:
            year = int(ym.group(1))
        works.append(
            KnownWork(
                title=title,
                year=year,
                sources=["wikipedia"],
                source_ids={"wikipedia": article_title},
            )
        )
    # Heuristic B: links of the form [[Painting Title (Artist)|Painting Title]]
    for m in re.finditer(r"\[\[([^\]|#]+?)\s*\(([^\)]+?)\)\|([^\]]+?)\]\]", wikitext):
        title = m.group(3).strip()
        nt = _norm_title(title)
        if nt and nt not in seen_titles and len(title) < 200:
            seen_titles.add(nt)
            works.append(
                KnownWork(
                    title=title,
                    sources=["wikipedia"],
                    source_ids={"wikipedia": article_title},
                )
            )
    LOG.info("[wikipedia] %s works from %r", len(works), article_title)
    return works


# --------------------------------------------------------------------------
# Source 3: Met Open Access API
# --------------------------------------------------------------------------
def fetch_met(artist_name: str, *, max_objects: int = 100) -> list[KnownWork]:
    """Search Met by artist, fetch each matching object record."""
    url = f"{MET_SEARCH}?artistOrCulture=true&hasImages=true&q=" + urllib.parse.quote(artist_name)
    try:
        sr = _http_json(url)
    except (
        TimeoutError,
        json.JSONDecodeError,
        urllib.error.HTTPError,
        urllib.error.URLError,
    ) as e:
        LOG.warning("[met] search FAIL: %s", e)
        return []
    object_ids = sr.get("objectIDs") or []
    if not object_ids:
        LOG.info("[met] no results for %r", artist_name)
        return []
    works: list[KnownWork] = []
    seen_titles: set[str] = set()
    for oid in object_ids[:max_objects]:
        try:
            obj = _http_json(f"{MET_OBJECT}/{oid}", timeout=10)
        except (
            TimeoutError,
            json.JSONDecodeError,
            urllib.error.HTTPError,
            urllib.error.URLError,
        ):
            continue
        # Verify the object is genuinely by this artist (not just mentions)
        artist = (obj.get("artistDisplayName") or "").lower()
        if artist_name.lower().split()[-1] not in artist:
            continue
        title = (obj.get("title") or "").strip()
        if not title:
            continue
        nt = _norm_title(title)
        if nt in seen_titles:
            continue
        seen_titles.add(nt)
        year = None
        # Met records dates as strings like "1880" or "ca. 1880-83"
        ds = obj.get("objectBeginDate") or obj.get("objectDate") or ""
        if isinstance(ds, int) and ds > 0:
            year = ds
        elif isinstance(ds, str):
            ym = re.search(r"(1[2-9]\d{2}|20[0-2]\d)", ds)
            if ym:
                year = int(ym.group(1))
        works.append(
            KnownWork(
                title=title,
                year=year,
                image_url=obj.get("primaryImage") or None,
                holder="The Metropolitan Museum of Art",
                sources=["met"],
                source_ids={"met": str(oid)},
            )
        )
        time.sleep(0.1)  # polite to Met
    LOG.info("[met] %s works", len(works))
    return works


# --------------------------------------------------------------------------
# Merger
# --------------------------------------------------------------------------
def merge_works(*sources: list[KnownWork]) -> list[KnownWork]:
    """Dedupe by (folded title, year ±2). When two sources agree, the
    merged record shows both source tags."""
    merged: dict[str, KnownWork] = {}
    for srcs in sources:
        for w in srcs:
            key = _norm_title(w.title)
            if not key:
                continue
            if key in merged:
                # Year proximity check (or no year on either side)
                existing = merged[key]
                if w.year and existing.year and abs(w.year - existing.year) > 3:
                    # Probably different works with the same title — keep both
                    key = f"{key}#{w.year}"
                    merged[key] = w
                    continue
                # Merge metadata
                for s in w.sources:
                    if s not in existing.sources:
                        existing.sources.append(s)
                existing.source_ids.update(w.source_ids)
                if not existing.year and w.year:
                    existing.year = w.year
                if not existing.image_url and w.image_url:
                    existing.image_url = w.image_url
                if not existing.holder and w.holder:
                    existing.holder = w.holder
            else:
                merged[key] = w
    return sorted(merged.values(), key=lambda w: (w.year or 9999, w.title or ""))


def works_to_dicts(works: list[KnownWork]) -> list[dict]:
    return [asdict(w) for w in works]
