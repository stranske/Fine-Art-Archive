#!/usr/bin/env python3
"""Assess explicit local works using the configured source-quality routing data."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fine_art_archive.collect.acquisition_flow import run_acquisition_flow  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--works-root", required=True, type=Path)
    parser.add_argument("--host-registry", required=True, type=Path)
    parser.add_argument("--source-quality", required=True, type=Path)
    parser.add_argument("--host-qid", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--work-class", default="western-painting-19c")
    parser.add_argument("--max-items", type=int)
    args = parser.parse_args(argv)

    for option, path in (
        ("--works-root", args.works_root),
        ("--host-registry", args.host_registry),
        ("--source-quality", args.source_quality),
    ):
        if not path.exists():
            parser.error(f"{option} does not exist: {path}")
    if not args.works_root.is_dir():
        parser.error(f"--works-root is not a directory: {args.works_root}")

    work_dirs = sorted(path for path in args.works_root.iterdir() if path.is_dir())
    results = run_acquisition_flow(
        args.source,
        work_dirs,
        max_items=args.max_items,
        host_qid=args.host_qid,
        work_class=args.work_class,
        source_quality_path=args.source_quality,
        host_registry_path=args.host_registry,
    )
    selected_source = results[0].source if results else None
    print(
        json.dumps({"assessed": len(results), "selected_source": selected_source}, sort_keys=True)
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
