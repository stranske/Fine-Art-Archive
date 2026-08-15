#!/usr/bin/env python3
"""Versioned Tier-3 CLIP tagger for the Fine Art Archive.

The implementation and policy belong in this repository.  The large artwork
corpus remains outside git and is selected with ``FAA_WORKSPACE``; this makes
the Companion API executable without treating operational data as source code.

.. warning::
   **THIS FILE HAS A TWIN, AND THE TWIN IS THE ONE THAT RUNS.**

   The tagger exists twice:

   * ``<repo>/scripts/vision_tag_works.py`` — this file. Version controlled and
     covered by ``tests/test_contrastive_scoring.py`` in CI.
   * ``Claude Project/scripts/vision_tag_works.py`` — wired to ``STAGING`` and
     the image masters. **This is the copy that actually tags the archive.**

   On 2026-08-07 that split produced a silent failure worth remembering: issue
   #442 added contrastive scoring HERE, CI went green, the issue was closed —
   and the archive did not change by a single tag, because the running copy
   never received it. ``filter:nudity-full`` sat at 3 works while the tests
   passed. Green CI is not evidence that the data moved.

   Until the logic is consolidated into the installed package (where both can
   import it), **any behaviour change here must be mirrored into the workspace
   copy and verified by counting tags in the archive**, not by running tests.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys
import time
from collections.abc import Mapping
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
ROOT = Path(
    os.environ.get(
        "FAA_WORKSPACE", "/Users/teacher/Library/CloudStorage/Dropbox/Pictures/Claude Project"
    )
)
STAGING = ROOT / "staging_sidecars"
ART_WORKS = Path(os.environ.get("FAA_ART_WORKS", ROOT.parent / "Art" / "works"))
CONFIG_PATH = Path(
    os.environ.get("FAA_TAGGER_CONFIG", REPO_ROOT / "config" / "clip_thresholds.yaml")
)
TELEMETRY_DIR = ROOT / "data" / "vision_tag_runs"
ENCODING_CACHE = ROOT / "data" / "image_cache" / "clip_encodings"
MODEL_NAME = "openai/clip-vit-large-patch14"
MODEL_VERSION_TAG = "clip-vit-large-patch14"

TAG_PROMPTS: dict[str, str] = {
    "genre:painting/portrait": "a painting of a portrait of a person",
    "genre:painting/landscape": "a painting of a natural landscape",
    "genre:painting/seascape": "a painting of the sea or maritime scene",
    "genre:painting/cityscape": "a painting of a city or urban scene",
    "genre:painting/still-life": "a painting of a still life of objects",
    "genre:painting/genre-scene": "a painting of an everyday-life scene",
    "genre:painting/religious": "a painting of a religious scene or biblical subject",
    "genre:painting/mythological": "a painting of a mythological scene",
    "genre:painting/nude": "a painting of a nude figure",
    "genre:painting/abstract": "an abstract non-representational painting",
    "genre:painting/animal": "a painting of an animal",
    "genre:painting/allegory": "an allegorical painting with symbolic figures",
    "genre:photograph/portrait": "a photographic portrait of a person",
    "genre:photograph/landscape": "a photograph of a natural landscape",
    "genre:manuscript-illumination": "a medieval or Islamic illuminated manuscript folio",
    "filter:religious": "religious art with a saint, biblical scene, or deity",
    "filter:nudity-partial": "a figure with partial nudity, exposed chest or buttocks",
    "filter:nudity-full": "a fully nude figure as the subject of the work",
    "filter:violence": "depicted violence, battle, or fighting",
    "filter:blood": "visible blood or wounds",
    "filter:death": "a corpse, deathbed scene, or martyrdom",
    "filter:disturbing": "disturbing imagery: torture, body horror, or extreme suffering",
    "filter:weapon-prominent": "a prominently displayed weapon",
    "filter:occult": "witchcraft, demonic, or satanic imagery",
    "subject:single-figure": "a single figure as the focus of the work",
    "subject:group": "a group of multiple figures",
    "subject:male": "a depiction of a man",
    "subject:female": "a depiction of a woman",
    "subject:child": "a depiction of a child",
    "subject:mother-and-child": "a mother holding a child",
    "subject:animal": "an animal as a prominent subject",
    "subject:horse": "a horse",
    "subject:building": "a prominent building or architecture",
    "subject:ship": "a ship or boat",
    "subject:flower": "flowers as a prominent element",
    "subject:tree": "trees as a prominent element",
    "setting:interior": "an interior architectural scene",
    "setting:outdoor": "an outdoor scene",
    "setting:landscape-natural": "a natural landscape with no buildings",
    "setting:urban": "an urban setting with buildings or streets",
    "setting:rural": "a rural countryside scene",
    "setting:night": "a nocturnal or nighttime scene",
    "setting:winter": "a winter or snowy scene",
    "palette:warm-toned": "predominantly warm colors (red, orange, yellow)",
    "palette:cool-toned": "predominantly cool colors (blue, green, purple)",
    "palette:monochrome": "monochromatic or grayscale",
    "palette:high-contrast": "high contrast with bright lights and deep shadows",
    "palette:predominantly-dark": "predominantly dark tones",
    "palette:predominantly-light": "predominantly light tones",
    "subject:dog": "a dog",
    "subject:bird": "a bird",
    "subject:train": "a railway train or locomotive",
    "subject:industrial-machinery": "industrial machinery or factory equipment",
    "genre:painting/history": "a painting of a historical event",
    "setting:water": "a scene on or beside water",
    "setting:autumn": "an autumn scene with turning foliage",
    "setting:summer": "a summer scene with full green foliage",
    "era-depicted:industrial-era": "a scene of the industrial era with factories or machines",
    "theme:religious-narrative": "a scene narrating a religious or biblical story",
    "theme:mythological": "a scene from classical mythology",
    "theme:war": "a scene of war or military conflict",
    "theme:labor": "people at manual work or labour",
    "theme:leisure": "people at leisure, resting or playing",
    "theme:celebration": "a festival, feast, or celebration",
    "theme:motherhood": "motherhood: a mother caring for a child",
}

_model: Any = None
_processor: Any = None
_device = "cpu"
_text_feature_cache: dict[tuple[str, ...], Any] = {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")  # noqa: UP017 (Python 3.9 CLI)


def load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    """Read the versioned threshold and contrastive policy."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError("vision configuration must be a mapping")
    raw.setdefault("thresholds", {})
    raw.setdefault("contrastive_pairs", {})
    if not isinstance(raw["thresholds"], dict) or not isinstance(raw["contrastive_pairs"], dict):
        raise ValueError("thresholds and contrastive_pairs must be mappings")
    return raw


