#!/usr/bin/env python3
"""Fast invariant gate for the versioned Tier-3 sidecar merge."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import vision_tag_works as vision


def main() -> int:
    original = {
        "subject": {
            "content_tags": [
                {"id": "filter:nudity-full", "source": "wikidata:P180", "state": "proposed"},
                {"id": "filter:religious", "source": "manual", "state": "confirmed"},
            ]
        }
    }
    result = vision.merge_into_sidecar(
        original,
        {
            "all_scores": [
                {"tag": "filter:nudity-full", "score": 0.9, "passed": True, "basis": "contrastive"},
                {"tag": "filter:occult", "score": 0.9, "passed": True, "basis": "contrastive"},
                {"tag": "filter:religious", "score": 0.9, "passed": True, "basis": "threshold"},
            ]
        },
    )
    tags = {item["id"]: item for item in result["subject"]["content_tags"]}
    checks = {
        "contrastive tag is added": tags["filter:occult"]["basis"] == "contrastive",
        "Wikidata P180 is preserved": tags["filter:nudity-full"]["source"] == "wikidata:P180",
        "reviewer state is preserved": tags["filter:religious"]["state"] == "confirmed",
        "new proposal is reviewable": result["subject"].get("needs_review") is True,
    }
    for name, passed in checks.items():
        print(f"{'PASS' if passed else 'FAIL'} {name}")
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
