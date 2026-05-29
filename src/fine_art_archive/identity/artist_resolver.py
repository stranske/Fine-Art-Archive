"""Artist identity resolver.

Maps a raw artist string (e.g. "Pieter Brueghel_d.J.", "Édouard Manet")
to a canonical (Wikidata Q-ID, display_name, lifespan, family_key).
See `artist_name_normalization_design.md`.

Resolution cascade:
  1. Direct alias-table lookup (hard-coded for high-volume artists +
     loaded from data/canonical_artists.yaml when entries have q_ids).
  2. Family-name + lifespan disambiguation when year context exists.
  3. Wikidata wbsearchentities fallback (network; cached).
  4. Returns unresolved with method='unresolved' for manual review.

This module deliberately doesn't write to sidecars. Step 1 of the
migration: produce a preview CSV; Tim reviews; step 2 wires the schema
and the bulk update.
"""

from __future__ import annotations

import json
import re
import unicodedata
import urllib.parse
import urllib.request
from dataclasses import dataclass

# --------------------------------------------------------------------------
# Curated alias table for high-volume clusters Tim has actually called out
# or that the manifest scan flagged as split. Hand-curated to be high-
# confidence; the wbsearch fallback handles the long tail.
# --------------------------------------------------------------------------
CURATED_ALIASES: list[dict] = [
    # Bruegel/Brueghel family — 4 canonical people. primary_surname is
    # the most-discriminating token to look for in unresolved inputs.
    # Suffix tokens (elder/younger) are NOT used for fold to keep them
    # separate.
    {
        "q": "Q43270",
        "display_name": "Pieter Bruegel the Elder",
        "lifespan": "c. 1525–1569",
        "family_key": "bruegel-elder",
        "primary_surname": "bruegel",
        "aliases": [
            "Pieter Bruegel",
            "Pieter Bruegel the Elder",
            "Pieter Brueghel",
            "Pieter Bruegel l'Ancien",
            "Pieter Bruegel d.Ä.",
        ],
    },
    {
        "q": "Q380732",
        "display_name": "Pieter Brueghel the Younger",
        "lifespan": "1564–1638",
        "family_key": "bruegel-younger",
        "primary_surname": None,  # ambiguous w/o "the Younger" — don't fold blind
        "aliases": [
            "Pieter Brueghel the Younger",
            "Pieter Bruegel the Younger",
            "Pieter Brueghel_d.J.",
            "Pieter Bruegel d.J.",
        ],
    },
    {
        "q": "Q150611",
        "display_name": "Jan Brueghel the Elder",
        "lifespan": "1568–1625",
        "family_key": "brueghel-jan-elder",
        "primary_surname": None,
        "aliases": [
            "Jan Brueghel the Elder",
            "Jan Brueghel the Older",
            "Jan Brueghel il Vecchio “Dei Velluti”",
            "Jan Brueghel",
            "Jan Brueghel d.Ä.",
        ],
    },
    {
        "q": "Q462281",
        "display_name": "Jan Brueghel the Younger",
        "lifespan": "1601–1678",
        "family_key": "brueghel-jan-younger",
        "primary_surname": None,
        "aliases": ["Jan Brueghel the Younger"],
    },
    {
        "q": "Q296",
        "display_name": "Claude Monet",
        "lifespan": "1840–1926",
        "family_key": "monet-claude",
        "primary_surname": "monet",
        "aliases": ["Claude Monet", "Monet"],
    },
    {
        "q": "Q352",
        "display_name": "Pierre-Auguste Renoir",
        "lifespan": "1841–1919",
        "family_key": "renoir-pierre-auguste",
        "primary_surname": "renoir",
        "aliases": ["Pierre-Auguste Renoir", "Auguste Renoir", "Renoir"],
    },
    {
        "q": "Q5598",
        "display_name": "Rembrandt van Rijn",
        "lifespan": "1606–1669",
        "family_key": "rembrandt-van-rijn",
        "primary_surname": "rembrandt",
        "aliases": [
            "Rembrandt van Rijn",
            "Rembrandt",
            "Rembrandt Harmensz. van Rijn",
            "Rembrandt Harmenszoon van Rijn",
        ],
    },
    {
        "q": "Q40599",
        "display_name": "Édouard Manet",
        "lifespan": "1832–1883",
        "family_key": "manet-edouard",
        "primary_surname": "manet",
        "aliases": ["Édouard Manet", "Edouard Manet", "Manet"],
    },
    {
        "q": "Q35548",
        "display_name": "Paul Cézanne",
        "lifespan": "1839–1906",
        "family_key": "cezanne-paul",
        "primary_surname": "cezanne",
        "aliases": ["Paul Cézanne", "Paul Cezanne", "Cézanne", "Cezanne"],
    },
    {
        "q": "Q297",
        "display_name": "Diego Velázquez",
        "lifespan": "1599–1660",
        "family_key": "velazquez-diego",
        "primary_surname": "velazquez",
        "aliases": ["Diego Velázquez", "Diego Velazquez", "Velazquez", "Velázquez", "Velasquez"],
    },
    {
        "q": "Q5580",
        "display_name": "Albrecht Dürer",
        "lifespan": "1471–1528",
        "family_key": "durer-albrecht",
        "primary_surname": "durer",
        "aliases": ["Albrecht Dürer", "Albrecht Durer", "Dürer", "Durer"],
    },
    {
        "q": "Q762",
        "display_name": "Leonardo da Vinci",
        "lifespan": "1452–1519",
        "family_key": "leonardo-da-vinci",
        "primary_surname": "vinci",
        "aliases": [
            "Leonardo da Vinci",
            "Leonardo Da Vinci",
            "Leonardo",
            "Leonardo di ser Piero da Vinci",
        ],
    },
    {
        "q": "Q5592",
        "display_name": "Michelangelo",
        "lifespan": "1475–1564",
        "family_key": "michelangelo",
        "primary_surname": "buonarroti",  # not "michelangelo" — too generic
        "aliases": ["Michelangelo", "Michelangelo Buonarroti"],
    },
    {
        "q": "Q5597",
        "display_name": "Raphael",
        "lifespan": "1483–1520",
        "family_key": "raphael",
        "primary_surname": "sanzio",
        "aliases": ["Raphael", "Raffaello Sanzio", "Raffaello", "Raffaello Sanzio da Urbino"],
    },
    # Caravaggio = Michelangelo Merisi. Polidoro DA Caravaggio is a
    # different artist (Polidoro Caldara, 1499-1543), so we DON'T fold
    # on "caravaggio" alone — only on "merisi" or exact alias.
    {
        "q": "Q42207",
        "display_name": "Caravaggio",
        "lifespan": "1571–1610",
        "family_key": "caravaggio",
        "primary_surname": "merisi",
        "aliases": ["Caravaggio", "Michelangelo Merisi da Caravaggio", "Merisi"],
    },
    {
        "q": "Q47551",
        "display_name": "Titian",
        "lifespan": "c. 1488–1576",
        "family_key": "titian",
        "primary_surname": "tiziano",
        "aliases": ["Titian", "Tiziano Vecellio", "Tiziano"],
    },
    {
        "q": "Q5582",
        "display_name": "Vincent van Gogh",
        "lifespan": "1853–1890",
        "family_key": "van-gogh-vincent",
        "primary_surname": "gogh",
        "aliases": ["Vincent van Gogh", "Van Gogh", "Vincent Van Gogh"],
    },
    {
        "q": "Q7814",
        "display_name": "Giotto di Bondone",
        "lifespan": "c. 1267–1337",
        "family_key": "giotto",
        "primary_surname": "giotto",
        "aliases": ["Giotto", "Giotto di Bondone"],
    },
    {
        "q": "Q5586",
        "display_name": "Katsushika Hokusai",
        "lifespan": "1760–1849",
        "family_key": "hokusai",
        "primary_surname": "hokusai",
        "aliases": ["Katsushika Hokusai", "Hokusai"],
    },
    {
        "q": "Q200798",
        "display_name": "Utagawa Hiroshige",
        "lifespan": "1797–1858",
        "family_key": "hiroshige",
        "primary_surname": "hiroshige",
        "aliases": ["Utagawa Hiroshige", "Hiroshige", "Andō Hiroshige"],
    },
    {
        "q": "Q5432",
        "display_name": "Francisco Goya",
        "lifespan": "1746–1828",
        "family_key": "goya-francisco",
        "primary_surname": "goya",
        "aliases": ["Francisco Goya", "Francisco de Goya", "Francisco de Goya y Lucientes", "Goya"],
    },
]


