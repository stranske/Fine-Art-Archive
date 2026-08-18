#!/usr/bin/env python3
"""Generate small local thumbnails for the weekly review page.

Why: the page references ~130 masters, several of them 30-250 MB, and some are Dropbox
cloud-only stubs that render as blanks until hydrated. Pointing the page at 480px JPEGs
instead makes it load instantly, removes the hydration dependency, and keeps the whole
review self-contained.

Originals are treated as immutable (CLAUDE.md): this reads them and writes new files into
docs/reports/thumbs_<date>/ only. Nothing in Art/ is modified.

Usage (on the Mac):
    /Users/teacher/.faa-venv/bin/python3 scripts/make_review_thumbs.py --date 2026-08-03
"""

from __future__ import annotations

import argparse
import hashlib
import json
import warnings
from pathlib import Path

from PIL import Image, ImageOps

# This archive legitimately holds gigapixel masters — G24 promoted an 837 MP Judith, and
# one file here decodes to 1.24 gigapixels. PIL's decompression-bomb ceiling is a defence
# against untrusted uploads; these are Tim's own files, read-only, so the ceiling only
# breaks thumbnailing of exactly the works most worth seeing. Lifted deliberately.
Image.MAX_IMAGE_PIXELS = None
warnings.simplefilter("ignore", Image.DecompressionBombWarning)

ROOT = Path(__file__).resolve().parent.parent
REPORTS = ROOT / "docs" / "reports"
MAX_EDGE = 480


def key(path: str) -> str:
    return hashlib.sha1(path.encode()).hexdigest()[:16]


def gather(data: dict) -> list[str]:
    out: list[str] = []
    for rows in data["ungranted"]["by_grant"].values():
        out += [r["master"] for r in rows if r.get("master")]
    for u in data["unpromoted"]:
        out += [p for p in (u.get("staged_master"), u.get("collision_master")) if p]
    for c in data["collisions"]["worst"]:
        out += [x["master"] for x in c["examples"] if x.get("master")]
    return list(dict.fromkeys(out))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    args = ap.parse_args()
    d = args.date

    data = json.loads((REPORTS / f"weekly_review_{d}.json").read_text())
    paths = gather(data)
    tdir = REPORTS / f"thumbs_{d}"
    tdir.mkdir(parents=True, exist_ok=True)

    mapping: dict[str, str] = {}
    ok = skipped = failed = 0
    for i, p in enumerate(paths, 1):
        src = Path(p)
        dst = tdir / f"{key(p)}.jpg"
        if dst.exists():
            mapping[p] = str(dst)
            skipped += 1
            continue
        try:
            with Image.open(src) as im:
                im = ImageOps.exif_transpose(im)
                im.thumbnail((MAX_EDGE, MAX_EDGE))
                if im.mode not in ("RGB", "L"):
                    im = im.convert("RGB")
                im.save(dst, "JPEG", quality=82, optimize=True)
            mapping[p] = str(dst)
            ok += 1
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  ! {src.name}: {type(exc).__name__}: {exc}")
        if i % 20 == 0:
            print(f"  … {i}/{len(paths)}", flush=True)

    (REPORTS / f"thumbmap_{d}.json").write_text(json.dumps(mapping, indent=1))
    total = sum(f.stat().st_size for f in tdir.glob("*.jpg"))
    print(f"thumbnails: {ok} new, {skipped} reused, {failed} failed")
    print(f"thumb dir total: {total/1_048_576:.1f} MB for {len(list(tdir.glob('*.jpg')))} files")
    print(f"wrote {REPORTS / f'thumbmap_{d}.json'}")


if __name__ == "__main__":
    main()
