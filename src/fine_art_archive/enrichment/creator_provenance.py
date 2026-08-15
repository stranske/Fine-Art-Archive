"""Classify and conservatively repair a work's CREATOR provenance.

Separates a work that legitimately has no creator from one whose creator is
merely unresolved or whose record is corrupt -- the distinction the work-QID
ledger cannot make and the whole point of this pass. Four outcomes:

  * ``resolved``       -- a real artist QID recovered from ``artist.name``,
    including a *conservative* typo / token-order repair, occupation-gated so a
    sitter or junk string never becomes a maker.
  * ``anonymous``      -- unattributed BY NATURE: an explicit anonymity marker
    ("Unknown", "Master of ...", "Unidentified") or a period / culture / date
    fragment standing in for a maker (a Tang tomb figure, a Byzantine icon).
    Terminal and version-INDEPENDENT -- better search never finds a name that
    does not exist.
  * ``searched``       -- a real personal name that did NOT resolve at the
    current artist-search-plan version. Terminal UNTIL the plan improves
    (mirrors the work-QID ledger; re-opens on a version bump).
  * ``unattributable`` -- the record is corrupt: the artist is absent from the
    metadata entirely (both fields hold junk / descriptor / filename / date
    fragments). Distinct from ``anonymous`` -- we do NOT claim the work has no
    maker, only that our record lost it. A data-repair problem, not a search.

The anonymity verdict is guarded: a date/fragment name whose *title* resolves to
a real artist (the "half-swap" -- e.g. name ``"1629:1630 - 1677)"`` / title
``"Anthonie van Borssom"``) is routed to ``unattributable``, never labelled
anonymous, so a corrupt record is never dressed up as a legitimate absence.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any, Protocol

from fine_art_archive.enrichment.wikidata_identity import fetch_identity
from fine_art_archive.identity.artist_lookup import clean_name, resolve_artist_qid


class HttpGet(Protocol):
    """A GET transport accepted by both the artist resolver and fetch_identity."""

    def get(
        self, url: str, *, params: Mapping[str, str] | None = None
    ) -> dict[str, Any] | None: ...


ARTIST_SEARCH_PLAN_VERSION = 1  # bump when an artist-search strategy is added

# Ledger source_ref prefixes -- the machine-distinguishable state markers.
REF_ANONYMOUS = "faa:creator/anonymous"
REF_UNATTRIBUTABLE = (
    "faa:creator/unattributable"  # legacy terminal; now reopened to REF_IMAGE_PENDING
)
# A corrupt / null-name record is NOT terminally unattributable from text alone:
# image search recovers many of these (a debris name hides a real, image-findable
# work). This is a NON-terminal "text exhausted, image search still owed" state --
# null/unusable name is never accepted as final until image search has run.
REF_IMAGE_PENDING = "faa:image-search/pending"
# Image search recovered a usable name but no safe single creator QID.  This is
# terminal: repeating image search would only rediscover the same name.
REF_IMAGE_NAME_RECOVERED = "faa:image-search/name-recovered"
REF_SEARCH = "faa:artist-search/v"  # + version

# Explicit anonymity / non-personal attribution markers in a name field.
_ANON_MARKER = re.compile(
    r"\b(unknown|anonymous|unidentified|unattributed|master of|circle of|"
    r"follower of|workshop of|attributed to|school of|manner of|studio of|"
    r"style of|imitator of|after)\b",
    re.IGNORECASE,
)
# Era / dynasty / period keyword -> a genuine cultural-anonymous stand-in.
# NOTE: a bare year ("1783", "1440-43") is deliberately NOT here -- a lost modern
# date is corruption, not evidence of anonymity, and routes to `unattributable`.
_ERA = re.compile(
    r"\b(century|dynasty|period|b\.?c\.?|a\.?d\.?|c\.?e\.?|"
    r"first quarter|second quarter|third quarter|fourth quarter|"
    r"byzantine|tang|song|ming|qing|edo|meiji|kamakura|heian|mughal|safavid|"
    r"gothic|romanesque|medieval|renaissance|hellenistic|ptolemaic|coptic|"
    r"early christian|old kingdom|new kingdom|middle kingdom)\b",
    re.IGNORECASE,
)
# A named non-Western/anthropological culture standing in for an anonymous maker.
_CULTURE = re.compile(
    r"\b(iranian|persian|indian|chinese|japanese|korean|tibetan|nepalese|"
    r"egyptian|roman|greek|etruscan|byzantine|ottoman|mughal|safavid|"
    r"aztec|mayan|inca|olmec|nubian|assyrian|sumerian|babylonian)\b",
    re.IGNORECASE,
)
_FILE = re.compile(r"[_/\\]|\.(jpe?g|png|tiff?|gif)$", re.IGNORECASE)
_WORD = re.compile(r"[^\W\d_]{2,}")


def _fold(text: str) -> str:
    return re.sub(r"[^a-z0-9 ]", "", text.lower()).strip()


def _token_set_sim(a: str, b: str) -> float:
    """Order-independent name similarity (so a token reorder scores ~1.0)."""
    ta = " ".join(sorted(_fold(a).split()))
    tb = " ".join(sorted(_fold(b).split()))
    if not ta or not tb:
        return 0.0
    return SequenceMatcher(None, ta, tb).ratio()


def _looks_personal(name: str) -> bool:
    """A plausible personal name: >= 2 alphabetic, capitalised tokens, no junk."""
    n = name.strip()
    if not n or _ANON_MARKER.search(n) or _FILE.search(n):
        return False
    if any(ch.isdigit() for ch in n):
        return False
    tokens = [t for t in re.split(r"\s+", n) if _WORD.search(t)]
    if len(tokens) < 2:
        return False
    return all(t[:1].isupper() for t in tokens)


def _conservative_variants(name: str) -> list[tuple[str, str]]:
    """Small, safe set of typo / order repairs to retry resolution against.

    Deliberately narrow: doubled/tripled-letter collapse and a two-token
    reorder. Pure insertions/deletions ("Guguin" -> "Gauguin") are NOT guessed
    -- conservative by design; those fall to the versioned ledger instead.
    """
    variants: list[tuple[str, str]] = []
    triple = re.sub(r"(.)\1{2,}", r"\1\1", name)  # 3+ repeats -> 2
    if triple != name:
        variants.append((triple, "collapse-tripled"))
    double = re.sub(r"(.)\1+", r"\1", name)  # any run -> 1
    if double != name:
        variants.append((double, "collapse-doubled"))
    tokens = [t for t in re.split(r"\s+", name.strip()) if t]
    if len(tokens) == 2:
        variants.append((f"{tokens[1]} {tokens[0]}", "token-reorder"))
    # dedupe preserving order
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for v, k in variants:
        if v not in seen and v != name:
            seen.add(v)
            out.append((v, k))
    return out


@dataclass(frozen=True)
class CreatorOutcome:
    kind: str  # resolved | anonymous | searched | unattributable
    qid: str | None = None
    display: str | None = None
    method: str | None = None
    note: str = ""


def _repair_resolve(name: str, *, client: HttpGet) -> CreatorOutcome | None:
    """Resolve ``name`` to an artist QID, trying conservative variants.

    A variant hit is accepted only when the resolved entity's label is an
    order-independent >= 0.90 match to the original cleaned name, so a repair can
    fix a typo but never drift to a different same-ish person.
    """
    qid, method = resolve_artist_qid(name, client=client)
    if qid:
        display, _ = fetch_identity(qid, client=client)
        return CreatorOutcome(
            "resolved",
            qid,
            display or name,
            method or "resolve",
            note=f"Resolved from artist name {name!r} ({method}).",
        )
    cleaned = clean_name(name)
    for variant, kind in _conservative_variants(name):
        vqid, vmethod = resolve_artist_qid(variant, client=client)
        if not vqid:
            continue
        display, _ = fetch_identity(vqid, client=client)
        if display and _token_set_sim(cleaned, display) >= 0.90:
            return CreatorOutcome(
                "resolved",
                vqid,
                display,
                f"{vmethod} via {kind}",
                note=f"Resolved from artist name {name!r} via {kind} -> {variant!r} ({vmethod}).",
            )
    return None


def _title_is_artist(title: str, *, client: HttpGet) -> bool:
    """True if the *title* field resolves to a real artist (a half-swap tell)."""
    if not title or not _WORD.search(title):
        return False
    qid, _ = resolve_artist_qid(title, client=client)
    return qid is not None


def classify(meta: Mapping[str, Any], *, client: HttpGet) -> CreatorOutcome:
    """Return the creator-provenance outcome for a work lacking a creator QID."""
    artist = meta.get("artist")
    artist = artist if isinstance(artist, Mapping) else {}
    canonical = artist.get("canonical")
    name = (
        (canonical.get("display_name") if isinstance(canonical, Mapping) else None)
        or artist.get("name")
        or ""
    ).strip()
    relation = str(artist.get("relation") or "").strip().lower()
    title = str(meta.get("title") or "")

    # 1) Recover a real artist (occupation-gated + conservative repair).
    resolved = _repair_resolve(name, client=client)
    if resolved is not None:
        return resolved

    # 2) Explicit anonymity: an anonymity marker, or a name that is only an
    #    anonymity relation. (An EMPTY name is NOT called anonymous here -- an
    #    absent name is missing data, so it falls through to `unattributable`;
    #    `relation == "unknown"` is likewise ignored, being the old catch-all.)
    if relation == "anonymous" or (name and _ANON_MARKER.search(name)):
        return CreatorOutcome("anonymous", note="Anonymous/unattributed per catalogue.")

    # 3) An era/dynasty or named-culture fragment -> genuine cultural anonymity,
    #    UNLESS the title is a real artist (half-swap) -- then the record is
    #    corrupt, not anonymous. A bare lost year is NOT an era signal and falls
    #    through to `unattributable`.
    era_or_culture = _ERA.search(name) or (_CULTURE.search(name) and not _looks_personal(name))
    if era_or_culture:
        if _title_is_artist(title, client=client):
            return CreatorOutcome(
                "unattributable",
                note=f"Corrupt record: name {name!r} is an era/culture fragment and the "
                f"title {title!r} names an artist (half-swap); creator not safely recoverable.",
            )
        return CreatorOutcome(
            "anonymous",
            note=f"Cultural/era attribution only ({name!r}); no individual maker.",
        )

    # 4) A real personal name that did not resolve -> versioned search ledger.
    if _looks_personal(name):
        return CreatorOutcome(
            "searched",
            note=f"Real personal name {name!r} not resolved at artist-search plan "
            f"v{ARTIST_SEARCH_PLAN_VERSION}.",
        )

    # 5) Everything else: junk / descriptor / filename / single-token fragment.
    return CreatorOutcome(
        "unattributable",
        note=f"Record incomplete: name field {name!r} is not a usable artist name.",
    )
