#!/usr/bin/env python3
"""Apply calibrated and contrastive vision-score proposals to archive sidecars.

The scorer is deliberately separate from this policy/merge layer. It accepts a
JSONL score export so a local CLIP runner can be swapped without changing the
review, provenance, or sidecar safety rules.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from collections.abc import Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(os.environ.get("FAA_WORKSPACE", Path(__file__).resolve().parents[1]))
STAGING = ROOT / "staging_sidecars"
DEFAULT_CONFIG = Path(__file__).resolve().parents[1] / "config" / "clip_thresholds.yaml"


def load_config(path: Path = DEFAULT_CONFIG) -> dict[str, Any]:
    """Load and minimally validate the threshold/contrastive policy."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError("vision configuration must be a mapping")
    raw.setdefault("thresholds", {})
    raw.setdefault("contrastive_pairs", {})
    if not isinstance(raw["thresholds"], dict) or not isinstance(raw["contrastive_pairs"], dict):
        raise ValueError("thresholds and contrastive_pairs must be mappings")
    return raw


def tag_one(
    tag: str,
    scores: Mapping[str, float],
    config: Mapping[str, Any],
    *,
    allow_contrastive: bool = True,
    min_f1: float | None = None,
) -> dict[str, Any] | None:
    """Return a proposal when ``tag`` clears its calibrated or contrastive gate."""
    pairs = config.get("contrastive_pairs", {})
    pair = pairs.get(tag) if isinstance(pairs, Mapping) else None
    if allow_contrastive and isinstance(pair, Mapping):
        positive_value = pair.get("positive")
        if not isinstance(positive_value, str) or not positive_value.strip():
            raise ValueError(f"contrastive tag {tag} needs a non-empty positive prompt")
        positive = positive_value
        negatives = pair.get("negatives", [])
        if not isinstance(negatives, list) or not negatives:
            raise ValueError(f"contrastive tag {tag} needs non-empty negatives")
        prompts = [positive, *(str(item) for item in negatives)]
        if any(prompt not in scores for prompt in prompts):
            return None
        try:
            positive_score = float(scores[positive])
            negative_score = max(float(scores[prompt]) for prompt in prompts[1:])
            margin = float(pair.get("margin", 0.0))
        except (TypeError, ValueError):
            return None
        if not all(math.isfinite(value) for value in (positive_score, negative_score, margin)):
            return None
        cutoff = negative_score + margin
        if positive_score <= cutoff or math.isclose(positive_score, cutoff, abs_tol=1e-12):
            return None
        return {
            "id": tag,
            "state": "proposed",
            "source": "vision:contrastive",
            "basis": "contrastive",
            "positive_score": positive_score,
            "negative_score": negative_score,
            "margin": margin,
        }

    thresholds = config.get("thresholds", {})
    policy = thresholds.get(tag) if isinstance(thresholds, Mapping) else None
    if policy is None or tag not in scores:
        return None
    if isinstance(policy, Mapping):
        threshold = policy.get("threshold")
        f1 = policy.get("f1")
    else:
        threshold, f1 = policy, None
    try:
        score = float(scores[tag])
        threshold_value = float(threshold)
        f1_value = float(f1) if f1 is not None else None
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(value) for value in (score, threshold_value)):
        return None
    if f1_value is not None and not math.isfinite(f1_value):
        return None
    if min_f1 is not None and (f1_value is None or f1_value < min_f1):
        return None
    if score < threshold_value:
        return None
    return {"id": tag, "state": "proposed", "source": "vision:threshold", "basis": "threshold"}


def propose(
    scores: Mapping[str, float],
    config: Mapping[str, Any],
    *,
    no_contrastive: bool = False,
    min_f1: float | None = None,
) -> list[dict[str, Any]]:
    """Produce all policy-approved proposals from a single work's score map."""
    tags = set((config.get("thresholds") or {}).keys())
    if not no_contrastive:
        tags.update((config.get("contrastive_pairs") or {}).keys())
    return [
        proposal
        for tag in sorted(tags)
        if (
            proposal := tag_one(
                tag,
                scores,
                config,
                allow_contrastive=not no_contrastive,
                min_f1=min_f1,
            )
        )
        is not None
    ]


def merge_into_sidecar(sidecar: dict[str, Any], proposals: list[dict[str, Any]]) -> dict[str, Any]:
    """Merge additive proposals without overriding reviewer or Wikidata decisions."""
    subject = sidecar.setdefault("subject", {})
    if not isinstance(subject, dict):
        raise ValueError("subject must be an object when present")
    current = subject.get("content_tags", [])
    if not isinstance(current, list):
        raise ValueError("subject.content_tags must be a list when present")
    by_id = {item.get("id"): item for item in current if isinstance(item, dict) and item.get("id")}
    changed = False
    for proposal in proposals:
        existing = by_id.get(proposal["id"])
        if existing and (
            existing.get("source") == "wikidata:P180" or existing.get("state") != "proposed"
        ):
            continue
        if by_id.get(proposal["id"]) != proposal:
            by_id[proposal["id"]] = proposal
            changed = True
    subject["content_tags"] = [by_id[key] for key in sorted(by_id)]
    if changed:
        subject["needs_review"] = True
    return sidecar


def _score_rows(path: Path) -> dict[str, dict[str, float]]:
    rows: dict[str, dict[str, float]] = {}
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        work_id, scores = row.get("work_id"), row.get("scores")
        if isinstance(work_id, str) and isinstance(scores, dict):
            rows[work_id] = {str(key): float(value) for key, value in scores.items()}
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--scores", type=Path, default=ROOT / "vision_scores.jsonl")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--no-contrastive", action="store_true")
    parser.add_argument("--min-f1", type=float, default=None)
    args = parser.parse_args()
    config = load_config(args.config)
    contrastive = sorted(config["contrastive_pairs"])
    print(
        f"gate: threshold tags={sorted(config['thresholds'])}; contrastive tags={[] if args.no_contrastive else contrastive}"
    )
    scores = _score_rows(args.scores)
    work_ids = sorted(path.name for path in STAGING.iterdir() if path.is_dir())[: args.limit]
    counts = dict.fromkeys(contrastive, 0)
    for work_id in work_ids:
        proposals = propose(
            scores.get(work_id, {}),
            config,
            no_contrastive=args.no_contrastive,
            min_f1=args.min_f1,
        )
        for proposal in proposals:
            if proposal["basis"] == "contrastive":
                counts[proposal["id"]] += 1
        if args.apply and proposals:
            path = STAGING / work_id / "meta.json"
            sidecar = json.loads(path.read_text(encoding="utf-8"))
            merge_into_sidecar(sidecar, proposals)
            path.write_text(
                json.dumps(sidecar, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
            )
    utc = timezone.utc  # noqa: UP017 (Python 3.9 CLI fallback)
    report = {
        "generated_at": datetime.now(utc).isoformat(),
        "contrastive_counts": counts,
        "contrastive_policies": config["contrastive_pairs"],
        "scored_works": len(scores),
    }
    (ROOT / "clip_calibration_report.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, sort_keys=True))
    if args.limit is None and scores and counts.get("filter:nudity-full", 0) <= 30:
        print("contrastive coverage check failed: filter:nudity-full must flag more than 30 works")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
