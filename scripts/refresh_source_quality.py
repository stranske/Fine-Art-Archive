#!/usr/bin/env python3
"""Rebuild source-quality routing data from an explicit local works tree."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fine_art_archive.quality.source_quality import (  # noqa: E402
    aggregate_sidecars,
    write_aggregates_atomically,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--works-root", required=True, type=Path)
    parser.add_argument("--host-registry", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--manifest-csv", type=Path)
    args = parser.parse_args(argv)

    if not args.works_root.is_dir():
        parser.error(f"--works-root is not a directory: {args.works_root}")
    if not args.host_registry.is_file():
        parser.error(f"--host-registry is not a file: {args.host_registry}")

    aggregates = aggregate_sidecars(
        args.works_root,
        args.host_registry,
        manifest_csv=args.manifest_csv,
    )
    write_aggregates_atomically(aggregates, args.output)
    print(
        f"refreshed {args.output}: {aggregates['n_sidecars_scanned']} sidecars, "
        f"{aggregates['n_real_sources']} real sources"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
