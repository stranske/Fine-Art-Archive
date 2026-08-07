from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import vision_tag_works as vision  # noqa: E402


def _config() -> dict:
    return {
        "thresholds": {
            "filter:religious": {"threshold": 0.8, "f1": 0.9, "basis": "curated"},
            "filter:nudity-full": {"threshold": 0.8, "f1": 0.9, "basis": "curated"},
        },
        "contrastive_pairs": {
            "filter:nudity-full": {"positive": "nude", "negatives": ["clothed"], "margin": 0.1}
        },
    }


def _scores(positive: float, negative: float) -> dict[str, float]:
    return {"nude": positive, "clothed": negative, vision.TAG_PROMPTS["filter:religious"]: 0.9}


def test_contrastive_tag_fires_without_threshold() -> None:
    proposals = vision.evaluate_policy(_scores(0.9, 0.7), _config())
    proposal = next(item for item in proposals if item["tag"] == "filter:nudity-full")
    assert proposal["passed"] and proposal["basis"] == "contrastive"


def test_contrastive_tag_requires_margin() -> None:
    proposals = vision.evaluate_policy(_scores(0.8, 0.75), _config())
    proposal = next(item for item in proposals if item["tag"] == "filter:nudity-full")
    assert proposal["passed"] is False


def test_contrastive_tag_rejects_non_finite_and_boundary_scores() -> None:
    invalid = vision.evaluate_policy(_scores(float("nan"), 0.1), _config())
    assert all(item["tag"] != "filter:nudity-full" for item in invalid)
    boundary = vision.evaluate_policy(_scores(0.8, 0.7), _config())
    proposal = next(item for item in boundary if item["tag"] == "filter:nudity-full")
    assert proposal["passed"] is False


def test_no_contrastive_uses_overlapping_threshold_policy() -> None:
    config = _config()
    config["thresholds"]["filter:nudity-full"] = {"threshold": 0.8, "f1": 0.9}
    scores = {
        vision.TAG_PROMPTS["filter:nudity-full"]: 0.85,
        "nude": 0.95,
        "clothed": 0.1,
        vision.TAG_PROMPTS["filter:religious"]: 0.0,
    }
    proposal = next(
        item
        for item in vision.evaluate_policy(scores, config, no_contrastive=True)
        if item["tag"] == "filter:nudity-full"
    )
    assert proposal["basis"] == "threshold" and proposal["passed"]


def test_min_f1_applies_only_to_threshold_proposals() -> None:
    config = _config()
    config["thresholds"]["filter:religious"] = {"threshold": 0.8, "f1": 0.6}
    proposals = vision.evaluate_policy(_scores(0.9, 0.7), config, min_f1=0.8)
    assert [proposal["tag"] for proposal in proposals if proposal["passed"]] == [
        "filter:nudity-full"
    ]


def test_non_contrastive_tag_retains_threshold_behavior() -> None:
    prompt = vision.TAG_PROMPTS["filter:religious"]
    assert next(
        item
        for item in vision.evaluate_policy({prompt: 0.81}, _config())
        if item["tag"] == "filter:religious"
    )["passed"]
    assert not next(
        item
        for item in vision.evaluate_policy({prompt: 0.79}, _config())
        if item["tag"] == "filter:religious"
    )["passed"]


def test_policy_accounts_for_every_known_tag() -> None:
    accounting = vision.policy_accounting(_config())
    assert set(accounting) == set(vision.TAG_PROMPTS)
    assert accounting["filter:nudity-full"] == "contrastive"


def test_merge_preserves_wikidata_and_marks_proposal_reviewable() -> None:
    sidecar = {
        "subject": {
            "content_tags": [
                {"id": "filter:nudity-full", "source": "wikidata:P180", "state": "proposed"}
            ]
        }
    }
    vision.merge_into_sidecar(
        sidecar,
        {
            "all_scores": [
                {"tag": "filter:nudity-full", "score": 0.9, "passed": True, "basis": "contrastive"},
                {"tag": "filter:occult", "score": 0.9, "passed": True, "basis": "contrastive"},
            ]
        },
    )
    tags = {tag["id"]: tag for tag in sidecar["subject"]["content_tags"]}
    assert tags["filter:nudity-full"]["source"] == "wikidata:P180"
    assert tags["filter:occult"]["basis"] == "contrastive"
    assert sidecar["subject"]["needs_review"] is True


def test_merge_does_not_mark_review_when_all_proposals_are_blocked() -> None:
    sidecar = {
        "subject": {
            "content_tags": [
                {"id": "filter:nudity-full", "source": "wikidata:P180", "state": "proposed"}
            ]
        }
    }
    vision.merge_into_sidecar(
        sidecar,
        {
            "all_scores": [
                {"tag": "filter:nudity-full", "score": 0.9, "passed": True, "basis": "contrastive"},
            ]
        },
    )
    assert "needs_review" not in sidecar["subject"]
