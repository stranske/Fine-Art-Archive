from __future__ import annotations

import json
import urllib.error
from pathlib import Path
from typing import Any

import pytest

from fine_art_archive.collect import discovery


def _entity(*claims: tuple[str, Any]) -> dict[str, Any]:
    return {
        "claims": {
            property_id: [
                {
                    "mainsnak": {
                        "snaktype": "value",
                        "datavalue": {"value": value},
                    }
                }
            ]
            for property_id, value in claims
        }
    }


def test_discover_candidates_resolves_and_ranks_without_shell() -> None:
    entity = _entity(
        ("P18", "Example.jpg"),
        ("P3634", "123"),
        ("P350", "SK-C-5"),
        ("P5253", "nga-7"),
        ("P9173", "artic-9"),
        ("P9092", "cleveland-11"),
        ("P973", "https://example.org/catalogue"),
        ("P6611", "smithsonian-1"),
    )

    def fake_json(url: str) -> dict[str, Any]:
        if "Special:EntityData" in url:
            return {"entities": {"Q1": entity}}
        if "commons.wikimedia.org" in url:
            return {
                "query": {
                    "pages": {
                        "1": {
                            "imageinfo": [
                                {
                                    "url": "https://commons.example/image.jpg",
                                    "width": 1000,
                                    "height": 500,
                                    "size": 12345,
                                    "mime": "image/jpeg",
                                }
                            ]
                        }
                    }
                }
            }
        if "collectionapi.metmuseum.org" in url:
            return {"isPublicDomain": True, "primaryImage": "https://met.example/image.jpg"}
        if "iiif.micr.io" in url:
            return {"width": 2000, "height": 1000}
        if "api.artic.edu" in url:
            return {"data": {"image_id": "abc123"}}
        if "artic.edu/iiif" in url:
            return {"width": 800, "height": 400}
        if "openaccess-api.clevelandart.org" in url:
            return {"data": {"images": {"web": {"url": "https://cleveland.example/image.jpg"}}}}
        raise AssertionError(f"unexpected URL {url}")

    def fake_text(url: str) -> str:
        assert url == "https://www.rijksmuseum.nl/en/collection/SK-C-5"
        return '<meta property="og:image" content="https://iiif.micr.io/Rijks123/full/200,/0/default.jpg">'

    result = discovery.discover_candidates(
        "Q1",
        get_json=fake_json,
        get_text=fake_text,
        head_size=lambda url: 999 if url == "https://met.example/image.jpg" else None,
    )

    assert result["qid"] == "Q1"
    sources = [candidate["source"] for candidate in result["candidates"]]
    assert sources[:2] == ["rijksmuseum", "wikimedia_commons"]
    assert sources == [
        "rijksmuseum",
        "wikimedia_commons",
        "artic",
        "met",
        "nga",
        "cleveland",
        "smithsonian",
        "described_at_url",
    ]
    met = next(candidate for candidate in result["candidates"] if candidate["source"] == "met")
    assert met["size_bytes"] == 999
    described = next(
        candidate for candidate in result["candidates"] if candidate["source"] == "described_at_url"
    )
    assert described["url"] == "https://example.org/catalogue"
    smithsonian = next(
        candidate for candidate in result["candidates"] if candidate["source"] == "smithsonian"
    )
    assert smithsonian["evidence"].endswith("; resolver TBD")


def test_discover_candidates_records_commons_without_image_url_as_error() -> None:
    entity = _entity(("P18", "Missing-url.jpg"))

    def fake_json(url: str) -> dict[str, Any]:
        if "Special:EntityData" in url:
            return {"entities": {"Q1": entity}}
        if "commons.wikimedia.org" in url:
            return {"query": {"pages": {"1": {"imageinfo": [{"width": 100}]}}}}
        raise AssertionError(f"unexpected URL {url}")

    result = discovery.discover_candidates("Q1", get_json=fake_json)

    assert result["candidates"] == [
        {
            "source": "wikimedia_commons",
            "error": "Commons image URL missing",
            "evidence": "P18 -> File:Missing-url.jpg",
        }
    ]


def test_discover_candidates_records_source_errors_without_aborting() -> None:
    entity = _entity(("P18", "Broken.jpg"), ("P5253", "nga-7"))

    def fake_json(url: str) -> dict[str, Any]:
        if "Special:EntityData" in url:
            return {"entities": {"Q1": entity}}
        raise discovery.DiscoveryFetchError("network unavailable")

    result = discovery.discover_candidates("Q1", get_json=fake_json)

    assert result["candidates"] == [
        {
            "source": "nga",
            "tier": 1,
            "url": None,
            "evidence": "Wikidata P5253 -> NGA nga-7; resolver TBD",
        },
        {
            "source": "wikimedia_commons",
            "error": "network unavailable",
            "evidence": "P18 -> File:Broken.jpg",
        },
    ]


def test_write_discovery_output_writes_payload(tmp_path: Path, monkeypatch) -> None:
    payload = {"qid": "Q1", "candidates": [{"source": "nga"}]}
    monkeypatch.setattr(discovery, "discover_candidates", lambda qid: payload)

    out_path = tmp_path / "nested" / "discovery.json"
    assert discovery.write_discovery_output("Q1", str(out_path)) == payload
    assert json.loads(out_path.read_text()) == payload


