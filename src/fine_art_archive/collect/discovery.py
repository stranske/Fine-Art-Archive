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

import shlex

# Wikidata property → source mapping. Each entry is a (property_id, source_id,
# source_tier, lookup_endpoint_template_or_None). For sources where the
# property's value IS the image URL or filename (like P18 → Commons file),
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


def discovery_shell_script(qid: str, out_path: str) -> str:
    """Bash script that produces a discovery JSON for the given Wikidata Q-ID.

    The script:
      1. Fetches the entity from Wikidata.
      2. For each known source property, extracts the value(s).
      3. Resolves to a candidate URL + claimed resolution where possible
         (Commons imageinfo, Met API primaryImage, Rijksmuseum Micrio via
         og:image, etc.).
      4. Writes a JSON array of candidates to out_path.

    Driven via osascript do shell script on a host with full network.
    """
    out_q = shlex.quote(out_path)
    return f"""set -e
mkdir -p "$(dirname {out_q})"
python3 <<'PYEOF'
import json, urllib.parse, urllib.request, sys, re

QID = {qid!r}
OUT = {out_path!r}

def get_json(url):
    req = urllib.request.Request(url, headers={{'User-Agent':'Mozilla/5.0 (Fine-Art-Archive)'}})
    return json.loads(urllib.request.urlopen(req, timeout=20).read())

def get_text(url):
    req = urllib.request.Request(url, headers={{'User-Agent':'Mozilla/5.0'}})
    return urllib.request.urlopen(req, timeout=20).read().decode('utf-8', errors='replace')

def claim_values(ent, p):
    out = []
    for s in ent.get('claims', {{}}).get(p, []):
        sn = s.get('mainsnak', {{}})
        if sn.get('snaktype') != 'value':
            continue
        v = sn.get('datavalue', {{}}).get('value')
        if isinstance(v, dict):
            out.append(v.get('id') or v.get('amount') or v)
        else:
            out.append(v)
    return out

# 1. Get entity
ent = get_json(f'https://www.wikidata.org/wiki/Special:EntityData/{{QID}}.json')['entities'][QID]
candidates = []

# Commons P18
for fname in claim_values(ent, 'P18'):
    try:
        api = ('https://commons.wikimedia.org/w/api.php?action=query&format=json'
               '&prop=imageinfo&iiprop=size|url|mime&titles='
               + urllib.parse.quote('File:' + fname))
        d = get_json(api)
        for p in d['query']['pages'].values():
            ii = (p.get('imageinfo') or [{{}}])[0]
            candidates.append({{
                'source': 'wikimedia_commons',
                'tier': 2,
                'url': ii.get('url'),
                'width': ii.get('width'),
                'height': ii.get('height'),
                'size_bytes': ii.get('size'),
                'mime': ii.get('mime'),
                'evidence': f'Wikidata P18 → File:{{fname}}',
            }})
    except Exception as e:
        candidates.append({{'source': 'wikimedia_commons', 'error': str(e),
                            'evidence': f'P18 → File:{{fname}}'}})

# Met P3634
for met_id in claim_values(ent, 'P3634'):
    try:
        d = get_json(f'https://collectionapi.metmuseum.org/public/collection/v1/objects/{{met_id}}')
        if d.get('isPublicDomain') and d.get('primaryImage'):
            img = d['primaryImage']
            # HEAD for size
            try:
                hreq = urllib.request.Request(img, method='HEAD', headers={{'User-Agent':'Mozilla/5.0'}})
                hresp = urllib.request.urlopen(hreq, timeout=15)
                sz = int(hresp.headers.get('Content-Length', 0))
            except Exception:
                sz = None
            candidates.append({{
                'source': 'met',
                'tier': 1,
                'url': img,
                'size_bytes': sz,
                'width': None, 'height': None,  # Met doesn't advertise; would need to download
                'evidence': f'Wikidata P3634 → Met {{met_id}}',
                'is_pd': True,
            }})
    except Exception as e:
        candidates.append({{'source': 'met', 'error': str(e)}})

# Rijksmuseum P350: og:image route → Micrio info.json
for rks_id in claim_values(ent, 'P350'):
    try:
        page_url = f'https://www.rijksmuseum.nl/en/collection/{{rks_id}}'
        html = get_text(page_url)
        m = re.search(r'<meta property="og:image" content="([^"]+)"', html)
        if m:
            mid = re.search(r'iiif\\.micr\\.io/([A-Za-z0-9]+)', m.group(1))
            if mid:
                micrio_id = mid.group(1)
                info = get_json(f'https://iiif.micr.io/{{micrio_id}}/info.json')
                candidates.append({{
                    'source': 'rijksmuseum',
                    'tier': 1,
                    'url': f'https://iiif.micr.io/{{micrio_id}}/full/max/0/default.jpg',
                    'width': info.get('width'),
                    'height': info.get('height'),
                    'evidence': f'Wikidata P350 → Rijksmuseum {{rks_id}} → Micrio {{micrio_id}}',
                }})
    except Exception as e:
        candidates.append({{'source': 'rijksmuseum', 'error': str(e)}})

# NGA P5253 (basic): the NGA serves direct image URLs at fixed paths; we
# would need their object page to discover. Marked as "known but unresolved"
# for the demo; the per-source adapter can fill in.
for nga_id in claim_values(ent, 'P5253'):
    candidates.append({{
        'source': 'nga',
        'tier': 1,
        'url': None,
        'evidence': f'Wikidata P5253 → NGA {{nga_id}}; resolver TBD',
    }})

# ARTIC P9173
for artic_id in claim_values(ent, 'P9173'):
    try:
        d = get_json(f'https://api.artic.edu/api/v1/artworks/{{artic_id}}')
        data = d.get('data', {{}})
        iiif_url = data.get('image_id') and f'https://www.artic.edu/iiif/2/{{data[\"image_id\"]}}/full/843,/0/default.jpg'
        # ARTIC's IIIF max is /full/max/0/default.jpg
        if data.get('image_id'):
            iiif_url = f'https://www.artic.edu/iiif/2/{{data[\"image_id\"]}}/full/max/0/default.jpg'
            try:
                info = get_json(f'https://www.artic.edu/iiif/2/{{data[\"image_id\"]}}/info.json')
                w, h = info.get('width'), info.get('height')
            except Exception:
                w = h = None
            candidates.append({{
                'source': 'artic',
                'tier': 1,
                'url': iiif_url,
                'width': w, 'height': h,
                'evidence': f'Wikidata P9173 → ARTIC {{artic_id}}',
            }})
    except Exception as e:
        candidates.append({{'source': 'artic', 'error': str(e)}})

# Cleveland P9092
for clev_id in claim_values(ent, 'P9092'):
    try:
        d = get_json(f'https://openaccess-api.clevelandart.org/api/artworks/{{clev_id}}')
        data = d.get('data', {{}})
        img_url = ((data.get('images') or {{}}).get('web') or {{}}).get('url') or ''
        candidates.append({{
            'source': 'cleveland',
            'tier': 1,
            'url': img_url or None,
            'evidence': f'Wikidata P9092 → Cleveland {{clev_id}}',
        }})
    except Exception as e:
        candidates.append({{'source': 'cleveland', 'error': str(e)}})

# Rank by claimed pixel area (descending); unknowns go last
def score(c):
    w, h = c.get('width'), c.get('height')
    if w and h:
        return w * h
    return -1

candidates.sort(key=lambda c: (score(c), -c.get('tier', 99)), reverse=True)

# Print and save
import os
with open(OUT, 'w') as f:
    json.dump({{'qid': QID, 'candidates': candidates}}, f, indent=2)
print(json.dumps({{'qid': QID, 'candidates': candidates}}, indent=2)[:4000])
PYEOF
"""