def _threshold_policy(value: Any) -> tuple[float | None, float | None, str]:
    if isinstance(value, Mapping):
        raw_threshold, raw_f1, basis = (
            value.get("threshold"),
            value.get("f1"),
            value.get("basis", "curated"),
        )
    else:
        raw_threshold, raw_f1, basis = value, None, "curated"
    try:
        threshold = float(raw_threshold)
        f1 = float(raw_f1) if raw_f1 is not None else None
    except (TypeError, ValueError):
        return None, None, "inert"
    if not math.isfinite(threshold) or (f1 is not None and not math.isfinite(f1)):
        return None, None, "inert"
    return threshold, f1, str(basis)


def evaluate_policy(
    scores: Mapping[str, float],
    config: Mapping[str, Any],
    *,
    min_f1: float = 0.50,
    no_contrastive: bool = False,
    allow_provisional: bool = False,
) -> list[dict[str, Any]]:
    """Evaluate already-computed prompt scores without loading a model."""
    proposals: list[dict[str, Any]] = []
    thresholds = config.get("thresholds", {})
    for tag, policy in thresholds.items() if isinstance(thresholds, Mapping) else []:
        threshold, f1, basis = _threshold_policy(policy)
        score = scores.get(TAG_PROMPTS.get(str(tag), str(tag)))
        if score is None or threshold is None:
            continue
        try:
            score_value = float(score)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(score_value) or (
            basis == "provisional-mixed" and not allow_provisional
        ):
            continue
        if f1 is not None and f1 < min_f1:
            continue
        proposals.append(
            {
                "tag": str(tag),
                "score": round(score_value, 4),
                "threshold": threshold,
                "passed": score_value >= threshold,
                "calibrated": True,
                "basis": "threshold",
            }
        )
    if no_contrastive:
        return proposals
    pairs = config.get("contrastive_pairs", {})
    for tag, pair in pairs.items() if isinstance(pairs, Mapping) else []:
        if not isinstance(pair, Mapping):
            continue
        positive = pair.get("positive")
        negatives = pair.get("negatives", [])
        if not isinstance(positive, str) or not isinstance(negatives, list) or not negatives:
            continue
        try:
            positive_score = float(scores[positive])
            negative_score = max(float(scores[str(prompt)]) for prompt in negatives)
            margin = float(pair.get("margin", 0.0))
        except (KeyError, TypeError, ValueError):
            continue
        if not all(math.isfinite(value) for value in (positive_score, negative_score, margin)):
            continue
        cutoff = negative_score + margin
        proposals.append(
            {
                "tag": str(tag),
                "score": round(positive_score, 4),
                "threshold": None,
                "passed": positive_score > cutoff
                and not math.isclose(positive_score, cutoff, abs_tol=1e-12),
                "calibrated": False,
                "basis": "contrastive",
                "margin": margin,
                "negative_score": round(negative_score, 4),
            }
        )
    return proposals


