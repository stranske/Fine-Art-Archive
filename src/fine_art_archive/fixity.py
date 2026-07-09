"""Fixity recording, verification, and minimal BagIt packaging helpers."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tempfile
from collections.abc import Iterable
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from fine_art_archive import sidecar

CHUNK_SIZE = 1024 * 1024
BAGIT_VERSION = "0.97"


@dataclass(frozen=True)
class FixityResult:
    """Result for one sidecar/master fixity check."""

    meta_path: Path
    master_path: Path
    expected_sha256: str | None
    actual_sha256: str

    @property
    def matched(self) -> bool:
        return self.expected_sha256 == self.actual_sha256

    def as_dict(self) -> dict[str, Any]:
        return {
            "meta_path": str(self.meta_path),
            "master_path": str(self.master_path),
            "expected_sha256": self.expected_sha256,
            "actual_sha256": self.actual_sha256,
            "matched": self.matched,
        }


@dataclass(frozen=True)
class BagVerificationResult:
    """Manifest verification result for a BagIt package."""

    bag_dir: Path
    checked: int
    mismatches: tuple[str, ...] = ()
    missing: tuple[str, ...] = ()
    unexpected: tuple[str, ...] = ()

    @property
    def valid(self) -> bool:
        return not self.mismatches and not self.missing and not self.unexpected

    def as_dict(self) -> dict[str, Any]:
        return {
            "bag_dir": str(self.bag_dir),
            "checked": self.checked,
            "valid": self.valid,
            "mismatches": list(self.mismatches),
            "missing": list(self.missing),
            "unexpected": list(self.unexpected),
        }


def utc_now() -> str:
    """Return the canonical timestamp shape used in sidecar history."""
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path | str) -> str:
    """Hash a file without loading the entire master into memory."""
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest()


def master_path_for_sidecar(meta_path: Path | str, meta: dict[str, Any] | None = None) -> Path:
    """Resolve the master image path named by a sidecar."""
    meta_file = Path(meta_path)
    loaded = meta if meta is not None else sidecar.load(meta_file)
    filename = ((loaded.get("files") or {}).get("master") or {}).get("filename")
    if not filename:
        raise ValueError("sidecar files.master.filename is required for fixity")
    return meta_file.parent / str(filename)


def _fixity_event(
    result: FixityResult,
    *,
    verified_at: str,
    status: str,
) -> dict[str, Any]:
    return {
        "algorithm": "sha256",
        "sha256": result.actual_sha256,
        "expected_sha256": result.expected_sha256,
        "verified_at": verified_at,
        "master_path": result.master_path.name,
        "status": status,
    }


def _append_fixity_event(
    meta: dict[str, Any],
    event: dict[str, Any],
    *,
    actor: str,
) -> dict[str, Any]:
    verification = (
        cast(dict[str, Any], meta["verification"])
        if isinstance(meta.get("verification"), dict)
        else {}
    )
    meta["verification"] = verification
    events = verification.setdefault("fixity_events", [])
    events.append(event)
    sidecar.merge_history(
        meta,
        {
            "ts": event["verified_at"],
            "actor": actor,
            "op": "fixity_verified",
            "notes": f"sha256 {event['status']}: {event['sha256']}",
        },
    )
    return meta


@contextmanager
def _sidecar_file_lock(path: Path):
    lock_path = path.with_suffix(path.suffix + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a") as lock_file:
        try:
            import fcntl

            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            yield
        finally:
            with suppress(NameError, OSError):
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _write_sidecar_atomic(path: Path, meta: dict[str, Any]) -> None:
    sidecar.validate(meta)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(meta, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        if path.exists():
            tmp_path.chmod(stat.S_IMODE(path.stat().st_mode))
        os.replace(tmp_path, path)
    except Exception:
        tmp_path.unlink(missing_ok=True)
        raise


def _ensure_master_block(meta: dict[str, Any]) -> dict[str, Any]:
    files = cast(dict[str, Any], meta["files"]) if isinstance(meta.get("files"), dict) else {}
    master = cast(dict[str, Any], files["master"]) if isinstance(files.get("master"), dict) else {}
    meta["files"] = files
    files["master"] = master
    return master


def verify_fixity(
    meta_path: Path | str,
    *,
    master_path: Path | str | None = None,
    record: bool = False,
    actor: str = "codex",
    verified_at: str | None = None,
) -> FixityResult:
    """Re-hash a sidecar's master file and report whether it matches metadata."""
    meta_file = Path(meta_path)
    with _sidecar_file_lock(meta_file):
        meta = sidecar.load(meta_file)
        resolved_master = (
            Path(master_path)
            if master_path is not None
            else master_path_for_sidecar(meta_file, meta)
        )
        actual = sha256_file(resolved_master)
        expected = ((meta.get("files") or {}).get("master") or {}).get("sha256")
        result = FixityResult(
            meta_path=meta_file,
            master_path=resolved_master,
            expected_sha256=expected,
            actual_sha256=actual,
        )

        if record:
            event = _fixity_event(
                result,
                verified_at=verified_at or utc_now(),
                status="verified" if result.matched else "mismatch",
            )
            _append_fixity_event(meta, event, actor=actor)
            _write_sidecar_atomic(meta_file, meta)

        return result


