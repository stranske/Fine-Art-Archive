"""Pre-acquisition duplicate detection against the existing inventory.

The Caillebotte incident (2026-05-17, see operations.log) was a 40 MB
acquisition that turned out to be a smaller-resolution copy of a
84.8 MB file already in the archive. Tim flagged: "Have you been
checking against existing archive work names to avoid duplicates?"

This module exists to make that check unmissable in the acquire
pipeline. Before the orchestrator fetches bytes, it normalizes
(title, artist) against the inventory and surfaces any plausible
match — letting the caller decide skip / upgrade / force.

Match tiers (decreasing confidence):
  - exact-title-artist : both normalize-equal
  - exact-artist+near-title : artist matches, title differs in
        punctuation / parenthetical / case but Jaccard-similar
  - exact-title : title matches but artist differs (suspicious;
        could be a duplicate uploaded under wrong artist label)
  - surname-only : artist surnames match + title fuzzy-similar

The duplicate-check does NOT replace the byte-level dedupe at finalize
(SHA-256 collision detection); it's a cheap upfront name-level filter.
"""

from __future__ import annotations

import csv
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

MatchTier = Literal[
    "exact-title-artist",
    "exact-artist+near-title",
    "exact-title",
    "surname-only",
]


@dataclass
class DuplicateMatch:
    inventory_row: dict
    tier: MatchTier
    confidence: float
    rel_path: str
    size_bytes: int
    why: str
    inventory_title: str = ""
    inventory_artist: str = ""


@dataclass
class DuplicateCheckResult:
    matches: list[DuplicateMatch] = field(default_factory=list)
    candidate_title: str = ""
    candidate_artist: str = ""

    @property
    def has_strong_match(self) -> bool:
        return any(m.confidence >= 0.85 for m in self.matches)

    @property
    def best(self) -> DuplicateMatch | None:
        return self.matches[0] if self.matches else None


# --- Normalization -----------------------------------------------------------

_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)
_WS_RE = re.compile(r"\s+")


def _normalize(s: str) -> str:
    """Lowercase, strip diacritics, drop punctuation, collapse whitespace."""
    if not s:
        return ""
    # Decompose diacritics, drop combining marks (Renoir's "é" → "e")
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower()
    s = _PUNCT_RE.sub(" ", s)
    s = _WS_RE.sub(" ", s).strip()
    return s


def _surname(artist: str) -> str:
    """Last token after normalize; empty if too short."""
    norm = _normalize(artist)
    if not norm:
        return ""
    last = norm.split()[-1]
    return last if len(last) >= 4 else ""


def _jaccard_token_set(a: str, b: str) -> float:
    """Token-set Jaccard similarity over normalized strings."""
    sa = set(_normalize(a).split())
    sb = set(_normalize(b).split())
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def _title_similarity(a: str, b: str) -> float:
    """Composite title similarity: max(Jaccard, containment).

    Containment counts when one title's tokens are a subset of the
    other — this catches cases like inventory title "Paris Street"
    (where the old positional parser dumped the subtitle into the
    year slot) vs candidate "Paris Street; Rainy Day". Restricted
    to min_tokens >= 2 to avoid single-word over-matching.
    """
    sa = set(_normalize(a).split())
    sb = set(_normalize(b).split())
    if not sa or not sb:
        return 0.0
    inter = len(sa & sb)
    union = len(sa | sb)
    jacc = inter / union
    min_n = min(len(sa), len(sb))
    if min_n >= 2:
        contain = inter / min_n
        return max(jacc, contain)
    return jacc


# --- Inventory match ---------------------------------------------------------


