from __future__ import annotations

import json
from pathlib import Path
from typing import Any

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
    ]
    met = next(candidate for candidate in result["candidates"] if candidate["source"] == "met")
    assert met["size_bytes"] == 999


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


def test_discovery_shell_script_is_thin_module_wrapper() -> None:
    script = discovery.discovery_shell_script("Q12418", "/tmp/discovery.json")
    assert "python3 -m fine_art_archive.collect.discovery Q12418 /tmp/discovery.json" in script
    assert "urllib.request" not in script
    assert "except Exception" not in script