def record_fixity(
    meta_path: Path | str,
    *,
    master_path: Path | str | None = None,
    actor: str = "codex",
    verified_at: str | None = None,
) -> FixityResult:
    """Record the current master SHA-256 in the sidecar verification history."""
    meta_file = Path(meta_path)
    with _sidecar_file_lock(meta_file):
        meta = sidecar.load(meta_file)
        resolved_master = (
            Path(master_path)
            if master_path is not None
            else master_path_for_sidecar(meta_file, meta)
        )
        actual = sha256_file(resolved_master)
        master = _ensure_master_block(meta)
        expected = master.get("sha256")
        master["sha256"] = actual
        result = FixityResult(
            meta_path=meta_file,
            master_path=resolved_master,
            expected_sha256=expected,
            actual_sha256=actual,
        )
        event = _fixity_event(result, verified_at=verified_at or utc_now(), status="recorded")
        _append_fixity_event(meta, event, actor=actor)
        _write_sidecar_atomic(meta_file, meta)
        return result


def _iter_files(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*")):
        if path.is_file():
            yield path


def _copy_payload(source_dirs: Iterable[Path], data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    for source in source_dirs:
        if not source.is_dir():
            raise ValueError(f"payload source is not a directory: {source}")
        destination = data_dir / source.name
        if destination.exists():
            raise FileExistsError(f"bag payload destination already exists: {destination}")
        shutil.copytree(source, destination)


def _payload_oxum(data_root: Path) -> tuple[int, int]:
    files = list(_iter_files(data_root))
    return sum(path.stat().st_size for path in files), len(files)


def _safe_manifest_path(bag_root: Path, rel_path: str) -> Path | None:
    payload_file = bag_root / rel_path
    try:
        payload_file.resolve().relative_to(bag_root.resolve())
    except ValueError:
        return None
    return payload_file


def _read_manifest_entries(manifest: Path) -> list[tuple[str, str]]:
    entries: list[tuple[str, str]] = []
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        expected, rel_path = line.split(maxsplit=1)
        entries.append((expected, rel_path.strip()))
    return entries


def create_bag(
    source_dirs: Iterable[Path | str],
    bag_dir: Path | str,
    *,
    payload_name: str = "works",
) -> Path:
    """Create a dependency-free BagIt 0.97 package and return the bag directory."""
    bag_root = Path(bag_dir)
    if bag_root.exists() and any(bag_root.iterdir()):
        raise FileExistsError(f"bag directory must be empty: {bag_root}")
    bag_root.mkdir(parents=True, exist_ok=True)
    data_root = bag_root / "data" / payload_name
    _copy_payload((Path(source) for source in source_dirs), data_root)

    data_dir = bag_root / "data"
    manifest_lines = []
    for payload_file in _iter_files(data_dir):
        rel = payload_file.relative_to(bag_root).as_posix()
        manifest_lines.append(f"{sha256_file(payload_file)}  {rel}")
    oxum_bytes, oxum_files = _payload_oxum(data_dir)

    (bag_root / "bagit.txt").write_text(
        f"BagIt-Version: {BAGIT_VERSION}\nTag-File-Character-Encoding: UTF-8\n",
        encoding="utf-8",
    )
    (bag_root / "bag-info.txt").write_text(
        f"Bagging-Date: {datetime.now(UTC).date().isoformat()}\n"
        f"Payload-Oxum: {oxum_bytes}.{oxum_files}\n",
        encoding="utf-8",
    )
    (bag_root / "manifest-sha256.txt").write_text(
        "\n".join(manifest_lines) + ("\n" if manifest_lines else ""),
        encoding="utf-8",
    )
    return bag_root


def verify_bag(bag_dir: Path | str) -> BagVerificationResult:
    """Verify a BagIt manifest-sha256.txt file against the data payload."""
    bag_root = Path(bag_dir)
    manifest = bag_root / "manifest-sha256.txt"
    if not manifest.exists():
        raise FileNotFoundError(f"missing BagIt manifest: {manifest}")

    mismatches: list[str] = []
    missing: list[str] = []
    unexpected: list[str] = []
    checked = 0
    manifest_entries = _read_manifest_entries(manifest)
    manifest_paths = {rel_path for _, rel_path in manifest_entries}
    for expected, rel_path in manifest_entries:
        payload_file = _safe_manifest_path(bag_root, rel_path)
        if payload_file is None:
            mismatches.append(rel_path)
            continue
        if not payload_file.exists():
            missing.append(rel_path)
            continue
        checked += 1
        if sha256_file(payload_file) != expected:
            mismatches.append(rel_path)

    data_root = bag_root / "data"
    if data_root.exists():
        for payload_file in _iter_files(data_root):
            rel_path = payload_file.relative_to(bag_root).as_posix()
            if rel_path not in manifest_paths:
                unexpected.append(rel_path)

    return BagVerificationResult(
        bag_dir=bag_root,
        checked=checked,
        mismatches=tuple(mismatches),
        missing=tuple(missing),
        unexpected=tuple(unexpected),
    )


def write_json_result(path: Path | str, payload: dict[str, Any]) -> None:
    """Write a JSON verification result for automation-friendly callers."""
    Path(path).write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
