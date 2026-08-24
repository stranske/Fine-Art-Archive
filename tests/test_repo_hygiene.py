"""Regression checks for tracked generated-directory hygiene."""

from __future__ import annotations

import subprocess


def _git_ls_files(pattern: str) -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", pattern],
        check=True,
        capture_output=True,
        text=True,
    )
    return [line for line in result.stdout.splitlines() if line]


def _git_ignore_rule(path: str) -> str | None:
    result = subprocess.run(
        ["git", "check-ignore", "-v", "--no-index", "--", path],
        capture_output=True,
        text=True,
    )
    if result.returncode == 1:
        return None
    result.check_returncode()
    match = result.stdout.strip()
    if not match:
        return None
    # With --no-index Git reports success for both ignore and negation matches.
    # The rule field is therefore authoritative for an explicitly unignored path.
    rule = match.split("\t", 1)[0].rsplit(":", 1)[-1]
    return None if rule.startswith("!") else match


def test_generated_dirs_untracked_and_vendored_preserved() -> None:
    """Root residue stays untracked while vendored workflow dependencies remain tracked."""
    assert not _git_ls_files("node_modules"), "Root node_modules/ must not be tracked."
    assert not _git_ls_files("tests/__pycache__"), "Tracked test bytecode must be removed."

    vendored = _git_ls_files(".github/scripts/node_modules")
    assert vendored, ".github/scripts/node_modules/ must remain tracked."

    root_rule = _git_ignore_rule("node_modules/probe.js")
    assert not _git_ignore_rule(".github/scripts/node_modules/minimatch/package.json")
    assert root_rule and root_rule.startswith(".gitignore:")
    root_pattern = root_rule.split("\t", 1)[0].rsplit(":", 1)[-1]
    assert root_pattern in {"node_modules/", "/node_modules/"}
