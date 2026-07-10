from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import jsonschema
import pytest
from iiif_prezi3 import Manifest

from fine_art_archive.iiif import emit_manifest, to_manifest

IIIF_PRESENTATION_3_SHAPE = {
    "type": "object",
    "required": ["@context", "id", "type", "label", "items"],
    "properties": {
        "@context": {"const": "http://iiif.io/api/presentation/3/context.json"},
        "id": {"type": "string", "format": "uri"},
        "type": {"const": "Manifest"},
        "label": {"type": "object"},
        "items": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "required": ["id", "type", "width", "height", "items"],
                "properties": {
                    "id": {"type": "string", "format": "uri"},
                    "type": {"const": "Canvas"},
                    "width": {"type": "integer", "minimum": 1},
                    "height": {"type": "integer", "minimum": 1},
                },
            },
        },
    },
}


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


def test_manifest_has_iiif_presentation_v3_shape_and_canvas() -> None:
    manifest = to_manifest(
        _sidecar(),
        base_url="https://archive.example/iiif/4f3a2b8-after-the-bullfight-cassatt",
    )

    assert manifest["@context"] == "http://iiif.io/api/presentation/3/context.json"
    assert urlparse(manifest["id"]).scheme == "https"
    assert manifest["type"] == "Manifest"
    assert manifest["label"] == {"en": ["After the Bullfight"]}
    assert manifest["rights"] == "https://creativecommons.org/publicdomain/mark/1.0/"

    canvas = manifest["items"][0]
    assert urlparse(canvas["id"]).scheme == "https"
    assert canvas["type"] == "Canvas"
    assert canvas["width"] == 640
    assert canvas["height"] == 825
    annotation = canvas["items"][0]["items"][0]
    assert annotation["motivation"] == "painting"
    assert annotation["target"] == canvas["id"]
    assert annotation["body"] == {
        "id": f"{manifest['id']}/files/master.jpeg",
        "type": "Image",
        "format": "image/jpeg",
        "width": 640,
        "height": 825,
    }
    jsonschema.validate(
        instance=manifest,
        schema=IIIF_PRESENTATION_3_SHAPE,
        format_checker=jsonschema.FormatChecker(),
    )
    parsed = Manifest.model_validate(manifest)
    round_tripped = Manifest.model_validate_json(
        parsed.model_dump_json(by_alias=True, exclude_none=True)
    )
    assert str(round_tripped.id) == manifest["id"]
    assert round_tripped.type == "Manifest"
    assert len(round_tripped.items) == 1


def test_manifest_shape_validation_is_load_bearing() -> None:
    manifest = to_manifest(_sidecar(), base_url="https://archive.example/iiif/work")
    del manifest["items"][0]["type"]

    with pytest.raises(jsonschema.ValidationError, match="'type' is a required property"):
        jsonschema.validate(instance=manifest, schema=IIIF_PRESENTATION_3_SHAPE)


def test_manifest_metadata_carries_core_sidecar_fields() -> None:
    manifest = to_manifest(
        _sidecar(),
        base_url="https://archive.example/iiif/4f3a2b8-after-the-bullfight-cassatt",
    )

    metadata = {item["label"]["en"][0]: item["value"]["en"][0] for item in manifest["metadata"]}
    assert metadata == {
        "Artist": "Mary Cassatt",
        "Year": "1873",
        "Medium": "Oil on canvas",
        "Holder": "Art Institute of Chicago",
        "Work ID": "4f3a2b8-after-the-bullfight-cassatt",
    }


def test_manifest_rejects_missing_or_non_http_base_url() -> None:
    with pytest.raises(ValueError, match="base_url is required"):
        to_manifest(_sidecar())

    with pytest.raises(ValueError, match="absolute HTTP"):
        to_manifest(_sidecar(), base_url="urn:fine-art-archive:iiif:work")

    with pytest.raises(ValueError, match="query string or fragment"):
        to_manifest(_sidecar(), base_url="https://archive.example/iiif/work?draft=1")


def test_manifest_rejects_non_positive_dimensions() -> None:
    sidecar = _sidecar()
    sidecar["files"]["master"]["dimensions_px"] = [640, 0]

    with pytest.raises(ValueError, match="dimensions_px"):
        to_manifest(sidecar, base_url="https://archive.example/iiif/work")


def test_manifest_rejects_boolean_dimensions_and_malformed_objects() -> None:
    sidecar = _sidecar()
    sidecar["files"]["master"]["dimensions_px"] = [True, 825]
    with pytest.raises(ValueError, match="dimensions_px"):
        to_manifest(sidecar, base_url="https://archive.example/iiif/work")

    malformed_files = _sidecar()
    malformed_files["files"] = []
    with pytest.raises(ValueError, match="files must be an object"):
        to_manifest(malformed_files, base_url="https://archive.example/iiif/work")

    malformed_rights = _sidecar()
    malformed_rights["rights"] = []
    with pytest.raises(ValueError, match="rights must be an object"):
        to_manifest(malformed_rights, base_url="https://archive.example/iiif/work")


def test_manifest_omits_evidence_url_and_escapes_filename() -> None:
    sidecar = _sidecar()
    sidecar["rights"] = {"status": "rights-reserved", "evidence_url": "https://example.test/work"}
    sidecar["files"]["master"]["filename"] = "master #1.jpg"

    manifest = to_manifest(sidecar, base_url="https://archive.example/iiif/work")

    assert "rights" not in manifest
    assert manifest["items"][0]["items"][0]["items"][0]["body"]["id"].endswith(
        "/files/master%20%231.jpg"
    )


def test_emit_manifest_writes_manifest_json(tmp_path: Path) -> None:
    meta_path = tmp_path / "meta.json"
    meta_path.write_text(json.dumps(_sidecar()), encoding="utf-8")

    manifest_path = emit_manifest(
        meta_path,
        base_url="https://archive.example/iiif/4f3a2b8-after-the-bullfight-cassatt",
    )

    assert manifest_path == tmp_path / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["id"] == "https://archive.example/iiif/4f3a2b8-after-the-bullfight-cassatt"
    assert manifest["items"][0]["id"].endswith("/canvas/master")


def test_emit_manifest_writes_to_explicit_output_dir(tmp_path: Path) -> None:
    meta_path = tmp_path / "meta.json"
    meta_path.write_text(json.dumps(_sidecar()), encoding="utf-8")
    out_dir = tmp_path / "out"

    manifest_path = emit_manifest(
        meta_path,
        out_dir,
        base_url="https://archive.example/iiif/4f3a2b8-after-the-bullfight-cassatt",
    )

    assert manifest_path == out_dir / "manifest.json"
    assert manifest_path.exists()
