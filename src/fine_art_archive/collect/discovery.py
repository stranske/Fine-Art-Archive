"""Wikidata-driven multi-source discovery.

For a work's Wikidata Q-ID, enumerate every digital source we can reach
without acquiring bytes: Wikimedia Commons (P18), the holding institution's
own API (resolved via per-source-Q-ID adapters), Met Open Access (P3634),
Rijksmuseum (P350), NGA (P5253), ARTIC (P9173), Cleveland CMA (P9092),
Yale CBA (P4738), Smithsonian (P6611), BnF (P5587), and others.

For each candidate the discovery step records what we can *cheaply* learn:
- The image URL (or the API endpoint to resolve it)
- Claimed pixel dimensions where the source advertises them
- Estimated file size where HEAD returns Content-Length
- The source tier from config/sources_seed.yaml

Acquisition is a separate step driven from the discovery's ranked list.
This module deliberately doesn't fetch image bytes — that's the expensive
phase to defer until we know which candidate is worth pulling.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from typing import Any

USER_AGENT = "Mozilla/5.0 (Fine-Art-Archive)"

# Wikidata property -> source mapping. Each entry is a (property_id, source_id,
# source_tier, lookup_endpoint_template_or_None). For sources where the
# property's value IS the image URL or filename (like P18 -> Commons file),
# we resolve directly; for others we need a small API hop.
SOURCE_PROPERTIES = [
    ("P18", "wikimedia_commons", 2, "commons_imageinfo"),
    ("P3634", "met", 1, "met_api"),
    ("P350", "rijksmuseum", 1, "rijksmuseum_micrio"),
    ("P5253", "nga", 1, "nga_open_access"),
    ("P9173", "artic", 1, "artic_api"),
    ("P9092", "cleveland", 1, "cleveland_api"),
    ("P4738", "yale_cba", 1, "yale_cba_iiif"),
    ("P6611", "smithsonian", 1, "smithsonian_open_access"),
    ("P5587", "bnf_gallica", 1, "bnf_iiif"),
    ("P347", "joconde", 2, None),  # French national museums; not directly resolvable
    ("P973", "described_at_url", 3, "url"),  # arbitrary
]

JsonFetcher = Callable[[str], dict[str, Any]]
TextFetcher = Callable[[str], str]
HeadSizer = Callable[[str], int | None]
Candidate = dict[str, Any]


class DiscoveryFetchError(RuntimeError):
    """Raised when an upstream discovery endpoint cannot be read or parsed."""


def _get_json(url: str) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            data = json.loads(response.read())
    except (
        TimeoutError,
        json.JSONDecodeError,
        urllib.error.HTTPError,
        urllib.error.URLError,
    ) as exc:
        raise DiscoveryFetchError(str(exc)) from exc
    if not isinstance(data, dict):
        raise DiscoveryFetchError(f"expected JSON object from {url}")
    return data


def _get_text(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=20) as response:
            return response.read().decode("utf-8", errors="replace")
    except (TimeoutError, urllib.error.HTTPError, urllib.error.URLError) as exc:
        raise DiscoveryFetchError(str(exc)) from exc


def _head_size(url: str) -> int | None:
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            value = response.headers.get("Content-Length")
    except (TimeoutError, urllib.error.HTTPError, urllib.error.URLError):
        return None
    try:
        return int(value) if value else None
    except ValueError:
        return None


def claim_values(entity: dict[str, Any], property_id: str) -> list[Any]:
    """Return plain Wikidata claim values for a property."""
    values: list[Any] = []
    claims = entity.get("claims", {})
    if not isinstance(claims, dict):
        return values
    for statement in claims.get(property_id, []):
        if not isinstance(statement, dict):
            continue
        snak = statement.get("mainsnak", {})
        if not isinstance(snak, dict) or snak.get("snaktype") != "value":
            continue
        value = snak.get("datavalue", {}).get("value")
        if isinstance(value, dict):
            values.append(value.get("id") or value.get("amount") or value)
        else:
            values.append(value)
    return values


def _candidate_score(candidate: Candidate) -> int:
    width = candidate.get("width")
    height = candidate.get("height")
    if isinstance(width, int) and isinstance(height, int):
        return width * height
    return -1


def _resolve_commons(entity: dict[str, Any], get_json: JsonFetcher) -> list[Candidate]:
    candidates: list[Candidate] = []
    for filename in claim_values(entity, "P18"):
        try:
            api = (
                "https://commons.wikimedia.org/w/api.php?action=query&format=json"
                "&prop=imageinfo&iiprop=size|url|mime&titles="
                + urllib.parse.quote("File:" + str(filename))
            )
            data = get_json(api)
            pages = data["query"]["pages"]
            for page in pages.values():
                imageinfo = (page.get("imageinfo") or [{}])[0]
                candidates.append(
                    {
                        "source": "wikimedia_commons",
                        "tier": 2,
                        "url": imageinfo.get("url"),
                        "width": imageinfo.get("width"),
                        "height": imageinfo.get("height"),
                        "size_bytes": imageinfo.get("size"),
                        "mime": imageinfo.get("mime"),
                        "evidence": f"Wikidata P18 -> File:{filename}",
                    }
                )
        except (DiscoveryFetchError, KeyError, TypeError, ValueError) as exc:
            candidates.append(
                {
                    "source": "wikimedia_commons",
                    "error": str(exc),
                    "evidence": f"P18 -> File:{filename}",
                }
            )
    return candidates


def _resolve_met(
    entity: dict[str, Any], get_json: JsonFetcher, head_size: HeadSizer
) -> list[Candidate]:
    candidates: list[Candidate] = []
    for met_id in claim_values(entity, "P3634"):
        try:
            data = get_json(
                f"https://collectionapi.metmuseum.org/public/collection/v1/objects/{met_id}"
            )
            if data.get("isPublicDomain") and data.get("primaryImage"):
                image_url = data["primaryImage"]
                candidates.append(
                    {
                        "source": "met",
                        "tier": 1,
                        "url": image_url,
                        "size_bytes": head_size(image_url),
                        "width": None,
                        "height": None,
                        "evidence": f"Wikidata P3634 -> Met {met_id}",
                        "is_pd": True,
                    }
                )
        except (DiscoveryFetchError, KeyError, TypeError, ValueError) as exc:
            candidates.append({"source": "met", "error": str(exc)})
    return candidates


def _resolve_rijksmuseum(
    entity: dict[str, Any], get_json: JsonFetcher, get_text: TextFetcher
) -> list[Candidate]:
    candidates: list[Candidate] = []
    for rijksmuseum_id in claim_values(entity, "P350"):
        try:
            page_url = f"https://www.rijksmuseum.nl/en/collection/{rijksmuseum_id}"
            html = get_text(page_url)
            meta = re.search(r'<meta property="og:image" content="([^"]+)"', html)
            if not meta:
                continue
            match = re.search(r"iiif\.micr\.io/([A-Za-z0-9]+)", meta.group(1))
            if not match:
                continue
            micrio_id = match.group(1)
            info = get_json(f"https://iiif.micr.io/{micrio_id}/info.json")
            candidates.append(
                {
                    "source": "rijksmuseum",
                    "tier": 1,
                    "url": f"https://iiif.micr.io/{micrio_id}/full/max/0/default.jpg",
                    "width": info.get("width"),
                    "height": info.get("height"),
                    "evidence": (
                        f"Wikidata P350 -> Rijksmuseum {rijksmuseum_id} -> Micrio {micrio_id}"
                    ),
                }
            )
        except (DiscoveryFetchError, KeyError, TypeError, ValueError, re.error) as exc:
            candidates.append({"source": "rijksmuseum", "error": str(exc)})
    return candidates


def _resolve_nga(entity: dict[str, Any]) -> list[Candidate]:
    return [
        {
            "source": "nga",
            "tier": 1,
            "url": None,
            "evidence": f"Wikidata P5253 -> NGA {nga_id}; resolver TBD",
        }
        for nga_id in claim_values(entity, "P5253")
    ]


def _resolve_artic(entity: dict[str, Any], get_json: JsonFetcher) -> list[Candidate]:
    candidates: list[Candidate] = []
    for artic_id in claim_values(entity, "P9173"):
        try:
            data = get_json(f"https://api.artic.edu/api/v1/artworks/{artic_id}").get("data", {})
            image_id = data.get("image_id") if isinstance(data, dict) else None
            if not image_id:
                continue
            width = height = None
            try:
                info = get_json(f"https://www.artic.edu/iiif/2/{image_id}/info.json")
                width = info.get("width")
                height = info.get("height")
            except DiscoveryFetchError:
                pass
            candidates.append(
                {
                    "source": "artic",
                    "tier": 1,
                    "url": f"https://www.artic.edu/iiif/2/{image_id}/full/max/0/default.jpg",
                    "width": width,
                    "height": height,
                    "evidence": f"Wikidata P9173 -> ARTIC {artic_id}",
                }
            )
        except (DiscoveryFetchError, KeyError, TypeError, ValueError) as exc:
            candidates.append({"source": "artic", "error": str(exc)})
    return candidates


def _resolve_cleveland(entity: dict[str, Any], get_json: JsonFetcher) -> list[Candidate]:
    candidates: list[Candidate] = []
    for cleveland_id in claim_values(entity, "P9092"):
        try:
            data = get_json(
                f"https://openaccess-api.clevelandart.org/api/artworks/{cleveland_id}"
            ).get("data", {})
            images = data.get("images") if isinstance(data, dict) else {}
            image_url = ((images or {}).get("web") or {}).get("url") or ""
            candidates.append(
                {
                    "source": "cleveland",
                    "tier": 1,
                    "url": image_url or None,
                    "evidence": f"Wikidata P9092 -> Cleveland {cleveland_id}",
                }
            )
        except (DiscoveryFetchError, KeyError, TypeError, ValueError) as exc:
            candidates.append({"source": "cleveland", "error": str(exc)})
    return candidates


def discover_candidates(
    qid: str,
    *,
    get_json: JsonFetcher = _get_json,
    get_text: TextFetcher = _get_text,
    head_size: HeadSizer = _head_size,
) -> dict[str, Any]:
    """Discover image candidates for a Wikidata entity.

    Dependency-injected fetchers keep the ranking and extraction logic directly
    unit-testable without spawning a shell or touching the network.
    """
    entity_data = get_json(f"https://www.wikidata.org/wiki/Special:EntityData/{qid}.json")
    entity = entity_data["entities"][qid]
    candidates: list[Candidate] = []
    candidates.extend(_resolve_commons(entity, get_json))
    candidates.extend(_resolve_met(entity, get_json, head_size))
    candidates.extend(_resolve_rijksmuseum(entity, get_json, get_text))
    candidates.extend(_resolve_nga(entity))
    candidates.extend(_resolve_artic(entity, get_json))
    candidates.extend(_resolve_cleveland(entity, get_json))
    candidates.sort(
        key=lambda candidate: (_candidate_score(candidate), -candidate.get("tier", 99)),
        reverse=True,
    )
    return {"qid": qid, "candidates": candidates}


def write_discovery_output(qid: str, out_path: str) -> dict[str, Any]:
    """Write discovery output and return the same payload for callers."""
    payload = discover_candidates(qid)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as output:
        json.dump(payload, output, indent=2)
    return payload


def discovery_shell_script(qid: str, out_path: str) -> str:
    """Bash script that produces a discovery JSON for the given Wikidata Q-ID.

    Driven via osascript do shell script on a host with full network. The shell
    layer is intentionally thin; discovery behavior lives in importable Python.
    """
    out_q = shlex.quote(out_path)
    qid_q = shlex.quote(qid)
    return f"""set -e
mkdir -p "$(dirname {out_q})"
python3 -m fine_art_archive.collect.discovery {qid_q} {out_q}
"""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Discover candidate image sources for a Wikidata Q-ID."
    )
    parser.add_argument("qid")
    parser.add_argument("out_path")
    args = parser.parse_args(argv)
    payload = write_discovery_output(args.qid, args.out_path)
    print(json.dumps(payload, indent=2)[:4000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