# --------------------------------------------------------------------------
# Data structures
# --------------------------------------------------------------------------
@dataclass
class AliasEntry:
    q: str
    display_name: str
    lifespan: str
    family_key: str
    aliases: list[str]
    primary_surname: str | None = None  # None = exact-alias-only, no fold


@dataclass
class ResolvedArtist:
    raw: str
    q: str | None
    display_name: str | None
    lifespan: str | None
    family_key: str | None
    method: str
    confidence: float
    notes: str = ""


# --------------------------------------------------------------------------
# Normalization
# --------------------------------------------------------------------------
def fold_name(s: str) -> str:
    """Lowercase, strip accents, collapse spaces. The cheap unification
    that catches Brueghel↔Bruegel-style spelling variants."""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower()
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


# --------------------------------------------------------------------------
# Alias table
# --------------------------------------------------------------------------
def build_alias_table() -> dict[str, AliasEntry]:
    """Folded-alias → AliasEntry map. The same canonical entry appears
    once per alias."""
    table: dict[str, AliasEntry] = {}
    for d in CURATED_ALIASES:
        entry = AliasEntry(
            q=d["q"],
            display_name=d["display_name"],
            lifespan=d["lifespan"],
            family_key=d["family_key"],
            aliases=list(d["aliases"]),
            primary_surname=d.get("primary_surname"),
        )
        for a in entry.aliases:
            table[fold_name(a)] = entry
    return table


