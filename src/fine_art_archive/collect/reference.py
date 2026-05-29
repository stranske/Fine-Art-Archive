"""Reference image bootstrap via Wikidata P18 + Wikimedia Commons.

For any work with a Wikidata Q-ID, this resolves the P18 ("image") property
to a Commons file and emits an osascript-runnable shell script that fetches
a display-resolution copy onto local disk. Display-resolution is intentional:
perceptual hash matching doesn't need full resolution and Commons display
copies fetch fast.

The fetch goes through `osascript do shell script` on the user's Mac because
the sandbox doesn't have network access to wikidata.org or commons.wikimedia.org.

Usage from the orchestrator side:

    >>> from fine_art_archive.collect.reference import wikidata_reference_script
    >>> script = wikidata_reference_script("Q586035", "/path/to/reference.jpg")
    >>> # run via osascript do shell script
"""

from __future__ import annotations

import shlex


def wikidata_reference_script(qid: str, out_path: str, width: int = 1024) -> str:
    """Build a bash script that fetches the P18 reference image for a Q-ID.

    The script:
      1. Queries Wikidata's EntityData endpoint for the Q-ID.
      2. Extracts the P18 (image) Commons filename.
      3. URL-encodes it via Python and fetches via Commons Special:FilePath
         with the `width` query parameter for a sensibly-sized copy.
      4. Saves to `out_path`.

    Failures (no P18, network error, malformed JSON) produce non-zero exit
    codes and stderr messages the caller can capture.
    """
    out_q = shlex.quote(out_path)
    return f"""set -e
mkdir -p "$(dirname {out_q})"
python3 <<'PYEOF'
import json, urllib.parse, urllib.request, sys
QID = {qid!r}
OUT = {out_path!r}
WIDTH = {width}
req = urllib.request.Request(
    f'https://www.wikidata.org/wiki/Special:EntityData/{{QID}}.json',
    headers={{'User-Agent': 'Mozilla/5.0 (Fine-Art-Archive verifier)'}}
)
data = json.loads(urllib.request.urlopen(req, timeout=30).read())
ent = data['entities'][QID]
p18 = ent.get('claims', {{}}).get('P18', [])
if not p18:
    print(f'no P18 for {{QID}}', file=sys.stderr)
    sys.exit(4)
fname = p18[0]['mainsnak']['datavalue']['value']
url = ('https://commons.wikimedia.org/wiki/Special:FilePath/'
       + urllib.parse.quote(fname) + f'?width={{WIDTH}}')
print('P18 filename:', repr(fname))
print('URL:', url)
req2 = urllib.request.Request(url, headers={{'User-Agent': 'Mozilla/5.0 (Fine-Art-Archive verifier)'}})
with urllib.request.urlopen(req2, timeout=60) as r, open(OUT, 'wb') as f:
    import shutil
    shutil.copyfileobj(r, f)
import os
print('saved:', OUT, os.path.getsize(OUT), 'bytes')
PYEOF
file {out_q}
"""