def _load_model() -> None:
    global _device, _model, _processor
    if _model is not None:
        return
    import torch
    from transformers import CLIPModel, CLIPProcessor

    _device = (
        "mps"
        if torch.backends.mps.is_available()
        else "cuda" if torch.cuda.is_available() else "cpu"
    )
    print(f"Loading {MODEL_NAME} on {_device} ...", file=sys.stderr, flush=True)
    _model = CLIPModel.from_pretrained(MODEL_NAME).to(_device)
    _processor = CLIPProcessor.from_pretrained(MODEL_NAME)
    _model.eval()


def _master_path(work_id: str) -> Path | None:
    work_dir = ART_WORKS / work_id
    if work_dir.is_dir():
        return next(
            (
                path
                for path in work_dir.iterdir()
                if path.is_file() and path.name.startswith("master.")
            ),
            None,
        )
    return None


def _image_features(work_id: str):
    import torch
    from PIL import Image

    master = _master_path(work_id)
    if master is None:
        return None
    cache_path = ENCODING_CACHE / f"{work_id}.pt"
    _load_model()
    if cache_path.exists():
        return torch.load(cache_path, weights_only=True).to(_device)
    Image.MAX_IMAGE_PIXELS = None
    with Image.open(master) as image:
        with suppress(OSError, ValueError):
            image.draft("RGB", (896, 896))
        image = image.convert("RGB")
        if max(image.size) > 896:
            image.thumbnail((896, 896), Image.Resampling.LANCZOS)
        with torch.no_grad():
            inputs = {
                key: value.to(_device)
                for key, value in _processor(images=image, return_tensors="pt").items()
            }
            output = _model.vision_model(**inputs).pooler_output
            features = _model.visual_projection(output)
            features = features / features.norm(dim=-1, keepdim=True)
    ENCODING_CACHE.mkdir(parents=True, exist_ok=True)
    torch.save(features.cpu(), cache_path)
    return features


