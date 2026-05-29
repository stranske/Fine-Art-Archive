"""Metropolitan Museum of Art (Met Open Access) collector.

References:
  - Open Access portal:  https://www.metmuseum.org/about-the-met/policies-and-documents/open-access
  - API docs:            https://metmuseum.github.io/
  - API root:            https://collectionapi.metmuseum.org/public/collection/v1/
  - Image CDN:           https://images.metmuseum.org/CRDImages/<dept>/<size>/<image_id>.jpg
  - Object pages:        https://www.metmuseum.org/art/collection/search/<object_id>

The Met API returns metadata with `primaryImage` (the highest-resolution
direct download offered) and `primaryImageSmall` (a smaller variant).
`additionalImages[]` lists detail crops and conservation imagery for some
works.

KNOWN LIMITATION (Tim's empirical experience, confirmed mid-2026):
the Met's `primaryImage` is typically capped around 2000-4000 px on the
long edge — a moderate-quality download by 2026 standards. For large
canvases this maps to low px/cm and unfit-for-display fitness scores.

A 208.6 × 109.9 cm Madame X (Sargent, Met 12127): primaryImage is
2336 × 4000 px = 19 px/cm. For comparison, a Rijksmuseum Micrio IIIF
max for a similarly sized work commonly delivers 7000+ on the long edge
(~70 px/cm at 100 cm physical size).

The collector here returns what the Met provides. Quality assessment
runs downstream; if a Met acquisition fails fitness for the user's
displays, the multi-source discovery layer (Phase 5b) should consult
other sources before committing.

Note: the Met does NOT appear to expose a public IIIF Image API endpoint
under iiif.metmuseum.org (verified May 2026). If they add one, the
acquire_shell_script should be updated to prefer IIIF max over the
primaryImage CDN URL.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass

API_BASE = "https://collectionapi.metmuseum.org/public/collection/v1"


@dataclass(frozen=True)
class MetObject:
    """Stable handle for a Met work."""

    object_id: str  # numeric, e.g. "12127" for Sargent's Madame X

    @property
    def web_url(self) -> str:
        return f"https://www.metmuseum.org/art/collection/search/{self.object_id}"

    @property
    def metadata_api_url(self) -> str:
        return f"{API_BASE}/objects/{self.object_id}"


def acquire_shell_script(obj: MetObject, out_path: str) -> str:
    """Bash script that resolves the Met API to a primaryImage URL and
    downloads it to `out_path`. Driven via osascript do shell script on
    a host with network access to the Met API.

    Pipeline:
      1. GET metadata JSON for the object.
      2. Reject if `isPublicDomain` is false (we don't ingest non-PD works).
      3. Extract `primaryImage`. Fail if absent.
      4. curl that URL to out_path. Verify with `file` and `shasum`.
    """
    out_q = shlex.quote(out_path)
    return f"""set -e
mkdir -p "$(dirname {out_q})"
python3 <<'PYEOF'
import json, urllib.request, sys
OBJ_ID = {obj.object_id!r}
url = 'https://collectionapi.metmuseum.org/public/collection/v1/objects/' + OBJ_ID
req = urllib.request.Request(url, headers={{'User-Agent': 'Mozilla/5.0 (Fine-Art-Archive)'}})
data = json.loads(urllib.request.urlopen(req, timeout=30).read())
if not data.get('isPublicDomain'):
    print(f'OBJECT {{OBJ_ID}} NOT PUBLIC DOMAIN; aborting', file=sys.stderr)
    sys.exit(4)
img = data.get('primaryImage')
if not img:
    print(f'OBJECT {{OBJ_ID}} HAS NO primaryImage; aborting', file=sys.stderr)
    sys.exit(5)
print('primaryImage:', img)
print('title:', data.get('title'))
print('artist:', data.get('artistDisplayName'))
print('dims:', data.get('dimensions'))
# Save the URL for the curl below
with open('/tmp/met_primary_url', 'w') as f:
    f.write(img)
PYEOF
URL=$(cat /tmp/met_primary_url)
curl -sL -A 'Mozilla/5.0 (Fine-Art-Archive)' -w 'HTTP %{{http_code}} %{{size_download}} bytes in %{{time_total}}s\\n' \\
     -o {out_q} "$URL"
rm -f /tmp/met_primary_url
file {out_q}
shasum -a 256 {out_q}
"""


def normalize_metadata(api_json: dict) -> dict:
    """Project the Met API response into our sidecar shape.

    Returns the fields that map to our schema; the caller composes with
    Wikidata-derived enrichment (Q-ID, P18 image, etc.).
    """
    a = api_json
    return {
        "title": a.get("title"),
        "title_alternate": (
            [a["objectName"]] if a.get("objectName") and a["objectName"] != a.get("title") else []
        ),
        "artist_name": a.get("artistDisplayName"),
        "artist_lifespan": (
            f"{a.get('artistBeginDate', '').split('-')[0]}-"
            f"{a.get('artistEndDate', '').split('-')[0]}"
            if a.get("artistBeginDate")
            else None
        ),
        "artist_nationality": a.get("artistNationality"),
        "artist_ulan": (
            (a.get("artistULAN_URL") or "").rstrip("/").split("/")[-1]
            if a.get("artistULAN_URL")
            else None
        ),
        "year": a.get("objectDate"),
        "year_min": (int(a["objectBeginDate"]) if a.get("objectBeginDate") is not None else None),
        "year_max": (int(a["objectEndDate"]) if a.get("objectEndDate") is not None else None),
        "medium": a.get("medium"),
        "dimensions_raw": a.get("dimensions"),
        "rights_status": ("public-domain" if a.get("isPublicDomain") else "rights-reserved"),
        "rights_evidence_url": "https://www.metmuseum.org/about-the-met/policies-and-documents/open-access",
        "holder_name": "The Metropolitan Museum of Art",
        "holder_wikidata_q": "Q160236",
        "holder_ror": "01xtbq813",
        "holder_url": a.get("objectURL"),
        "met_object_id": a.get("objectID"),
        "met_credit_line": a.get("creditLine"),
        "met_department": a.get("department"),
        "met_primary_image_url": a.get("primaryImage"),
        "met_primary_image_small_url": a.get("primaryImageSmall"),
        "met_additional_images": a.get("additionalImages", []),
    }
