"""Replay manifest-membership regressions and restore production bytes."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

root = Path.cwd()
evidence = Path(__file__).resolve().parent
source = root / "src/fine_art_archive/api/main.py"
corrected = source.read_bytes()
baseline = "30e1006a9c35e9b7e628ad53b8e62deb2a404212"
command = [
    sys.executable,
    "-m",
    "pytest",
    "tests/test_healthz_manifest_drift.py",
    "-k",
    "same_count or differences_are_sorted",
    "-q",
    "-o",
    "addopts=",
]
needle = "manifest_drift == 0 and membership_matches"
assert corrected.decode().count(needle) == 1
mutated = corrected.decode().replace(needle, "manifest_drift == 0").encode()
receipts = []


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def capture(name: str, expected: int) -> None:
    result = subprocess.run(
        command + [f"--junitxml={evidence / (name + '.xml')}"],
        text=True,
        capture_output=True,
        env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"),
    )
    for target, text in [
        (evidence / (name + ".log"), result.stdout + result.stderr),
        (evidence / (name + ".xml"), (evidence / (name + ".xml")).read_text()),
    ]:
        text = re.sub(r"/Users/[^\s\"'<>]+", "<redacted-home>", text)
        text = re.sub(r"/private/var/folders/[^\s\"'<>]+", "<redacted-tmp>", text)
        text = re.sub(r'hostname="[^"]+"', 'hostname="redacted"', text)
        target.write_text(text)
    assert result.returncode == expected, (name, result.stdout, result.stderr)
    receipts.append(
        {
            "phase": name,
            "exit": result.returncode,
            "source_sha256": digest(source.read_bytes()),
            "command": ["python", *command[1:]],
        }
    )


try:
    source.write_bytes(
        subprocess.check_output(["git", "show", f"{baseline}:src/fine_art_archive/api/main.py"])
    )
    capture("original-red", 1)
    source.write_bytes(mutated)
    capture("count-only-red", 1)
finally:
    source.write_bytes(corrected)
assert source.read_bytes() == corrected
capture("restored-green", 0)
receipt = {
    "baseline": baseline,
    "corrected_sha256": digest(corrected),
    "restored_sha256": digest(source.read_bytes()),
    "test_sha256": digest((root / "tests/test_healthz_manifest_drift.py").read_bytes()),
    "phases": receipts,
}
(evidence / "mutation-receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
print(json.dumps(receipt, indent=2))
