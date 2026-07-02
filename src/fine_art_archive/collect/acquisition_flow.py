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
import logging
import math
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

from PIL import Image

from fine_art_archive.collect import discovery, host_registry
from fine_art_archive.collect.dedup_cascade import (
    ArchiveEntry,
    DedupVerdict,
    build_candidate,
    dedup_check,
)
from fine_art_archive.collect.quality import quality_report
from fine_art_archive.collect.sources import (
    artic,
    cleveland,
    google_arts_culture,
    met,
    rijksmuseum,
)
from fine_art_archive.collect.verify import verify
from fine_art_archive.quality import source_quality

SOURCE_QUALITY_PATH = Path(__file__).resolve().parents[3] / "config" / "source_quality.yaml"
HOST_REGISTRY_PATH = Path(__file__).resolve().parents[3] / "config" / "host_registry.yaml"
LOGGER = logging.getLogger(__name__)

# Source name -> collector module. Each collector exposes acquire_shell_script().
SOURCE_COLLECTORS: dict[str, ModuleType] = {
    "met": met,
    "rijksmuseum": rijksmuseum,
    "cleveland": cleveland,
    "artic": artic,
    "google_arts_culture": google_arts_culture,
}

SOURCE_ALIASES = {
    "cleveland_museum_of_art": "cleveland",
    "art_institute_chicago": "artic",
}


def _collector_key(source: str) -> str:
    return SOURCE_ALIASES.get(source, source)


def _source_quality_score(source: str, work_class: str, aggregates: dict) -> float:
    sources = aggregates.get("sources", {})
    if source in sources:
        return source_quality.score_for(source, work_class, aggregates=aggregates)
    collector_key = _collector_key(source)
    return source_quality.score_for(collector_key, work_class, aggregates=aggregates)


def load_source_quality_config(path: Path | None = None) -> dict:
    """Load source quality routing config, failing loudly when it is absent."""
    p = path or SOURCE_QUALITY_PATH
    if not p.exists():
        raise FileNotFoundError(f"source-quality config not found: {p}")
    aggregates = source_quality.load_aggregates(p)
    if not aggregates.get("sources"):
        raise ValueError(f"source-quality config has no sources: {p}")
    return aggregates


def source_chain_for_host(qid: str, path: Path | None = None) -> list[str]:
    """Return primary adapter plus configured fallback chain for a host Q-ID."""
    entry = host_registry.find_by_wikidata_q(qid, path or HOST_REGISTRY_PATH)
    if entry is None or not entry.primary_adapter:
        return []
    return [entry.primary_adapter, *entry.fallback_chain]


def rank_sources(
    work_class: str, candidate_sources: list[str], aggregates: dict
) -> list[tuple[str, float]]:
    """Return candidate sources sorted by descending source-quality score."""
    ranked: list[tuple[str, float]] = []
    for src in candidate_sources:
        ranked.append((src, _source_quality_score(src, work_class, aggregates)))
    ranked.sort(key=lambda item: (math.isfinite(item[1]), item[1]), reverse=True)
    return ranked


def select_source(
    work_class: str, candidate_sources: list[str], aggregates: dict
) -> tuple[str, str]:
    """Pick a source by margin rule: >=0.10 gap wins, else tied-fallback."""
    if not candidate_sources:
        raise ValueError("candidate_sources must not be empty")

    ranked = rank_sources(work_class, candidate_sources, aggregates)
    if len(ranked) == 1:
        return ranked[0][0], "margin"

    margin = ranked[0][1] - ranked[1][1]
    if margin >= 0.10:
        return ranked[0][0], "margin"
    return ranked[0][0], "tied-fallback"


def get_collector(source: str) -> ModuleType:
    """Return the collector module for ``source`` or raise ``ValueError``."""
    source = _collector_key(source)
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
    dedup: DedupVerdict | None = None


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
    candidate_sources: list[str] | None = None,
    host_qid: str | None = None,
    work_class: str = "western-painting-19c",
    aggregates: dict | None = None,
    source_quality_path: Path | None = None,
    host_registry_path: Path | None = None,
    archive: Sequence[ArchiveEntry] | None = None,
    dino_hook=None,
) -> list[AcquisitionAssessment]:
    """Assess a batch of ``source`` acquisitions through verify + quality, and —
    when an ``archive`` index is supplied — gate each through the D017 dedup
    cascade (sha256 -> pHash -> artist-Q-ID -> metadata, plus an optional DINOv2
    ``dino_hook``), attaching the verdict to each assessment's ``dedup`` field.

    Each entry in ``work_dirs`` is a directory holding ``master.jpg`` and an
    optional ``meta.json`` (``dimensions_original`` + ``artist``/``title``). The
    source name is validated first; directories without a master are skipped.
    """
    chosen_source = source
    if candidate_sources is None and host_qid:
        candidate_sources = source_chain_for_host(host_qid, path=host_registry_path)
        if not candidate_sources:
            raise ValueError(f"host {host_qid!r} has no acquisition source chain")
    if candidate_sources:
        loaded_aggregates = aggregates or load_source_quality_config(source_quality_path)
        chosen_source, _reason = select_source(work_class, candidate_sources, loaded_aggregates)

    get_collector(chosen_source)  # validate the source up front
    selected = work_dirs if max_items is None else work_dirs[:max_items]
    results: list[AcquisitionAssessment] = []
    for raw in selected:
        wd = Path(raw)
        master = wd / "master.jpg"
        if not master.exists():
            continue
        meta: dict = {}
        meta_p = wd / "meta.json"
        if meta_p.exists():
            try:
                meta = json.loads(meta_p.read_text())
            except json.JSONDecodeError as exc:
                LOGGER.warning(
                    "Ignoring malformed staged metadata for %s; continuing with empty metadata: %s",
                    meta_p,
                    exc,
                )
        dim = meta.get("dimensions_original") or {}
        assessment = assess_master(
            master,
            source=chosen_source,
            h_cm=dim.get("h_cm"),
            w_cm=dim.get("w_cm"),
        )
        if archive is not None:
            assessment.dedup = dedup_check(
                build_candidate(master, meta), archive, dino_hook=dino_hook
            )
        results.append(assessment)
    return results
