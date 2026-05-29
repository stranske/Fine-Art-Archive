"""Acquisition flow — wire source collectors, discovery, verify, and quality.

Ties the in-repo ``collect`` modules into one orchestration (issue #4;
DECISIONS D013/D014/D015):

- a **source registry / validation** over the per-institution collectors,
- a **discovery** passthrough (Wikidata-driven candidate enumeration), and
- a **post-fetch assessment** running the verify (identity / aspect) and
  quality (per-device fitness) layers over an acquired master.

The network fetch itself is produced as a shell script by each collector
(``acquire_shell_script``) and run via osascript on a networked host; this
module is the pure-Python glue plus the post-fetch assessment, so it is fully
testable without network access.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

from PIL import Image

from fine_art_archive.collect import discovery
from fine_art_archive.collect.quality import quality_report
from fine_art_archive.collect.sources import (
    artic,
    cleveland,
    google_arts_culture,
    met,
    rijksmuseum,
)
from fine_art_archive.collect.verify import verify

# Source name -> collector module. Each collector exposes acquire_shell_script().
SOURCE_COLLECTORS: dict[str, ModuleType] = {
    "met": met,
    "rijksmuseum": rijksmuseum,
    "cleveland": cleveland,
    "artic": artic,
    "google_arts_culture": google_arts_culture,
}


def get_collector(source: str) -> ModuleType:
    """Return the collector module for ``source`` or raise ``ValueError``."""
    try:
        return SOURCE_COLLECTORS[source]
    except KeyError:
        known = ", ".join(sorted(SOURCE_COLLECTORS))
        raise ValueError(f"unknown source {source!r}; known sources: {known}") from None


def plan_discovery(qid: str, out_path: str) -> str:
    """Discovery stage: a bash script that enumerates candidate sources for a
    work's Wikidata Q-ID (run via osascript on a networked host)."""
    return discovery.discovery_shell_script(qid, out_path)


@dataclass
class AcquisitionAssessment:
    """Verify + quality + per-device fitness for one acquired master."""

    work_dir: Path
    source: str
    verification: dict
    quality: dict
    fitness: dict


def assess_master(
    master_path: Path,
    *,
    source: str,
    h_cm: float | None = None,
    w_cm: float | None = None,
    reference_path: Path | None = None,
) -> AcquisitionAssessment:
    """Run verify (Layer 1 aspect; Layer 2 pHash when a reference is supplied)
    and quality (per-device fitness) over an acquired master."""
    master_path = Path(master_path)
    with Image.open(master_path) as img:
        w_px, h_px = img.size
    has_ref = reference_path is not None and Path(reference_path).exists()
    vreport = verify(
        h_cm=h_cm,
        w_cm=w_cm,
        h_px=h_px,
        w_px=w_px,
        candidate_path=master_path if has_ref else None,
        reference_path=reference_path if has_ref else None,
    )
    qd = quality_report(master_path, h_cm=h_cm, w_cm=w_cm).to_dict()
    fitness = qd.pop("fitness", {})
    return AcquisitionAssessment(
        work_dir=master_path.parent,
        source=source,
        verification=vreport.to_dict(),
        quality=qd,
        fitness=fitness,
    )


def run_acquisition_flow(
    source: str,
    work_dirs: list[Path],
    *,
    max_items: int | None = None,
) -> list[AcquisitionAssessment]:
    """Assess a batch of ``source`` acquisitions through verify + quality.

    Each entry in ``work_dirs`` is a directory holding ``master.jpg`` and an
    optional ``meta.json`` carrying ``dimensions_original`` (h_cm/w_cm). The
    source name is validated first; directories without a master are skipped.
    """
    get_collector(source)  # validate the source up front
    selected = work_dirs if max_items is None else work_dirs[:max_items]
    results: list[AcquisitionAssessment] = []
    for raw in selected:
        wd = Path(raw)
        master = wd / "master.jpg"
        if not master.exists():
            continue
        h_cm: float | None = None
        w_cm: float | None = None
        meta_p = wd / "meta.json"
        if meta_p.exists():
            dim = json.loads(meta_p.read_text()).get("dimensions_original") or {}
            h_cm, w_cm = dim.get("h_cm"), dim.get("w_cm")
        results.append(assess_master(master, source=source, h_cm=h_cm, w_cm=w_cm))
    return results
