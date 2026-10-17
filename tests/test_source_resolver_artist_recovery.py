"""Museum artist identity must survive missing aliases and failed Getty requests."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from fine_art_archive.enrichment import source_resolver as resolver


def test_museum_artist_direct_qid_needs_no_name_or_lookup(monkeypatch):
    local = Mock(side_effect=AssertionError("direct identity should not search aliases"))
    monkeypatch.setattr(resolver, "resolve_artist", local)
    result = resolver.ArtistQidResolver().resolve({"artist_wikidata_q": "Q123"}, {}, {})
    assert result == ("Q123", "museum record artist link supplied a Wikidata QID")
    local.assert_not_called()


def test_museum_artist_uses_confident_local_alias_before_getty(monkeypatch):
    local = Mock(return_value=SimpleNamespace(q="Q123", confidence=0.85, method="alias"))
    monkeypatch.setattr(resolver, "resolve_artist", local)
    getty = Mock(side_effect=AssertionError("known local artist should not query Getty"))
    monkeypatch.setattr(resolver, "resolve_getty_ids", getty)
    result = resolver.ArtistQidResolver().resolve({}, {"artist_name": "Painter"}, {})
    assert result == ("Q123", "artist alias match (alias)")
    local.assert_called_once_with("Painter", allow_wikidata=False)
    getty.assert_not_called()


@pytest.mark.parametrize("qid", ["Q123", None], ids=["recovered", "absent"])
def test_getty_outage_falls_back_to_named_wikidata_search(monkeypatch, qid):
    monkeypatch.setattr(resolver, "resolve_artist", lambda *_args, **_kw: SimpleNamespace(q=None))
    getty = Mock(side_effect=OSError("Getty unavailable"))
    monkeypatch.setattr(resolver, "resolve_getty_ids", getty)
    wikidata = SimpleNamespace(find_artist=Mock(return_value=(qid, "name search")))
    artist = resolver.ArtistQidResolver(wikidata=wikidata, timeout=0.1)
    result = artist.resolve({}, {}, {"artist": {"name": "Painter"}})
    assert result == ((qid, "name search") if qid else (None, None))
    getty.assert_called_once_with(name="Painter", vocabulary="ulan", timeout=1)
    wikidata.find_artist.assert_called_once_with("Painter", ulan=None)


def test_artist_without_any_name_remains_unresolved_without_search(monkeypatch):
    getty = Mock(side_effect=AssertionError("nameless artist must not search Getty"))
    monkeypatch.setattr(resolver, "resolve_getty_ids", getty)
    wikidata = SimpleNamespace(find_artist=Mock())
    assert resolver.ArtistQidResolver(wikidata=wikidata).resolve({}, {}, {}) == (None, None)
    getty.assert_not_called()
    wikidata.find_artist.assert_not_called()


@pytest.mark.parametrize(
    "local_qid,confidence", [("Q999", 0.84), (None, 0.99)], ids=["low-confidence", "no-qid"]
)
def test_unconfirmed_alias_uses_getty_bridge_and_museum_name(monkeypatch, local_qid, confidence):
    local = Mock(return_value=SimpleNamespace(q=local_qid, confidence=confidence, method="alias"))
    monkeypatch.setattr(resolver, "resolve_artist", local)
    getty = Mock(return_value=SimpleNamespace(ulan="http://vocab.getty.edu/ulan/500123456"))
    monkeypatch.setattr(resolver, "resolve_getty_ids", getty)
    wikidata = SimpleNamespace(find_artist=Mock(return_value=("Q123", "Wikidata P245 match")))

    result = resolver.ArtistQidResolver(wikidata=wikidata, timeout=2.6).resolve(
        {}, {"artist_name": "Museum Painter"}, {"artist": {"name": "Old attribution"}}
    )

    assert result == ("Q123", "Wikidata P245 match via Getty ULAN 500123456")
    local.assert_called_once_with("Museum Painter", allow_wikidata=False)
    getty.assert_called_once_with(name="Museum Painter", vocabulary="ulan", timeout=3)
    wikidata.find_artist.assert_called_once_with("Museum Painter", ulan="500123456")


@pytest.mark.parametrize(
    "getty_result", [None, SimpleNamespace(ulan="invalid")], ids=["absent", "invalid-ulan"]
)
def test_unusable_getty_result_still_searches_museum_creator(monkeypatch, getty_result):
    monkeypatch.setattr(resolver, "resolve_artist", lambda *_args, **_kw: SimpleNamespace(q=None))
    getty = Mock(return_value=getty_result)
    monkeypatch.setattr(resolver, "resolve_getty_ids", getty)
    wikidata = SimpleNamespace(find_artist=Mock(return_value=("Q123", "name search")))

    result = resolver.ArtistQidResolver(wikidata=wikidata).resolve(
        {"creators": [{"name": "Museum Painter"}]}, {}, {}
    )

    assert result == ("Q123", "name search")
    getty.assert_called_once_with(name="Museum Painter", vocabulary="ulan", timeout=15)
    wikidata.find_artist.assert_called_once_with("Museum Painter", ulan=None)


def test_getty_identity_without_wikidata_cannot_supply_a_qid(monkeypatch):
    monkeypatch.setattr(resolver, "resolve_artist", lambda *_args, **_kw: SimpleNamespace(q=None))
    getty = Mock(return_value=SimpleNamespace(ulan="500123456"))
    monkeypatch.setattr(resolver, "resolve_getty_ids", getty)

    result = resolver.ArtistQidResolver().resolve({}, {"artist_name": "Painter"}, {})

    assert result == (None, None)
    getty.assert_called_once_with(name="Painter", vocabulary="ulan", timeout=15)


def test_museum_artist_wikidata_url_supplies_identity_without_search(monkeypatch):
    local = Mock(side_effect=AssertionError("linked artist should not search aliases"))
    getty = Mock(side_effect=AssertionError("linked artist should not query Getty"))
    wikidata = SimpleNamespace(find_artist=Mock())
    monkeypatch.setattr(resolver, "resolve_artist", local)
    monkeypatch.setattr(resolver, "resolve_getty_ids", getty)

    result = resolver.ArtistQidResolver(wikidata=wikidata).resolve(
        {"creator": "Museum Painter (https://www.wikidata.org/wiki/Q123)"}, {}, {}
    )

    assert result == ("Q123", "museum record artist link supplied a Wikidata QID")
    local.assert_not_called()
    getty.assert_not_called()
    wikidata.find_artist.assert_not_called()
