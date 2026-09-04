"""Select acquisition candidates from JSON and publish selected IDs plus lens reports.

Input is either a JSON list of candidate objects or an object containing a
``candidates`` list. Output is a JSON object with deterministic ``selected_ids``
and one status record per selection lens.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fine_art_archive.selection.lenses import select  # noqa: E402


def load_candidates(path: Path) -> list[dict[str, Any]]:
    """Read the documented candidate-list input schema."""
    payload = json.loads(path.read_text(encoding="utf-8"))
    candidates = payload.get("candidates") if isinstance(payload, dict) else payload
    if not isinstance(candidates, list) or not all(isinstance(row, dict) for row in candidates):
        raise ValueError("input must be a JSON candidate list or an object with a candidates list")
    return candidates


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="JSON candidate list")
    parser.add_argument("--output", required=True, type=Path, help="destination JSON report")
    parser.add_argument("--batch-cap", required=True, type=int, help="maximum candidates to select")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.batch_cap < 1:
        raise ValueError("--batch-cap must be at least one")
    selected, reports = select(load_candidates(args.input), batch_cap=args.batch_cap)
    payload = {
        "selected_ids": [str(candidate.get("qid", "")) for candidate in selected],
        "lens_reports": [report.summary() for report in reports],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
