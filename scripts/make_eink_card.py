#!/usr/bin/env python3
"""Build an e-paper SD card from a playlist query.

    # what would be selected, no files written
    python3 scripts/make_eink_card.py --mood open-air --period golden-age --dry-run

    # write a card
    python3 scripts/make_eink_card.py \
        --artist "Jacob van Ruisdael" --sort year --limit 20 \
        --target gooddisplay-315-diy --out /Volumes/EINK

    # list what is available to filter on
    python3 scripts/make_eink_card.py --list

Reads sidecars from FAA_STAGING_DIR (the app's own metadata root — see
faa_app_data_roots_env) and masters from FAA_ART_WORKS_ROOT, so a card always
reflects what the app shows.

Dry run is the default for --out; you must pass --write to touch the card.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from fine_art_archive.eink import (  # noqa: E402
    MOODS,
    PERIODS,
    TARGETS,
    ExportItem,
    PlaylistSpec,
    build,
    export,
    get_target,
    load_ratings,
)
from fine_art_archive.eink.sdcard import card_free_space  # noqa: E402

STAGING = Path(
    os.environ.get(
        "FAA_STAGING_DIR",
        Path.home() / "Library/CloudStorage/Dropbox/Pictures/Claude Project/staging_sidecars",
    )
).expanduser()
ART = Path(
    os.environ.get(
        "FAA_ART_WORKS_ROOT",
        Path.home() / "Library/CloudStorage/Dropbox/Pictures/Art/works",
    )
).expanduser()
RATINGS = Path(
    os.environ.get(
        "FAA_RATINGS_LOG",
        Path.home() / "Library/CloudStorage/Dropbox/Pictures/Claude Project/data/ratings_log.jsonl",
    )
).expanduser()


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def iter_sidecars():
    for p in sorted(glob.glob(str(STAGING / "*" / "meta.json"))):
        try:
            yield os.path.basename(os.path.dirname(p)), json.loads(Path(p).read_text())
        except (OSError, ValueError) as exc:
            print(f"skipped sidecar {p}: {exc}", file=sys.stderr)
            continue


def master_for(work_id: str) -> Path | None:
    d = ART / work_id
    if not d.is_dir():
        return None
    for ext in ("jpeg", "jpg", "png", "tif", "tiff", "webp"):
        c = d / f"master.{ext}"
        if c.exists():
            return c
    cands = sorted(d.glob("master.*"))
    return cands[0] if cands else None


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--list", action="store_true", help="print available targets, moods, periods and exit"
    )
    ap.add_argument("--artist", action="append", default=[])
    ap.add_argument("--genre", action="append", default=[])
    ap.add_argument("--mood", action="append", default=[])
    ap.add_argument("--period", action="append", default=[])
    ap.add_argument("--year-from", type=int)
    ap.add_argument("--year-to", type=int)
    ap.add_argument(
        "--tag",
        action="append",
        default=[],
        dest="any_tags",
        help="match works with ANY of these tags (repeatable)",
    )
    ap.add_argument("--all-tag", action="append", default=[], dest="all_tags")
    ap.add_argument("--not-tag", action="append", default=[], dest="not_tags")
    ap.add_argument(
        "--exclude-filter",
        action="append",
        default=[],
        help="e.g. nudity-full, violence — drops works carrying it",
    )
    ap.add_argument("--min-fit", type=int)
    ap.add_argument("--min-quality", type=int)
    ap.add_argument("--dossier-only", action="store_true")
    ap.add_argument("--limit", type=positive_int)
    ap.add_argument(
        "--sort",
        default="fit",
        choices=["fit", "quality", "year", "artist", "title", "random", "as-filtered"],
    )
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--target", default="gooddisplay-315-diy", choices=sorted(TARGETS))
    ap.add_argument("--fit", choices=["contain", "cover", "stretch"])
    ap.add_argument(
        "--dither", default="floyd-steinberg", choices=["none", "floyd-steinberg", "atkinson"]
    )
    ap.add_argument(
        "--slow-dither",
        action="store_true",
        help="use the NumPy serpentine path (250x slower, no "
        "measured benefit — see palette.quantize)",
    )
    ap.add_argument("--format", default="png", choices=["png", "bmp", "jpg"])
    ap.add_argument("--no-range-compress", action="store_true")
    ap.add_argument("--out", type=Path, help="card root directory")
    ap.add_argument(
        "--write", action="store_true", help="actually write files (default is a dry run)"
    )
    ap.add_argument(
        "--overwrite", action="store_true", help="replace files a previous export wrote"
    )
    a = ap.parse_args()

    if a.list:
        print("RENDER TARGETS")
        for k, t in TARGETS.items():
            print(f"  {k:24} {t.width}x{t.height:<6} {t.palette_name:9} {t.label}")
        print("\nMOODS (named queries over existing tags)")
        for k, v in MOODS.items():
            bits = []
            if v.get("any_tags"):
                bits.append("any " + ",".join(v["any_tags"]))
            if v.get("genres"):
                bits.append("genre " + ",".join(v["genres"]))
            if v.get("not_tags"):
                bits.append("not " + ",".join(v["not_tags"]))
            print(f"  {k:18} {v['label']:22} {'; '.join(bits)}")
        print("\nPERIODS")
        for k, (label, lo, hi) in PERIODS.items():
            print(f"  {k:18} {label:28} {lo}-{hi}")
        return 0

    spec = PlaylistSpec(
        artists=a.artist,
        genres=a.genre,
        moods=a.mood,
        periods=a.period,
        year_from=a.year_from,
        year_to=a.year_to,
        any_tags=a.any_tags,
        all_tags=a.all_tags,
        not_tags=a.not_tags,
        exclude_filters=a.exclude_filter,
        min_fit=a.min_fit,
        min_quality=a.min_quality,
        require_dossier=a.dossier_only,
        limit=a.limit,
        sort=a.sort,
        seed=a.seed,
    )

    sidecars = list(iter_sidecars())
    dossier_ids = {
        wid for wid, sc in sidecars if isinstance(sc.get("dossier"), dict) and sc["dossier"]
    }
    res = build(sidecars, spec, ratings=load_ratings(RATINGS), dossier_ids=dossier_ids)

    print(
        f"candidates {res.total_candidates}  matched {res.matched}"
        f"  selected {len(res.work_ids)}"
    )
    if res.coverage["excluded_for_missing_metadata"]:
        print(
            "  dropped for missing metadata: "
            + ", ".join(
                f"{k}={v}" for k, v in res.coverage["excluded_for_missing_metadata"].items()
            )
        )
    if res.facets["genre"]:
        print("  genres: " + ", ".join(f"{g}({n})" for g, n in res.facets["genre"][:6]))
    if res.facets["artist"]:
        print("  artists: " + ", ".join(f"{g}({n})" for g, n in res.facets["artist"][:5]))

    by_id = dict(sidecars)
    items = []
    # Display the CANONICAL artist name, the same one the filter matched on.
    # The raw `artist.name` field holds whatever the source wrote -- the 14
    # Ruisdael works carry "Jacob von Ruisdael", "van Ruisdael",
    # "Ruisdael, Jacob Isaacksz v..." -- so printing it makes a correct
    # canonical match look like a broken one.
    from fine_art_archive.eink.playlist import _artist_of, parse_year

    for wid in res.work_ids:
        sc = by_id.get(wid) or {}
        items.append(
            ExportItem(
                work_id=wid,
                title=sc.get("title") or "",
                artist=_artist_of(sc),
                year=parse_year(sc.get("year")),
            )
        )

    for it in items[:12]:
        print(f"    {it.year or '????'}  {it.artist[:26]:26} {it.title[:44]}")
    if len(items) > 12:
        print(f"    … and {len(items) - 12} more")

    if not a.out:
        print("\nNo --out given, so nothing to write. Add --out <dir> --write.")
        return 0

    target = get_target(a.target)
    free = card_free_space(a.out)
    if free:
        print(f"\ncard volume free: {free['free'] / 1e9:.1f} GB")
    print(
        f"target: {target.label}  {target.width}x{target.height}  "
        f"palette={target.palette_name} "
        f"({'MEASURED' if target.palette.measured else 'ESTIMATED — see docs'})"
    )

    def progress(i, n, wid):
        print(f"  [{i}/{n}] {wid[:52]}", flush=True)

    try:
        rep = export(
            items,
            a.out,
            target,
            master_for=master_for,
            fmt=a.format,
            method=a.dither,
            fit=a.fit,
            compress_range=not a.no_range_compress,
            fast=not a.slow_dither,
            overwrite=a.overwrite,
            dry_run=not a.write,
            spec=spec.__dict__,
            progress=progress if a.write else None,
        )
    except (FileExistsError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    d = rep.as_dict()
    print(
        f"\n{'WROTE' if a.write else 'WOULD WRITE'} {d['written']} file(s)"
        + (f", {d['bytes_written'] / 1e6:.1f} MB" if a.write else "")
    )
    if d["skipped"]:
        print(
            f"  skipped {d['skipped']}: "
            + "; ".join(f"{w} ({why})" for w, why in d["skipped_detail"][:6])
        )
    if not a.write:
        print("  pass --write to create the card")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
