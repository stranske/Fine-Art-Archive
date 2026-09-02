"""CLI and report-contract coverage for the work Q-ID collision audit."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path


def _load_audit_module():
    script = Path(__file__).resolve().parents[1] / "scripts" / "audit_work_qid_collisions.py"
    spec = importlib.util.spec_from_file_location("audit_work_qid_collisions", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _write_meta(root: Path) -> Path:
    path = root / "aaaaaaa-one" / "meta.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps({"work_id": "aaaaaaa-one", "stable_identifiers": {"wikidata_q": "Q900"}}),
        encoding="utf-8",
    )
    return path


def test_audit_report_has_fixed_schema_version(tmp_path: Path) -> None:
    """Bumped to 2 when `crop_sibling_qids`/`actionable_qids` joined the measures.

    Consumers pin this, so it moves only with a deliberate contract change.
    """
    root = tmp_path / "works"
    _write_meta(root)

    payload = _load_audit_module().report(root)

    assert payload["report_schema_version"] == 2


def test_audit_script_cli_emits_versioned_json(tmp_path: Path, monkeypatch, capsys) -> None:
    root = tmp_path / "works"
    _write_meta(root)
    module = _load_audit_module()
    monkeypatch.setattr(sys, "argv", ["audit_work_qid_collisions.py", str(root)])

    assert module.main() == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["report_schema_version"] == 2
    assert payload["measures"]["valid_work_qid"] == 1
    # A review surface must be able to read the drainable count and the list it
    # goes with, in the same payload as the blocking total.
    assert payload["measures"]["actionable_qids"] == 0
    assert payload["actionable_offenders"] == {}


def test_audit_fails_for_unreadable_sidecar(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "works"
    path = _write_meta(root)
    module = _load_audit_module()

    def unreadable(_path: Path, *, encoding: str) -> str:
        raise OSError("permission denied")

    monkeypatch.setattr(Path, "read_text", unreadable)

    try:
        module.load_sidecars(root)
    except RuntimeError as exc:
        assert str(path) in str(exc)
    else:
        raise AssertionError("unreadable sidecar must fail the audit")
