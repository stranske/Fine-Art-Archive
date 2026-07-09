#!/usr/bin/env python3
"""Emit a IIIF Presentation v3 manifest for one Fine Art sidecar."""

from __future__ import annotations

import argparse
from pathlib import Path

from fine_art_archive.iiif import emit_manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("meta_json", type=Path, help="Path to a work meta.json sidecar")
    parser.add_argument("--out", type=Path, default=None, help="Directory for manifest.json")
    parser.add_argument(
        "--base-url",
        required=True,
        help="Absolute IIIF manifest URL to use as the manifest id",
    )
    args = parser.parse_args()

    print(emit_manifest(args.meta_json, args.out, base_url=args.base_url))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
