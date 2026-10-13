"""Replay two surgical production regressions; restore identical source in finally."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path


def _redact_local_paths(text: str) -> str:
    """Scrub machine-local paths from retained JUnit/log evidence."""
    text = re.sub(r"/private/var/folders/[^\s\"'<>]+", "<redacted-tmp>", text)
    text = re.sub(r"/Users/[^\s\"'<>]+", "<redacted-home>", text)
    text = re.sub(r'hostname="[^"]+"', 'hostname="redacted"', text)
    return text


def _write_redacted(path: Path, content: str) -> None:
    path.write_text(_redact_local_paths(content))


root = Path.cwd()
evidence = Path(__file__).resolve().parent
proofs = [
    (
        "strategy",
        "src/fine_art_archive/eink/targets.py",
        '    if strategy not in {"color", "grayscale", "duotone"}:',
        '    strategy = "color"  # deliberate regression: ignore A11 selection\n    if strategy not in {"color", "grayscale", "duotone"}:',
        "test_companion_feed_and_sd_apply_reported_strategy",
    ),
    (
        "etag",
        "src/fine_art_archive/eink/feed.py",
        "|a11-v1|{render_strategy}",
        "|a11-v1",
        "test_changed_policy_invalidates_cached_strategy",
    ),
]
receipts = []
# Compare final tests to the immutable original production implementation.
baseline = "5a236579"
paths = [
    "src/fine_art_archive/eink/targets.py",
    "src/fine_art_archive/eink/feed.py",
    "src/fine_art_archive/eink/sdcard.py",
    "src/fine_art_archive/eink/__init__.py",
    "src/fine_art_archive/api/main.py",
]
corrected = {name: (root / name).read_bytes() for name in paths}
originals = {name: subprocess.check_output(["git", "show", f"{baseline}:{name}"]) for name in paths}
original_command = [
    sys.executable,
    "-m",
    "pytest",
    "tests/test_eink_monochrome_delivery.py",
    "-k",
    "test_companion_feed_and_sd_apply_reported_strategy or test_changed_policy_invalidates_cached_strategy",
    "-q",
    "-o",
    "addopts=",
    f"--junitxml={evidence / 'original-red.xml'}",
]
try:
    for name, data in originals.items():
        (root / name).write_bytes(data)
    original_red = subprocess.run(
        original_command,
        env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"),
        text=True,
        capture_output=True,
    )
    _write_redacted(evidence / "original-red.log", original_red.stdout + original_red.stderr)
    _write_redacted(
        evidence / "original-red.xml",
        (evidence / "original-red.xml").read_text(encoding="utf-8"),
    )
    assert original_red.returncode == 1, ("original RED must fail", original_red.returncode)
finally:
    for name, data in corrected.items():
        (root / name).write_bytes(data)
assert all((root / name).read_bytes() == data for name, data in corrected.items())
receipts.append(
    {
        "mutation": "original-source",
        "baseline": subprocess.check_output(["git", "rev-parse", baseline], text=True).strip(),
        "test_sha256": hashlib.sha256(
            (root / "tests/test_eink_monochrome_delivery.py").read_bytes()
        ).hexdigest(),
        "corrected_source_sha256": {
            name: hashlib.sha256(data).hexdigest() for name, data in corrected.items()
        },
        "original_source_sha256": {
            name: hashlib.sha256(data).hexdigest() for name, data in originals.items()
        },
        "red_exit": original_red.returncode,
    }
)
for name, relative, needle, replacement, test in proofs:
    source = root / relative
    original = source.read_bytes()
    text = original.decode()
    assert text.count(needle) == 1, (name, text.count(needle))
    corrected_sha = hashlib.sha256(original).hexdigest()
    mutated = text.replace(needle, replacement).encode()
    command = [
        sys.executable,
        "-m",
        "pytest",
        "tests/test_eink_monochrome_delivery.py",
        "-k",
        test,
        "-q",
        "-o",
        "addopts=",
    ]
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    try:
        source.write_bytes(mutated)
        red = subprocess.run(
            command + [f"--junitxml={evidence / (name + '-red.xml')}"],
            env=env,
            text=True,
            capture_output=True,
        )
        _write_redacted(evidence / (name + "-red.log"), red.stdout + red.stderr)
        _write_redacted(
            evidence / (name + "-red.xml"),
            (evidence / (name + "-red.xml")).read_text(encoding="utf-8"),
        )
        assert red.returncode == 1, (name, "RED must fail", red.returncode)
    finally:
        source.write_bytes(original)
    assert hashlib.sha256(source.read_bytes()).hexdigest() == corrected_sha
    green = subprocess.run(
        command + [f"--junitxml={evidence / (name + '-green.xml')}"],
        env=env,
        text=True,
        capture_output=True,
    )
    _write_redacted(evidence / (name + "-green.log"), green.stdout + green.stderr)
    _write_redacted(
        evidence / (name + "-green.xml"),
        (evidence / (name + "-green.xml")).read_text(encoding="utf-8"),
    )
    assert green.returncode == 0, (name, "restored GREEN must pass", green.returncode)
    receipts.append(
        {
            "mutation": name,
            "source": relative,
            "corrected_sha256": corrected_sha,
            "mutated_sha256": hashlib.sha256(mutated).hexdigest(),
            "restored_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "command": command,
            "red_exit": red.returncode,
            "green_exit": green.returncode,
        }
    )
(evidence / "mutation-receipt.json").write_text(json.dumps(receipts, indent=2) + "\n")
print(json.dumps(receipts, indent=2))