# --------------------------------------------------------------------------
# Multi-creator splitter
# --------------------------------------------------------------------------
SPLIT_RE = re.compile(r"\s*(?:&| and |, ?)\s*", re.IGNORECASE)


def split_multi(name: str) -> list[str]:
    """Split a 'Rubens and Jan Brueghel' string into its parts.

    Strips leading "Style of " / "After " / "Copy of " markers from each
    piece since those alter relation but not identity."""
    # Don't split if the comma appears to be inside a single name
    # (e.g. "Vermeer, Johannes" — comma-separated last,first form)
    if name.count(",") == 1 and " and " not in name and " & " not in name:
        # Likely a "Family, Given" form; treat as single
        return [name.strip()]
    parts = [p.strip() for p in SPLIT_RE.split(name) if p.strip()]
    # Strip relation markers
    out = []
    for p in parts:
        p2 = re.sub(
            r"^(style of|after|copy of|attributed to|circle of|follower of|workshop of|school of)\s+",
            "",
            p,
            flags=re.I,
        )
        out.append(p2.strip())
    return out


# --------------------------------------------------------------------------
# Resolver
# --------------------------------------------------------------------------
SUFFIX_WORDS = {"elder", "younger", "older", "ancien", "jeune", "vecchio", "giovane"}
PREFIX_PHRASES = (
    "studio of",
    "school of",
    "circle of",
    "follower of",
    "workshop of",
    "manner of",
    "after",
    "style of",
    "attributed to",
    "copy of",
    "and workshop",
    "& workshop",
)


def _distinctive_surname(display_name: str) -> str:
    """Extract the family-key surname from a canonical display name by
    dropping 'the elder/younger', articles, and any leading given names.

    'Pieter Bruegel the Elder' -> 'bruegel'
    'Caspar David Friedrich' -> 'friedrich'
    'Jan Brueghel the Elder' -> 'brueghel'
    """
    folded = fold_name(display_name)
    tokens = [
        t
        for t in folded.split()
        if t not in {"the", "von", "van", "de", "da", "di", "del", "la", "le"}
    ]
    # Drop suffix words from the end
    while tokens and tokens[-1] in SUFFIX_WORDS:
        tokens.pop()
    return tokens[-1] if tokens else ""


