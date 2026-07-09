"""Best-effort Getty Vocabulary enrichment for sidecar identifiers."""

from __future__ import annotations

import json
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

GETTY_URIS = {
    "ulan": "http://vocab.getty.edu/ulan/",
    "aat": "http://vocab.getty.edu/aat/",
    "tgn": "http://vocab.getty.edu/tgn/",
}


@dataclass(frozen=True)
class GettyIds:
    ulan: str | None = None
    aat: str | None = None
    tgn: str | None = None

    def as_dict(self) -> dict[str, str | None]:
        return {"ulan": self.ulan, "aat": self.aat, "tgn": self.tgn}


def enrich_sidecar_getty(meta: dict[str, Any], *, timeout: int = 15) -> dict[str, Any]:
    """Return a copy of ``meta`` with Getty IDs stored beside Wikidata IDs.

    Network failures and unresolved names leave null Getty IDs rather than
    blocking acquisition or validation.
    """
    enriched = dict(meta)
    artist = dict(enriched.get("artist") or {})
    stable = dict(enriched.get("stable_identifiers") or {})

    artist_ids = resolve_getty_ids(
        name=_clean_string(artist.get("name")),
        wikidata_q=_clean_qid(artist.get("wikidata_q")),
        vocabulary="ulan",
        timeout=timeout,
    )
    artist["ulan"] = artist_ids.ulan
    stable["ulan"] = artist_ids.ulan
    stable["ulan_for_artist"] = artist_ids.ulan

    aat = _resolve_first_content_tag(enriched.get("subject"), timeout=timeout)
    tgn = _resolve_site_tgn(enriched.get("site"), timeout=timeout)
    stable["aat"] = aat
    stable["tgn"] = tgn

    enriched["artist"] = artist
    enriched["stable_identifiers"] = stable
    return enriched


def resolve_getty_ids(
    *,
    name: str | None,
    wikidata_q: str | None = None,
    vocabulary: str,
    timeout: int = 15,
) -> GettyIds:
    """Resolve one Wikidata/name pair to Getty IDs.

    The resolver uses Wikidata claims first: P245 for ULAN, P1014 for AAT, and
    P1667 for TGN. If Wikidata has no claim, it falls back to Getty
    reconciliation by name. Both paths are best-effort and return null IDs on
    failure.
    """
    if vocabulary not in GETTY_URIS:
        raise ValueError(f"unsupported Getty vocabulary: {vocabulary}")

    from_wikidata = _getty_id_from_wikidata(wikidata_q, vocabulary=vocabulary, timeout=timeout)
    value = from_wikidata or _getty_id_from_reconcile(name, vocabulary=vocabulary, timeout=timeout)
    return GettyIds(**{vocabulary: _as_getty_uri(value, vocabulary)})


def _resolve_first_content_tag(subject: Any, *, timeout: int) -> str | None:
    if not isinstance(subject, dict):
        return None
    tags = subject.get("content_tags")
    if not isinstance(tags, list):
        return None
    for tag in tags:
        if isinstance(tag, str):
            name = _clean_string(tag)
            if name is None:
                continue
        elif isinstance(tag, dict):
            tag_name = _clean_string(tag.get("label") or tag.get("name"))
            qid = _clean_qid(tag.get("wikidata_q"))
            resolved = resolve_getty_ids(
                name=tag_name, wikidata_q=qid, vocabulary="aat", timeout=timeout
            )
            if resolved.aat:
                return resolved.aat
            continue
        else:
            continue
        resolved = resolve_getty_ids(name=name, vocabulary="aat", timeout=timeout)
        if resolved.aat:
            return resolved.aat
    return None


def _resolve_site_tgn(site: Any, *, timeout: int) -> str | None:
    if not isinstance(site, dict):
        return None
    resolved = resolve_getty_ids(
        name=_clean_string(site.get("name")),
        wikidata_q=_clean_qid(site.get("wikidata_q")),
        vocabulary="tgn",
        timeout=timeout,
    )
    return resolved.tgn


def _getty_id_from_wikidata(qid: str | None, *, vocabulary: str, timeout: int) -> str | None:
    if not qid:
        return None
    property_id = {"ulan": "P245", "aat": "P1014", "tgn": "P1667"}[vocabulary]
    url = "https://www.wikidata.org/wiki/Special:EntityData/" + urllib.parse.quote(qid) + ".json"
    try:
        data = _read_json(url, timeout=timeout)
    except Exception:
        return None
    entity = (data.get("entities") or {}).get(qid) or {}
    claims = entity.get("claims") or {}
    for claim in claims.get(property_id, []) or []:
        value = claim.get("mainsnak", {}).get("datavalue", {}).get("value")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _getty_id_from_reconcile(name: str | None, *, vocabulary: str, timeout: int) -> str | None:
    if not name:
        return None
    url = "https://services.getty.edu/vocab/reconcile?" + urllib.parse.urlencode(
        {
            "queries": json.dumps(
                {
                    "q0": {
                        "query": name,
                        "type": GETTY_URIS[vocabulary],
                        "limit": 1,
                    }
                }
            )
        }
    )
    try:
        data = _read_json(url, timeout=timeout)
    except Exception:
        return None
    results = (data.get("q0") or {}).get("result") or []
    if not results:
        return None
    return _extract_getty_id(results[0])


def _read_json(url: str, *, timeout: int) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"User-Agent": "FAA/0.2"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.loads(response.read())


def _extract_getty_id(value: Any) -> str | None:
    raw = value.get("id") or value.get("uri") if isinstance(value, dict) else value
    if not isinstance(raw, str):
        return None
    raw = raw.strip()
    if not raw:
        return None
    if raw.startswith("http://vocab.getty.edu/"):
        return raw.rstrip("/").split("/")[-1]
    match = re.search(r"(\d{3,})$", raw)
    return match.group(1) if match else None


def _as_getty_uri(value: str | None, vocabulary: str) -> str | None:
    if not value:
        return None
    if value.startswith("http://vocab.getty.edu/"):
        return value
    return GETTY_URIS[vocabulary] + value


def _clean_qid(value: Any) -> str | None:
    if isinstance(value, str) and re.fullmatch(r"Q[0-9]+", value.strip()):
        return value.strip()
    return None


def _clean_string(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None
