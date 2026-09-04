"""A bigger file is not authority to overwrite a master.

`/variant_upgrades/{wid}/decision` told the operator to run
`scripts/promote_variant_upgrade.py`, which did not exist: a decision surface
with no executor behind it. Writing the executor the message described — swap
the master for the candidate — would have destroyed data, because on 2026-09-02
EVERY row the detector produced named a different painting:

* One 311 MB file was proposed as the upgrade for FOUR works. Its directory is
  named after the SERIES (`...thirty-six-views-of-mount-fuji-hokusai`) but its
  sidecar says *South Wind, Clear Sky* (Q3565037) — Red Fuji. Three of the four
  targets are *Under the Wave off Kanagawa*.
* The last surviving row proposed replacing Bruegel's Rotterdam *Tower of
  Babel* (Q15295671, Boijmans) with the Vienna one (Q15293656,
  Kunsthistorisches) because Vienna's file is 71x bigger. Bruegel painted it
  twice.

So these tests pin refusal, not application. The candidate list is untrusted
input, identity is checked on Wikidata Q-ID rather than on size, and anything
unverifiable is refused — "cannot determine identity" must never look like
"identity confirmed".
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))

from scripts import promote_variant_upgrade as pvu  # noqa: E402


def _meta(qid: str | None, title: str = "A Work") -> dict:
    meta: dict = {
        "work_id": "0000001-a-work",
        "schema_version": "1.0",
        "title": title,
        "artist": {"name": "An Artist"},
        "files": {"master": {"filename": "master.jpg"}},
        "history": [],
    }
    if qid:
        meta["stable_identifiers"] = {"wikidata_q": qid}
    return meta


@pytest.fixture
def archive(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A works tree and a staging root, with the script pointed at both."""
    works = tmp_path / "works"
    staging = tmp_path / "staging"
    works.mkdir()
    staging.mkdir()
    monkeypatch.setattr(pvu, "ART_WORKS_ROOT", works)
    monkeypatch.setattr(pvu, "VARIANT_CANDIDATE_ROOTS", (works, staging))

    def put_work(wid: str, qid: str | None, body: bytes = b"existing-master") -> Path:
        d = works / wid
        d.mkdir()
        (d / "master.jpg").write_bytes(body)
        (d / "meta.json").write_text(json.dumps(_meta(qid)), encoding="utf-8")
        return d

    def put_candidate(name: str, qid: str | None, body: bytes = b"candidate-bytes") -> Path:
        d = staging / name
        d.mkdir()
        path = d / "master.tif"
        path.write_bytes(body)
        if qid is not None:
            (d / "meta.json").write_text(json.dumps(_meta(qid)), encoding="utf-8")
        return path

    return works, staging, put_work, put_candidate


def _row(wid: str, candidate: Path) -> dict[str, str]:
    return {"existing_wid": wid, "candidate_path": str(candidate)}


def _claims(*rows: dict[str, str]):
    from collections import Counter

    return Counter(str(Path(r["candidate_path"]).resolve(strict=False)) for r in rows)


def test_same_work_is_ready(archive) -> None:
    _works, _staging, put_work, put_candidate = archive
    put_work("aaaaaaa-a-work", "Q123")
    cand = put_candidate("better", "Q123")
    row = _row("aaaaaaa-a-work", cand)
    verdict = pvu.evaluate(row, _claims(row))
    assert verdict["status"] == "READY", verdict["reason"]
    assert "Q123" in verdict["reason"]


def test_a_different_painting_is_refused(archive) -> None:
    """The Tower of Babel case: two Bruegels, two museums, one 71x bigger."""
    _works, _staging, put_work, put_candidate = archive
    put_work("aaaaaaa-tower-rotterdam", "Q15295671")
    cand = put_candidate("tower-vienna", "Q15293656", body=b"x" * 5000)
    row = _row("aaaaaaa-tower-rotterdam", cand)
    verdict = pvu.evaluate(row, _claims(row))
    assert verdict["status"] == "REFUSED"
    assert "Q15295671" in verdict["reason"] and "Q15293656" in verdict["reason"]


def test_one_candidate_for_several_works_is_refused(archive) -> None:
    """The Hokusai case: one file offered as the better copy of four paintings."""
    _works, _staging, put_work, put_candidate = archive
    for wid in ("aaaaaaa-great-wave", "bbbbbbb-great-wave", "ccccccc-red-fuji"):
        put_work(wid, "Q3565037")  # even with matching identity, ambiguity wins
    cand = put_candidate("series-file", "Q3565037")
    rows = [_row(w, cand) for w in ("aaaaaaa-great-wave", "bbbbbbb-great-wave", "ccccccc-red-fuji")]
    claims = _claims(*rows)
    for row in rows:
        verdict = pvu.evaluate(row, claims)
        assert verdict["status"] == "REFUSED"
        assert "3 different works" in verdict["reason"]


@pytest.mark.parametrize("target_q,candidate_q", [(None, "Q1"), ("Q1", None), (None, None)])
def test_unverifiable_identity_is_refused(archive, target_q, candidate_q) -> None:
    """Missing a Q-ID is a refusal, never a pass."""
    _works, _staging, put_work, put_candidate = archive
    put_work("aaaaaaa-a-work", target_q)
    cand = put_candidate("better", candidate_q)
    row = _row("aaaaaaa-a-work", cand)
    verdict = pvu.evaluate(row, _claims(row))
    assert verdict["status"] == "REFUSED"
    assert "cannot verify identity" in verdict["reason"]


