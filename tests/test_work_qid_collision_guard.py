"""A work Q-ID must never be written onto a second work.

An artist who painted a subject twice produces two sidecars whose titles match
the same Wikidata label at score 1.00 — Cezanne's *Card Players*, Kinstler's two
1991 Reagan portraits, two *Feast of Herod* at one gallery. The holder
tie-breaker added in #485 cannot separate those: the collisions observed in the
archive carry the SAME institution on both sides.

Observed 2026-08-09: seven Q-IDs sitting on two works each, every one written by
this pass at score >= 0.96. Two are provably distinct from metadata alone -- two
"Feast of Herod" at one gallery dated 1635 and 1425, and two Cezanne "Card
Player(s)" dated 1890-92 and 1892-95.

The guard deliberately does NOT depend on deciding which case applies. Whether
the second work is a different painting or another holding of the same one, a
work Q-ID denotes ONE work, so a second sidecar must not silently take it. The
refusal is reported so the pair can be judged; it is never resolved here by
image comparison, because no image statistic tested against this archive
separates "different work" from "another photograph of the same work".
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "backfill_work_qids_by_creator", ROOT / "scripts" / "backfill_work_qids_by_creator.py"
)
bwq = importlib.util.module_from_spec(spec)
sys.modules["backfill_work_qids_by_creator"] = bwq
spec.loader.exec_module(bwq)


def _sidecar(tmp_path: Path, work_id: str, title: str, **extra) -> Path:
    meta = {
        "work_id": work_id,
        "schema_version": "1.0",
        "artist": {"name": "Paul Cezanne", "wikidata_q": "Q35548"},
        "title": title,
        "files": {"master": {"filename": "master.jpg"}},
        "history": [],
        **extra,
    }
    d = tmp_path / work_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "meta.json").write_text(json.dumps(meta))
    return d / "meta.json"


class _Match:
    def __init__(self, qid: str, label: str, score: float = 1.0):
        self.work_qid, self.label, self.score = qid, label, score


def _run(tmp_path, monkeypatch, *, apply: bool):
    calls = []

    def fake_resolve(title, year, creator, *, client, **_discriminators):
        # **_discriminators, not an explicit kwarg list: resolve_work_qid grows
        # tie-breakers over time (holder_qid in #485, dimensions in #492) and a
        # stub pinned to today's signature turns each addition into a spurious
        # CI failure in an unrelated test.
        calls.append(title)
        return _Match("Q17277950", "The Card Players"), "match"

    monkeypatch.setattr(bwq, "resolve_work_qid", fake_resolve)
    return bwq.backfill(tmp_path, client=object(), limit=100,
                        apply=apply, include_categorized=True)


def test_refuses_a_qid_another_sidecar_already_holds(tmp_path, monkeypatch):
    _sidecar(tmp_path, "aaaaaaa-card-players", "The Card Players",
             stable_identifiers={"wikidata_q": "Q17277950"})
    _sidecar(tmp_path, "bbbbbbb-card-player", "The Card Player")

    stats, reasons = _run(tmp_path, monkeypatch, apply=True)

    assert stats.resolved == 0, "must not write a Q-ID that is already taken"
    assert reasons["already-held-by-another-work"] == 1
    assert reasons["match"] == 0
    assert stats.collisions[0]["work_qid"] == "Q17277950"
    assert stats.collisions[0]["held_by"] == ["aaaaaaa-card-players"]


def test_the_refusal_is_reported_not_silently_dropped(tmp_path, monkeypatch):
    """A dropped match must be visible — silence reads as 'nothing to do'."""
    _sidecar(tmp_path, "aaaaaaa-card-players", "The Card Players",
             stable_identifiers={"wikidata_q": "Q17277950"})
    _sidecar(tmp_path, "bbbbbbb-card-player", "The Card Player")

    stats, _ = _run(tmp_path, monkeypatch, apply=False)
    assert len(stats.collisions) == 1
    assert stats.collisions[0]["title"] == "The Card Player"


def test_two_eligible_works_cannot_both_take_the_same_qid(tmp_path, monkeypatch):
    """The second write in one run must see the first — not just pre-existing state.

    Both sidecars start QID-less, so a guard built only from the initial scan
    would let the run itself create the collision it exists to prevent.
    """
    _sidecar(tmp_path, "aaaaaaa-card-players", "The Card Players")
    _sidecar(tmp_path, "bbbbbbb-card-player", "The Card Player")

    monkeypatch.setattr(bwq.sidecar, "validate", lambda meta: None)
    stats, reasons = _run(tmp_path, monkeypatch, apply=True)

    assert stats.resolved == 1, "exactly one work may take the Q-ID"
    assert reasons["already-held-by-another-work"] == 1


def test_a_free_qid_is_still_written(tmp_path, monkeypatch):
    """The guard must not block the normal case."""
    _sidecar(tmp_path, "bbbbbbb-card-player", "The Card Player")
    monkeypatch.setattr(bwq.sidecar, "validate", lambda meta: None)

    stats, reasons = _run(tmp_path, monkeypatch, apply=True)

    assert stats.resolved == 1
    assert reasons["match"] == 1
    assert not stats.collisions


def test_rewriting_a_works_own_qid_is_not_a_collision(tmp_path, monkeypatch):
    """A work already holding the Q-ID is ineligible, never self-refused."""
    _sidecar(tmp_path, "aaaaaaa-card-players", "The Card Players",
             stable_identifiers={"wikidata_q": "Q17277950"})

    stats, reasons = _run(tmp_path, monkeypatch, apply=True)

    assert stats.attempted == 0, "a work with a Q-ID is not eligible"
    assert not stats.collisions
