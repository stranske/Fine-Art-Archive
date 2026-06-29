"""Source-quality aggregator + scorer.

Implements `source_quality_design.md`:
  - read every sidecar's `verification.source_quality_inputs`
  - group by (source, work_class)
  - compute the composite score
  - blend with priors from host_registry.yaml during a 30-day warmup
  - write `config/source_quality.yaml` for the routing path in acquire.py

Public API:
  - `aggregate_sidecars(staging_dir, host_registry_path) -> dict`
  - `write_aggregates(aggregates, out_path)`
  - `load_aggregates(path) -> dict`
  - `score_for(source, work_class, *, aggregates) -> float`
  - `composite_score(stats) -> float`
  - `extract_signals(meta) -> SignalRow | None`

A "signal row" is whatever a single acquisition contributed. The
aggregator reduces many SignalRows for the same (source, work_class)
into a SourceQualityAggregate.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import yaml

# --------------------------------------------------------------------------
# Priors — when a source has fewer than 10 acquisitions we lean on these.
# Tier comes from host_registry.yaml. Adjusts to empirical scores after
# 30 days per the design's linear blend.
# --------------------------------------------------------------------------
DEFAULT_TIER_PRIORS: dict[int, dict[str, float]] = {
    1: {  # peer-reviewed institutional museum APIs
        "verify_pass_rate": 0.95,
        "attribution_agreement": 0.95,
        "link_health_30d": 0.98,
        "metadata_completeness": 0.85,
    },
    2: {  # aggregator (e.g. wikimedia_commons) — variable per upload
        "verify_pass_rate": 0.80,
        "attribution_agreement": 0.80,
        "link_health_30d": 0.95,
        "metadata_completeness": 0.65,
    },
    3: {
        "verify_pass_rate": 0.65,
        "attribution_agreement": 0.65,
        "link_health_30d": 0.85,
        "metadata_completeness": 0.50,
    },
}

# Composite formula coefficients (from source_quality_design.md §Aggregation)
COMPOSITE_WEIGHTS = {
    "verify_pass_rate": 0.40,
    "attribution_agreement": 0.25,
    "link_health_30d": 0.15,
    "metadata_completeness": 0.15,
    # 0.05 weight for the confidence floor — applied separately
}
CONFIDENCE_FLOOR_WEIGHT = 0.05
CONFIDENCE_FLOOR_FULL_AT = 10  # n_acquired needed to maximise the floor term

# Warmup window: how many days after first sighting before we trust
# empirical numbers alone (linear blend before that).
WARMUP_DAYS = 30


# --------------------------------------------------------------------------
# Data structures
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class SignalRow:
    """One acquisition's worth of source-quality signals."""

    source: str
    work_class: str
    work_id: str
    phash_match: bool | None = None
    aspect_match: bool | None = None
    dim_match: bool | None = None
    verify_match: bool | None = None
    attribution_match: bool | None = None
    link_alive: bool | None = None
    metadata_completeness: float | None = None  # 0..1
    download_speed_bps: float | None = None
    ts: str | None = None  # ISO8601 of acquisition

    @property
    def verify_pass(self) -> bool | None:
        """Aggregate identity-verification gates.

        Prefer the explicit overall verification result when present. Older
        sidecars fall back to requiring every available pHash/aspect/dim gate.
        """
        if self.verify_match is not None:
            return self.verify_match
        gates = [g for g in (self.phash_match, self.aspect_match, self.dim_match) if g is not None]
        if not gates:
            return None
        return all(gates)


