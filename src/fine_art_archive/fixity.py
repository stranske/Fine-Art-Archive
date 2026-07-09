"""Fixity recording, verification, and minimal BagIt packaging helpers."""

from __future__ import annotations

import hashlib
import json
import shutil
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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

    @property
    def valid(self) -> bool:
        return not self.mismatches and not self.missing

    def as_dict(self) -> dict[str, Any]:
        return {
            "bag_dir": str(self.bag_dir),
            "checked": self.checked,
            "valid": self.valid,
            "mismatches": list(self.mismatches),
            "missing": list(self.missing),
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
    verification = meta.setdefault("verification", {})
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
    meta = sidecar.load(meta_file)
    resolved_master = (
        Path(master_path) if master_path is not None else master_path_for_sidecar(meta_file, meta)
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
        sidecar.write(meta_file, meta, validate_first=False)

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
    meta = sidecar.load(meta_file)
    resolved_master = (
        Path(master_path) if master_path is not None else master_path_for_sidecar(meta_file, meta)
    )
    actual = sha256_file(resolved_master)
    master = meta.setdefault("files", {}).setdefault("master", {})
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
    sidecar.write(meta_file, meta, validate_first=False)
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


def create_bag(
    source_dirs: Iterable[Path | str],
    bag_dir: Path | str,
    *,
    payload_name: str = "works",
) -> Path:
    """Create a minimal BagIt package and return the bag directory."""
    bag_root = Path(bag_dir)
    if bag_root.exists() and any(bag_root.iterdir()):
        raise FileExistsError(f"bag directory must be empty: {bag_root}")
    bag_root.mkdir(parents=True, exist_ok=True)
    data_root = bag_root / "data" / payload_name
    _copy_payload((Path(source) for source in source_dirs), data_root)

    manifest_lines = []
    for payload_file in _iter_files(bag_root / "data"):
        rel = payload_file.relative_to(bag_root).as_posix()
        manifest_lines.append(f"{sha256_file(payload_file)}  {rel}")

    (bag_root / "bagit.txt").write_text(
        f"BagIt-Version: {BAGIT_VERSION}\nTag-File-Character-Encoding: UTF-8\n",
        encoding="utf-8",
    )
    (bag_root / "bag-info.txt").write_text(
        f"Bagging-Date: {datetime.now(UTC).date().isoformat()}\nPayload-Oxum: 0.0\n",
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
    checked = 0
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        expected, rel_path = line.split(maxsplit=1)
        rel_path = rel_path.strip()
        payload_file = bag_root / rel_path
        if not payload_file.exists():
            missing.append(rel_path)
            continue
        checked += 1
        if sha256_file(payload_file) != expected:
            mismatches.append(rel_path)

    return BagVerificationResult(
        bag_dir=bag_root,
        checked=checked,
        mismatches=tuple(mismatches),
        missing=tuple(missing),
    )


def write_json_result(path: Path | str, payload: dict[str, Any]) -> None:
    """Write a JSON verification result for automation-friendly callers."""
    Path(path).write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
