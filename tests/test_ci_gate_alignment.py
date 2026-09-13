"""PR Gate and main CI must agree on black format enforcement."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
REUSABLE_CI = "stranske/Workflows/.github/workflows/reusable-10-ci-python.yml@main"


def _workflow(path: str) -> dict[str, Any]:
    return cast(dict[str, Any], yaml.safe_load((REPO_ROOT / path).read_text(encoding="utf-8")))


def _reusable_python_job(workflow: dict[str, Any]) -> tuple[str, dict[str, Any], str]:
    for job_id, job in workflow["jobs"].items():
        uses = job.get("uses", "")
        if "reusable-10-ci-python.yml" in uses:
            return job_id, cast(dict[str, Any], job.get("with") or {}), uses
    raise AssertionError("no reusable python-ci job found")


def test_gate_and_main_ci_agree_on_format_check() -> None:
    pr_gate = _workflow(".github/workflows/pr-00-gate.yml")
    main_ci = _workflow(".github/workflows/ci.yml")

    _, gate_with, gate_uses = _reusable_python_job(pr_gate)
    _, main_with, main_uses = _reusable_python_job(main_ci)

    assert gate_uses == main_uses == REUSABLE_CI

    assert "format_check" in gate_with, "format_check must be explicit in pr-00-gate.yml"
    assert gate_with["format_check"] is True

    assert "format_check" in main_with, "format_check must be explicit in ci.yml"
    assert main_with["format_check"] is True