@dataclass
class SourceQualityAggregate:
    source: str
    work_class: str
    n_acquired: int = 0
    n_verify_pass: int = 0
    n_verify_total: int = 0  # rows that had at least one verify gate
    n_attribution_pass: int = 0
    n_attribution_total: int = 0
    n_link_alive: int = 0
    n_link_total: int = 0
    metadata_completeness_sum: float = 0.0
    metadata_completeness_n: int = 0
    first_seen: str | None = None
    last_seen: str | None = None
    # Carry the host_tier so to_dict/composite can use the prior even
    # when n_acquired is low.
    host_tier: int | None = None

    def add(self, row: SignalRow) -> None:
        self.n_acquired += 1
        vp = row.verify_pass
        if vp is not None:
            self.n_verify_total += 1
            if vp:
                self.n_verify_pass += 1
        if row.attribution_match is not None:
            self.n_attribution_total += 1
            if row.attribution_match:
                self.n_attribution_pass += 1
        if row.link_alive is not None:
            self.n_link_total += 1
            if row.link_alive:
                self.n_link_alive += 1
        if row.metadata_completeness is not None:
            self.metadata_completeness_sum += row.metadata_completeness
            self.metadata_completeness_n += 1
        if row.ts:
            if self.first_seen is None or row.ts < self.first_seen:
                self.first_seen = row.ts
            if self.last_seen is None or row.ts > self.last_seen:
                self.last_seen = row.ts

    def empirical_stats(self) -> dict[str, float | None]:
        """Return raw rates from observed signals — None when no data."""
        return {
            "verify_pass_rate": (
                self.n_verify_pass / self.n_verify_total if self.n_verify_total else None
            ),
            "attribution_agreement": (
                self.n_attribution_pass / self.n_attribution_total
                if self.n_attribution_total
                else None
            ),
            "link_health_30d": (
                self.n_link_alive / self.n_link_total if self.n_link_total else None
            ),
            "metadata_completeness": (
                self.metadata_completeness_sum / self.metadata_completeness_n
                if self.metadata_completeness_n
                else None
            ),
        }

    def blended_stats(self, now: datetime | None = None) -> dict[str, float]:
        """Blend empirical with prior using a linear warmup over WARMUP_DAYS.

        - If no first_seen (no empirical data yet), returns prior fully.
        - If first_seen is older than WARMUP_DAYS, returns empirical (with
          prior fill-in for any missing metric).
        - In between, linear blend t/WARMUP * empirical + (1-t/WARMUP) * prior.
        """
        prior = DEFAULT_TIER_PRIORS.get(self.host_tier or 1, DEFAULT_TIER_PRIORS[1])
        emp = self.empirical_stats()
        if self.first_seen is None:
            return dict(prior)
        now = now or datetime.now(UTC)
        try:
            first = datetime.fromisoformat(self.first_seen.replace("Z", "+00:00"))
        except ValueError:
            return dict(prior)
        age_days = (now - first).total_seconds() / 86400.0
        t = max(0.0, min(1.0, age_days / WARMUP_DAYS))
        out: dict[str, float] = {}
        for k, p in prior.items():
            e = emp.get(k)
            if e is None:
                out[k] = p
            else:
                out[k] = t * e + (1 - t) * p
        return out

    def to_dict(self) -> dict:
        stats = self.blended_stats()
        return {
            "source": self.source,
            "work_class": self.work_class,
            "n_acquired": self.n_acquired,
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "host_tier": self.host_tier,
            "empirical": self.empirical_stats(),
            "blended": {k: round(v, 4) for k, v in stats.items()},
            "composite_score": round(composite_score(stats, self.n_acquired), 4),
        }


# --------------------------------------------------------------------------
# Scoring
# --------------------------------------------------------------------------
def composite_score(
    stats: dict[str, float],
    n_acquired: int = 0,
    *,
    weights: dict[str, float] | None = None,
    confidence_floor_weight: float = CONFIDENCE_FLOOR_WEIGHT,
) -> float:
    """The weighted formula from source_quality_design.md."""
    active_weights = COMPOSITE_WEIGHTS if weights is None else weights
    base = sum(active_weights[k] * float(stats.get(k, 0.0)) for k in active_weights)
    floor_term = (
        1.0 if n_acquired >= CONFIDENCE_FLOOR_FULL_AT else n_acquired / CONFIDENCE_FLOOR_FULL_AT
    )
    return base + confidence_floor_weight * floor_term


def _routing_score_from_record(rec: dict, aggregates: dict) -> float:
    weights = aggregates.get("composite_weights")
    confidence_floor_weight = aggregates.get("confidence_floor_weight", CONFIDENCE_FLOOR_WEIGHT)
    blended = rec.get("blended")
    if isinstance(weights, dict) and isinstance(blended, dict):
        return composite_score(
            blended,
            n_acquired=int(rec.get("n_acquired") or 0),
            weights={k: float(v) for k, v in weights.items()},
            confidence_floor_weight=float(confidence_floor_weight),
        )
    return float(rec.get("composite_score", 0.0))


