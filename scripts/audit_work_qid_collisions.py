#!/usr/bin/env python3
"""Read-only audit of work Q-ID collision counters for a sidecar corpus."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fine_art_archive.identity.work_qid_collision_audit import (  # noqa: E402
    actionable_offenders,
    measure_work_qid_collisions,
    measures_as_dict,
    worst_offenders,
)

REPORT_SCHEMA_VERSION = 2


def load_sidecars(root: Path) -> list[dict[str, Any]]:
    metas: list[dict[str, Any]] = []
    for path in sorted(root.glob("*/meta.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        except OSError as exc:
            raise RuntimeError(f"cannot read sidecar {path}") from exc
        if isinstance(value, dict):
            metas.append(value)
    return metas


def report(root: Path) -> dict[str, Any]:
    metas = load_sidecars(root)
    measures = measure_work_qid_collisions(metas)
    return {
        "read_only": True,
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "sidecar_root": str(root),
        "measures": measures_as_dict(measures),
        "worst_offenders": worst_offenders(metas),
        # What a review surface must read. `worst_offenders` lists every shared
        # Q-ID including the complementary-crop groups, which are correct and
        # have nothing to decide; this drops those.
        "actionable_offenders": actionable_offenders(metas),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sidecar_root", type=Path)
    args = parser.parse_args()
    print(json.dumps(report(args.sidecar_root), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
