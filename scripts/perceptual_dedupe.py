#!/usr/bin/env python3
"""Perceptual de-duplication for the Fine Art Archive.

Title + artist + file size do NOT uniquely identify an artwork: the same
painting is stored under many official / translated titles and at many
resolutions. This matches works by IMAGE CONTENT using perceptual hashes
(dHash + aHash, 256-bit), which are invariant to resolution, format and
filename and tolerant of mild recompression.

Usage:
  perceptual_dedupe.py build [BUDGET_SECONDS]   # hash archive masters (resumable cache)
  perceptual_dedupe.py match WID [WID ...]      # match staged works vs archive
  perceptual_dedupe.py match-all                # match every staged_acquisitions/<wid>

Cache: archive_phash_cache.json   (wid -> {dhash, ahash, title, size})
Hamming guide (out of 256):  <=10 = same image; <=20 = same work, different
processing/crop; higher = unrelated.  Tune after eyeballing real matches.
"""

from __future__ import annotations

import concurrent.futures as cf
import glob
import json
import os
import sys
import time
from pathlib import Path

from PIL import Image

Image.MAX_IMAGE_PIXELS = None

# Paths derive from this file's location (scripts/ lives at the workspace root),
# so the tool runs unchanged on the Mac and inside the Cowork sandbox mount.
WS = Path(__file__).resolve().parents[1]
ART = WS.parent / "Art" / "works"  # Dropbox/Pictures/Art/works
STAGE = WS / "staging_acquisitions"
SIDE = WS / "staging_sidecars"
CACHE = WS / "archive_phash_cache.json"
HS = 16  # 16x16 -> 256-bit


def _gray(path, target=72):
    im = Image.open(path)
    try:
        im.draft("L", (target, target))  # fast scaled JPEG decode for huge masters
    except Exception:
        pass
    return im.convert("L")


def _hashes(path, hs=HS):
    im = _gray(path)
    gd = im.resize((hs + 1, hs), Image.BILINEAR)
    px = gd.tobytes()
    w = hs + 1
    d = 0
    for r in range(hs):
        base = r * w
        for c in range(hs):
            d = (d << 1) | (1 if px[base + c] < px[base + c + 1] else 0)
    ga = im.resize((hs, hs), Image.BILINEAR)
    pa = ga.tobytes()
    avg = sum(pa) / len(pa)
    a = 0
    for p in pa:
        a = (a << 1) | (1 if p >= avg else 0)
    return d, a


def ham(a, b):
    return bin(a ^ b).count("1")


def master_of(d):
    g = sorted(glob.glob(str(Path(d) / "master.*"))) or sorted(glob.glob(str(Path(d) / "*.jp*g")))
    return g[0] if g else None


def _title(wid):
    for cand in (SIDE / wid / "meta.json", STAGE / wid / "meta.json"):
        if cand.exists():
            try:
                return json.load(open(cand)).get("title") or ""
            except Exception:
                return ""
    return ""


def load_cache():
    if CACHE.exists():
        try:
            return json.load(open(CACHE))
        except Exception:
            return {}
    return {}


def build(budget=40, workers=16):
    cache = load_cache()
    dirs = [d for d in sorted(glob.glob(str(ART / "*"))) if os.path.isdir(d)]
    todo = [d for d in dirs if os.path.basename(d) not in cache]
    t0 = time.time()
    done = 0

    def work(d):
        wid = os.path.basename(d)
        m = master_of(d)
        if not m:
            return wid, {"err": "no-master"}
        try:
            dh, ah = _hashes(m)
            return wid, {
                "dhash": format(dh, "064x"),
                "ahash": format(ah, "064x"),
                "title": _title(wid),
                "size": os.path.getsize(m),
            }
        except Exception as e:
            return wid, {"err": str(e)[:60]}

    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(work, d) for d in todo]
        for f in cf.as_completed(futs):
            wid, rec = f.result()
            cache[wid] = rec
            done += 1
            if time.time() - t0 > budget:
                for ff in futs:
                    ff.cancel()
                break
    json.dump(cache, open(CACHE, "w"))
    total = len(dirs)
    good = sum(1 for v in cache.values() if "dhash" in v)
    print(
        f"build(threaded): +{done} now | hashed {good}/{total} | "
        f"remaining {total - len(cache)} | {time.time() - t0:.1f}s"
    )


def match(wids):
    cache = load_cache()
    arch = [
        (k, int(v["dhash"], 16), int(v["ahash"], 16), v.get("title", ""))
        for k, v in cache.items()
        if "dhash" in v
    ]
    print(f"archive hashed: {len(arch)}")
    for wid in wids:
        m = master_of(STAGE / wid)
        if not m:
            print(f"\n{wid}: NO master file")
            continue
        dh, ah = _hashes(m)
        scored = sorted(
            ((ham(dh, a), ham(ah, aa), k, t) for (k, a, aa, t) in arch), key=lambda x: x[0] + x[1]
        )
        print(f"\n=== {wid}  ({_title(wid)})")
        for hd, hax, k, t in scored[:5]:
            tag = "DUP " if hd <= 10 else ("near" if hd <= 20 else "    ")
            print(f"   dHam={hd:3} aHam={hax:3} {tag} {k[:44]:44} {t[:34]}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)
    cmd = sys.argv[1]
    if cmd == "build":
        build(int(sys.argv[2]) if len(sys.argv) > 2 else 40)
    elif cmd == "match":
        match(sys.argv[2:])
    elif cmd == "match-all":
        match(
            [os.path.basename(d) for d in sorted(glob.glob(str(STAGE / "*"))) if os.path.isdir(d)]
        )
    else:
        print("unknown cmd", cmd)
        sys.exit(2)