def _text_features(prompts: list[str]):
    """Return cached CLIP text embeddings for the stable prompt set of a run."""
    import torch

    key = tuple(prompts)
    cached = _text_feature_cache.get(key)
    if cached is not None:
        return cached
    _load_model()
    with torch.no_grad():
        inputs = {
            name: value.to(_device)
            for name, value in _processor(text=prompts, return_tensors="pt", padding=True).items()
        }
        output = _model.text_model(**inputs).pooler_output
        features = _model.text_projection(output)
        features = features / features.norm(dim=-1, keepdim=True)
    _text_feature_cache[key] = features
    return features


def score_work(work_id: str, config: Mapping[str, Any]) -> dict[str, float] | None:
    """Score all threshold and contrastive prompts for one operational work."""
    image_features = _image_features(work_id)
    if image_features is None:
        return None
    import torch

    prompts = list(TAG_PROMPTS.values())
    pairs = config.get("contrastive_pairs", {})
    if isinstance(pairs, Mapping):
        for pair in pairs.values():
            if isinstance(pair, Mapping):
                prompts.extend(
                    [
                        str(pair.get("positive", "")),
                        *(str(item) for item in pair.get("negatives", [])),
                    ]
                )
    prompts = list(dict.fromkeys(prompt for prompt in prompts if prompt))
    text_features = _text_features(prompts)
    with torch.no_grad():
        values = (image_features @ text_features.T).squeeze(0).tolist()
    return dict(zip(prompts, (float(value) for value in values), strict=True))


_SOURCE_RANK = {"wikidata:P180": 0, "wikidata:P136": 0, "title-heuristic": 1, "tag-fallback": 2}


def merge_into_sidecar(sidecar: dict[str, Any], vision_result: Mapping[str, Any]) -> dict[str, Any]:
    """Add only reviewable weaker-source proposals; never overwrite human/Wikidata state."""
    subject = sidecar.setdefault("subject", {})
    if not isinstance(subject, dict):
        raise ValueError("subject must be an object")
    tags = subject.get("content_tags", [])
    if not isinstance(tags, list):
        raise ValueError("subject.content_tags must be a list")
    by_id = {
        entry.get("id"): entry for entry in tags if isinstance(entry, dict) and entry.get("id")
    }
    changed = False
    passed_genres = [
        proposal
        for proposal in vision_result.get("all_scores", [])
        if proposal.get("passed") and str(proposal.get("tag", "")).startswith("genre:")
    ]
    current_genre_source = subject.get("genre_source")
    if passed_genres and _SOURCE_RANK.get(current_genre_source, 3) > 2:
        best_genre = max(passed_genres, key=lambda proposal: float(proposal.get("score", 0)))
        subject["genre"] = str(best_genre["tag"]).split(":", 1)[1]
        subject["genre_source"] = (
            "vision:contrastive" if best_genre.get("basis") == "contrastive" else MODEL_VERSION_TAG
        )
        changed = True
    for proposal in vision_result.get("all_scores", []):
        if not proposal.get("passed") or str(proposal.get("tag", "")).startswith("genre:"):
            continue
        tag = proposal["tag"]
        current = by_id.get(tag)
        if current and (
            current.get("state") in {"confirmed", "rejected", "added"}
            or _SOURCE_RANK.get(current.get("source"), 3) <= 2
        ):
            continue
        source = (
            "vision:contrastive" if proposal.get("basis") == "contrastive" else MODEL_VERSION_TAG
        )
        by_id[tag] = {
            "id": tag,
            "state": "proposed",
            "source": source,
            "basis": proposal.get("basis"),
            "evidence": f"clip-score={proposal['score']}",
        }
        changed = True
    subject["content_tags"] = [by_id[key] for key in sorted(by_id)]
    if changed:
        subject["needs_review"] = True
    sidecar["subject"] = subject
    return sidecar


def policy_accounting(config: Mapping[str, Any]) -> dict[str, str]:
    thresholds = config.get("thresholds", {})
    pairs = config.get("contrastive_pairs", {})
    accounting: dict[str, str] = {}
    for tag in TAG_PROMPTS:
        if isinstance(pairs, Mapping) and tag in pairs:
            accounting[tag] = "contrastive"
        elif isinstance(thresholds, Mapping) and tag in thresholds:
            accounting[tag] = _threshold_policy(thresholds[tag])[2]
        else:
            accounting[tag] = "inert"
    return accounting


