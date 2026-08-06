from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import vision_tag_works as vision  # noqa: E402


def _config() -> dict:
    return {
        "thresholds": {"filter:religious": 0.8},
        "contrastive_pairs": {
            "filter:nudity-full": {"positive": "nude", "negatives": ["clothed"], "margin": 0.1}
        },
    }


def test_contrastive_tag_fires_without_threshold() -> None:
    proposal = vision.tag_one("filter:nudity-full", {"nude": 0.9, "clothed": 0.7}, _config())
    assert proposal and proposal["basis"] == "contrastive"


def test_contrastive_tag_requires_margin() -> None:
    assert vision.tag_one("filter:nudity-full", {"nude": 0.8, "clothed": 0.75}, _config()) is None


def test_contrastive_tag_rejects_non_finite_and_boundary_scores() -> None:
    assert (
        vision.tag_one("filter:nudity-full", {"nude": float("nan"), "clothed": 0.1}, _config())
        is None
    )
    assert vision.tag_one("filter:nudity-full", {"nude": 0.8, "clothed": 0.7}, _config()) is None


def test_no_contrastive_uses_overlapping_threshold_policy() -> None:
    config = _config()
    config["thresholds"]["filter:nudity-full"] = {"threshold": 0.8, "f1": 0.9}
    proposal = vision.propose(
        {"filter:nudity-full": 0.85, "nude": 0.95, "clothed": 0.1}, config, no_contrastive=True
    )
    assert proposal and proposal[0]["basis"] == "threshold"


def test_min_f1_applies_only_to_threshold_proposals() -> None:
    config = _config()
    config["thresholds"]["filter:religious"] = {"threshold": 0.8, "f1": 0.6}
    proposals = vision.propose(
        {"filter:religious": 0.9, "nude": 0.9, "clothed": 0.7}, config, min_f1=0.8
    )
    assert [proposal["id"] for proposal in proposals] == ["filter:nudity-full"]


def test_non_contrastive_tag_retains_threshold_behavior() -> None:
    assert vision.tag_one("filter:religious", {"filter:religious": 0.81}, _config())
    assert vision.tag_one("filter:religious", {"filter:religious": 0.79}, _config()) is None


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
        [
            {
                "id": "filter:nudity-full",
                "source": "vision:contrastive",
                "state": "proposed",
                "basis": "contrastive",
            },
            {
                "id": "filter:occult",
                "source": "vision:contrastive",
                "state": "proposed",
                "basis": "contrastive",
            },
        ],
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
        [{"id": "filter:nudity-full", "source": "vision:contrastive", "state": "proposed"}],
    )
    assert "needs_review" not in sidecar["subject"]
