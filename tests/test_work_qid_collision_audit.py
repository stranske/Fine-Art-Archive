"""Regression for Fine-Art-Archive#591 collision under-reporting."""

from __future__ import annotations

import json
from pathlib import Path

from fine_art_archive.identity.work_qid_collision_audit import (
    measure_work_qid_collisions,
    worst_offenders,
)


def _meta(
    work_id: str,
    qid: str,
    *,
    variants: list[dict[str, str]] | None = None,
) -> dict[str, object]:
    files: dict[str, object] = {
        "master": {
            "filename": "master.jpeg",
            "sha256": "a" * 64,
            "size_bytes": 1,
            "ingested_at": "2026-08-24T00:00:00Z",
        }
    }
    if variants is not None:
        files["variants"] = variants
    return {
        "work_id": work_id,
        "schema_version": "1.0",
        "artist": {"name": "Test Artist"},
        "title": work_id,
        "files": files,
        "history": [{"ts": "2026-08-24T00:00:00Z", "actor": "test", "op": "ingested"}],
        "stable_identifiers": {"wikidata_q": qid},
    }


def test_mutual_variant_pair_is_counted_as_a_collision() -> None:
    """Tintoretto-style mutual partial-crop links must not disappear from totals."""
    tintoretto_a = _meta(
        "0777183-loaves",
        "Q19904859",
        variants=[{"rel_path": "works/7c89c9a-loaves/master.jpeg", "role": "partial-crop"}],
    )
    tintoretto_b = _meta(
        "7c89c9a-loaves",
        "Q19904859",
        variants=[{"rel_path": "works/0777183-loaves/master.jpeg", "role": "partial-crop"}],
    )

    measures = measure_work_qid_collisions([tintoretto_a, tintoretto_b])

    assert measures.valid_work_qid == 2
    assert measures.distinct_work_qids == 1
    assert measures.qids_on_multiple == 1
    assert measures.extra_assignments == 1
    assert measures.mutual_links_ambiguous == 2
    assert worst_offenders([tintoretto_a, tintoretto_b]) == {
        "Q19904859": sorted(["0777183-loaves", "7c89c9a-loaves"])
    }


def test_unlinked_duplicate_pair_is_counted_as_a_collision() -> None:
    """Van Gogh-style duplicate ingests with no variant links still collide."""
    van_gogh_a = _meta("569ac23-asylum", "Q24020196")
    van_gogh_b = _meta("8716d0e-asylum", "Q24020196")

    measures = measure_work_qid_collisions([van_gogh_a, van_gogh_b])

    assert measures.valid_work_qid == 2
    assert measures.distinct_work_qids == 1
    assert measures.qids_on_multiple == 1
    assert measures.extra_assignments == 1
    assert measures.mutual_links_ambiguous == 0


def test_combined_fixture_matches_issue_arithmetic() -> None:
    """Two independent shared Q-IDs must produce qids_on_multiple=2, extra=2."""
    metas = [
        _meta(
            "0777183-loaves",
            "Q19904859",
            variants=[{"rel_path": "works/7c89c9a-loaves/master.jpeg", "role": "partial-crop"}],
        ),
        _meta(
            "7c89c9a-loaves",
            "Q19904859",
            variants=[{"rel_path": "works/0777183-loaves/master.jpeg", "role": "partial-crop"}],
        ),
        _meta("569ac23-asylum", "Q24020196"),
        _meta("8716d0e-asylum", "Q24020196"),
    ]

    measures = measure_work_qid_collisions(metas)

    assert measures.sidecars == 4
    assert measures.valid_work_qid == 4
    assert measures.distinct_work_qids == 2
    assert measures.qids_on_multiple == 2
    assert measures.extra_assignments == 2


def test_audit_script_emits_versioned_measures(tmp_path: Path) -> None:
    root = tmp_path / "works"
    root.mkdir()
    for work_id, qid in (("aaaaaaa-one", "Q900"), ("bbbbbbb-two", "Q900")):
        path = root / work_id / "meta.json"
        path.parent.mkdir()
        path.write_text(json.dumps(_meta(work_id, qid)), encoding="utf-8")

    import importlib.util
    import sys

    script = Path(__file__).resolve().parents[1] / "scripts" / "audit_work_qid_collisions.py"
    spec = importlib.util.spec_from_file_location("audit_work_qid_collisions", script)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    payload = module.report(root)
    assert payload["measures"]["qids_on_multiple"] == 1
    assert payload["measures"]["extra_assignments"] == 1
    assert payload["worst_offenders"] == {"Q900": ["aaaaaaa-one", "bbbbbbb-two"]}
