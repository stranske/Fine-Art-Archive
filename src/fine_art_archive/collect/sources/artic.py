"""Art Institute of Chicago (ARTIC) Open Access collector.

API: https://api.artic.edu/api/v1/artworks/<id>
IIIF Image API 2.0 at https://www.artic.edu/iiif/2/<image_id>/info.json
                       /full/max/0/default.jpg for the maximum-resolution single
                       request (typically 2000-6000 px on the long edge for
                       public-domain works).

Critically: ARTIC has the longest curatorial descriptions of any major US
museum (CC-BY field `description`). Capture and store in
sidecar.description_long during ingest. This is one of the strongest
sources for narrative metadata.

Object IDs are numeric (e.g. 11723 for Cassatt's "The Child's Bath").
Wikidata property: P9173.

Rights: CC0 metadata; image rights per object (is_public_domain field).
"""

from __future__ import annotations

from dataclasses import dataclass

from fine_art_archive.collect.sources._shared import (
    holder_fields,
    render_image_acquire_shell,
    year_fields,
)

API_BASE = "https://api.artic.edu/api/v1/artworks"


@dataclass(frozen=True)
class ARTICObject:
    object_id: str

    @property
    def web_url(self) -> str:
        return f"https://www.artic.edu/artworks/{self.object_id}"

    @property
    def metadata_api_url(self) -> str:
        return f"{API_BASE}/{self.object_id}"


def acquire_shell_script(
    obj: ARTICObject, out_path: str, title: str | None = None, artist: str | None = None
) -> str:
    """Bash script to acquire the IIIF max-resolution master.

    Pipeline:
      1. Try direct lookup at /api/v1/artworks/<object_id>.
      2. If 404 (or no P9173 in Wikidata for this work), fall back to
         /api/v1/artworks/search?q=<title>+<artist>&query[term][is_public_domain]=true
         to find the real ARTIC object ID.
      3. Verify is_public_domain.
      4. curl /iiif/2/<image_id>/full/max/0/default.jpg to out_path.
    """
    obj_id = obj.object_id
    python_body = f"""
import json, sys, urllib.parse, urllib.request, urllib.error
OBJ_ID = {obj_id!r}
TITLE = {title or ""!r}
ARTIST = {artist or ""!r}

def get(url):
    req = urllib.request.Request(url, headers={{'User-Agent':'Mozilla/5.0 (Fine-Art-Archive)'}})
    return json.loads(urllib.request.urlopen(req, timeout=30).read())

def fetch_artwork(oid):
    return get('https://api.artic.edu/api/v1/artworks/' + str(oid)).get('data', {{}})

def search(title, artist):
    q = (title + ' ' + (artist or '')).strip()
    params = {{
        'q': q,
        'limit': 8,
        'fields': 'id,title,artist_title,is_public_domain,image_id,date_display',
    }}
    res = get('https://api.artic.edu/api/v1/artworks/search?' + urllib.parse.urlencode(params))
    hits = res.get('data', [])
    if not hits: return None
    # Prefer exact title match where artist label contains the requested artist
    title_lc = title.strip().lower()
    artist_lc = (artist or '').strip().lower()
    for h in hits:
        if ((h.get('title') or '').strip().lower() == title_lc
                and (not artist_lc or artist_lc.split()[-1] in (h.get('artist_title') or '').lower())):
            return h
    return hits[0]

# Phase 1: direct lookup (only if OBJ_ID looks numeric — Q-IDs were a fallback signal)
d = None
if OBJ_ID and not OBJ_ID.startswith('Q'):
    try:
        d = fetch_artwork(OBJ_ID)
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
        print(f'direct lookup 404 for {{OBJ_ID!r}}; falling back to search', file=sys.stderr)
else:
    print(f'OBJ_ID {{OBJ_ID!r}} is not numeric; going straight to search', file=sys.stderr)

# Phase 2: search fallback
if not d:
    if not TITLE:
        print('no title for fallback search; aborting', file=sys.stderr)
        sys.exit(4)
    hit = search(TITLE, ARTIST)
    if not hit:
        print('no search hits; aborting', file=sys.stderr)
        sys.exit(5)
    print(f'recovered: id={{hit.get("id")}} title={{hit.get("title")!r}} artist={{hit.get("artist_title")!r}}', file=sys.stderr)
    d = fetch_artwork(hit['id'])

if not d.get('is_public_domain'):
    print('NOT PUBLIC DOMAIN; aborting', file=sys.stderr)
    sys.exit(6)
image_id = d.get('image_id')
if not image_id:
    print('NO image_id; aborting', file=sys.stderr)
    sys.exit(7)
print(f'title:   {{d.get("title")}}')
print(f'artist:  {{d.get("artist_display") or d.get("artist_title")}}')
print(f'dims:    {{d.get("dimensions")}}')
print(f'image_id: {{image_id}}')
try:
    info = get(f'https://www.artic.edu/iiif/2/{{image_id}}/info.json')
    print(f'IIIF max: {{info.get("width")}} x {{info.get("height")}} px')
except Exception as e:
    print(f'info.json fetch failed: {{e}}', file=sys.stderr)
with open('/tmp/artic_master_url', 'w') as f:
    f.write(f'https://www.artic.edu/iiif/2/{{image_id}}/full/max/0/default.jpg')
"""
    return render_image_acquire_shell(
        out_path=out_path,
        python_body=python_body,
        temp_url_path="/tmp/artic_master_url",
    )


def normalize_metadata(api_json: dict) -> dict:
    """Project the ARTIC API response into our sidecar shape."""
    d = api_json.get("data", api_json)
    return {
        "title": d.get("title"),
        "title_alternate": (
            [d["alt_titles"]]
            if isinstance(d.get("alt_titles"), str)
            else (d.get("alt_titles") or [])
        ),
        "artist_name": d.get("artist_display") or d.get("artist_title"),
        **year_fields(
            year=d.get("date_display"),
            year_min=d.get("date_start"),
            year_max=d.get("date_end"),
        ),
        "medium": d.get("medium_display") or d.get("classification_title"),
        "dimensions_raw": d.get("dimensions"),
        "rights_status": ("public-domain" if d.get("is_public_domain") else "rights-reserved"),
        "rights_evidence_url": "https://www.artic.edu/image-licensing",
        **holder_fields(
            name="Art Institute of Chicago",
            wikidata_q="Q239303",
            ror="03kyqs312",
            url=f"https://www.artic.edu/artworks/{d.get('id')}",
        ),
        "artic_object_id": d.get("id"),
        "artic_image_id": d.get("image_id"),
        "artic_credit_line": d.get("credit_line"),
        "artic_description": d.get("description") or d.get("publication_history"),
        "artic_thumbnail_alt": (d.get("thumbnail") or {}).get("alt_text"),
    }
