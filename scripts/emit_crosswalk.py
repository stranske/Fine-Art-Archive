#!/usr/bin/env python3
"""Emit Dublin Core and Linked Art projections for one Fine Art sidecar."""

from __future__ import annotations

import argparse
from pathlib import Path

from fine_art_archive.crosswalk import emit_crosswalks


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("meta_json", type=Path, help="Path to a work meta.json sidecar")
    parser.add_argument(
        "--out", type=Path, default=None, help="Directory for dc.json and linkedart.json"
    )
    args = parser.parse_args()

    dc_path, linked_art_path = emit_crosswalks(args.meta_json, args.out)
    print(dc_path)
    print(linked_art_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
