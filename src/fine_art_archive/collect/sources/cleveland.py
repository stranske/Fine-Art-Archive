"""Cleveland Museum of Art Open Access collector.

API: https://openaccess-api.clevelandart.org/api/artworks/<accession_number>
IIIF: tile-level IIIF via api.images, plus direct download via images.web.url
       and images.print.url for the high-resolution single-file paths.

Accession numbers are mixed alphanumeric: e.g. "1942.647" (Rouault).
Wikidata property: P9092.

Rights: CC0 for both metadata AND images (most public-domain works).

Cleveland's `wall_description` and `tombstone` fields per work are
genuinely essay-length for major works; capture into sidecar.description_long.
"""

from __future__ import annotations

import shlex
from dataclasses import dataclass

API_BASE = "https://openaccess-api.clevelandart.org/api/artworks"


@dataclass(frozen=True)
class ClevelandObject:
    accession: str  # e.g. "1942.647"

    @property
    def web_url(self) -> str:
        return f"https://www.clevelandart.org/art/{self.accession}"

    @property
    def metadata_api_url(self) -> str:
        return f"{API_BASE}/{self.accession}"


def acquire_shell_script(
    obj: ClevelandObject, out_path: str, title: str | None = None, artist: str | None = None
) -> str:
    """Bash script to acquire the highest-resolution Cleveland image.

    Strategy:
      1. Try the direct lookup at /api/artworks/<accession>.
      2. If that 404s AND title+artist are provided, fall back to
         /api/artworks?title=<title>&q=<artist> to find the real
         accession_number. (Wikidata P9092 is unreliable; see
         host_registry.yaml#cleveland_museum_of_art.known_issues.)
      3. Prefer `images.print.url` (largest variant), fall back to `web`.

    Cleveland doesn't expose IIIF /full/max/ directly, but its direct-image
    URLs serve full-resolution.
    """
    out_q = shlex.quote(out_path)
    return f"""set -e
mkdir -p "$(dirname {out_q})"
python3 <<'PYEOF'
import json, sys, urllib.parse, urllib.request
ACC = {obj.accession!r}
TITLE = {title or ""!r}
ARTIST = {artist or ""!r}

def fetch_artwork(acc):
    url = 'https://openaccess-api.clevelandart.org/api/artworks/' + acc
    req = urllib.request.Request(url, headers={{'User-Agent':'Mozilla/5.0 (Fine-Art-Archive)'}})
    return json.loads(urllib.request.urlopen(req, timeout=30).read()).get('data', {{}})

def search_artwork(title, artist):
    params = {{
        'title': title,
        'limit': 5,
        'has_image': 1,
        'cc0': 1,
    }}
    if artist:
        params['q'] = artist
    url = 'https://openaccess-api.clevelandart.org/api/artworks/?' + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={{'User-Agent':'Mozilla/5.0'}})
    res = json.loads(urllib.request.urlopen(req, timeout=30).read())
    hits = res.get('data', [])
    if not hits:
        return None
    # Prefer exact title match
    for h in hits:
        if (h.get('title') or '').strip().lower() == title.strip().lower():
            return h
    return hits[0]

# Phase 1: direct lookup
d = None
try:
    d = fetch_artwork(ACC)
except urllib.error.HTTPError as e:
    if e.code != 404:
        raise
    print(f'direct lookup 404 for {{ACC!r}}; falling back to title+artist search', file=sys.stderr)

# Phase 2: search fallback when direct lookup fails (or returns empty)
if not d:
    if not TITLE:
        print('no title for fallback search; aborting', file=sys.stderr)
        sys.exit(4)
    print(f'searching: title={{TITLE!r}} artist={{ARTIST!r}}', file=sys.stderr)
    hit = search_artwork(TITLE, ARTIST)
    if not hit:
        print('no search hits; aborting', file=sys.stderr)
        sys.exit(5)
    acc_canonical = hit.get('accession_number')
    print(f'recovered accession: {{acc_canonical}}', file=sys.stderr)
    d = fetch_artwork(acc_canonical)

share_license = d.get('share_license_status')
if share_license not in ('CC0', 'PUBLIC'):
    print(f'rights status {{share_license!r}} not PD/CC0; aborting', file=sys.stderr)
    sys.exit(6)
images = d.get('images') or {{}}
chosen = (images.get('print') or {{}}).get('url') or (images.get('web') or {{}}).get('url')
if not chosen:
    print('no usable image URL; aborting', file=sys.stderr)
    sys.exit(7)
print(f'title:    {{d.get("title")}}')
print(f'artist:   {{d.get("creators",[{{}}])[0].get("description") if d.get("creators") else "?"}}')
print(f'access:   {{d.get("accession_number")}}')
print(f'dims:     {{d.get("measurements")}}')
print(f'image:    {{chosen}}')
with open('/tmp/cle_master_url', 'w') as f:
    f.write(chosen)
with open('/tmp/cle_accession_resolved', 'w') as f:
    f.write(d.get('accession_number') or '')
PYEOF
URL=$(cat /tmp/cle_master_url)
curl -sL -A 'Mozilla/5.0' -w 'HTTP %{{http_code}} %{{size_download}} bytes in %{{time_total}}s\\n' \\
     -o {out_q} "$URL"
rm -f /tmp/cle_master_url
file {out_q}
shasum -a 256 {out_q}
"""


def normalize_metadata(api_json: dict) -> dict:
    """Project the Cleveland API response into our sidecar shape."""
    d = api_json.get("data", api_json)
    creator = (d.get("creators") or [{}])[0]
    return {
        "title": d.get("title"),
        "title_alternate": (
            [d["title_in_original_language"]] if d.get("title_in_original_language") else []
        ),
        "artist_name": creator.get("description"),
        "year": d.get("creation_date"),
        "year_min": d.get("creation_date_earliest"),
        "year_max": d.get("creation_date_latest"),
        "medium": d.get("technique") or d.get("type"),
        "dimensions_raw": d.get("measurements"),
        "rights_status": (
            "public-domain"
            if d.get("share_license_status") in ("CC0", "PUBLIC")
            else "rights-reserved"
        ),
        "rights_evidence_url": "https://www.clevelandart.org/open-access",
        "holder_name": "Cleveland Museum of Art",
        "holder_wikidata_q": "Q657415",
        "holder_ror": "04em7w569",
        "holder_url": f"https://www.clevelandart.org/art/{d.get('accession_number')}",
        "cleveland_accession": d.get("accession_number"),
        "cleveland_wall_description": d.get("wall_description"),
        "cleveland_tombstone": d.get("tombstone"),
        "cleveland_provenance": d.get("provenance"),
    }
