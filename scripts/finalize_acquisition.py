#!/usr/bin/env python3
"""Autonomous post-acquisition finalizer.

Given a sample directory containing `master.jpg` and a draft `meta.json`,
runs the full verification + quality assessment pipeline and writes the
finalized sidecar with `verification`, `quality`, and `fitness` sections
populated. Optionally fetches the Wikidata P18 reference image first (via
osascript+curl on the Mac) when the work has a Wikidata Q-ID and a
reference isn't already present.

Usage:

    # Finalize an existing sample (master.jpg already in place)
    python3 scripts/finalize_acquisition.py samples/0441b1c-the-little-street-vermeer

    # Same, but also fetch the Wikidata P18 reference if missing
    python3 scripts/finalize_acquisition.py samples/<id> --fetch-reference

This script runs entirely in the sandbox (no network needed) once the
master and reference image bytes are already on disk in the sample folder.
The orchestrator-side acquisition (acquire_shell_script + Wikidata fetch)
is a separate step driven via osascript+curl on the Mac.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from datetime import UTC, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "src"))

from PIL import Image  # noqa: E402

from fine_art_archive import sidecar  # noqa: E402
from fine_art_archive.collect.quality import quality_report  # noqa: E402
from fine_art_archive.collect.verify import verify  # noqa: E402


def update_files_master_from_bytes(meta: dict, master_path: Path) -> None:
    """Recompute and persist SHA-256, size, pixel dims, color profile."""
    sha = hashlib.sha256(master_path.read_bytes()).hexdigest()
    size = master_path.stat().st_size
    img = Image.open(master_path)
    dims = list(img.size)
    profile = "ICC profile present" if img.info.get("icc_profile") else "sRGB (no embedded ICC)"
    m = meta["files"]["master"]
    m["sha256"] = sha
    m["size_bytes"] = size
    m["dimensions_px"] = dims
    m["color_profile"] = profile
    m["filename"] = master_path.name
    # Update work_id to reflect real SHA prefix if it was a placeholder
    slug = meta["work_id"].split("-", 1)[1] if "-" in meta["work_id"] else "untitled"
    meta["work_id"] = sidecar.derive_work_id(sha, slug)


def run_finalize(work_dir: Path, *, refetch_master_hash: bool = True) -> dict:
    """Run verify + quality + fitness against the master in `work_dir`.

    Returns the updated meta dict. Writes meta.json on the caller's side.
    """
    meta_path = work_dir / "meta.json"
    master_path = work_dir / "master.jpg"
    if not master_path.exists():
        raise FileNotFoundError(f"no master.jpg at {master_path}")
    meta = sidecar.load(meta_path)

    if refetch_master_hash:
        update_files_master_from_bytes(meta, master_path)

    # --- Identity verification --------------------------------------------
    dim = meta.get("dimensions_original") or {}
    fm = meta["files"]["master"]
    px = fm["dimensions_px"]
    ref_path = (
        work_dir
        / "resources"
        / f"reference_{meta.get('stable_identifiers',{}).get('wikidata_q','none')}.jpg"
    )
    has_ref = ref_path.exists()
    vreport = verify(
        h_cm=dim.get("h_cm"),
        w_cm=dim.get("w_cm"),
        h_px=px[1],
        w_px=px[0],
        candidate_path=master_path if has_ref else None,
        reference_path=ref_path if has_ref else None,
    )

    ts = datetime.now(UTC).isoformat(timespec="seconds")
    meta["verification"] = {
        **vreport.to_dict(),
        "verified_at": ts,
        "verifier_version": "1.0",
        "reference_source": (
            f"wikimedia_commons:Wikidata:{meta.get('stable_identifiers',{}).get('wikidata_q')}#P18"
            if has_ref
            else None
        ),
    }
    meta["verification"]["source_quality_inputs"] = vreport.to_source_quality_inputs()
    # TODO: set acquisition_provenance.source on museum-API acquisitions.

    # --- Display-quality assessment ---------------------------------------
    qreport = quality_report(
        master_path,
        h_cm=dim.get("h_cm"),
        w_cm=dim.get("w_cm"),
    )
    qd = qreport.to_dict()
    meta["fitness"] = qd.pop("fitness")
    meta["quality"] = {**qd, "assessed_at": ts, "assessor_version": "1.0"}

    # --- History event ----------------------------------------------------
    fit_summary = ", ".join(f"{k}:{v}" for k, v in meta["fitness"].items() if v != "unfit")
    history_event = {
        "ts": ts,
        "actor": "claude",
        "op": f"finalize:verify={vreport.overall},quality_assessed",
        "notes": (
            f"verify={vreport.overall}; "
            f"px/cm={qreport.px_per_cm_long:.1f} if known; "
            f"jpeg_q={qreport.jpeg_quality_factor}; "
            f"fft_hf={qreport.fft_highfreq_ratio:.5f}; "
            f"fit_for={fit_summary or 'none'}"
        ),
    }
    meta["history"].append(history_event)

    sidecar.validate(meta)
    sidecar.write(meta_path, meta)
    return meta


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("work_dir", type=Path, help="Path to samples/<work_id>/")
    args = ap.parse_args(argv)

    meta = run_finalize(args.work_dir)

    # Summary print-out
    print(f"✓ {meta['work_id']}")
    print(f"  title:        {meta['title']!r}")
    print(f"  artist:       {meta['artist']['name']!r}")
    print(f"  sha256:       {meta['files']['master']['sha256']}")
    print(
        f"  dimensions:   {meta['files']['master']['dimensions_px']} px"
        f" / {meta['files']['master']['size_bytes']/1e6:.2f} MB"
    )
    print()
    v = meta["verification"]
    print(f"  verification: {v['status']}")
    for c in v.get("checks", []):
        msg = f" — {c['message']}" if c.get("message") else ""
        print(f"    {c['name']}: {c['status']}{msg}")
    print()
    q = meta["quality"]
    print("  quality:")
    print(
        f"    px/cm:        {q.get('px_per_cm_long'):.1f}"
        if q.get("px_per_cm_long")
        else "    px/cm:        N/A"
    )
    print(f"    jpeg Q:       {q.get('jpeg_quality_factor')}")
    print(f"    KB per MP:    {q.get('bytes_per_megapixel')/1000:.1f}")
    print(f"    fft hf ratio: {q.get('fft_highfreq_ratio'):.5f}")
    print(f"    laplacian:    {q.get('laplacian_variance'):.1f}")
    print(f"    notes:        {q.get('notes', [])}")
    print()
    print("  fitness:")
    for dev, status in meta["fitness"].items():
        print(f"    {dev:30}: {status}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
