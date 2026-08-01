"""Build a viewer-facing *dossier* for a work: a plain-language summary, attributed
key facts, and ranked, durable source references.

Design (see Code/Audits/Fine-Art-Archive/2026-07-26-VIEWER-CONTEXT-STRATEGY.md):
  * Sources are discovered holder-first, then open encyclopedic (Wikipedia work +
    artist, via the work/artist Wikidata sitelinks).
  * Every candidate is scored for authority and screened for **commerce** -- a
    source whose purpose is selling prints/reproductions/auctions is never cited,
    detected by a domain blocklist plus on-page buy signals.
  * Durability: each accepted reference stores the live URL, a Wayback snapshot,
    a content hash, and (for the summary source) the fetched text locally, tagged
    with ``license`` + ``redistributable`` so the viewer text survives link rot.

The HTTP/SPARQL access is injected via a :class:`FetchClient` so the assembly
logic is pure and testable; the real client lives in ``scripts/build_dossiers.py``.

For this first slice the ``viewer_summary`` is the Wikipedia lead extract
(attributed, CC-BY-SA); a later phase can replace it with an LLM synthesis.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

# --- commerce screening ----------------------------------------------------
# Domains whose purpose is selling products alongside (or instead of) information.
COMMERCE_DOMAINS = frozenset({
    "fineartamerica.com", "art.com", "allposters.com", "poster.com",
    "redbubble.com", "etsy.com", "amazon.", "ebay.", "zazzle.com",
    "saatchiart.com", "artsy.net", "artnet.com", "invaluable.com",
    "christies.com", "sothebys.com", "bonhams.com", "phillips.com",
    "shutterstock.com", "gettyimages.", "alamy.com", "istockphoto.com",
    "1stdibs.com", "artfinder.com", "society6.com", "canvasprints",
    "printful.com", "displate.com", "wall-art", "posterlounge.",
})
_COMMERCE_SIGNALS = re.compile(
    r"add to (cart|basket|bag)|buy (this |a )?(print|poster|canvas)|shopping cart|"
    r"checkout|framed print|canvas print|\bshop now\b|add to wishlist|"
    r"price[:\s]*[$£€]|starting at [$£€]|our price",
    re.IGNORECASE,
)


def domain_of(url: str) -> str:
    m = re.match(r"https?://([^/]+)/?", url or "")
    return (m.group(1).lower() if m else "").removeprefix("www.")


def is_commercial(url: str, text: str | None = None) -> bool:
    dom = domain_of(url)
    if any(bad in dom for bad in COMMERCE_DOMAINS):
        return True
    return bool(text and len(_COMMERCE_SIGNALS.findall(text)) >= 2)


# --- authority ranking -----------------------------------------------------
_AUTHORITY = {
    "holder_object_page": 5.0,
    "encyclopedia_work": 4.0,
    "encyclopedia_artist": 3.5,
    "scholarly": 4.0,
    "reference": 3.0,
}


def authority_score(kind: str, url: str) -> float:
    base = _AUTHORITY.get(kind, 2.0)
    dom = domain_of(url)
    if dom.endswith(".edu") or dom.endswith(".gov"):
        base += 0.5
    if kind == "holder_object_page" and any(m in dom for m in (".museum", "gallery", "museum")):
        base += 0.25
    return round(base, 2)


# --- data model ------------------------------------------------------------
@dataclass
class Reference:
    id: str
    kind: str
    title: str | None
    publisher: str | None
    license: str | None
    redistributable: bool | None
    live_url: str | None
    wayback_url: str | None = None
    retrieved_at: str | None = None
    content_hash: str | None = None
    authority_score: float | None = None
    commerce_flag: bool | None = None
    excerpt: str | None = None
    local_snapshot_path: str | None = None
    snapshot_text: str | None = None  # in-memory; the CLI writes it to disk
    status: str | None = "live"

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id, "kind": self.kind, "title": self.title,
            "publisher": self.publisher, "license": self.license,
            "redistributable": self.redistributable, "live_url": self.live_url,
            "wayback_url": self.wayback_url, "retrieved_at": self.retrieved_at,
            "content_hash": self.content_hash, "authority_score": self.authority_score,
            "commerce_flag": self.commerce_flag, "excerpt": self.excerpt,
            "local_snapshot_path": self.local_snapshot_path, "status": self.status,
        }


@dataclass
class Dossier:
    viewer_summary: str | None = None
    key_facts: list[dict[str, str | None]] = field(default_factory=list)
    references: list[Reference] = field(default_factory=list)
    generated_at: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "viewer_summary": self.viewer_summary,
            "key_facts": self.key_facts,
            "references": [r.to_json() for r in self.references],
            "generated_at": self.generated_at,
        }


class FetchClient(Protocol):
    def wiki_title_for_qid(self, qid: str, wiki: str = "enwiki") -> str | None: ...
    def wiki_summary(self, title: str, lang: str = "en") -> dict[str, Any] | None: ...
    def wikidata_facts(self, qid: str) -> list[dict[str, str]]: ...
    def fetch(self, url: str) -> dict[str, Any] | None: ...
    def wayback_save(self, url: str) -> str | None: ...


# --- helpers ---------------------------------------------------------------
def _hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _artist_qid(sidecar: dict[str, Any]) -> str | None:
    a = sidecar.get("artist")
    return a.get("wikidata_q") if isinstance(a, dict) else None


def _work_qid(sidecar: dict[str, Any]) -> str | None:
    s = sidecar.get("stable_identifiers")
    return s.get("wikidata_q") if isinstance(s, dict) else None


def _sidecar_facts(sidecar: dict[str, Any]) -> list[dict[str, str | None]]:
    facts: list[dict[str, str | None]] = []
    artist = sidecar.get("artist") or {}
    if artist.get("name"):
        facts.append({"text": f"Artist: {artist['name']}.", "source_id": "archive"})
    if sidecar.get("year"):
        facts.append({"text": f"Dated {sidecar['year']}.", "source_id": "archive"})
    if sidecar.get("medium"):
        facts.append({"text": f"Medium: {sidecar['medium']}.", "source_id": "archive"})
    holder = sidecar.get("holder") or {}
    if holder.get("name"):
        where = "On view / held at" if holder.get("wikidata_q") else "Held at"
        facts.append({"text": f"{where} {holder['name']}.", "source_id": "wikidata"})
    return facts


def build_dossier(
    sidecar: dict[str, Any], *, client: FetchClient, retrieved_at: str
) -> Dossier:
    """Assemble a dossier for one work. Network access is via ``client``."""
    dossier = Dossier(generated_at=retrieved_at)
    dossier.key_facts = _sidecar_facts(sidecar)

    seen_urls: set[str] = set()

    def add_reference(kind: str, url: str | None, *, title: str | None,
                      publisher: str | None, license_: str | None,
                      redistributable: bool, text: str | None) -> None:
        if not url or url in seen_urls:
            return
        seen_urls.add(url)
        if is_commercial(url, text):
            return  # never cite a sales-driven source
        ref = Reference(
            id=f"{kind}:{domain_of(url)}",
            kind=kind, title=title, publisher=publisher, license=license_,
            redistributable=redistributable, live_url=url, retrieved_at=retrieved_at,
            authority_score=authority_score(kind, url), commerce_flag=False,
        )
        if text:
            ref.snapshot_text = text
            ref.content_hash = _hash(text)
            ref.excerpt = text[:280].strip()
        ref.wayback_url = client.wayback_save(url)
        dossier.references.append(ref)

    wqid, aqid = _work_qid(sidecar), _artist_qid(sidecar)

    # 1. holder object page (work's P973 "described at URL"), holder-as-hub
    facts_extra: list[dict[str, str]] = client.wikidata_facts(wqid) if wqid else []
    described_url = next((f["text"] for f in facts_extra if f.get("prop") == "P973"), None)
    if described_url:
        page = client.fetch(described_url)
        add_reference(
            "holder_object_page", described_url,
            title=(sidecar.get("holder") or {}).get("name"),
            publisher=(sidecar.get("holder") or {}).get("name"),
            license_="restricted", redistributable=False,
            text=(page or {}).get("text"),
        )
    for f in facts_extra:
        if f.get("prop") != "P973" and f.get("text"):
            dossier.key_facts.append({"text": f["text"], "source_id": "wikidata"})

    # 2. Wikipedia article for the work
    work_title = client.wiki_title_for_qid(wqid) if wqid else None
    if work_title:
        summary = client.wiki_summary(work_title)
        if summary:
            add_reference(
                "encyclopedia_work", summary.get("content_url"),
                title=summary.get("title"), publisher="Wikipedia",
                license_="CC-BY-SA-4.0", redistributable=True,
                text=summary.get("extract"),
            )
            if summary.get("extract") and not dossier.viewer_summary:
                dossier.viewer_summary = summary["extract"].strip()

    # 3. Wikipedia article for the artist (context)
    artist_title = client.wiki_title_for_qid(aqid) if aqid else None
    if artist_title:
        summary = client.wiki_summary(artist_title)
        if summary:
            add_reference(
                "encyclopedia_artist", summary.get("content_url"),
                title=summary.get("title"), publisher="Wikipedia",
                license_="CC-BY-SA-4.0", redistributable=True,
                text=summary.get("extract"),
            )
            if not dossier.viewer_summary and summary.get("extract"):
                dossier.viewer_summary = summary["extract"].strip()

    dossier.references.sort(key=lambda r: -(r.authority_score or 0))
    return dossier
