"""Detect a title/artist swap in a work that has no work QID.

Some works were ingested with the fields reversed: the ``title`` holds the
*artist's* name and ``artist.name`` holds the real title -- e.g.
``title="George Wesley Bellows"``, ``artist.name="Love of Winter"``. The QID-based
un-swap (:mod:`misresolved_work_qid`) only catches these when a mis-resolved work
QID points at the artist's person entity; a work with no work QID at all slips
through. This detects the same swap from the *title* instead.

The signal is the occupation-gated artist resolver run on the TITLE: if the title
resolves to a real **artist** (a human with a visual-art P106 occupation) it is an
artist name in the title slot, not a work title -- so the fields are swapped. A
title that is a *sitter* ("Rutherford B. Hayes", a politician) or an actual work
title ("The Great Wave") does not resolve to an artist, so it is left alone. This
is the same painter-vs-sitter discrimination the QID-based un-swap uses.

Guards (precision over recall):
  * only when the work has no resolved ``artist.wikidata_q`` / canonical QID;
  * the field being promoted to the title must look like a title (>= 1 real word,
    so a junk date/number is never promoted);
  * **subject-portrait guard** -- if the recovered title mentions the resolved
    person (a >=4-letter name token appears in it), the person is the depicted
    subject, not the maker (a *portrait of* them), so decline;
  * **oeuvre confirmation** -- the recovered title must match a work in the
    resolved artist's Wikidata oeuvre (the guarded by-creator matcher). This
    defeats name ambiguity: "Jan Vermeer" resolves to *Jan Vermeer van Haarlem*,
    but "The Glass of Wine" is not in his oeuvre, so the swap self-rejects rather
    than attaching the wrong same-named painter. The confirmed work's QID is
    captured as a bonus.

Both transports are injected (a ``.get`` JSON client and a ``.query`` SPARQL
client) for offline tests.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from fine_art_archive.enrichment.holder_by_creator import (
    match_work_entity,
    works_by_creator,
    year_of,
)
from fine_art_archive.enrichment.wikidata_identity import fetch_identity
from fine_art_archive.identity.artist_lookup import resolve_artist_qid
from fine_art_archive.identity.artist_resolver import fold_name

_WORD_RE = re.compile(r"[^\W\d_]{3,}")
# An attribution qualifier in the title slot ("Parmigianino (after)", "circle of
# Rembrandt") means the work is a copy/associate, not by that artist -- un-swapping
# would wrongly attribute it as an autograph work, so decline.
_ATTRIBUTION_RE = re.compile(
    r"\b(after|copy|circle|follower|manner|workshop|studio|school|attributed|imitator|"
    r"style)\b",
    re.IGNORECASE,
)


class JsonGetter(Protocol):
    def get(
        self, url: str, *, params: Mapping[str, str] | None = None
    ) -> dict[str, Any] | None: ...


class SparqlQuerier(Protocol):
    def query(self, sparql: str) -> dict[str, Any] | None: ...


@dataclass(frozen=True)
class Swap:
    artist_name: str  # resolved artist display name (was in the title slot)
    artist_qid: str
    lifespan: str | None
    new_title: str  # the real title (was in the artist slot)
    old_title: str  # the artist name that was wrongly in the title slot
    work_qid: str | None  # the confirmed work's QID (oeuvre match), if captured
    method: str
    note: str


def _has_valid_artist_qid(meta: Mapping[str, Any]) -> bool:
    artist = meta.get("artist")
    if not isinstance(artist, Mapping):
        return False
    if isinstance(artist.get("wikidata_q"), str) and artist["wikidata_q"]:
        return True
    canonical = artist.get("canonical")
    return (
        isinstance(canonical, Mapping)
        and isinstance(canonical.get("wikidata_q"), str)
        and bool(canonical["wikidata_q"])
    )


def _mentions_person(display_name: str, text: str) -> bool:
    """True if a distinctive (>=4-letter) name token appears in ``text``."""
    text_folded = fold_name(text)
    tokens = {t for t in fold_name(display_name).split() if len(t) >= 4}
    return any(re.search(rf"\b{re.escape(t)}\b", text_folded) for t in tokens)


def detect_swap(
    meta: Mapping[str, Any], *, json_client: JsonGetter, sparql_client: SparqlQuerier
) -> Swap | None:
    """Return the un-swap for a title/artist-reversed work, or ``None``."""
    if _has_valid_artist_qid(meta):
        return None
    title = str(meta.get("title") or "").strip()
    artist = meta.get("artist")
    artist_field = str(artist.get("name") or "").strip() if isinstance(artist, Mapping) else ""
    if not title or not artist_field:
        return None
    # The artist field becomes the title -> it must look like a real title.
    if not _WORD_RE.search(artist_field):
        return None
    # An attribution qualifier in the title ("... (after)", "circle of ...") means
    # the work is a copy/associate, not autograph -> don't attribute it as one.
    if _ATTRIBUTION_RE.search(title):
        return None
    # The title must resolve to a real ARTIST (occupation-gated) to be a swap.
    qid, method = resolve_artist_qid(title, client=json_client)
    if qid is None:
        return None
    display, lifespan = fetch_identity(qid, client=json_client)
    if not display:
        return None
    # Subject-portrait guard: if the recovered title names the person, they are
    # the depicted subject (a portrait *of* them), not the maker.
    if _mentions_person(display, artist_field):
        return None
    # Oeuvre confirmation: the recovered title must be a work in this artist's
    # Wikidata oeuvre. Defeats same-name ambiguity (wrong Vermeer) and confirms
    # the pair is real; the matched work's QID comes along.
    works = works_by_creator(qid, client=sparql_client)
    matched, _score, _reason = match_work_entity(artist_field, year_of(meta.get("year")), works)
    if matched is None:
        return None
    return Swap(
        artist_name=display,
        artist_qid=qid,
        lifespan=lifespan,
        new_title=artist_field,
        old_title=title,
        work_qid=matched.work_qid,
        method=method or "artist-name-in-title",
        note=(
            f"Un-swapped title/artist (no work QID): title {title!r} is the artist "
            f"{display!r} ({method}); artist field held the title {artist_field!r}; "
            f"confirmed in oeuvre as work {matched.work_qid}."
        ),
    )
