from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fine_art_archive.identity.getty import enrich_sidecar_getty  # noqa: E402


class _Response:
    def __init__(self, payload: dict[str, Any]):
        self._payload = payload

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def read(self) -> bytes:
        return json.dumps(self._payload).encode()


def _minimal_meta() -> dict[str, Any]:
    return {
        "work_id": "4f3a2b8-after-the-bullfight-cassatt",
        "schema_version": "1.0",
        "artist": {"name": "Mary Cassatt", "wikidata_q": "Q173223"},
        "title": "After the Bullfight",
        "files": {
            "master": {
                "filename": "master.jpeg",
                "sha256": "4f3a2b8" + ("0" * 57),
                "size_bytes": 12378451,
                "ingested_at": "2026-05-16T21:30:00Z",
            },
        },
        "history": [
            {"ts": "2026-05-16T21:30:00Z", "actor": "codex", "op": "ingested"},
        ],
        "stable_identifiers": {"wikidata_q": "Q98549878"},
    }


def test_artist_wikidata_ulan_is_stored_beside_qid(monkeypatch):
    def fake_urlopen(request, timeout):  # noqa: ANN001
        url = request.full_url
        assert "Special:EntityData/Q173223.json" in url
        return _Response(
            {
                "entities": {
                    "Q173223": {
                        "claims": {
                            "P245": [
                                {
                                    "mainsnak": {
                                        "datavalue": {"value": "500030502"},
                                    }
                                }
                            ]
                        }
                    }
                }
            }
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    enriched = enrich_sidecar_getty(_minimal_meta())

    assert enriched["artist"]["ulan"] == "http://vocab.getty.edu/ulan/500030502"
    assert enriched["stable_identifiers"]["wikidata_q"] == "Q98549878"
    assert enriched["stable_identifiers"]["ulan"] == "http://vocab.getty.edu/ulan/500030502"
    assert enriched["stable_identifiers"]["ulan_for_artist"] == (
        "http://vocab.getty.edu/ulan/500030502"
    )


def test_unresolved_getty_ids_degrade_to_null(monkeypatch):
    def fake_urlopen(request, timeout):  # noqa: ANN001
        raise OSError("network unavailable")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    meta = _minimal_meta()
    meta["artist"] = {"name": "Unresolved Artist", "wikidata_q": "Q999999"}

    enriched = enrich_sidecar_getty(meta)

    assert enriched["artist"]["ulan"] is None
    assert enriched["stable_identifiers"]["ulan"] is None
    assert enriched["stable_identifiers"]["aat"] is None
    assert enriched["stable_identifiers"]["tgn"] is None


def test_subject_and_site_reconcile_to_aat_and_tgn(monkeypatch):
    def fake_urlopen(request, timeout):  # noqa: ANN001
        url = request.full_url
        if "Special:EntityData/Q173223.json" in url:
            return _Response({"entities": {"Q173223": {"claims": {}}}})
        if "query%22%3A+%22print%22" in url:
            return _Response({"q0": {"result": [{"id": "http://vocab.getty.edu/aat/300041273"}]}})
        if "query%22%3A+%22Chartres+Cathedral%22" in url:
            return _Response({"q0": {"result": [{"id": "http://vocab.getty.edu/tgn/7008038"}]}})
        if "query%22%3A+%22Mary+Cassatt%22" in url:
            return _Response({"q0": {"result": [{"id": "http://vocab.getty.edu/ulan/500030502"}]}})
        raise AssertionError(url)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    meta = _minimal_meta()
    meta["subject"] = {"content_tags": [{"label": "print"}]}
    meta["site"] = {"name": "Chartres Cathedral", "wikidata_q": "Q188527"}

    enriched = enrich_sidecar_getty(meta)

    assert enriched["stable_identifiers"]["ulan"] == "http://vocab.getty.edu/ulan/500030502"
    assert enriched["stable_identifiers"]["aat"] == "http://vocab.getty.edu/aat/300041273"
    assert enriched["stable_identifiers"]["tgn"] == "http://vocab.getty.edu/tgn/7008038"


def test_plain_string_content_tags_are_cleaned_before_reconcile(monkeypatch):
    seen_urls: list[str] = []

    def fake_urlopen(request, timeout):  # noqa: ANN001
        url = request.full_url
        seen_urls.append(url)
        if "Special:EntityData/Q173223.json" in url:
            return _Response({"entities": {"Q173223": {"claims": {}}}})
        if "query%22%3A+%22Mary+Cassatt%22" in url:
            return _Response({"q0": {"result": [{"id": "http://vocab.getty.edu/ulan/500030502"}]}})
        if "query%22%3A+%22print%22" in url:
            return _Response({"q0": {"result": [{"id": "http://vocab.getty.edu/aat/300041273"}]}})
        raise AssertionError(url)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    meta = _minimal_meta()
    meta["subject"] = {"content_tags": ["   ", "  print  "]}

    enriched = enrich_sidecar_getty(meta)

    assert enriched["stable_identifiers"]["aat"] == "http://vocab.getty.edu/aat/300041273"
    assert not any("%22+++%22" in url for url in seen_urls)


def test_schema_allows_getty_stable_identifier_fields():
    schema_path = Path(__file__).resolve().parents[1] / "schemas" / "meta.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))

    stable_properties = schema["properties"]["stable_identifiers"]["properties"]

    assert {"ulan", "aat", "tgn", "ulan_for_artist"}.issubset(stable_properties)
