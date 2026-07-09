"""IIIF Presentation v3 manifests for Fine Art Archive sidecars."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fine_art_archive import sidecar

IIIF_CONTEXT = "http://iiif.io/api/presentation/3/context.json"


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _language_map(value: str) -> dict[str, list[str]]:
    return {"en": [value]}


def _metadata_item(label: str, value: str | None) -> dict[str, dict[str, list[str]]] | None:
    if not value:
        return None
    return {
        "label": _language_map(label),
        "value": _language_map(value),
    }


def _rights_uri(meta: dict[str, Any]) -> str | None:
    rights = meta.get("rights") or {}
    status = _clean(rights.get("status"))
    evidence_url = _clean(rights.get("evidence_url"))
    if status in {"public-domain", "public_domain", "pd"}:
        return "https://creativecommons.org/publicdomain/mark/1.0/"
    if evidence_url and evidence_url.startswith(("http://", "https://")):
        return evidence_url
    return None


def _master_file(meta: dict[str, Any]) -> dict[str, Any]:
    files = meta.get("files") or {}
    master = files.get("master") or {}
    if not isinstance(master, dict):
        return {}
    return master


def _master_dimensions(master: dict[str, Any]) -> tuple[int, int] | None:
    dimensions = master.get("dimensions_px")
    if (
        isinstance(dimensions, list)
        and len(dimensions) == 2
        and all(isinstance(value, int) for value in dimensions)
    ):
        return dimensions[0], dimensions[1]
    width = master.get("width") or master.get("width_px")
    height = master.get("height") or master.get("height_px")
    if isinstance(width, int) and isinstance(height, int):
        return width, height
    return None


def _master_format(master: dict[str, Any]) -> str:
    filename = str(master.get("filename") or "").lower()
    if filename.endswith((".jpg", ".jpeg")):
        return "image/jpeg"
    if filename.endswith(".png"):
        return "image/png"
    if filename.endswith(".webp"):
        return "image/webp"
    if filename.endswith(".tif") or filename.endswith(".tiff"):
        return "image/tiff"
    return "application/octet-stream"


def _image_id(manifest_id: str, meta: dict[str, Any], master: dict[str, Any]) -> str:
    source_url = _clean(master.get("url")) or _clean(master.get("source_url"))
    if source_url:
        return source_url
    filename = _clean(master.get("filename")) or "master"
    return f"{manifest_id}/files/{filename}"


def to_manifest(meta: dict[str, Any], *, base_url: str | None = None) -> dict[str, Any]:
    """Build a minimal IIIF Presentation 3.0 manifest for one work sidecar."""
    work_id = _clean(meta.get("work_id")) or "unknown"
    title = _clean(meta.get("title")) or "Untitled"
    artist = meta.get("artist") or {}
    holder = meta.get("holder") or {}
    master = _master_file(meta)
    dimensions = _master_dimensions(master)
    if dimensions is None:
        raise ValueError("files.master.dimensions_px must provide [width, height]")
    width, height = dimensions

    manifest_id = (base_url.rstrip("/") if base_url else f"urn:fine-art-archive:iiif:{work_id}") + (
        "" if base_url else ""
    )
    canvas_id = f"{manifest_id}/canvas/master"
    annotation_page_id = f"{canvas_id}/page"
    annotation_id = f"{annotation_page_id}/annotation"
    image_id = _image_id(manifest_id, meta, master)

    metadata = [
        item
        for item in [
            _metadata_item("Artist", _clean(artist.get("name"))),
            _metadata_item("Year", _clean(meta.get("year")) or _clean(meta.get("year_min"))),
            _metadata_item("Medium", _clean(meta.get("medium"))),
            _metadata_item("Holder", _clean(holder.get("name"))),
            _metadata_item("Work ID", work_id),
        ]
        if item is not None
    ]

    manifest: dict[str, Any] = {
        "@context": IIIF_CONTEXT,
        "id": manifest_id,
        "type": "Manifest",
        "label": _language_map(title),
        "metadata": metadata,
        "items": [
            {
                "id": canvas_id,
                "type": "Canvas",
                "label": _language_map(title),
                "width": width,
                "height": height,
                "items": [
                    {
                        "id": annotation_page_id,
                        "type": "AnnotationPage",
                        "items": [
                            {
                                "id": annotation_id,
                                "type": "Annotation",
                                "motivation": "painting",
                                "target": canvas_id,
                                "body": {
                                    "id": image_id,
                                    "type": "Image",
                                    "format": _master_format(master),
                                    "width": width,
                                    "height": height,
                                },
                            }
                        ],
                    }
                ],
            }
        ],
    }
    rights = _rights_uri(meta)
    if rights:
        manifest["rights"] = rights
    return manifest


def emit_manifest(
    meta_path: Path | str,
    out_dir: Path | str | None = None,
    *,
    base_url: str | None = None,
) -> Path:
    """Write manifest.json for one sidecar and return its path."""
    meta_file = Path(meta_path)
    output_dir = Path(out_dir) if out_dir is not None else meta_file.parent
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = to_manifest(sidecar.load(meta_file), base_url=base_url)
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return manifest_path
