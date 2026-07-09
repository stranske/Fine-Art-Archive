#!/usr/bin/env python3
"""Record/verify sidecar fixity and create or verify BagIt packages."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from fine_art_archive.fixity import create_bag, record_fixity, verify_bag, verify_fixity


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    record = sub.add_parser("record", help="Record current master SHA-256 in a sidecar")
    record.add_argument("meta_json", type=Path)
    record.add_argument("--master", type=Path, default=None)
    record.add_argument("--actor", default="codex")

    verify = sub.add_parser("verify", help="Verify a sidecar master SHA-256")
    verify.add_argument("meta_json", type=Path)
    verify.add_argument("--master", type=Path, default=None)
    verify.add_argument("--record", action="store_true", help="Append a verification event")
    verify.add_argument("--actor", default="codex")

    bag = sub.add_parser("bag", help="Create a minimal BagIt package")
    bag.add_argument("bag_dir", type=Path)
    bag.add_argument("source_dirs", type=Path, nargs="+")

    bag_verify = sub.add_parser("bag-verify", help="Verify manifest-sha256.txt in a bag")
    bag_verify.add_argument("bag_dir", type=Path)

    args = parser.parse_args()

    try:
        if args.command == "record":
            print(
                json.dumps(
                    record_fixity(
                        args.meta_json, master_path=args.master, actor=args.actor
                    ).as_dict(),
                    indent=2,
                )
            )
            return 0
        if args.command == "verify":
            result = verify_fixity(
                args.meta_json,
                master_path=args.master,
                record=args.record,
                actor=args.actor,
            )
            print(json.dumps(result.as_dict(), indent=2))
            return 0 if result.matched else 2
        if args.command == "bag":
            print(create_bag(args.source_dirs, args.bag_dir))
            return 0
        if args.command == "bag-verify":
            bag_result = verify_bag(args.bag_dir)
            print(json.dumps(bag_result.as_dict(), indent=2))
            return 0 if bag_result.valid else 2
    except (FileNotFoundError, ValueError, FileExistsError) as exc:
        print(json.dumps({"error": str(exc)}, indent=2))
        return 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
