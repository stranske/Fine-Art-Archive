"""Unit tests for fine_art_archive.known_works.fetchers.

Run with: pytest -q tests/test_known_works_fetchers.py --no-cov
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fine_art_archive.known_works.fetchers import (  # noqa: E402
    KnownWork,
    _http_text,
    _norm_title,
    fetch_met,
    fetch_wikidata_sparql,
    fetch_wikipedia_list,
    merge_works,
    works_to_dicts,
)


class MockResponse:
    def __init__(self, data: bytes):
        self.data = data

    def read(self):
        return self.data

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass


# ---------------------------------------------------------------------------
# HTTP Helpers Tests
# ---------------------------------------------------------------------------
def test_http_text(monkeypatch):
    def mock_urlopen(req, timeout=None):
        return MockResponse(b"Hello World")

    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)
    res = _http_text("https://example.com")
    assert res == "Hello World"


# ---------------------------------------------------------------------------
# Title Normalization Tests
# ---------------------------------------------------------------------------
def test_norm_title():
    assert _norm_title("Mona Lisa!") == "mona lisa"
    assert _norm_title("The Last  Supper") == "the last supper"
    assert _norm_title("") == ""
    assert _norm_title("  La Gioconda; or, Mona Lisa  ") == "la gioconda or mona lisa"
    assert _norm_title(None) == ""


# ---------------------------------------------------------------------------
# Wikidata SPARQL Fetcher Tests
# ---------------------------------------------------------------------------
def test_fetch_wikidata_sparql_success(monkeypatch):
    mock_data = {
        "results": {
            "bindings": [
                {
                    "work": {"value": "http://www.wikidata.org/entity/Q12418"},
                    "workLabel": {"value": "Mona Lisa"},
                    "inception": {"value": "1503-01-01T00:00:00Z"},
                    "image": {
                        "value": "https://upload.wikimedia.org/wikipedia/commons/e/ec/Mona_Lisa.jpg"
                    },
                },
                {
                    "work": {"value": "http://www.wikidata.org/entity/Q191024"},
                    "workLabel": {"value": "The Last Supper"},
                    "inception": {"value": "1495"},
                },
                {
                    "work": {"value": "http://www.wikidata.org/entity/Q999"},
                    "workLabel": {"value": "No Year Work"},
                    "inception": {"value": "circa middle ages"},
                },
                {
                    "work": {"value": "http://www.wikidata.org/entity/Q12345"},
                },
                {
                    "work": {},
                    "workLabel": {"value": "Skipped Work"},
                },
            ]
        }
    }

    called_urls = []

    def mock_urlopen(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else req
        called_urls.append(url)
        return MockResponse(json.dumps(mock_data).encode("utf-8"))

    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)

    results = fetch_wikidata_sparql("Q12418")

    assert len(results) == 4
    mona = next(r for r in results if r.title == "Mona Lisa")
    assert mona.year == 1503
    assert mona.image_url == "https://upload.wikimedia.org/wikipedia/commons/e/ec/Mona_Lisa.jpg"
    assert mona.sources == ["wikidata"]
    assert mona.source_ids == {"wikidata": "Q12418"}

    supper = next(r for r in results if r.title == "The Last Supper")
    assert supper.year == 1495
    assert supper.image_url is None

    no_year = next(r for r in results if r.title == "No Year Work")
    assert no_year.year is None

    anonymous = next(r for r in results if r.source_ids.get("wikidata") == "Q12345")
    assert anonymous.title == ""
    assert anonymous.year is None

    assert len(called_urls) == 1
    assert "wikidata.org" in called_urls[0]


def test_fetch_wikidata_sparql_request_failure(monkeypatch):
    def mock_urlopen_fail(req, timeout=None):
        raise urllib.error.URLError("Connection refused")

    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen_fail)

    assert fetch_wikidata_sparql("Q12418") == []


def test_fetch_wikidata_sparql_parse_failure(monkeypatch):
    def mock_urlopen_bad_json(req, timeout=None):
        return MockResponse(b"invalid json")

    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen_bad_json)

    assert fetch_wikidata_sparql("Q12418") == []


# ---------------------------------------------------------------------------
# Wikipedia List Fetcher Tests
# ---------------------------------------------------------------------------
MOCK_WIKITEXT = """
{| class="wikitable"
|-
| [[File:Mona_Lisa.jpg|thumb|100px]]
| ''[[Mona Lisa]]''
| 1503
|-
| ''[[Mona Lisa|La Gioconda]]''
| 1503
|-
| ''The Last Supper''
| 1495-1498
|-
| ''The Baptism of Christ''
| no date here
|-
| ''""" + ("A" * 201) + """''
| no date here
|-
| [[Lady with an Ermine (painting)|Lady with an Ermine]]
|-
| [[Lady with an Ermine (painting)|Lady with an Ermine]]
|-
| [[Ginevra de' Benci (Leonardo)|Ginevra de' Benci]]
|-
| [[""" + ("B" * 201) + """ (Leonardo)|""" + ("B" * 201) + """]]
|}
"""


def test_fetch_wikipedia_list_success(monkeypatch):
    called_urls = []

    def mock_urlopen(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else req
        called_urls.append(url)
        if "action=query" in url:
            resp = {
                "query": {
                    "search": [
                        {"title": "Vinci's life"},
                        {"title": "List of paintings by Leonardo da Vinci"},
                    ]
                }
            }
            return MockResponse(json.dumps(resp).encode("utf-8"))
        if "action=parse" in url:
            resp = {"parse": {"wikitext": {"*": MOCK_WIKITEXT}}}
            return MockResponse(json.dumps(resp).encode("utf-8"))
        return MockResponse(b"{}")

    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)

    results = fetch_wikipedia_list("Leonardo da Vinci")

    assert len(results) == 5
    mona = next(r for r in results if r.title == "Mona Lisa")
    assert mona.year == 1503
    assert mona.sources == ["wikipedia"]
    assert mona.source_ids == {"wikipedia": "List of paintings by Leonardo da Vinci"}

    supper = next(r for r in results if r.title == "The Last Supper")
    assert supper.year == 1495

    baptism = next(r for r in results if r.title == "The Baptism of Christ")
    assert baptism.year is None

    lady = next(r for r in results if r.title == "Lady with an Ermine")
    assert lady.year is None

    ginevra = next(r for r in results if r.title == "Ginevra de' Benci")
    assert ginevra.year is None

    assert len(called_urls) == 2


def test_fetch_wikipedia_list_search_failure(monkeypatch):
    def mock_urlopen(req, timeout=None):
        raise urllib.error.URLError("Search offline")

    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)

    assert fetch_wikipedia_list("Leonardo da Vinci") == []


def test_fetch_wikipedia_list_no_article_found(monkeypatch):
    def mock_urlopen(req, timeout=None):
        return MockResponse(json.dumps({"query": {"search": []}}).encode("utf-8"))

    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)

    assert fetch_wikipedia_list("Leonardo da Vinci") == []


def test_fetch_wikipedia_list_parse_failure(monkeypatch):
    def mock_urlopen(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else req
        if "action=query" in url:
            resp = {"query": {"search": [{"title": "List of paintings by Leonardo da Vinci"}]}}
            return MockResponse(json.dumps(resp).encode("utf-8"))
        raise urllib.error.URLError("Parse offline")

    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)

    assert fetch_wikipedia_list("Leonardo da Vinci") == []


def test_fetch_wikipedia_list_empty_wikitext(monkeypatch):
    def mock_urlopen(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else req
        if "action=query" in url:
            resp = {"query": {"search": [{"title": "List of paintings by Leonardo da Vinci"}]}}
            return MockResponse(json.dumps(resp).encode("utf-8"))
        resp = {"parse": {"wikitext": {"*": ""}}}
        return MockResponse(json.dumps(resp).encode("utf-8"))

    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)

    assert fetch_wikipedia_list("Leonardo da Vinci") == []


# ---------------------------------------------------------------------------
# Met Fetcher Tests
# ---------------------------------------------------------------------------
def test_fetch_met(monkeypatch):
    sleep_calls = []

    def mock_sleep(seconds):
        sleep_calls.append(seconds)

    monkeypatch.setattr(time, "sleep", mock_sleep)

    def mock_urlopen(req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else req

        if "public/collection/v1/search" in url:
            return MockResponse(json.dumps({"objectIDs": [101, 102, 103, 104, 105, 106, 107, 108]}).encode("utf-8"))

        if "public/collection/v1/objects/101" in url:
            return MockResponse(
                json.dumps(
                    {
                        "artistDisplayName": "Leonardo da Vinci",
                        "title": "Mona Lisa",
                        "objectBeginDate": 1503,
                        "primaryImage": "https://example.com/mona.jpg",
                    }
                ).encode("utf-8")
            )

        if "public/collection/v1/objects/102" in url:
            return MockResponse(
                json.dumps(
                    {
                        "artistDisplayName": "School of Leonardo da Vinci",
                        "title": "Study of a Hand",
                        "objectDate": "ca. 1490",
                        "primaryImage": "",
                    }
                ).encode("utf-8")
            )

        if "public/collection/v1/objects/103" in url:
            return MockResponse(
                json.dumps(
                    {
                        "artistDisplayName": "Michelangelo",
                        "title": "David",
                        "objectBeginDate": 1501,
                    }
                ).encode("utf-8")
            )

        if "public/collection/v1/objects/104" in url:
            raise urllib.error.URLError("Object not found")

        if "public/collection/v1/objects/105" in url:
            return MockResponse(
                json.dumps(
                    {
                        "artistDisplayName": "Leonardo da Vinci",
                        "title": "",
                        "objectBeginDate": 1503,
                    }
                ).encode("utf-8")
            )

        if "public/collection/v1/objects/106" in url:
            return MockResponse(
                json.dumps(
                    {
                        "artistDisplayName": "Leonardo da Vinci",
                        "title": "Mona Lisa",
                        "objectBeginDate": 1503,
                    }
                ).encode("utf-8")
            )

        if "public/collection/v1/objects/107" in url:
            return MockResponse(
                json.dumps(
                    {
                        "artistDisplayName": "Leonardo da Vinci",
                        "title": "No Date Work",
                        "objectDate": "unknown date",
                    }
                ).encode("utf-8")
            )

        if "public/collection/v1/objects/108" in url:
            return MockResponse(
                json.dumps(
                    {
                        "artistDisplayName": "Leonardo da Vinci",
                        "title": "Ancient Work",
                        "objectBeginDate": -100,
                    }
                ).encode("utf-8")
            )

        return MockResponse(b"{}")

    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)

    results = fetch_met("Leonardo da Vinci", max_objects=10)

    assert len(results) == 4
    mona = next(r for r in results if r.title == "Mona Lisa")
    assert mona.year == 1503
    assert mona.image_url == "https://example.com/mona.jpg"
    assert mona.holder == "The Metropolitan Museum of Art"
    assert mona.sources == ["met"]
    assert mona.source_ids == {"met": "101"}

    hand = next(r for r in results if r.title == "Study of a Hand")
    assert hand.year == 1490
    assert hand.image_url is None

    no_date = next(r for r in results if r.title == "No Date Work")
    assert no_date.year is None

    ancient = next(r for r in results if r.title == "Ancient Work")
    assert ancient.year is None

    assert len(sleep_calls) == 4
    assert all(s == 0.1 for s in sleep_calls)


def test_fetch_met_search_failure(monkeypatch):
    def mock_urlopen(req, timeout=None):
        raise urllib.error.URLError("Met offline")

    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)

    assert fetch_met("Leonardo da Vinci") == []


def test_fetch_met_no_results(monkeypatch):
    def mock_urlopen(req, timeout=None):
        return MockResponse(json.dumps({"objectIDs": None}).encode("utf-8"))

    monkeypatch.setattr(urllib.request, "urlopen", mock_urlopen)

    assert fetch_met("Leonardo da Vinci") == []


# ---------------------------------------------------------------------------
# Merger Tests
# ---------------------------------------------------------------------------
def test_merge_works():
    w1 = KnownWork(title="Mona Lisa", year=1503, sources=["wikidata"], source_ids={"wikidata": "Q12418"})
    w2 = KnownWork(
        title="Mona Lisa",
        year=1505,
        sources=["wikipedia"],
        source_ids={"wikipedia": "List of paintings"},
    )
    w3 = KnownWork(title="Self Portrait", year=1500, sources=["met"])
    w4 = KnownWork(title="Self Portrait", year=1510, sources=["wikipedia"])
    w5 = KnownWork(title="Virgin of the Rocks", year=None, sources=["wikipedia"])
    w6 = KnownWork(title="Virgin of the Rocks", year=1483, sources=["met"])
    w_empty = KnownWork(title="", year=1400)

    merged = merge_works([w1, w3, w5, w_empty], [w2, w4, w6])

    assert len(merged) == 4
    assert merged[0].title == "Virgin of the Rocks"
    assert merged[0].year == 1483
    assert merged[0].sources == ["wikipedia", "met"]

    assert merged[1].title == "Self Portrait"
    assert merged[1].year == 1500

    assert merged[2].title == "Mona Lisa"
    assert merged[2].year == 1503
    assert merged[2].sources == ["wikidata", "wikipedia"]

    assert merged[3].title == "Self Portrait"
    assert merged[3].year == 1510


def test_merge_metadata():
    w1 = KnownWork(title="Mona Lisa", year=1503, sources=["wikidata"])
    w2 = KnownWork(
        title="Mona Lisa",
        year=1503,
        sources=["wikipedia"],
        image_url="https://example.com/mona.jpg",
        holder="Louvre",
    )

    merged = merge_works([w1], [w2])
    assert len(merged) == 1
    assert merged[0].image_url == "https://example.com/mona.jpg"
    assert merged[0].holder == "Louvre"


def test_merge_existing_source():
    w1 = KnownWork(title="Mona Lisa", year=1503, sources=["met"])
    w2 = KnownWork(title="Mona Lisa", year=1503, sources=["met"])
    merged = merge_works([w1], [w2])
    assert len(merged) == 1
    assert merged[0].sources == ["met"]


# ---------------------------------------------------------------------------
# Works to Dicts Tests
# ---------------------------------------------------------------------------
def test_works_to_dicts():
    works = [
        KnownWork(
            title="Mona Lisa",
            year=1503,
            image_url="http://...",
            holder="Louvre",
            sources=["wikidata"],
            source_ids={"wikidata": "Q12418"},
        )
    ]
    dicts = works_to_dicts(works)
    assert len(dicts) == 1
    assert dicts[0] == {
        "title": "Mona Lisa",
        "year": 1503,
        "image_url": "http://...",
        "holder": "Louvre",
        "sources": ["wikidata"],
        "source_ids": {"wikidata": "Q12418"},
    }
