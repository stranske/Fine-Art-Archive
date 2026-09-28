"""Guards against Dropbox conflict forks beside Track A workspace files."""

from __future__ import annotations

from pathlib import Path

import pytest

import fine_art_archive.api.gates as gates
from fine_art_archive.api.gates import (
    assert_workspace_files_unforked,
    automation_lock_path,
    conflicted_copy_siblings,
    is_cloud_synced_workspace_path,
    resolve_automation_lock_path,
)


def test_conflicted_copy_siblings_detects_dropbox_fork_names(tmp_path: Path) -> None:
    ops = tmp_path / "operations.log"
    ops.write_text("ok\n", encoding="utf-8")
    fork = tmp_path / "operations.log (Teacher's conflicted copy 2026-09-21)"
    fork.write_text("stale\n", encoding="utf-8")
    before_extension = tmp_path / "operations (Teacher's conflicted copy 2026-09-21).log"
    before_extension.write_text("older\n", encoding="utf-8")

    assert conflicted_copy_siblings(ops) == sorted([fork.name, before_extension.name])


def test_conflicted_copy_siblings_empty_when_clean(tmp_path: Path) -> None:
    frontier = tmp_path / "discovery_frontier.json"
    frontier.write_text("{}", encoding="utf-8")
    assert conflicted_copy_siblings(frontier) == []


def test_assert_workspace_files_unforked_raises_with_fork(tmp_path: Path) -> None:
    ops = tmp_path / "operations.log"
    ops.write_text("ok\n", encoding="utf-8")
    (tmp_path / "operations.log (conflicted copy 1)").write_text("x\n", encoding="utf-8")

    with pytest.raises(ValueError, match="conflict copies detected"):
        assert_workspace_files_unforked(ops)


def test_assert_workspace_files_unforked_passes_clean_fixture(tmp_path: Path) -> None:
    ops = tmp_path / "operations.log"
    frontier = tmp_path / "discovery_frontier.json"
    ops.write_text("[]\n", encoding="utf-8")
    frontier.write_text("{}\n", encoding="utf-8")
    assert_workspace_files_unforked(ops, frontier)


def test_automation_lock_path_is_not_on_dropbox_tree() -> None:
    lock = automation_lock_path("growth_tick.lock")
    assert not is_cloud_synced_workspace_path(lock)


def test_automation_lock_path_rejects_configured_dropbox_directory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configured = Path.home() / "Library" / "CloudStorage" / "Dropbox" / "faa-locks"
    monkeypatch.setattr(gates, "AUTOMATION_LOCK_DIR", configured)

    lock = gates.automation_lock_path("growth_tick.lock")

    assert lock.parent == gates._DEFAULT_AUTOMATION_LOCK_DIR
    assert not is_cloud_synced_workspace_path(lock)


def test_resolve_automation_lock_path_redirects_synced_candidate(tmp_path: Path) -> None:
    # Simulate a lock file colocated with workspace data on a Dropbox path.
    dropbox_like = Path.home() / "Library" / "CloudStorage" / "Dropbox" / "tmp-faa-test"
    candidate = dropbox_like / "growth_tick.lock"
    resolved = resolve_automation_lock_path(candidate, "growth_tick.lock")
    assert resolved != candidate
    assert not is_cloud_synced_workspace_path(resolved)


def test_sidecar_file_lock_redirects_lock_when_sidecar_is_on_dropbox(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """_sidecar_file_lock must not place the lock file beside a Dropbox-synced sidecar.

    Deliberate-break: comment out the gates.resolve_automation_lock_path call in
    _sidecar_file_lock (reverting to path.with_suffix) — this assertion fails because
    the lock file lands in tmp_path instead of the host-local automation lock dir.
    """
    import fine_art_archive.api.main as main_mod
    import fine_art_archive.fixity as fixity_mod

    # Treat tmp_path as a cloud-synced workspace so resolve_automation_lock_path
    # redirects any lock that would land there to the host-local automation dir.
    monkeypatch.setattr(gates, "is_cloud_synced_workspace_path", lambda p: str(tmp_path) in str(p))

    sidecar_path = tmp_path / "meta.json"
    sidecar_path.write_text("{}", encoding="utf-8")

    lock_files_created: list[Path] = []
    original_open = Path.open

    def _tracking_open(self: Path, *args, **kwargs):  # type: ignore[no-untyped-def]
        if self.suffix == ".lock":
            lock_files_created.append(self)
        return original_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, "open", _tracking_open)

    for module in (main_mod, fixity_mod):
        with module._sidecar_file_lock(sidecar_path):
            pass

    assert lock_files_created, "No lock file was created"
    for lock_file in lock_files_created:
        assert str(tmp_path) not in str(
            lock_file
        ), f"Lock file landed beside Dropbox sidecar: {lock_file}"


def test_sidecar_lock_name_distinguishes_equal_basenames(tmp_path: Path) -> None:
    first = tmp_path / "first" / "meta.json"
    second = tmp_path / "second" / "meta.json"

    assert gates.sidecar_lock_name(first) != gates.sidecar_lock_name(second)
    assert gates.sidecar_lock_name(first) == gates.sidecar_lock_name(first)
    assert gates.sidecar_lock_name(first).endswith(".lock")
