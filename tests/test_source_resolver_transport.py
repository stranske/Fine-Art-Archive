"""Offline regression coverage for enrichment transport recovery and failure bounds."""

import io
import urllib.error

import pytest

from fine_art_archive.enrichment import source_resolver as resolver


@pytest.fixture
def sleeps(monkeypatch):
    delays = []
    monkeypatch.setattr(resolver, "_throttle", lambda: None)
    monkeypatch.setattr(resolver.time, "sleep", delays.append)
    return delays


@pytest.mark.parametrize("status", [429, 503])
@pytest.mark.parametrize("retry_after,delay", [(" 7 ", 7.0), ("120", 30.0), ("invalid", 1.0)])
def test_retry_recovers_same_request(monkeypatch, sleeps, status, retry_after, delay):
    requests = []

    def open_response(request, *, timeout):
        requests.append((request.full_url, timeout, request.get_header("Accept")))
        if len(requests) == 1:
            raise urllib.error.HTTPError(
                request.full_url, status, "busy", {"Retry-After": retry_after}, None
            )
        return io.BytesIO(b'{"title": "Recovered"}')

    monkeypatch.setattr(resolver.urllib.request, "urlopen", open_response)

    result = resolver.JsonClient(timeout=2.5).get(
        "https://example.test/data?format=json", params={"search": "A & B"}
    )

    assert result == {"title": "Recovered"}
    assert (
        requests
        == [("https://example.test/data?format=json&search=A+%26+B", 2.5, "application/json")] * 2
    )
    assert sleeps == [delay]


@pytest.mark.parametrize("status", [429, 503])
def test_retry_exhaustion_is_bounded(monkeypatch, sleeps, status):
    calls = []

    def unavailable(request, *, timeout):
        calls.append(request.full_url)
        raise urllib.error.HTTPError(request.full_url, status, "busy", {}, None)

    monkeypatch.setattr(resolver.urllib.request, "urlopen", unavailable)

    assert resolver.JsonClient().get("https://example.test/data") is None
    assert calls == ["https://example.test/data"] * 4
    assert sleeps == [1.0, 2.0, 4.0]


def test_permanent_http_failure_is_not_retried(monkeypatch, sleeps):
    calls = []

    def missing(request, *, timeout):
        calls.append(request.full_url)
        raise urllib.error.HTTPError(request.full_url, 404, "missing", {}, None)

    monkeypatch.setattr(resolver.urllib.request, "urlopen", missing)

    assert resolver.JsonClient().get("https://example.test/missing") is None
    assert calls == ["https://example.test/missing"]
    assert sleeps == []


@pytest.mark.parametrize("payload", [b"not json", b"\xff", b"[]", b"null"])
def test_invalid_payload_is_unavailable_without_retry(monkeypatch, sleeps, payload):
    calls = []

    def response(request, *, timeout):
        calls.append(request.full_url)
        return io.BytesIO(payload)

    monkeypatch.setattr(resolver.urllib.request, "urlopen", response)

    assert resolver.JsonClient().get("https://example.test/data") is None
    assert calls == ["https://example.test/data"]
    assert sleeps == []