def test_write_discovery_output_handles_basename_path(tmp_path: Path, monkeypatch) -> None:
    payload = {"qid": "Q1", "candidates": [{"source": "nga"}]}
    monkeypatch.setattr(discovery, "discover_candidates", lambda qid: payload)
    monkeypatch.chdir(tmp_path)

    assert discovery.write_discovery_output("Q1", "discovery.json") == payload
    assert json.loads((tmp_path / "discovery.json").read_text()) == payload


def test_discovery_shell_script_is_thin_module_wrapper() -> None:
    script = discovery.discovery_shell_script("Q12418", "/tmp/discovery.json")
    src_root = Path(discovery.__file__).resolve().parents[2]
    assert f"export PYTHONPATH={src_root}" in script
    assert "python3 -m fine_art_archive.collect.discovery Q12418 /tmp/discovery.json" in script
    assert "urllib.request" not in script
    assert "except Exception" not in script


class _Response:
    def __init__(self, body: bytes, headers: dict[str, str] | None = None) -> None:
        self.body = body
        self.headers = headers or {}

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read(self) -> bytes:
        return self.body


def test_transport_helpers_normalize_payloads_and_upstream_failures(monkeypatch) -> None:
    responses = iter(
        [
            _Response(b'{"ok": true}'),
            _Response(b"plain text"),
            _Response(b"", {"Content-Length": "123"}),
            _Response(b"", {"Content-Length": "not-a-number"}),
        ]
    )
    monkeypatch.setattr(
        discovery.urllib.request, "urlopen", lambda *_args, **_kwargs: next(responses)
    )

    assert discovery._get_json("https://example.test/json") == {"ok": True}
    assert discovery._get_text("https://example.test/text") == "plain text"
    assert discovery._head_size("https://example.test/image") == 123
    assert discovery._head_size("https://example.test/bad-size") is None

    monkeypatch.setattr(
        discovery.urllib.request,
        "urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(urllib.error.URLError("offline")),
    )
    with pytest.raises(discovery.DiscoveryFetchError, match="offline"):
        discovery._get_json("https://example.test/fails")
    with pytest.raises(discovery.DiscoveryFetchError, match="offline"):
        discovery._get_text("https://example.test/fails")
    assert discovery._head_size("https://example.test/fails") is None


def test_claim_values_skips_malformed_claims_and_retains_scalar_amount_and_id() -> None:
    assert discovery.claim_values({"claims": []}, "P1") == []
    entity = {
        "claims": {
            "P1": [
                None,
                {"mainsnak": {"snaktype": "novalue"}},
                {"mainsnak": {"snaktype": "value", "datavalue": {"value": {"id": "Q2"}}}},
                {"mainsnak": {"snaktype": "value", "datavalue": {"value": {"amount": "+3"}}}},
                {"mainsnak": {"snaktype": "value", "datavalue": {"value": "plain"}}},
            ]
        }
    }
    assert discovery.claim_values(entity, "P1") == ["Q2", "+3", "plain"]


def test_resolvers_keep_partial_discovery_when_optional_metadata_is_missing_or_broken() -> None:
    entity = _entity(
        ("P18", "bad-page.jpg"),
        ("P3634", "met-1"),
        ("P350", "r-1"),
        ("P9173", "a-1"),
        ("P9092", "c-1"),
    )

    def fake_json(url: str) -> dict[str, Any]:
        if "commons.wikimedia.org" in url:
            return {"query": {"pages": {"1": "not-a-page"}}}
        if "collectionapi.metmuseum.org" in url:
            return {"isPublicDomain": False, "primaryImage": "https://met.test/unused"}
        if "api.artic.edu" in url:
            return {"data": {"image_id": "artic-image"}}
        if "artic.edu/iiif" in url:
            raise discovery.DiscoveryFetchError("no info.json")
        if "clevelandart.org" in url:
            raise discovery.DiscoveryFetchError("unavailable")
        raise AssertionError(url)

    candidates = discovery.discover_candidates(
        "Q1",
        get_json=lambda url: (
            {"entities": {"Q1": entity}} if "EntityData" in url else fake_json(url)
        ),
        get_text=lambda _url: "<html>no og image</html>",
    )["candidates"]

    assert {candidate["source"] for candidate in candidates} == {
        "wikimedia_commons",
        "artic",
        "cleveland",
    }
    artic = next(candidate for candidate in candidates if candidate["source"] == "artic")
    assert artic["width"] is None and artic["height"] is None
    assert (
        next(candidate for candidate in candidates if candidate["source"] == "cleveland")["error"]
        == "unavailable"
    )


def test_discovery_main_writes_output_and_prints_a_bounded_preview(monkeypatch, capsys) -> None:
    payload = {"qid": "Q5", "candidates": [{"source": "x", "note": "z" * 5000}]}
    seen: list[tuple[str, str]] = []
    monkeypatch.setattr(
        discovery,
        "write_discovery_output",
        lambda qid, output: seen.append((qid, output)) or payload,
    )

    assert discovery.main(["Q5", "out.json"]) == 0
    assert seen == [("Q5", "out.json")]
    assert len(capsys.readouterr().out) <= 4001