def check_inventory(
    candidate_title: str,
    candidate_artist: str,
    inventory_csv: Path,
    near_title_threshold: float = 0.60,
) -> DuplicateCheckResult:
    """Search the inventory CSV for entries plausibly matching the candidate.

    Returns matches sorted by confidence descending. Empty list means
    no plausible duplicate — safe to proceed with acquisition.
    """
    out = DuplicateCheckResult(candidate_title=candidate_title, candidate_artist=candidate_artist)
    norm_title = _normalize(candidate_title)
    norm_artist = _normalize(candidate_artist)
    candidate_surname = _surname(candidate_artist)

    if not norm_title and not norm_artist:
        return out

    with open(inventory_csv) as f:
        r = csv.DictReader(f)
        for row in r:
            inv_title = (row.get("title") or "").strip()
            inv_artist = (row.get("artist") or "").strip()
            if not inv_title and not inv_artist:
                continue

            n_inv_title = _normalize(inv_title)
            n_inv_artist = _normalize(inv_artist)
            inv_surname = _surname(inv_artist)

            tier: MatchTier | None = None
            confidence = 0.0
            why = ""

            # Tier 1: both normalize-equal
            if n_inv_title == norm_title and n_inv_artist == norm_artist:
                tier = "exact-title-artist"
                confidence = 0.99
                why = "exact normalized match on title AND artist"
            # Tier 2: artist matches (full or surname), title is near-equal
            elif norm_artist and (
                n_inv_artist == norm_artist
                or (candidate_surname and candidate_surname == inv_surname)
            ):
                sim = _title_similarity(candidate_title, inv_title) if norm_title else 0.0
                if sim >= near_title_threshold:
                    artist_match_kind = "full" if n_inv_artist == norm_artist else "surname"
                    tier = "exact-artist+near-title"
                    confidence = 0.70 + 0.25 * sim  # 0.85–0.95 range
                    why = f"artist matches ({artist_match_kind}); " f"title similarity {sim:.2f}"
            # Tier 3: title matches but artist differs (suspicious)
            if tier is None and norm_title and n_inv_title == norm_title:
                tier = "exact-title"
                confidence = 0.70
                why = "exact title match; artist differs — verify"
            # Tier 4: surname matches + fuzzy title
            if tier is None and candidate_surname and candidate_surname == inv_surname:
                sim = _title_similarity(candidate_title, inv_title) if norm_title else 0.0
                if sim >= near_title_threshold:
                    tier = "surname-only"
                    confidence = 0.55 + 0.15 * sim  # 0.64–0.70 range
                    why = f"surname matches; title similarity {sim:.2f}"

            if tier:
                out.matches.append(
                    DuplicateMatch(
                        inventory_row=row,
                        tier=tier,
                        confidence=confidence,
                        rel_path=row.get("rel_path", ""),
                        size_bytes=int(row.get("size_bytes") or 0),
                        why=why,
                        inventory_title=inv_title,
                        inventory_artist=inv_artist,
                    )
                )

    out.matches.sort(key=lambda m: -m.confidence)
    return out


def format_report(result: DuplicateCheckResult, top_n: int = 5) -> str:
    """Human-readable report for the acquire pipeline."""
    if not result.matches:
        return (
            f"[dedupe] no plausible duplicates for "
            f"{result.candidate_artist!r} / {result.candidate_title!r}"
        )
    lines = [
        f"[dedupe] {len(result.matches)} possible duplicate(s) for "
        f"{result.candidate_artist!r} / {result.candidate_title!r}:"
    ]
    for i, m in enumerate(result.matches[:top_n], start=1):
        lines.append(
            f"  {i}. [{m.tier}] conf={m.confidence:.2f}  "
            f"({m.size_bytes / 1_000_000:.1f} MB)  {m.rel_path}"
        )
        lines.append(f"     {m.why}")
        if m.inventory_title:
            lines.append(f"     inv-title:  {m.inventory_title}")
        if m.inventory_artist:
            lines.append(f"     inv-artist: {m.inventory_artist}")
    if len(result.matches) > top_n:
        lines.append(f"  ... and {len(result.matches) - top_n} more")
    return "\n".join(lines)