def score_for(source: str, work_class: str, *, aggregates: dict) -> float:
    """Routing call site uses this. Returns the composite for (source, work_class)
    or — when there's no aggregate — a tier-1 prior (0.05 floor is 0 since
    n_acquired=0)."""
    rec = aggregates.get("sources", {}).get(source, {}).get(work_class)
    if rec:
        return _routing_score_from_record(rec, aggregates)
    # No record: fall back to tier-1 prior with zero confidence floor.
    return composite_score(DEFAULT_TIER_PRIORS[1], n_acquired=0)


# --------------------------------------------------------------------------
# Signal extraction
# --------------------------------------------------------------------------
def _infer_work_class(meta: dict) -> str:
    """Coarse taxonomy from category + artist + year. Keeps the v1
    classification small and deterministic so the per-class rollups don't
    explode."""
    cat = (meta.get("category") or "painting").lower()
    year_raw = meta.get("year") or meta.get("year_min") or ""
    year = None
    match = re.search(r"\b(\d{3,4})(?:\.0)?\b", str(year_raw))
    if match:
        year = int(match.group(1))
    if cat == "photograph":
        return "photograph"
    if cat in {"sculpture"}:
        return "sculpture"
    if cat in {"illuminated_manuscript", "icon", "fresco", "mural", "altarpiece", "tapestry"}:
        return "manuscript-or-monumental"
    if cat in {"painting", "drawing", "print"}:
        if year is None:
            return "western-painting-unknown-period"
        if year < 1800:
            return "western-painting-pre1800"
        if year < 1900:
            return "western-painting-19c"
        return "western-painting-modern"
    return "other"


LEGACY_BUCKETS = {
    "meural",
    "tv",
    "landscape",
    "portrait",
    "still life",
    "others photos",
    "family",
    "frame",
    "iphone",
    "art",
    "downloads",
    "art_others",
    "art family - to load",
}


def _legacy_source_from_path(ingested: str) -> str | None:
    if not ingested:
        return None
    first_seg = ingested.split("/", 1)[0].lower() if "/" in ingested else ""
    if first_seg in LEGACY_BUCKETS:
        return f"legacy-{first_seg.replace(' ', '-')}"
    return None


def extract_signals(
    meta: dict,
    legacy_bucket_lookup: dict | None = None,
) -> SignalRow | None:
    """Pull a SignalRow from a sidecar dict. Returns None when the sidecar
    has no source-quality block to harvest (legacy inventory sidecars).

    `legacy_bucket_lookup`: optional {work_id: master_ingested_from} mapping
    used when the sidecar dropped its `ingested_from` field (Phase 3 move
    pops it after promotion). Falls back to bucket inference from the path.
    """
    ap = meta.get("acquisition_provenance") or {}
    src = ap.get("source")
    v = meta.get("verification") or {}
    sq = v.get("source_quality_inputs") or {}

    # Legacy fallback — try to infer source from ingested_from path.
    if not src:
        ingested = meta.get("files", {}).get("master", {}).get("ingested_from", "") or ""
        # Phase 3 popped ingested_from; recover from the manifest lookup.
        if not ingested and legacy_bucket_lookup is not None:
            ingested = legacy_bucket_lookup.get(meta.get("work_id", ""), "")
        src = _legacy_source_from_path(ingested)
        if not src:
            return None

    return SignalRow(
        source=src,
        work_class=_infer_work_class(meta),
        work_id=meta.get("work_id", ""),
        verify_match=sq.get("verify_match"),
        phash_match=sq.get("phash_match"),
        aspect_match=sq.get("aspect_match"),
        dim_match=sq.get("dim_match"),
        attribution_match=sq.get("attribution_match"),
        link_alive=sq.get("link_alive"),
        metadata_completeness=sq.get("metadata_completeness"),
        download_speed_bps=sq.get("download_speed"),
        ts=ap.get("ts") or meta.get("files", {}).get("master", {}).get("ingested_at"),
    )


# --------------------------------------------------------------------------
# Aggregation
# --------------------------------------------------------------------------
def _load_host_tiers(host_registry_path: Path) -> dict[str, int]:
    if not host_registry_path.exists():
        return {}
    d = yaml.safe_load(host_registry_path.read_text()) or {}
    hosts = d.get("hosts", {})
    return {hid: int(h.get("source_tier", 1)) for hid, h in hosts.items()}