def test_candidate_outside_the_permitted_roots_is_refused(archive, tmp_path: Path) -> None:
    """The CSV is untrusted input, and this check precedes a WRITE."""
    _works, _staging, put_work, _put_candidate = archive
    put_work("aaaaaaa-a-work", "Q123")
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    cand = outside / "master.tif"
    cand.write_bytes(b"x")
    (outside / "meta.json").write_text(json.dumps(_meta("Q123")), encoding="utf-8")
    row = _row("aaaaaaa-a-work", cand)
    verdict = pvu.evaluate(row, _claims(row))
    assert verdict["status"] == "REFUSED"
    assert "outside permitted roots" in verdict["reason"]


def test_applying_preserves_the_replaced_master(archive) -> None:
    """A swap must stay reversible: the old master is moved, never deleted."""
    works, _staging, put_work, put_candidate = archive
    work_dir = put_work("aaaaaaa-a-work", "Q123", body=b"the-original-master")
    cand = put_candidate("better", "Q123", body=b"the-better-copy")
    row = _row("aaaaaaa-a-work", cand)
    verdict = pvu.evaluate(row, _claims(row))
    assert verdict["status"] == "READY"

    result = pvu.apply_swap(verdict, grant="G-TEST")
    assert result["status"] == "APPLIED"

    superseded = list(work_dir.glob("superseded-*"))
    assert len(superseded) == 1, "the previous master must still be on disk"
    assert superseded[0].read_bytes() == b"the-original-master"
    assert (work_dir / "master.tif").read_bytes() == b"the-better-copy"

    meta = json.loads((work_dir / "meta.json").read_text())
    assert meta["files"]["master"]["filename"] == "master.tif"
    assert meta["files"]["master"]["size_bytes"] == len(b"the-better-copy")
    assert any(e.get("op") == "variant-upgrade" for e in meta["history"]), "swap must be recorded"


def test_latest_decision_wins(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An accept the operator later reversed is not an accept.

    The log is append-only, so reading it as "an accept appears anywhere" would
    resurrect a decision that had already been changed.
    """
    log = tmp_path / "decisions.jsonl"
    log.write_text(
        "\n".join(
            json.dumps(e)
            for e in (
                {"existing_wid": "aaaaaaa-kept", "decision": "accept"},
                {"existing_wid": "bbbbbbb-reversed", "decision": "accept"},
                {"existing_wid": "bbbbbbb-reversed", "decision": "reject"},
                {"existing_wid": "ccccccc-late", "decision": "reject"},
                {"existing_wid": "ccccccc-late", "decision": "accept"},
            )
        )
        + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(pvu, "VARIANT_UPGRADE_DECISIONS", log)
    assert pvu.accepted_work_ids() == {"aaaaaaa-kept", "ccccccc-late"}


def test_no_decisions_log_means_nothing_accepted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pvu, "VARIANT_UPGRADE_DECISIONS", tmp_path / "absent.jsonl")
    assert pvu.accepted_work_ids() == set()


def test_a_display_crop_master_is_refused_even_with_matching_identity(archive) -> None:
    """Identity confirms the WORK; it does not confirm the file is redundant.

    `e2ed232-las-meninas-velazquez` holds a 9:16 crop cut for a frame, and the
    candidate is the uncropped painting — same work, both wanted. Without the
    crop test this swap passes every identity check and destroys the crop.
    """
    works, _staging, put_work, put_candidate = archive
    work_dir = put_work("aaaaaaa-las-meninas", "Q297")
    meta = json.loads((work_dir / "meta.json").read_text())
    meta["files"]["master"]["dimensions_px"] = [16875, 30000]  # exactly 9:16
    (work_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")

    cand = put_candidate("uncropped", "Q297")
    cand_meta = json.loads((cand.parent / "meta.json").read_text())
    cand_meta["files"]["master"]["dimensions_px"] = [26065, 30000]
    (cand.parent / "meta.json").write_text(json.dumps(cand_meta), encoding="utf-8")

    verdict = pvu.evaluate(
        _row("aaaaaaa-las-meninas", cand), _claims(_row("aaaaaaa-las-meninas", cand))
    )
    assert verdict["status"] == "REFUSED"
    assert "PROTECTED" in verdict["reason"]
    assert verdict.get("overridable") is False


def test_a_genuine_enlargement_still_passes_the_crop_test(archive) -> None:
    """The gate must not refuse the case the feature exists for."""
    works, _staging, put_work, put_candidate = archive
    work_dir = put_work("aaaaaaa-a-work", "Q123")
    meta = json.loads((work_dir / "meta.json").read_text())
    meta["files"]["master"]["dimensions_px"] = [1000, 1200]
    (work_dir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")

    cand = put_candidate("better", "Q123")
    cand_meta = json.loads((cand.parent / "meta.json").read_text())
    cand_meta["files"]["master"]["dimensions_px"] = [4000, 4800]
    (cand.parent / "meta.json").write_text(json.dumps(cand_meta), encoding="utf-8")

    verdict = pvu.evaluate(_row("aaaaaaa-a-work", cand), _claims(_row("aaaaaaa-a-work", cand)))
    assert verdict["status"] == "READY", verdict["reason"]
    assert "crop test clear" in verdict["reason"]
