"""Wikidata transport and entity-contract coverage for holder enrichment."""

from __future__ import annotations

import json
import urllib.error
from typing import Any

import pytest

from fine_art_archive.enrichment import holder


class _Response:
    def __init__(self, body: bytes) -> None:
        self.body = body

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self) -> bytes:
        return self.body


def _claim(value: Any) -> dict[str, Any]:
    return {"mainsnak": {"datavalue": {"value": value}}}


def test_lookup_holder_reads_work_and_collection_entities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The work's holder QID must lead to the collection's identity fields."""
    client = holder.WikidataClient(timeout=4.5)
    calls: list[dict[str, str]] = []
    payloads = {
        "Q123": {
            "entities": {
                "Q123": {
                    "claims": {
                        "P195": [_claim({"id": "Q456"})],
                        "P217": [_claim("  1969.332  ")],
                        "P6108": [_claim("  https://iiif.example/manifest.json  ")],
                    }
                }
            }
        },
        "Q456": {
            "entities": {
                "Q456": {
                    "labels": {"en": {"value": "  Example Museum  "}},
                    "claims": {
                        "P6782": [_claim("https://ror.org/03vek6s52")],
                        "P856": [_claim("  https://museum.example/  ")],
                    },
                }
            }
        },
    }

    def request_json(params: dict[str, str]) -> dict[str, Any]:
        calls.append(params)
        return payloads[params["ids"]]

    monkeypatch.setattr(client, "_request_json", request_json)

    assert client.lookup_holder("not-a-qid") is None
    assert calls == []

    result = client.lookup_holder("Q123")

    assert result == holder.HolderLookup(
        work_qid="Q123",
        collection_qid="Q456",
        collection_name="Example Museum",
        ror="03vek6s52",
        url="https://museum.example/",
        accession="1969.332",
        iiif_manifest_url="https://iiif.example/manifest.json",
    )
    assert [(call["ids"], call["props"]) for call in calls] == [
        ("Q123", "claims"),
        ("Q456", "claims|labels"),
    ]


def test_request_json_retries_503_then_returns_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A transient Wikidata outage should honour Retry-After and then recover."""
    outcomes: list[BaseException | _Response] = [
        urllib.error.HTTPError(
            "https://www.wikidata.org/w/api.php",
            503,
            "Service Unavailable",
            {"Retry-After": "2"},
            None,
        ),
        _Response(json.dumps({"entities": {}}).encode()),
    ]
    requests: list[tuple[str, float]] = []
    sleeps: list[float] = []

    def urlopen(request: Any, *, timeout: float) -> _Response:
        requests.append((request.full_url, timeout))
        outcome = outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    monkeypatch.setattr(holder, "_throttle", lambda: None)
    monkeypatch.setattr(holder.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(holder.time, "sleep", sleeps.append)

    result = holder.WikidataClient(timeout=4.5)._request_json(
        {"action": "wbgetentities", "ids": "Q123"}
    )

    assert result == {"entities": {}}
    assert len(requests) == 2
    assert all(timeout == 4.5 for _, timeout in requests)
    assert all("action=wbgetentities" in url and "ids=Q123" in url for url, _ in requests)
    assert sleeps == [2.0]


def test_request_json_treats_invalid_utf8_as_an_unusable_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bad upstream bytes are a skipped source, not a fatal enrichment pass."""
    monkeypatch.setattr(holder, "_throttle", lambda: None)
    monkeypatch.setattr(
        holder.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: _Response(b"\xff"),
    )

    result = holder.WikidataClient()._request_json({"action": "wbgetentities", "ids": "Q123"})

    assert result is None
