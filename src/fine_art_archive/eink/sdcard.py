"""Write a playlist to an SD card as files a panel will actually play.

Why SD card is worth first-class support
----------------------------------------
It is the one ingest path shared by every open device in the survey, it needs no
network and no vendor cloud, and it keeps working after a vendor folds. Good
Display's DEAM-315E1 kit boots straight off a hot-swappable card; MEiNK, SEEKINK
and Digital View all take USB/SD images; the DIY 31.5" route is card-first by
design. So a card is the lowest-common-denominator deliverable, and it is
testable on a desk today with no hardware at all.

Layout, and why filenames look like this
----------------------------------------
    <root>/
        001_bfcc959-dunes-by-the-sea-ruisdael.png
        002_d1e8260-pieter-bruegel-egypt.png
        ...
        playlist.json      full provenance: spec, order, render settings
        playlist.m3u       plain-text order, for anything that reads one
        README.txt         what this card is, in human words

Firmware that plays a folder almost always sorts lexicographically, so the
zero-padded ordinal prefix IS the play order — it is not decoration. The work_id
stays in the name so a file on a card can always be traced back to a record.

Safety
------
Writing to a removable volume is easy to get wrong in a way that costs someone
their photos, so:
  * the target directory is created if absent but NEVER recursively deleted;
  * an existing card is only touched with `overwrite=True`, and even then only
    files matching this tool's own `NNN_<wid>.<ext>` pattern plus its three
    manifests are removed — anything else on the card is left alone;
  * a dry run reports exactly what would be written before anything is.
"""
from __future__ import annotations

import contextlib
import json
import re
import shutil
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image

from .targets import RenderTarget, coerce_fit, render_for_target

OURS_RE = re.compile(r"^\d{3,5}_[A-Za-z0-9._-]+\.(png|bmp|jpg|jpeg)$")
MANIFESTS = ("playlist.json", "playlist.m3u", "README.txt")


@dataclass
class ExportItem:
    work_id: str
    title: str = ""
    artist: str = ""
    year: int | None = None


@dataclass
class ExportReport:
    written: list[str] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    bytes_written: int = 0
    dry_run: bool = True

    def as_dict(self) -> dict:
        return {
            "written": len(self.written), "skipped": len(self.skipped),
            "removed": len(self.removed), "bytes_written": self.bytes_written,
            "dry_run": self.dry_run,
            "skipped_detail": self.skipped[:20],
        }


def _reclaimable(root: Path) -> list[Path]:
    """Files on the card this tool is allowed to replace."""
    if not root.is_dir():
        return []
    return [
        p for p in sorted(root.iterdir())
        if p.is_file() and (OURS_RE.match(p.name) or p.name in MANIFESTS)
    ]


def export(
    items: Iterable[ExportItem],
    root: Path,
    target: RenderTarget,
    *,
    master_for: Callable[[str], Path | None],
    fmt: str = "png",
    method: str = "floyd-steinberg",
    fit: str | None = None,
    compress_range: bool = True,
    fast: bool = True,
    overwrite: bool = False,
    dry_run: bool = True,
    spec: dict | None = None,
    progress: Callable[[int, int, str], None] | None = None,
) -> ExportReport:
    """Render each item for `target` and write an ordered, playable card."""
    items = list(items)
    rep = ExportReport(dry_run=dry_run)
    fmt = fmt.lower().lstrip(".")
    if fmt not in ("png", "bmp", "jpg", "jpeg"):
        raise ValueError(f"unsupported format {fmt!r}")

    existing = _reclaimable(root)
    if existing and not overwrite:
        raise FileExistsError(
            f"{root} already holds {len(existing)} file(s) from a previous "
            f"export. Pass overwrite=True to replace them (other files on the "
            f"card are never touched)."
        )

    if not dry_run:
        root.mkdir(parents=True, exist_ok=True)
        for p in existing:
            p.unlink()
            rep.removed.append(p.name)

    manifest_items: list[dict[str, object]] = []
    width = max(3, len(str(len(items))))
    for i, it in enumerate(items, 1):
        master = master_for(it.work_id)
        if master is None or not Path(master).exists():
            rep.skipped.append((it.work_id, "no local master image"))
            continue
        name = f"{i:0{width}d}_{it.work_id}.{fmt}"
        dest = root / name
        if progress:
            progress(i, len(items), it.work_id)
        if not dry_run:
            try:
                with Image.open(master) as im:
                    # Decode gigapixel masters at reduced scale: draft() lets the
                    # JPEG decoder skip DCT levels, which is the difference
                    # between seconds and minutes on a 600 MB master.
                    # draft() is a JPEG-only optimisation; a PNG or TIFF
                    # master simply has no DCT levels to skip.
                    with contextlib.suppress(Exception):
                        im.draft("RGB", (target.width * 2, target.height * 2))
                    out = render_for_target(
                        im, target, fit=coerce_fit(fit), method=method,
                        compress_range=compress_range, fast=fast,
                    )
                    # JPEG is the only format here that takes a quality
                    # setting; PNG/BMP reject the kwarg outright.
                    if fmt in ("jpg", "jpeg"):
                        out.save(dest, quality=95)
                    else:
                        out.save(dest)
            except Exception as exc:                      # noqa: BLE001
                rep.skipped.append((it.work_id, f"render failed: {exc}"))
                continue
            rep.bytes_written += dest.stat().st_size
        rep.written.append(name)
        manifest_items.append({
            "order": i, "file": name, "work_id": it.work_id,
            "title": it.title, "artist": it.artist, "year": it.year,
        })

    manifest = {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "target": target.as_dict(),
        "render": {
            "dither": method, "fit": fit or target.fit,
            "range_compressed": compress_range, "format": fmt,
            "fast_dither": fast,
        },
        "palette_measured": target.palette.measured,
        "palette_warning": (
            None if target.palette.measured else
            "Palette values are ESTIMATES, not measurements. No vendor "
            "publishes a colour profile at these sizes. Colours on the panel "
            "will differ until the palette is measured on real hardware."
        ),
        "playlist_spec": spec or {},
        "count": len(manifest_items),
        "items": manifest_items,
    }

    if not dry_run and manifest_items:
        (root / "playlist.json").write_text(json.dumps(manifest, indent=2))
        (root / "playlist.m3u").write_text(
            "\n".join(str(m["file"]) for m in manifest_items) + "\n"
        )
        (root / "README.txt").write_text(
            "Fine Art Archive — e-paper playlist card\n"
            "=======================================\n\n"
            f"Generated : {manifest['generated_at']}\n"
            f"Target    : {target.label} ({target.width}x{target.height})\n"
            f"Works     : {len(manifest_items)}\n"
            f"Dither    : {method}\n\n"
            "Files are named NNN_<work-id> so that a panel which plays a folder\n"
            "in filename order plays them in the intended order.\n\n"
            "playlist.json carries the full selection and render provenance.\n\n"
            + ("NOTE: the colour palette used here is ESTIMATED, not measured.\n"
               "No vendor publishes a colour profile for panels this size, so\n"
               "on-panel colour will differ from the preview until the palette\n"
               "is measured on real hardware.\n" if not target.palette.measured else "")
        )

    return rep


def card_free_space(root: Path) -> dict[str, int] | None:
    """Free space on the volume holding `root`, for a pre-flight check."""
    probe = root if root.exists() else root.parent
    if not probe.exists():
        return None
    u = shutil.disk_usage(probe)
    return {"total": u.total, "used": u.used, "free": u.free}
