#!/usr/bin/env python3
"""Report variant-link identity classifications without changing sidecars."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fine_art_archive.identity.variant_identity import (  # noqa: E402
    classify_variant_links,
    finding_as_dict,
)


def load_sidecars(root: Path) -> list[dict[str, Any]]:
    """Load readable ``meta.json`` files beneath *root* for a read-only audit."""
    metas: list[dict[str, Any]] = []
    for path in root.rglob("meta.json"):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(value, dict):
            metas.append(value)
    return metas


def report(root: Path) -> dict[str, Any]:
    """Build a stable JSON report; this function never writes to *root*."""
    findings = classify_variant_links(load_sidecars(root))
    return {
        "read_only": True,
        "sidecar_root": str(root),
        "finding_count": len(findings),
        "verdict_counts": dict(sorted(Counter(item.verdict.value for item in findings).items())),
        "findings": [finding_as_dict(item) for item in findings],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sidecar_root", type=Path)
    args = parser.parse_args()
    print(json.dumps(report(args.sidecar_root), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