def _all_distinctive_surnames(alias_table: dict) -> set[str]:
    """All surnames currently in the alias table (used to reject
    candidates whose input contains a DIFFERENT canonical surname).

    Uses explicit primary_surname when set; otherwise falls back to the
    heuristic distinctive_surname extraction."""
    out = set()
    seen_q: set[str] = set()
    for e in alias_table.values():
        if e.q in seen_q:
            continue
        seen_q.add(e.q)
        s = e.primary_surname or _distinctive_surname(e.display_name)
        if s:
            out.add(s)
    return out


def resolve_artist(
    raw: str,
    alias_table: dict[str, AliasEntry] | None = None,
    *,
    allow_wikidata: bool = False,
    wb_cache: dict[str, dict] | None = None,
    _surnames_cache: set[str] | None = None,
) -> ResolvedArtist:
    """Resolve one raw artist string to a canonical entry.

    `allow_wikidata=True` permits an online wbsearchentities call when
    the alias table misses. Caller is responsible for rate limiting.
    """
    if not raw or not raw.strip():
        return ResolvedArtist(
            raw=raw,
            q=None,
            display_name=None,
            lifespan=None,
            family_key=None,
            method="empty",
            confidence=0.0,
        )
    if alias_table is None:
        alias_table = build_alias_table()

    parts = split_multi(raw)
    # For multi-creator strings, resolve each and report the primary as
    # the resolution; the caller can re-run resolve_artist on each piece
    # if it needs secondary creators.
    if len(parts) > 1:
        primary = parts[0]
        sub = resolve_artist(primary, alias_table, allow_wikidata=allow_wikidata, wb_cache=wb_cache)
        return ResolvedArtist(
            raw=raw,
            q=sub.q,
            display_name=sub.display_name,
            lifespan=sub.lifespan,
            family_key=sub.family_key,
            method=f"multi-primary({sub.method})",
            confidence=sub.confidence * 0.9,
            notes=f"multi-creator string; primary={primary!r}; " f"co-creators={parts[1:]}",
        )

    folded = fold_name(raw)
    # If the input has a "prefix phrase" (Studio of, Workshop of, etc.),
    # treat as derived attribution — don't try to fold into the parent
    # artist as if it were the same hand. Resolve the suffix only.
    has_prefix_phrase = any(
        folded.startswith(p) or f" {p} " in f" {folded} " for p in PREFIX_PHRASES
    )
    # 1. Exact folded match
    if folded in alias_table:
        e = alias_table[folded]
        return ResolvedArtist(
            raw=raw,
            q=e.q,
            display_name=e.display_name,
            lifespan=e.lifespan,
            family_key=e.family_key,
            method="alias-exact",
            confidence=0.99,
        )

    # 2. Family-key fold: primary-surname token match, with veto when
    # the input contains a DIFFERENT canonical surname. Entries with
    # primary_surname=None are exact-alias-only (e.g. all the "Pieter
    # Brueghel" / "Jan Brueghel" variants need "the Elder/Younger" to
    # disambiguate, so we don't fold blind).
    if _surnames_cache is None:
        _surnames_cache = _all_distinctive_surnames(alias_table)
    raw_tokens = set(folded.split())
    seen_q: set[str] = set()
    for e in alias_table.values():
        if e.q in seen_q:
            continue
        seen_q.add(e.q)
        dsurname = e.primary_surname
        if not dsurname or dsurname not in raw_tokens:
            continue
        # Is there a competing surname in the input? Reject if yes.
        other_surnames = (raw_tokens & _surnames_cache) - {dsurname}
        if other_surnames:
            continue
        # Studio-of / Workshop-of / Style-of attribution attaches to the
        # named artist but is NOT the same hand. Still resolves to the
        # same canonical Q (provenance is what we're tracking), but with
        # lower confidence and a relation note. The caller can choose to
        # split as a derived-attribution later.
        if has_prefix_phrase:
            return ResolvedArtist(
                raw=raw,
                q=e.q,
                display_name=e.display_name,
                lifespan=e.lifespan,
                family_key=e.family_key,
                method="alias-family-fold-derived",
                confidence=0.50,
                notes=f"derived attribution (workshop/style/etc.) for {dsurname!r}",
            )
        return ResolvedArtist(
            raw=raw,
            q=e.q,
            display_name=e.display_name,
            lifespan=e.lifespan,
            family_key=e.family_key,
            method="alias-family-fold",
            confidence=0.85,
            notes=f"distinctive-surname match on {dsurname!r}",
        )

    # 3. Wikidata search fallback
    if allow_wikidata:
        cache = wb_cache if wb_cache is not None else {}
        cached = cache.get(folded)
        if cached is None:
            cached = _wb_search_for_artist(raw)
            cache[folded] = cached  # type: ignore[assignment]
        if cached:
            return ResolvedArtist(
                raw=raw,
                q=cached["q"],
                display_name=cached["label"],
                lifespan=cached.get("lifespan") or "",
                family_key=fold_name(cached["label"]).split()[-1] if cached["label"] else "",
                method="wikidata-search",
                confidence=cached.get("confidence", 0.70),
                notes=cached.get("notes", ""),
            )

    return ResolvedArtist(
        raw=raw,
        q=None,
        display_name=None,
        lifespan=None,
        family_key=None,
        method="unresolved",
        confidence=0.0,
    )


