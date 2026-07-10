"""IIIF Presentation v3 manifests for Fine Art Archive sidecars."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, TypeGuard
from urllib.parse import quote, urlparse

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


def _mapping(value: Any, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field} must be an object")
    return value


def _rights_uri(meta: Mapping[str, Any]) -> str | None:
    rights = meta.get("rights")
    if rights is None:
        return None
    rights = _mapping(rights, "rights")
    status = _clean(rights.get("status"))
    if status in {"public-domain", "public_domain", "pd"}:
        return "https://creativecommons.org/publicdomain/mark/1.0/"
    return None


def _master_file(meta: Mapping[str, Any]) -> Mapping[str, Any]:
    files = _mapping(meta.get("files"), "files")
    master = _mapping(files.get("master"), "files.master")
    return master


def _positive_int(value: Any) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _master_dimensions(master: Mapping[str, Any]) -> tuple[int, int] | None:
    dimensions = master.get("dimensions_px")
    if isinstance(dimensions, list) and len(dimensions) == 2:
        width, height = dimensions
        if _positive_int(width) and _positive_int(height):
            return width, height
    width = master.get("width") or master.get("width_px")
    height = master.get("height") or master.get("height_px")
    if _positive_int(width) and _positive_int(height):
        return width, height
    return None


def _master_format(master: Mapping[str, Any]) -> str:
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


def _image_id(manifest_id: str, master: Mapping[str, Any]) -> str:
    filename = _clean(master.get("filename")) or "master"
    return f"{manifest_id}/files/{quote(filename, safe='')}"


def _manifest_id(base_url: str | None) -> str:
    if not base_url:
        raise ValueError("base_url is required for IIIF Presentation 3.0 HTTP(S) ids")
    manifest_id = base_url.rstrip("/")
    parsed = urlparse(manifest_id)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("base_url must be an absolute HTTP(S) URL")
    if parsed.query or parsed.fragment:
        raise ValueError("base_url must not contain a query string or fragment")
    return manifest_id


def to_manifest(meta: dict[str, Any], *, base_url: str | None = None) -> dict[str, Any]:
    """Build a minimal IIIF Presentation 3.0 manifest for one work sidecar."""
    source = _mapping(meta, "meta")
    work_id = _clean(source.get("work_id")) or "unknown"
    title = _clean(source.get("title")) or "Untitled"
    artist = _mapping(source.get("artist"), "artist")
    holder_value = source.get("holder")
    holder = _mapping(holder_value, "holder") if holder_value is not None else {}
    master = _master_file(source)
    dimensions = _master_dimensions(master)
    if dimensions is None:
        raise ValueError("files.master.dimensions_px must provide [width, height]")
    width, height = dimensions

    manifest_id = _manifest_id(base_url)
    canvas_id = f"{manifest_id}/canvas/master"
    annotation_page_id = f"{canvas_id}/page"
    annotation_id = f"{annotation_page_id}/annotation"
    image_id = _image_id(manifest_id, master)

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
    rights = _rights_uri(source)
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
