from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_FIXTURES = {
    "valid_run.json",
    "missing_cost.json",
    "unsafe_rows_inline.json",
    "unsafe_prompt_inline.json",
    "artifact_not_in_manifest.json",
    "bad_identity_ref.json",
}


def test_validate_run_contract_self_smoke() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "validate_run_contract.py"),
            "--self-smoke",
            "--registry",
            str(ROOT / "config" / "backplane_participants.json"),
            "--repo",
            "stranske/Fine-Art-Archive",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "FAIL fixture" not in output, output
    assert "NOTE: no fixtures found" not in output, output

    observed = {
        line.split("fixture ", 1)[1].split(":", 1)[0]
        for line in result.stdout.splitlines()
        if line.startswith("PASS fixture ")
    }
    assert observed == EXPECTED_FIXTURES, output
