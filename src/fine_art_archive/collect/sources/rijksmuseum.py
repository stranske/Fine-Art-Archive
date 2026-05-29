"""Rijksmuseum collector.

References:
  - Data services portal: https://data.rijksmuseum.nl/
  - IIIF Presentation: https://data.rijksmuseum.nl/docs/iiif/presentation
  - Collection API: https://data.rijksmuseum.nl/object-metadata/api/
  - dezoomify-rs: https://github.com/lovasoa/dezoomify-rs

Rijksmuseum URL patterns (mid-2026):
  Object page (human):   https://www.rijksmuseum.nl/en/collection/<obj>
  Linked Art:            https://data.rijksmuseum.nl/<obj>
  IIIF tile service:     https://iiif.micr.io/<micrio_id>/info.json
                         (Micrio is the IIIF Image API 3.0 server)
  Direct max-res:        https://iiif.micr.io/<micrio_id>/full/max/0/default.jpg

The Micrio ID is *not* the object number. Each Rijksmuseum object page
embeds multiple Micrio IDs — one for the main work plus others for
"more by this artist" related works visible on the page. The MAIN work's
Micrio ID is reliably exposed via the page's `<meta property="og:image">`
tag, which is the only consistent way to identify it from page HTML alone.

KNOWN PITFALL: simply grepping the page for `iiif.micr.io/<5 chars>` will
return all of them in unpredictable order, and the first match is often
NOT the main work. We learned this the hard way: an early test pulled
'QkOGy' (which is The Milkmaid) when targeting SK-A-2860 (The Little
Street, Micrio ID 'VWEov'). The og:image-based extraction below avoids it.

VISUAL VERIFICATION is required before finalizing any acquired master.
The collector should always produce a downscaled thumbnail and surface it
for human (or VLM) confirmation before the sidecar's history records
'master-bytes-acquired'.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass

# Micrio IDs are 5-char alphanumeric (mixed case observed: e.g. VWEov, QkOGy).
MICRIO_ID_RE = re.compile(r"iiif\.micr\.io/([A-Za-z0-9]{5})")
OG_IMAGE_RE = re.compile(r'<meta\s+property="og:image"\s+content="([^"]+)"', re.IGNORECASE)


@dataclass(frozen=True)
class RijksmuseumObject:
    """The minimal stable handle for a Rijksmuseum work."""

    object_number: str  # e.g. "SK-A-2860"

    @property
    def web_url(self) -> str:
        return f"https://www.rijksmuseum.nl/en/collection/{self.object_number}"

    @property
    def linked_art_url(self) -> str:
        return f"https://data.rijksmuseum.nl/{self.object_number}"

    @property
    def metadata_api_url(self) -> str:
        return f"https://www.rijksmuseum.nl/api/en/collection/{self.object_number}" f"?format=json"


def micrio_id_from_html(page_html: str) -> str | None:
    """Extract the canonical Micrio ID for the main work from the object page.

    Strategy: read the og:image meta tag — that's what Open Graph designates
    as the page's representative image, and it always points to the main
    work (not the 'more by this artist' carousel).
    """
    m = OG_IMAGE_RE.search(page_html)
    if not m:
        return None
    og_url = m.group(1)
    found = MICRIO_ID_RE.search(og_url)
    return found.group(1) if found else None


def iiif_info_url(micrio_id: str) -> str:
    return f"https://iiif.micr.io/{micrio_id}/info.json"


def iiif_max_image_url(micrio_id: str, fmt: str = "jpg") -> str:
    """Single-request maximum-resolution image URL (IIIF Image API 3.0).

    Faster and simpler than running dezoomify-rs against the tile pyramid.
    Use dezoomify-rs only when info.json reports a max smaller than the
    real underlying image (rare on Micrio; common on older IIIF servers).
    """
    return f"https://iiif.micr.io/{micrio_id}/full/max/0/default.{fmt}"


def iiif_max_curl_command(micrio_id: str, out_path: str) -> list[str]:
    """Preferred acquisition: a single curl to the IIIF max endpoint.

    For Rijksmuseum's Micrio-backed IIIF this returns the same bytes a
    full dezoomify-rs tile-stitching run would produce, in one HTTPS request.
    32 MP / ~8 MB for SK-A-2860 in under a second.
    """
    return ["curl", "-sL", "-A", "Mozilla/5.0", "-o", out_path, iiif_max_image_url(micrio_id)]


def dezoomify_command(
    obj: RijksmuseumObject, out_path: str, max_retries: int = 3, tile_storage: str | None = None
) -> list[str]:
    """Fallback: dezoomify-rs against the object page.

    Use only when iiif_max_image_url returns a smaller-than-expected image
    (some IIIF servers cap `/full/max/`). Slower but robust on edge cases.
    """
    cmd = ["dezoomify-rs", "--retries", str(max_retries)]
    if tile_storage:
        cmd.extend(["--tile-storage", tile_storage])
    cmd.extend([obj.web_url, out_path])
    return cmd


def acquire_shell_script(obj: RijksmuseumObject, out_path: str) -> str:
    """A bash script that does the full acquisition from scratch.

    Pipeline:
      1. curl the object page HTML.
      2. Extract the og:image meta tag (canonical pointer to the main work).
      3. Extract the Micrio ID from that URL.
      4. curl the IIIF max-resolution endpoint for that ID into out_path.
      5. shasum + file for verification.

    Driven via osascript `do shell script` from the orchestrator. Returns
    the script string; the caller invokes it.
    """
    out = shlex.quote(out_path)
    obj_q = shlex.quote(obj.web_url)
    return f"""set -e
