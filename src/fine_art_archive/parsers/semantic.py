"""Semantic field classifier for Meural-style filename stems.

Replaces the positional parser's "1st field = title, 2nd = artist..." rule
with type-based slotting: each fragment is classified by what it contains
(year, dimensions, medium, name, title) and placed in the right slot
regardless of source order. This handles:

  - Artist-first inventory entries ("Ensor, Masks Confronting Death; ...")
  - Multi-comma titles ("Orchard in Bloom, Louveciennes, Camille Pissarro")
  - Out-of-order fields ("Arrival of the Normandy Train; 1877; Claude Monet; ...")
  - Series prefixes ("No. 32 - Seba, from the series ...")

The classifier returns a confidence score per slot. When confidence is low,
the row goes to manual review with both interpretations shown side-by-side
rather than the positional parser's wrong-guess-by-default behavior.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from fine_art_archive.parsers.year_utils import (
    CIRCA_TOKEN,
    DECADE_TOKEN,
    YEAR_RANGE_TOKEN,
    YEAR_TOKEN,
    split_with_separators,
)
from fine_art_archive.parsers.year_utils import (
    looks_like_year as _looks_like_year_fragment,
)

FieldType = Literal["year", "dimensions", "medium", "name", "title", "series", "number", "unknown"]


# --- Known-artist corpus -----------------------------------------------------
#
# The corpus lets us disambiguate cases where multiple fragments look like
# names (e.g. "Ensor, Masks Confronting Death" — both pieces parse as name
# under the regex heuristic alone). A piece that matches a known artist gets
# a confidence boost; the boost breaks the tie correctly in favor of "Ensor".
#
# Two lookups: (1) full-string exact match (lowercased), (2) surname match
# against the last token. The surname pass catches hyphenation/spelling
# variants ("Pierre-Auguste Renoir" vs "Pierre Auguste Renoir").

_KNOWN_ARTISTS_FULL: set[str] = set()
_KNOWN_ARTISTS_SURNAMES: set[str] = set()
# Subset of _KNOWN_ARTISTS_FULL that has a Wikidata Q-ID — these are the
# most authoritative entries (cross-validated against Wikidata's "instance
# of painter" class via the enrichment cache or hand-curated seed).
_WIKIDATA_ATTESTED: set[str] = set()


def _strip_diacritics(s: str) -> str:
    """NFKD decompose + drop combining marks: 'Eugène' → 'Eugene'."""
    import unicodedata

    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def _add_artist_to_corpus(name: str) -> None:
    """Insert `name` (and a diacritic-stripped variant) into the corpus."""
    nl = name.lower().strip()
    if not nl:
        return
    _KNOWN_ARTISTS_FULL.add(nl)
    stripped = _strip_diacritics(nl)
    if stripped != nl:
        _KNOWN_ARTISTS_FULL.add(stripped)
    toks = nl.split()
    if not toks:
        return
    surname = toks[-1].strip(".,;:'’\"")
    if len(surname) >= 4:
        _KNOWN_ARTISTS_SURNAMES.add(surname)
        _KNOWN_ARTISTS_SURNAMES.add(_strip_diacritics(surname))


def load_known_artists(inventory_csv: str | Path, min_frequency: int = 1) -> tuple[int, int]:
    """Populate the known-artist corpus from an inventory CSV.

    The CSV must have an 'artist' column. Names that appear at least
    `min_frequency` times are added. Returns (full_count, surname_count).
    """
    global _KNOWN_ARTISTS_FULL, _KNOWN_ARTISTS_SURNAMES
    from collections import Counter

    c: Counter = Counter()
    with open(inventory_csv) as f:
        r = csv.DictReader(f)
        for row in r:
            a = (row.get("artist") or "").strip()
            if a:
                c[a] += 1
    _KNOWN_ARTISTS_FULL = set()
    _KNOWN_ARTISTS_SURNAMES = set()
    for k, v in c.items():
        if v >= min_frequency:
            _add_artist_to_corpus(k)
    return len(_KNOWN_ARTISTS_FULL), len(_KNOWN_ARTISTS_SURNAMES)


def load_canonical_corpus(yaml_path: str | Path) -> tuple[int, int]:
    """Populate the corpus from data/canonical_artists.yaml.

    Each YAML entry contributes its canonical name and every alias to
    the corpus. Entries with a `wikidata_qid` additionally populate the
    Wikidata-attested set, used as the strongest tier in tie-breaks.

    Returns (full_count, surname_count). Replaces any previously-loaded
    corpus.
    """
    global _KNOWN_ARTISTS_FULL, _KNOWN_ARTISTS_SURNAMES, _WIKIDATA_ATTESTED
    import yaml  # local import — yaml is already a project dep

    _KNOWN_ARTISTS_FULL = set()
    _KNOWN_ARTISTS_SURNAMES = set()
    _WIKIDATA_ATTESTED = set()

    doc = yaml.safe_load(Path(yaml_path).read_text())
    for entry in (doc or {}).get("artists", []):
        nm = entry.get("name") or ""
        has_qid = bool(entry.get("wikidata_qid"))
        if nm:
            _add_artist_to_corpus(nm)
            if has_qid:
                _WIKIDATA_ATTESTED.add(nm.lower())
                _WIKIDATA_ATTESTED.add(_strip_diacritics(nm.lower()))
        for alias in entry.get("aliases", []) or []:
            _add_artist_to_corpus(alias)
            if has_qid:
                _WIKIDATA_ATTESTED.add(alias.lower())
                _WIKIDATA_ATTESTED.add(_strip_diacritics(alias.lower()))
    return len(_KNOWN_ARTISTS_FULL), len(_KNOWN_ARTISTS_SURNAMES)


def matches_known_artist(s: str) -> str | None:
    """Return 'wikidata', 'full', 'surname', or None for `s`.

    'wikidata' means the candidate has a Wikidata Q-ID in the canonical
    corpus — strongest signal. 'full' means inventory-only full-string
    match. 'surname' means only the last token matches. Matching is
    case- and diacritic-insensitive ('Eugène' === 'Eugene').
    """
    sl = s.strip().lower()
    if not sl:
        return None
    sl_strip = _strip_diacritics(sl)
    if sl in _WIKIDATA_ATTESTED or sl_strip in _WIKIDATA_ATTESTED:
        return "wikidata"
    if sl in _KNOWN_ARTISTS_FULL or sl_strip in _KNOWN_ARTISTS_FULL:
        return "full"
    toks = sl_strip.split()
    if toks:
        surname = toks[-1].strip(".,;:'’\"")
        if surname in _KNOWN_ARTISTS_SURNAMES:
            return "surname"
    return None


# --- Patterns for classification --------------------------------------------

# Year patterns: 4-digit year, year range, decade, "c. <year>"
YEAR_RE = YEAR_TOKEN
DECADE_RE = DECADE_TOKEN
YEAR_RANGE_RE = YEAR_RANGE_TOKEN
CIRCA_RE = CIRCA_TOKEN

# Dimensions: cm/in/mm × x dimensions
# Variant A: "72 × 94 cm"      — unit only on second number
# Variant B: "72 cm × 94 cm"   — unit on both numbers
# Variant C: "72 × 94"          — no unit (lower confidence)
DIM_RE = re.compile(
    r"\b\d+(?:\.\d+)?\s*(?:cm|in|inches|mm)?\s*[×x]\s*\d+(?:\.\d+)?\s*(cm|in|inches|mm)\b",
    re.I,
)
DIM_SOFT_RE = re.compile(r"\b\d+(?:\.\d+)?\s*[×x]\s*\d+(?:\.\d+)?\b")

# Medium keywords (case-insensitive). Order matters slightly — longer phrases first.
MEDIUM_KEYWORDS = [
    "oil on canvas",
    "oil on panel",
    "oil on wood",
    "oil on cardboard",
    "oil on paper",
    "oil and tempera",
    "tempera on panel",
    "watercolor",
    "watercolour",
    "gouache",
    "pastel",
    "color woodblock print",
    "woodblock print",
    "etching",
    "lithograph",
    "engraving",
    "drypoint",
    "aquatint",
    "tempera",
    "fresco",
    "ink",
    "charcoal",
    "chalk",
    "graphite",
    "acrylic",
    "mixed media",
    "dispersion on fabric",
    "oil paint",
    "oil",
]

# Series indicators
SERIES_RE = re.compile(r"\b(from the series|series|set|suite)\b", re.I)
NUMBERED_PREFIX_RE = re.compile(r"^(?:No\.\s*)?(\d+)\.?\s+", re.I)

# Name heuristics: 1-4 capitalized words, possibly with lowercase connectors
# (van, der, de, du, di, von, le, la, l', d')
NAME_CONNECTOR = r"(?:van|der|den|de|du|di|von|le|la|l['’]|d['’]|of)"
NAME_RE = re.compile(
    r"^(?:[A-ZÄÖÜÉÈÊÀÁÂÇÑ][A-Za-zäöüéèêàáâçñ\.\-'’]*\s+|" + NAME_CONNECTOR + r"\s+){1,5}"
    r"[A-ZÄÖÜÉÈÊÀÁÂÇÑ][A-Za-zäöüéèêàáâçñ\.\-'’]*$"
)


@dataclass
class FieldClassification:
    """The result of classifying a single fragment."""

    text: str
    type: FieldType
    confidence: float
    evidence: str = ""


@dataclass
class ParsedFilename:
    """Semantic parse of a filename stem."""

    title: str = ""
    artist: str = ""
    year: str = ""
    medium: str = ""
    dimensions: str = ""
    series: str = ""
    number: str = ""
    raw_stem: str = ""
    fragments: list[FieldClassification] = field(default_factory=list)
    title_confidence: float = 0.0
    artist_confidence: float = 0.0
    ambiguous: bool = False
    notes: list[str] = field(default_factory=list)


# --- Classification -------------------------------------------------------


def looks_like_year(s: str) -> tuple[bool, float, str]:
    return _looks_like_year_fragment(s, dimension_pattern=DIM_SOFT_RE)


def looks_like_dimensions(s: str) -> tuple[bool, float, str]:
    if DIM_RE.search(s):
        return True, 0.95, "dimensions-with-unit"
    if DIM_SOFT_RE.search(s):
        return True, 0.70, "dimensions-no-unit"
    return False, 0.0, ""


def looks_like_medium(s: str) -> tuple[bool, float, str]:
    sl = s.lower().strip()
    for kw in MEDIUM_KEYWORDS:
        if kw in sl:
            # When the keyword covers most of the fragment, it's almost
            # certainly a medium phrase — boost confidence to beat the
            # soft-name heuristic that fires on "Oil on Canvas"-style
            # capitalization.
            coverage = len(kw) / max(len(sl), 1)
            if coverage >= 0.70:
                return True, 0.95, f"medium-keyword:{kw} (cov {coverage:.2f})"
            return True, 0.85, f"medium-keyword:{kw}"
    return False, 0.0, ""


def looks_like_name(s: str) -> tuple[bool, float, str]:
    """Heuristic for an artist name.

    Names are 1-5 mostly-capitalized words. Lowercase connectors allowed.
    Not too long. No digits. No semicolons. The known-artist corpus
    (when loaded via load_known_artists) provides a confidence boost
    that breaks ties when multiple fragments look like names.
    """
    if not s or len(s) > 60 or any(c.isdigit() for c in s):
        return False, 0.0, ""
    words = s.split()
    if len(words) > 6:
        return False, 0.0, ""
    if not s[0].isupper():
        return False, 0.0, ""

    # Strongest signal: known artist (full string or surname). The corpus
    # is the ground-truth from prior inventory parses, so this is high-conf.
    known = matches_known_artist(s)

    if NAME_RE.fullmatch(s):
        if known == "wikidata":
            return True, 0.99, f"name-pattern+wikidata ({len(words)} words)"
        if known == "full":
            return True, 0.96, f"name-pattern+known-artist ({len(words)} words)"
        if known == "surname":
            return True, 0.93, f"name-pattern+known-surname ({len(words)} words)"
        return True, 0.85, f"name-pattern ({len(words)} words)"

    # Soft: 2+ capitalized words, doesn't fully match NAME_RE
    cap_words = sum(1 for w in words if w and w[0].isupper())
    if cap_words >= 2 and len(words) <= 4:
        if known == "wikidata":
            return True, 0.96, "soft-name+wikidata-match"
        if known:
            return True, 0.90, f"soft-name+{known}-match"
        return True, 0.65, "soft-name-pattern"

    # Single capitalized word — Giotto, Rembrandt, Caravaggio, Ensor, ...
    if len(words) == 1 and s[0].isupper() and 4 <= len(s) <= 20:
        if known == "wikidata":
            return True, 0.96, "single-word+wikidata-match"
        if known == "full" or known == "surname":
            return True, 0.92, f"single-word+{known}-match"
        return True, 0.55, "single-capitalized-word"
    return False, 0.0, ""


def looks_like_series(s: str) -> tuple[bool, float, str]:
    if SERIES_RE.search(s):
        return True, 0.90, "series-keyword"
    return False, 0.0, ""


def classify_fragment(s: str) -> FieldClassification:
    """Classify a single fragment by its strongest signal.

    Order of strength: dimensions > year > medium > series > name > title.
    The strongest match wins; ties broken by precedence above.
    """
    candidates = []

    ok, conf, ev = looks_like_dimensions(s)
    if ok:
        candidates.append(("dimensions", conf, ev))

    ok, conf, ev = looks_like_year(s)
    if ok:
        candidates.append(("year", conf, ev))

    ok, conf, ev = looks_like_medium(s)
    if ok:
        candidates.append(("medium", conf, ev))

    ok, conf, ev = looks_like_series(s)
    if ok:
        candidates.append(("series", conf, ev))

    ok, conf, ev = looks_like_name(s)
    if ok:
        candidates.append(("name", conf, ev))

    if not candidates:
        return FieldClassification(
            text=s, type="title", confidence=0.40, evidence="default-residue"
        )

    # Pick the highest-confidence type
    type_, conf, ev = max(candidates, key=lambda c: c[1])
    return FieldClassification(text=s, type=type_, confidence=conf, evidence=ev)  # type: ignore[arg-type]


# --- Top-level parser -----------------------------------------------------


def _maybe_extract_suffix_artist(
    fragment: str, max_artist_words: int = 4
) -> tuple[str, str] | None:
    """If a long fragment ends with a known artist name and no delimiter
    separates the artist from the preceding text, peel off the artist.

    Example: "The Beach and the Falaise d'Amont Claude Monet" → ends with
    "Claude Monet" (known full match). Returns ("The Beach...", "Claude Monet").

    Enumerates all suffix windows 1..max_artist_words, scores each as
    (tier, length), and picks the best. Tier 2 = full corpus match,
    tier 1 = surname corpus match. Longest match within highest tier
    wins — this fixes the "Seated Figures Eugene Boudin" case where a
    naive surname-first scan would peel only "Figures Eugene Boudin"
    (3 tokens, tier 1) instead of "Eugene Boudin" (2 tokens, tier 2).

    Returns None if no qualifying suffix is found.
    """
    tokens = fragment.split()
    if len(tokens) < 3:
        return None
    connectors = {c.strip("()") for c in NAME_CONNECTOR.split("|")}
    candidates: list[tuple[int, int, str]] = []  # (tier, length, candidate)
    for n in range(1, max_artist_words + 1):
        if n >= len(tokens):
            continue
        candidate = " ".join(tokens[-n:])
        if not candidate[0].isupper():
            continue
        m = matches_known_artist(candidate)
        if m == "wikidata":
            candidates.append((3, n, candidate))
        elif m == "full":
            candidates.append((2, n, candidate))
        elif m == "surname" and n >= 2:
            ok = all(t[0].isupper() or t.lower() in connectors for t in tokens[-n:] if t)
            if ok:
                candidates.append((1, n, candidate))
    if not candidates:
        return None
    # Prefer higher tier; within tier, prefer longer match
    candidates.sort(reverse=True)
    _, n, candidate = candidates[0]
    head = " ".join(tokens[:-n])
    return head, candidate


def _maybe_subsplit_fragment(fragment: str) -> list[str]:
    """Try comma-splitting a fragment if the split improves classification.

    Three real-world cases:
      A. 2-piece "Title, Artist" — split if a piece is a name.
      B. 2-piece "Artist, Title" — split if exactly one piece is a known
         artist ("Ensor, Masks Confronting Death").
      C. N-piece (N≥3) multi-comma title + artist, e.g.
         "Orchard in Bloom, Louveciennes, Camille Pissarro" or
         "Waterloo Bridge, London, at Dusk, Claude Monet" — pull out the
         one DOMINANT artist piece and rejoin the rest as title.

    The corpus has noise (place names like "Louveciennes" leaked in from
    prior misparses), so we can't require "exactly one known artist".
    Instead, score each piece by (corpus-tier, surface-confidence) and
    pull out the piece whose score dominates the runner-up. Tiers:
        2 = full-string corpus match
        1 = surname-only corpus match
        0 = name-pattern alone, no corpus support
    """
    if "," not in fragment:
        return [fragment]
    pieces = [p.strip() for p in fragment.split(",") if p.strip()]
    if len(pieces) < 2:
        return [fragment]

    sub_classes = [classify_fragment(p) for p in pieces]

    # Structural signal anywhere → adopt split (year/dim/medium pieces
    # should never be glued together with a title).
    if any(
        c.type in {"year", "dimensions", "medium"} and c.confidence >= 0.80 for c in sub_classes
    ):
        return pieces

    # Tier-score every piece that looks like a name
    scored: list[tuple[int, float, int, str]] = []
    tier_map = {"wikidata": 3, "full": 2, "surname": 1}
    for i, p in enumerate(pieces):
        c = sub_classes[i]
        if c.type != "name":
            continue
        tier = tier_map.get(matches_known_artist(p) or "", 0)
        scored.append((tier, c.confidence, i, p))

    if not scored:
        return [fragment]

    scored.sort(reverse=True)
    best = scored[0]

    # Exactly one name-like piece → trivial pull-out
    if len(scored) == 1:
        idx, artist = best[2], best[3]
        remaining = pieces[:idx] + pieces[idx + 1 :]
        return [", ".join(remaining), artist] if remaining else [artist]

    # Multiple name-like pieces — adopt the split only if the best
    # dominates the runner-up. Domination = strictly higher tier,
    # OR same tier with confidence at least 0.05 higher.
    second = scored[1]
    dominates = (best[0] > second[0]) or (best[0] == second[0] and best[1] >= second[1] + 0.05)
    if dominates:
        idx, artist = best[2], best[3]
        remaining = pieces[:idx] + pieces[idx + 1 :]
        return [", ".join(remaining), artist]

    # Tie among same-tier known artists — positional tie-break: the LAST
    # piece in the comma-list is conventionally the artist
    # ("Title, Subtitle, Place, Artist"). Only apply when both contenders
    # are tier ≥ 1 (i.e. corpus-attested), to avoid arbitrary picks
    # among genuinely-ambiguous unknown tokens.
    if best[0] == second[0] and best[0] >= 1 and abs(best[1] - second[1]) < 0.05:
        # Pick the contender with the highest source-position index
        latest = max(scored, key=lambda s: s[2])
        idx, artist = latest[2], latest[3]
        remaining = pieces[:idx] + pieces[idx + 1 :]
        return [", ".join(remaining), artist]

    # Genuinely ambiguous — keep the fragment whole and let the slotter
    # flag it. (parse_semantic flags ambiguous when names compete.)
    return [fragment]


def parse_semantic(stem: str) -> ParsedFilename:
    """Parse a filename stem by classifying each fragment then slotting.

    Two-pass split:
      1. Split on semicolons (or commas if no semicolons).
      2. For each fragment, attempt a comma sub-split if doing so
         pulls out a confident artist name. This handles the
         "Title, Artist; Year; Medium; Dimensions" shape that's
         dominant in the inventory, AND the rarer "Artist, Title; ..."
         shape (e.g. "Ensor, Masks Confronting Death").
    """
    out = ParsedFilename(raw_stem=stem)

    # Strip a leading "<num>. " prefix (Presidents series, etc.)
    m = NUMBERED_PREFIX_RE.match(stem)
    if m:
        out.number = m.group(1)
        stem = stem[m.end() :]

    fragments = split_with_separators(stem)

    # Two-pass: sub-comma-split any fragment that benefits from it.
    expanded: list[str] = []
    for f in fragments:
        expanded.extend(_maybe_subsplit_fragment(f))

    # Third pass: peel an embedded-suffix artist off any long fragment
    # whose tail tokens correspond to a known artist (e.g. "The Beach
    # and the Falaise d'Amont Claude Monet" → ".... Étretat" + "Claude
    # Monet", or "Seated Figures Eugene Boudin" → "Seated Figures" +
    # "Eugene Boudin"). The suffix extractor only fires when the
    # head is non-empty AND the tail outranks the whole fragment as
    # an artist signal — so it won't damage already-clean name pieces
    # like "Pierre-Auguste Renoir".
    final: list[str] = []
    for f in expanded:
        # Skip third-pass on fragments that still contain a comma — they
        # are either a sub-split residue (comma is intentional title
        # punctuation) or an unreduced original. Running the extractor
        # on them produces leading/trailing-comma artifacts when the
        # head boundary doesn't align with token boundaries.
        if "," in f:
            final.append(f)
            continue
        if len(f.split()) >= 4:
            extracted = _maybe_extract_suffix_artist(f)
            if extracted:
                head, artist = extracted
                # Sanity: only adopt if the tail is a STRICTER artist
                # signal than the whole fragment. If the whole fragment
                # is already Wikidata-attested and the tail isn't, keep
                # the whole — this prevents peeling a true 3-word name
                # like "Joseph Mallord William Turner" into ["...", "Turner"].
                whole_match = matches_known_artist(f)
                tail_match = matches_known_artist(artist)
                whole_tier = {"wikidata": 3, "full": 2, "surname": 1, None: 0}[whole_match]
                tail_tier = {"wikidata": 3, "full": 2, "surname": 1, None: 0}[tail_match]
                if head and tail_tier > whole_tier:
                    final.append(head)
                    final.append(artist)
                    continue
        final.append(f)

    out.fragments = [classify_fragment(f) for f in final]

    # First-pass slotting: take the highest-confidence claim for each slot
    for slot in ("year", "dimensions", "medium", "name", "series"):
        candidates_for_slot = [c for c in out.fragments if c.type == slot]
        if not candidates_for_slot:
            continue
        best = max(candidates_for_slot, key=lambda c: c.confidence)
        setattr(out, "artist" if slot == "name" else slot, best.text)
        if slot == "name":
            out.artist_confidence = best.confidence

    # Title is the residue: fragments not slotted into year/dim/medium/name/series
    used = {out.year, out.dimensions, out.medium, out.artist, out.series}
    used.discard("")
    title_parts = [f.text for f in out.fragments if f.text not in used]
    out.title = ", ".join(title_parts) if title_parts else ""
    out.title_confidence = (
        1.0 if len(title_parts) == 1 else max(0.3, 1.0 - 0.2 * (len(title_parts) - 1))
    )

    # Flag ambiguity
    name_fragments = [c for c in out.fragments if c.type == "name"]
    if len(name_fragments) > 1:
        # Multiple name candidates resolved by max-conf; flag for review only
        # if the second-best is close to the winner.
        sorted_names = sorted(name_fragments, key=lambda c: -c.confidence)
        if (
            len(sorted_names) >= 2
            and sorted_names[0].confidence - sorted_names[1].confidence < 0.20
        ):
            out.ambiguous = True
            out.notes.append(
                f"competing name candidates: {sorted_names[0].text!r} ({sorted_names[0].confidence:.2f}) "
                f"vs {sorted_names[1].text!r} ({sorted_names[1].confidence:.2f})"
            )
    if not out.artist and any(c.type != "title" for c in out.fragments):
        out.notes.append("no artist identified — title may be misclassified")
    if out.artist and out.artist_confidence < 0.70:
        out.notes.append(f"low artist confidence ({out.artist_confidence:.2f})")

    return out


# --- Canonical output --------------------------------------------------------


def canonical_artist_first(parsed: ParsedFilename) -> str:
    """Render a ParsedFilename in artist-first canonical form.

    Format: ``Artist; Title; Year; Medium; Dimensions``
    Empty slots are omitted (no trailing/double semicolons). When the
    parser couldn't identify an artist, returns the title-first form
    instead (so we don't lie about parse success in the filename).

    Tim's argument for artist-first: every legitimate filename starts
    with a painter, which makes duplicate-check, sort-by-artist, and
    "all the Renoirs" trivial. The current title-first format has none
    of these properties.
    """
    parts: list[str] = []
    if parsed.artist:
        parts.append(parsed.artist)
    if parsed.title:
        parts.append(parsed.title)
    if parsed.year:
        parts.append(parsed.year)
    if parsed.medium:
        parts.append(parsed.medium)
    if parsed.dimensions:
        parts.append(parsed.dimensions)
    if parsed.series:
        parts.append(parsed.series)
    if not parts:
        return parsed.raw_stem
    return "; ".join(parts)