def _fit_threshold(positive: list[float], negative: list[float]) -> tuple[float | None, float]:
    """Return the F1-maximising threshold and its conservative F1 floor."""
    if not positive:
        return None, 0.0
    if not negative:
        return round(min(positive) - 0.05, 4), 0.0
    best_threshold, best_f1 = None, 0.0
    candidates = sorted(set(positive + negative))
    for left, right in zip(candidates, candidates[1:], strict=False):
        threshold = (left + right) / 2
        true_positive = sum(score >= threshold for score in positive)
        if not true_positive:
            continue
        false_positive = sum(score >= threshold for score in negative)
        precision = true_positive / (true_positive + false_positive)
        recall = true_positive / len(positive)
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        if f1 > best_f1:
            best_threshold, best_f1 = round(threshold, 4), round(f1, 4)
    return best_threshold, best_f1


def calibrate() -> None:
    """Fit versioned threshold policy from the operational calibration set.

    The calibration corpus stays in FAA_WORKSPACE, while the generated policy
    and report deliberately land beside this script's versioned config so the
    result is reviewed and committed before it can govern production tagging.
    """
    calibration_path = Path(
        os.environ.get("FAA_CALIBRATION_SET", ROOT / "config" / "calibration_set.yaml")
    )
    if not calibration_path.exists():
        raise FileNotFoundError(f"calibration set not found: {calibration_path}")
    raw = yaml.safe_load(calibration_path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, Mapping):
        raise ValueError("calibration set must be a mapping")
    curated_sources = {"wikidata:P180", "wikidata:P136"}
    positives = {tag: [] for tag in TAG_PROMPTS}
    curated = {tag: [] for tag in TAG_PROMPTS}
    negatives = {tag: [] for tag in TAG_PROMPTS}
    encoded = 0
    for work_id, labels in raw.items():
        if not isinstance(work_id, str):
            continue
        scores = score_work(work_id, {})
        if scores is None:
            continue
        encoded += 1
        label_map = (
            labels if isinstance(labels, Mapping) else dict.fromkeys(labels or [], "unknown")
        )
        for tag, prompt in TAG_PROMPTS.items():
            score = scores[prompt]
            if tag in label_map:
                positives[tag].append(score)
                if label_map[tag] in curated_sources:
                    curated[tag].append(score)
            else:
                negatives[tag].append(score)
    threshold_config: dict[str, dict[str, Any]] = {}
    rows: list[dict[str, Any]] = []
    for tag in TAG_PROMPTS:
        sample, basis = (
            (curated[tag], "curated")
            if len(curated[tag]) >= 6
            else (positives[tag], "provisional-mixed")
        )
        threshold, f1 = _fit_threshold(sample, negatives[tag])
        row = {
            "tag": tag,
            "basis": basis if threshold is not None else "inert",
            "n_pos": len(positives[tag]),
            "n_curated": len(curated[tag]),
            "n_neg": len(negatives[tag]),
            "threshold": threshold,
            "f1_floor": f1,
        }
        rows.append(row)
        if threshold is not None:
            threshold_config[tag] = {"threshold": threshold, "f1": f1, "basis": basis}
    policy = load_config()
    policy["thresholds"] = threshold_config
    CONFIG_PATH.write_text(yaml.safe_dump(policy, sort_keys=True), encoding="utf-8")
    report_path = CONFIG_PATH.with_name("clip_calibration_report.json")
    report_path.write_text(
        json.dumps({"works_encoded": encoded, "tags": rows}, indent=2) + "\n", encoding="utf-8"
    )
    print(
        f"calibrated {len(threshold_config)} tags from {encoded} works -> {CONFIG_PATH}",
        file=sys.stderr,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wid")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--random", type=int)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--no-contrastive", action="store_true")
    parser.add_argument("--min-f1", type=float, default=0.50)
    parser.add_argument("--allow-provisional", action="store_true")
    parser.add_argument("--calibrate", action="store_true")
    args = parser.parse_args()
    config = load_config()
    if args.calibrate:
        calibrate()
        return 0
    if args.wid:
        work_ids = [args.wid]
    else:
        work_ids = sorted(path.name for path in STAGING.iterdir() if path.is_dir())
        if args.random:
            random.Random(42).shuffle(work_ids)
            work_ids = work_ids[: args.random]
        elif args.limit:
            work_ids = work_ids[: args.limit]
    enabled = sorted(config["thresholds"])
    contrastive = [] if args.no_contrastive else sorted(config["contrastive_pairs"])
    print(f"gate: threshold tags={enabled}; contrastive tags={contrastive}", file=sys.stderr)
    output: dict[str, Any] = {
        "model": MODEL_VERSION_TAG,
        "applied": args.apply,
        "gate": {
            "tags_enabled": sorted(set(enabled) | set(contrastive)),
            "threshold_tags": enabled,
            "contrastive_tags": contrastive,
        },
        "works": [],
    }
    counts = dict.fromkeys(contrastive, 0)
    for work_id in work_ids:
        started = time.monotonic()
        scores = score_work(work_id, config)
        if scores is None:
            output["works"].append({"work_id": work_id, "error": "no local master"})
            continue
        proposals = evaluate_policy(
            scores,
            config,
            min_f1=args.min_f1,
            no_contrastive=args.no_contrastive,
            allow_provisional=args.allow_provisional,
        )
        for proposal in proposals:
            if proposal["basis"] == "contrastive" and proposal["passed"]:
                counts[proposal["tag"]] += 1
        result = {
            "model_version": MODEL_VERSION_TAG,
            "all_scores": proposals,
            "passed_tags": [proposal["tag"] for proposal in proposals if proposal["passed"]],
        }
        entry: dict[str, Any] = {
            "work_id": work_id,
            "elapsed_ms": int((time.monotonic() - started) * 1000),
            "proposals": [proposal for proposal in proposals if proposal["passed"]],
        }
        if args.apply:
            sidecar_path = STAGING / work_id / "meta.json"
            if sidecar_path.exists():
                sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
                prior_subject = (
                    sidecar.get("subject") if isinstance(sidecar.get("subject"), dict) else {}
                )
                prior_tags = {
                    item.get("id")
                    for item in prior_subject.get("content_tags", [])
                    if isinstance(item, dict) and item.get("id")
                }
                sidecar = merge_into_sidecar(sidecar, result)
                subject = sidecar["subject"]
                entry["clip_tags_added"] = len(
                    {
                        item.get("id")
                        for item in subject.get("content_tags", [])
                        if isinstance(item, dict) and item.get("id")
                    }
                    - prior_tags
                )
                entry["genre"] = subject.get("genre")
                entry["genre_source"] = subject.get("genre_source")
                sidecar_path.write_text(
                    json.dumps(sidecar, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
                )
                entry["written"] = True
            else:
                entry["written"], entry["error"] = False, "sidecar missing"
        output["works"].append(entry)
    report = {
        "generated_at": _now(),
        "policy_accounting": policy_accounting(config),
        "contrastive_counts": counts,
        "contrastive_policies": config["contrastive_pairs"],
    }
    print(json.dumps(report, sort_keys=True), file=sys.stderr)
    if (
        not args.wid
        and not args.limit
        and not args.random
        and counts.get("filter:nudity-full", 0) <= 30
    ):
        print(
            "contrastive coverage check failed: filter:nudity-full must flag more than 30 works",
            file=sys.stderr,
        )
        return 1
    if args.json:
        output["totals"] = {"works": len(output["works"]), "contrastive_counts": counts}
        print(json.dumps(output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
