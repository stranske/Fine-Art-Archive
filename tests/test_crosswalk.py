from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fine_art_archive.crosswalk import emit_crosswalks, to_dublin_core, to_linked_art


def _sidecar() -> dict[str, Any]:
    return {
        "work_id": "4f3a2b8-after-the-bullfight-cassatt",
        "schema_version": "1.0",
        "artist": {
            "name": "Mary Cassatt",
            "wikidata_q": "Q173223",
            "ulan": "500030502",
        },
        "title": "After the Bullfight",
        "year": "1873",
        "medium": "Oil on canvas",
        "holder": {
            "name": "Art Institute of Chicago",
            "wikidata_q": "Q239303",
            "accession": "1969.332",
            "url": "https://www.artic.edu/artworks/61446",
        },
        "rights": {
            "status": "public-domain",
            "evidence_url": "https://www.artic.edu/artworks/61446",
        },
        "stable_identifiers": {
            "wikidata_q": "Q98549878",
            "museum_accession": "1969.332",
        },
        "files": {
            "master": {
                "filename": "master.jpeg",
                "sha256": "4f3a2b8" + ("0" * 57),
                "size_bytes": 12378451,
                "ingested_at": "2026-05-16T21:30:00Z",
                "dimensions_px": [640, 825],
            },
        },
        "history": [
            {"ts": "2026-05-16T21:30:00Z", "actor": "codex", "op": "ingested"},
        ],
    }


def test_dublin_core_projection_populates_core_terms() -> None:
    dc = to_dublin_core(_sidecar())

    assert dc == {
        "title": "After the Bullfight",
        "creator": "Mary Cassatt",
        "date": "1873",
        "medium": "Oil on canvas",
        "rights": "public-domain",
        "identifier": [
            "4f3a2b8-after-the-bullfight-cassatt",
            "https://www.wikidata.org/entity/Q98549878",
            "1969.332",
        ],
    }


def test_linked_art_projection_has_valid_context_type_and_identifiers() -> None:
    linked = to_linked_art(_sidecar())

    assert linked["@context"] == "https://linked.art/ns/v1/linked-art.json"
    assert linked["type"] == "HumanMadeObject"
    assert linked["id"] == "https://www.wikidata.org/entity/Q98549878"
    assert linked["_label"] == "After the Bullfight"
    assert linked["produced_by"]["carried_out_by"][0]["id"] == (
        "https://www.wikidata.org/entity/Q173223"
    )
    assert linked["current_owner"][0]["id"] == "https://www.wikidata.org/entity/Q239303"
    identifiers = linked["identified_by"]
    assert {
        "type": "Identifier",
        "content": "https://www.wikidata.org/entity/Q98549878",
        "id": "https://www.wikidata.org/entity/Q98549878",
    } in identifiers
    assert {"type": "Identifier", "content": "1969.332"} in identifiers


def test_emit_crosswalks_writes_dc_and_linked_art_json(tmp_path: Path) -> None:
    meta_path = tmp_path / "meta.json"
    meta_path.write_text(json.dumps(_sidecar()), encoding="utf-8")

    dc_path, linked_path = emit_crosswalks(meta_path)

    assert dc_path == tmp_path / "dc.json"
    assert linked_path == tmp_path / "linkedart.json"
    assert json.loads(dc_path.read_text(encoding="utf-8"))["title"] == "After the Bullfight"
    assert json.loads(linked_path.read_text(encoding="utf-8"))["type"] == "HumanMadeObject"