def _wb_search_for_artist(raw: str) -> dict | None:
    """Find a human (Q5) Wikidata entity matching the artist string."""
    url = (
        "https://www.wikidata.org/w/api.php?action=wbsearchentities"
        "&language=en&format=json&type=item&limit=8&search=" + urllib.parse.quote(raw)
    )
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "FAA/0.2"})
        with urllib.request.urlopen(req, timeout=15) as r:
            data = json.loads(r.read())
    except Exception:
        return None
    hits = data.get("search", [])
    if not hits:
        return None
    # Validate top hit is a human via wbgetentities
    qids = [h["id"] for h in hits[:5]]
    url2 = (
        "https://www.wikidata.org/w/api.php?action=wbgetentities"
        "&format=json&props=claims|labels&ids=" + "|".join(qids)
    )
    try:
        req2 = urllib.request.Request(url2, headers={"User-Agent": "FAA/0.2"})
        with urllib.request.urlopen(req2, timeout=15) as r:
            ents = json.loads(r.read()).get("entities", {})
    except Exception:
        return None
    for qid in qids:
        e = ents.get(qid) or {}
        p31s = []
        for c in e.get("claims", {}).get("P31", []) or []:
            v = c.get("mainsnak", {}).get("datavalue", {}).get("value") or {}
            if isinstance(v, dict):
                p31s.append(v.get("id"))
        if "Q5" not in p31s:  # human
            continue
        label = (e.get("labels", {}).get("en") or {}).get("value")
        # Try to extract birth/death (P569/P570) for lifespan
        birth = death = None
        for c in e.get("claims", {}).get("P569", []) or []:
            t = c.get("mainsnak", {}).get("datavalue", {}).get("value", {}).get("time", "")
            m = re.search(r"\+?(\d{4})", t)
            if m:
                birth = m.group(1)
                break
        for c in e.get("claims", {}).get("P570", []) or []:
            t = c.get("mainsnak", {}).get("datavalue", {}).get("value", {}).get("time", "")
            m = re.search(r"\+?(\d{4})", t)
            if m:
                death = m.group(1)
                break
        lifespan = f"{birth or '?'}–{death or '?'}" if (birth or death) else ""
        return {
            "q": qid,
            "label": label,
            "lifespan": lifespan,
            "confidence": 0.75 if qid == qids[0] else 0.60,
            "notes": "wbsearch top hit, P31=human",
        }
    return None