def _load_legacy_bucket_lookup(manifest_csv: Path) -> dict[str, str]:
    """Recover {work_id: master_ingested_from} from the manifest, which
    still carries the original bucket path even after Phase 3 popped it
    from the sidecar."""
    import csv as _csv

    out: dict[str, str] = {}
    if not manifest_csv.exists():
        return out
    with open(manifest_csv) as f:
        for row in _csv.DictReader(f):
            wid = row.get("work_id") or ""
            ingested = row.get("master_ingested_from") or ""
            if wid and ingested:
                out[wid] = ingested
    return out


def aggregate_sidecars(
    staging_dir: Path,
    host_registry_path: Path | None = None,
    *,
    manifest_csv: Path | None = None,
    seed_priors_from_registry: bool = True,
) -> dict:
    host_tiers = _load_host_tiers(host_registry_path) if host_registry_path else {}
    legacy_lookup = _load_legacy_bucket_lookup(manifest_csv) if manifest_csv else {}
    aggs: dict[tuple[str, str], SourceQualityAggregate] = {}

    n_total = 0
    n_with_signals = 0
    n_legacy_recovered = 0
    for sc in sorted(staging_dir.iterdir()):
        meta_p = sc / "meta.json"
        if not meta_p.exists():
            continue
        n_total += 1
        try:
            meta = json.loads(meta_p.read_text())
        except Exception:
            continue
        row = extract_signals(meta, legacy_bucket_lookup=legacy_lookup)
        if row is None:
            continue
        n_with_signals += 1
        if row.source.startswith("legacy-"):
            n_legacy_recovered += 1
        key = (row.source, row.work_class)
        if key not in aggs:
            aggs[key] = SourceQualityAggregate(
                source=row.source,
                work_class=row.work_class,
                host_tier=host_tiers.get(row.source, 1),
            )
        aggs[key].add(row)

    # Seed prior-only entries for every host in the registry so the routing
    # call site always has *something* to fall back on, even before any
    # real acquisitions land.
    n_priors_seeded = 0
    if seed_priors_from_registry:
        # One generic work-class row per host so score_for() returns a
        # sensible value before the first acquisition.
        seed_classes = [
            "western-painting-pre1800",
            "western-painting-19c",
            "western-painting-modern",
        ]
        for host_id, tier in host_tiers.items():
            for wc in seed_classes:
                key = (host_id, wc)
                if key in aggs:
                    continue
                aggs[key] = SourceQualityAggregate(
                    source=host_id,
                    work_class=wc,
                    host_tier=tier,
                )
                n_priors_seeded += 1

    # Split real acquisition sources from legacy folder-bucket aggregates.
    # Legacy entries have no verify/attribution signals — they're a folder,
    # not a museum API — so their composite_score is meaningless. Keep the
    # counts as an "archive_composition" view; reserve `sources` for entries
    # whose composite_score the orchestrator can actually act on.
    real_sources: dict[str, dict[str, dict]] = {}
    legacy_composition: dict[str, dict[str, dict]] = {}
    for (src, wc), agg in sorted(aggs.items()):
        rec = agg.to_dict()
        target = legacy_composition if src.startswith("legacy-") else real_sources
        # For legacy entries, drop the score keys to avoid implying
        # they're comparable to a real source.
        if src.startswith("legacy-"):
            rec = {
                k: v
                for k, v in rec.items()
                if k in {"source", "work_class", "n_acquired", "first_seen", "last_seen"}
            }
        target.setdefault(src, {})[wc] = rec

    return {
        "schema_version": "1.0",
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "warmup_days": WARMUP_DAYS,
        "composite_weights": COMPOSITE_WEIGHTS,
        "confidence_floor_weight": CONFIDENCE_FLOOR_WEIGHT,
        "n_sidecars_scanned": n_total,
        "n_with_signals": n_with_signals,
        "n_legacy_bucket_recovered": n_legacy_recovered,
        "n_prior_only_rows": n_priors_seeded,
        "n_real_sources": len(real_sources),
        "n_legacy_buckets": len(legacy_composition),
        "sources": real_sources,
        "archive_composition": legacy_composition,
    }


def write_aggregates(aggregates: dict, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        yaml.safe_dump(aggregates, f, sort_keys=False, default_flow_style=False, allow_unicode=True)


def load_aggregates(path: Path) -> dict:
    if not path.exists():
        return {"sources": {}}
    return yaml.safe_load(path.read_text()) or {"sources": {}}