HTML=$(curl -sL -A 'Mozilla/5.0' {obj_q})
OG_URL=$(echo "$HTML" | grep -oE '<meta property="og:image" content="[^"]+"' | head -1 | sed -E 's/.*content="([^"]+)".*/\\1/')
if [ -z "$OG_URL" ]; then
  echo "FAILED to find og:image" >&2
  exit 2
fi
MICRIO_ID=$(echo "$OG_URL" | grep -oE 'iiif\\.micr\\.io/[A-Za-z0-9]+' | head -1 | sed 's|iiif\\.micr\\.io/||')
if [ -z "$MICRIO_ID" ]; then
  echo "FAILED to find Micrio ID in $OG_URL" >&2
  exit 3
fi
echo "Micrio ID: $MICRIO_ID"
echo "IIIF URL:  https://iiif.micr.io/$MICRIO_ID/full/max/0/default.jpg"
curl -sL -A 'Mozilla/5.0' -w 'HTTP %{{http_code}} %{{size_download}} bytes in %{{time_total}}s\\n' \\
     -o {out} "https://iiif.micr.io/$MICRIO_ID/full/max/0/default.jpg"
file {out}
shasum -a 256 {out}
"""


# Tags inferred from object metadata when we have it. The collector populates
# this dict with whatever the API returns; the rest is heuristic at the
# enrichment step.
def normalize_metadata(api_json: dict) -> dict:
    """Project a Rijksmuseum collection-API response into our sidecar shape.

    Args:
        api_json: The parsed JSON of
            https://www.rijksmuseum.nl/api/en/collection/<obj>?format=json
            The Rijksmuseum response wraps the work under `artObject`.

    Returns: a partial sidecar dict, suitable for merging with the canonical
    skeleton built by scripts/collect_work.py.
    """
    a = api_json.get("artObject", api_json)
    title = a.get("title") or a.get("longTitle", "")
    artist = a.get("principalOrFirstMaker") or ""
    year = a.get("dating", {}).get("presentingDate") if isinstance(a.get("dating"), dict) else None
    year_min = a.get("dating", {}).get("yearEarly") if isinstance(a.get("dating"), dict) else None
    year_max = a.get("dating", {}).get("yearLate") if isinstance(a.get("dating"), dict) else None

    medium = None
    materials = a.get("materials") or []
    techniques = a.get("techniques") or []
    if materials and techniques:
        medium = f"{', '.join(techniques)} on {', '.join(materials)}"
    elif materials:
        medium = ", ".join(materials)

    dims_raw = a.get("subTitle") or ""  # Rijksmuseum uses subTitle for dimensions
    return {
        "title": title,
        "artist": artist,
        "year": year,
        "year_min": year_min,
        "year_max": year_max,
        "medium": medium,
        "dimensions_raw": dims_raw,
        "rijksmuseum_object_number": a.get("objectNumber"),
        "rijksmuseum_web_url": a.get("webImage", {}).get("url"),
        "rijksmuseum_long_title": a.get("longTitle"),
        "rijksmuseum_label": (a.get("label") or {}).get("description"),
        "rijksmuseum_plaque_description_english": a.get("plaqueDescriptionEnglish"),
    }
