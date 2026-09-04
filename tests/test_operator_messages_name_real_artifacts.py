"""An operator message must not send someone to a tool that does not exist.

`/variant_upgrades/{wid}/decision` told the operator to "run
scripts/promote_variant_upgrade.py" for eleven months while no such file was in
the tree. The accept was recorded, the review surface cleared, and the named
executor did not exist — the failure was silent because the only thing that
would have caught it was someone typing the command.

Prose in a docstring does not catch that a second time; a check does. These
tests read the API module's own text, pull every repo-relative `scripts/*.py`
path out of it, and require each one to resolve on disk.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fine_art_archive.api import main as api_main
from fine_art_archive.api import store as api_store

REPO_ROOT = Path(__file__).resolve().parents[1]
MAIN_PY = REPO_ROOT / "src" / "fine_art_archive" / "api" / "main.py"

# Repo-relative script paths only. The lookbehind drops `Claude Project/scripts/x.py`
# and friends: those name a different tree, and asserting them against this repo
# would fail for the wrong reason.
SCRIPT_RE = re.compile(r"(?<![\w/-])scripts/[A-Za-z0-9_./-]+\.py")


def _named_scripts(text: str) -> list[str]:
    return sorted(set(SCRIPT_RE.findall(text)))


def test_every_script_named_in_the_api_module_exists() -> None:
    source = MAIN_PY.read_text(encoding="utf-8")

    # Prove the scan actually ran before trusting what it did or did not find.
    # Without this, an unreadable or moved main.py would report the same clean
    # "no bad paths" as a genuinely clean one — one sentinel meaning both
    # "could not measure" and "measured, and it is fine".
    assert source, f"could not read {MAIN_PY}; the check below would be vacuous"

    missing = [path for path in _named_scripts(source) if not (REPO_ROOT / path).is_file()]
    assert not missing, (
        f"{MAIN_PY.name} names {len(missing)} script(s) that do not exist: "
        f"{', '.join(missing)}. Operator-facing text must only name real artifacts."
    )


def test_the_regex_finds_the_paths_it_is_supposed_to_find() -> None:
    """Guard the guard: a regex that matched nothing would pass the test above."""
    found = _named_scripts("run scripts/promote_variant_upgrade.py then scripts/build_manifest.py")
    assert found == ["scripts/build_manifest.py", "scripts/promote_variant_upgrade.py"]
    # A path rooted in another tree is deliberately NOT a repo-relative claim.
    assert _named_scripts("see Claude Project/scripts/test_vision_tag_merge.py") == []


def test_accept_message_names_only_artifacts_that_exist(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The live accept response, not just the source: every tool it names is real."""
    candidates_csv = tmp_path / "variant_upgrade_candidates.csv"
    candidates_csv.write_text(
        "existing_wid,title,artist\nknown-work,A Work,An Artist\n", encoding="utf-8"
    )
    monkeypatch.setattr(api_main, "VARIANT_UPGRADE_CSV", candidates_csv)
    monkeypatch.setattr(
        api_main, "VARIANT_UPGRADE_DECISIONS", tmp_path / "variant_upgrade_decisions.jsonl"
    )

    with TestClient(api_main.app) as client:
        response = client.post(
            "/variant_upgrades/known-work/decision",
            json={"decision": "accept", "note": "better scan"},
        )
    assert response.status_code == 200
    message = response.json()["next_steps"]

    named = _named_scripts(message)
    assert named, "the accept message should still tell the operator what to run"
    missing = [path for path in named if not (REPO_ROOT / path).is_file()]
    assert not missing, f"accept message names non-existent script(s): {', '.join(missing)}"

    # permissions.md is the other artifact it cites. It is a workspace file, not a
    # repo file, so this asserts the claim is about the ledger rather than about a
    # path in this tree that would silently never resolve.
    assert "permissions.md" in message
    assert not (
        REPO_ROOT / "permissions.md"
    ).exists(), "permissions.md now exists in the repo; the message should say where it is"


def test_reject_message_promises_nothing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    candidates_csv = tmp_path / "variant_upgrade_candidates.csv"
    candidates_csv.write_text("existing_wid,title\nknown-work,A Work\n", encoding="utf-8")
    monkeypatch.setattr(api_main, "VARIANT_UPGRADE_CSV", candidates_csv)
    monkeypatch.setattr(
        api_main, "VARIANT_UPGRADE_DECISIONS", tmp_path / "variant_upgrade_decisions.jsonl"
    )
    monkeypatch.setattr(api_store, "get_manifest_row", lambda _wid: None)

    with TestClient(api_main.app) as client:
        response = client.post(
            "/variant_upgrades/known-work/decision", json={"decision": "reject", "note": ""}
        )
    assert response.status_code == 200
    assert _named_scripts(response.json()["next_steps"]) == []
