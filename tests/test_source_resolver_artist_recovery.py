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
