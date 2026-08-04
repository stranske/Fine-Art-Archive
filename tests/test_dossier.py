"""Tests for viewer-dossier assembly (commerce screening, authority, build)."""

from __future__ import annotations

from typing import Any

from fine_art_archive.enrichment import dossier as d

SIDECAR: dict[str, Any] = {
    "work_id": "abc1234-the-rock-blume",
    "title": "The Rock",
    "year": "1944-1948",
    "medium": "Oil on canvas",
    "category": "painting",
    "artist": {"name": "Peter Blume", "wikidata_q": "Q2990693"},
    "holder": {
        "name": "Art Institute of Chicago",
        "wikidata_q": "Q239303",
        "url": "https://www.artic.edu",
    },
    "stable_identifiers": {"wikidata_q": "Q20268090"},
}


class FakeClient:
    def __init__(
        self,
        *,
        described_url: str | None = "https://www.artic.edu/artworks/1",
        commerce: bool = False,
    ):
        self.described_url = described_url
        self.commerce = commerce

    def wiki_title_for_qid(self, qid: str, wiki: str = "enwiki") -> str | None:
        return {"Q20268090": "The Rock (Blume)", "Q2990693": "Peter Blume"}.get(qid)

    def wiki_summary(self, title: str, lang: str = "en") -> dict[str, Any] | None:
        return {
            "title": title,
            "extract": f"{title} is described here in an encyclopedic lead paragraph.",
            "content_url": f"https://en.wikipedia.org/wiki/{title.replace(' ', '_')}",
        }

    def wikidata_facts(self, qid: str) -> list[dict[str, str]]:
        facts = [{"prop": "P135", "text": "Movement: Magic realism."}]
        if self.described_url:
            facts.insert(0, {"prop": "P973", "text": self.described_url})
        return facts

    def fetch(self, url: str) -> dict[str, Any] | None:
        return {
            "status": "live",
            "text": (
                "Add to cart. Buy this print. $29.99"
                if self.commerce
                else "Object page: The Rock, 1944-48, oil on canvas."
            ),
        }

    def wayback_save(self, url: str) -> str | None:
        return f"https://web.archive.org/web/2024/{url}"


# --- commerce + authority --------------------------------------------------
def test_is_commercial_by_domain() -> None:
    assert d.is_commercial("https://fineartamerica.com/x")
    assert d.is_commercial("https://redbubble.com/shop/x")
    assert not d.is_commercial("https://www.artic.edu/artworks/1")


def test_auction_houses_are_not_commercial() -> None:
    # auction/market scholarship is a deliberate exception: high-value, transient
    assert not d.is_commercial("https://www.christies.com/lot/1", "Estimate $2m. Add to cart.")
    assert not d.is_commercial("https://www.sothebys.com/en/buy/auction/lot")
    assert d.is_transient_source("https://www.christies.com/lot/1")
    assert not d.is_transient_source("https://en.wikipedia.org/wiki/x")


def test_is_commercial_by_signals() -> None:
    assert d.is_commercial("https://blog.example.com", "Add to cart. Buy this poster for $19.")
    assert not d.is_commercial(
        "https://blog.example.com", "An essay about the painting's composition."
    )


def test_authority_ordering() -> None:
    assert d.authority_score("holder_object_page", "https://x.museum/1") > d.authority_score(
        "encyclopedia_work", "https://en.wikipedia.org/x"
    )
    assert d.authority_score("encyclopedia_work", "https://en.wikipedia.org/x") > d.authority_score(
        "encyclopedia_artist", "https://en.wikipedia.org/y"
    )


# --- assembly --------------------------------------------------------------
def test_build_dossier_full() -> None:
    doss = d.build_dossier(SIDECAR, client=FakeClient(), retrieved_at="2026-07-26T00:00:00Z")
    assert doss.viewer_summary and "encyclopedic lead" in doss.viewer_summary
    kinds = [r.kind for r in doss.references]
    assert (
        "holder_object_page" in kinds
        and "encyclopedia_work" in kinds
        and "encyclopedia_artist" in kinds
    )
    # sorted by authority, holder page first
    assert doss.references[0].kind == "holder_object_page"
    # durability: wayback + hash + license tagging
    work_ref = next(r for r in doss.references if r.kind == "encyclopedia_work")
    assert work_ref.wayback_url and work_ref.content_hash
    assert work_ref.license == "CC-BY-SA-4.0" and work_ref.redistributable is True
    holder_ref = next(r for r in doss.references if r.kind == "holder_object_page")
    assert holder_ref.redistributable is False  # restricted museum text
    # key facts include archive facts + the wikidata movement fact
    fact_text = " ".join(f["text"] for f in doss.key_facts)
    assert "Peter Blume" in fact_text and "Magic realism" in fact_text


def test_commercial_holder_page_excluded() -> None:
    doss = d.build_dossier(
        SIDECAR, client=FakeClient(commerce=True), retrieved_at="2026-07-26T00:00:00Z"
    )
    assert "holder_object_page" not in [r.kind for r in doss.references]
    # encyclopedic sources still present
    assert any(r.kind == "encyclopedia_work" for r in doss.references)


def test_no_sources_yields_empty_dossier() -> None:
    class Empty:
        def wiki_title_for_qid(self, qid: str, wiki: str = "enwiki") -> None:
            return None

        def wiki_summary(self, title: str, lang: str = "en") -> None:
            return None

        def wikidata_facts(self, qid: str) -> list:
            return []

        def fetch(self, url: str) -> None:
            return None

        def wayback_save(self, url: str) -> None:
            return None

    doss = d.build_dossier(SIDECAR, client=Empty(), retrieved_at="2026-07-26T00:00:00Z")
    assert doss.viewer_summary is None
    assert doss.references == []
    assert doss.key_facts  # archive-derived facts still present
