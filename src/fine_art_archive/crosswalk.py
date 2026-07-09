"""Read-only metadata projections for standard cultural-heritage formats."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fine_art_archive import sidecar

WIKIDATA_ENTITY = "https://www.wikidata.org/entity/"
LINKED_ART_CONTEXT = "https://linked.art/ns/v1/linked-art.json"


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _qid_uri(qid: str | None) -> str | None:
    qid = _clean(qid)
    if qid and qid.startswith("Q") and qid[1:].isdigit():
        return f"{WIKIDATA_ENTITY}{qid}"
    return None


def _artist_name(meta: dict[str, Any]) -> str:
    artist = meta.get("artist") or {}
    return _clean(artist.get("name")) or "Unknown artist"


def _rights_label(meta: dict[str, Any]) -> str | None:
    rights = meta.get("rights") or {}
    return _clean(rights.get("status")) or _clean(rights.get("evidence_url"))


def _identifier_values(meta: dict[str, Any]) -> list[str]:
    identifiers = [_clean(meta.get("work_id"))]
    stable = meta.get("stable_identifiers") or {}
    holder = meta.get("holder") or {}

    identifiers.extend(
        [
            _qid_uri(stable.get("wikidata_q")),
            _clean(stable.get("museum_accession")),
            _clean(holder.get("accession")),
            _clean(stable.get("doi")),
            _clean(stable.get("ark")),
        ]
    )
    seen: set[str] = set()
    out: list[str] = []
    for value in identifiers:
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return out


def to_dublin_core(meta: dict[str, Any]) -> dict[str, Any]:
    """Project a sidecar into a compact Dublin Core-style metadata dict."""
    return {
        "title": _clean(meta.get("title")) or "Untitled",
        "creator": _artist_name(meta),
        "date": _clean(meta.get("year")) or _clean(meta.get("year_min")),
        "medium": _clean(meta.get("medium")),
        "rights": _rights_label(meta),
        "identifier": _identifier_values(meta),
    }


def _linked_art_name(content: str, *, ident_type: str = "Name") -> dict[str, Any]:
    return {
        "type": ident_type,
        "content": content,
    }


def _linked_art_identifier(value: str) -> dict[str, Any]:
    ident: dict[str, Any] = _linked_art_name(value, ident_type="Identifier")
    if value.startswith("http://") or value.startswith("https://"):
        ident["id"] = value
    return ident


def _linked_art_actor(name: str, qid: str | None) -> dict[str, Any]:
    actor: dict[str, Any] = {
        "type": "Actor",
        "_label": name,
        "identified_by": [_linked_art_name(name)],
    }
    uri = _qid_uri(qid)
    if uri:
        actor["id"] = uri
        actor["identified_by"].append(_linked_art_identifier(uri))
    return actor


def to_linked_art(meta: dict[str, Any]) -> dict[str, Any]:
    """Project a sidecar into a minimal Linked Art JSON-LD HumanMadeObject."""
    title = _clean(meta.get("title")) or "Untitled"
    work_id = _clean(meta.get("work_id")) or "unknown"
    artist = meta.get("artist") or {}
    stable = meta.get("stable_identifiers") or {}
    holder = meta.get("holder") or {}

    record: dict[str, Any] = {
        "@context": LINKED_ART_CONTEXT,
        "id": f"urn:fine-art-archive:work:{work_id}",
        "type": "HumanMadeObject",
        "_label": title,
        "identified_by": [_linked_art_name(title)],
        "produced_by": {
            "type": "Production",
            "carried_out_by": [_linked_art_actor(_artist_name(meta), artist.get("wikidata_q"))],
        },
    }

    for value in _identifier_values(meta):
        record["identified_by"].append(_linked_art_identifier(value))

    object_uri = _qid_uri(stable.get("wikidata_q"))
    if object_uri:
        record["id"] = object_uri

    medium = _clean(meta.get("medium"))
    if medium:
        record["made_of"] = [{"type": "Material", "_label": medium}]

    year = _clean(meta.get("year")) or _clean(meta.get("year_min"))
    if year:
        record["produced_by"]["timespan"] = {
            "type": "TimeSpan",
            "_label": year,
        }

    holder_name = _clean(holder.get("name"))
    if holder_name:
        owner: dict[str, Any] = {
            "type": "Group",
            "_label": holder_name,
            "identified_by": [_linked_art_name(holder_name)],
        }
        holder_uri = _qid_uri(holder.get("wikidata_q"))
        if holder_uri:
            owner["id"] = holder_uri
            owner["identified_by"].append(_linked_art_identifier(holder_uri))
        record["current_owner"] = [owner]

    rights = _rights_label(meta)
    if rights:
        record["subject_to"] = [{"type": "Right", "_label": rights}]

    return record


def emit_crosswalks(meta_path: Path | str, out_dir: Path | str | None = None) -> tuple[Path, Path]:
    """Write dc.json and linkedart.json for one sidecar and return their paths."""
    meta_file = Path(meta_path)
    output_dir = Path(out_dir) if out_dir is not None else meta_file.parent
    output_dir.mkdir(parents=True, exist_ok=True)
    meta = sidecar.load(meta_file)

    dc_path = output_dir / "dc.json"
    linked_art_path = output_dir / "linkedart.json"
    dc_path.write_text(
        json.dumps(to_dublin_core(meta), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    linked_art_path.write_text(
        json.dumps(to_linked_art(meta), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return dc_path, linked_art_path
