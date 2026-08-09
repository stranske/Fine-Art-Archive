"""A work Q-ID must never be erased because the query said nothing.

Audit finding 06 (2026-08-08). `_row_to_type` derives every flag from OPTIONAL
SPARQL clauses, so a QID we learned NOTHING about — deleted, redirected, or
lagging in WDQS — returns a row with no label and every flag False. That is
byte-identical to "positively not an artwork", and fell straight through to
`Repair(action="clear")`.

This is data destruction on a transient network condition, against the very
field the project is trying to raise coverage on, and it is not reversible:
`field_provenance.prior_value` is declared in the schema but not yet
implementable (finding 48), so the superseded Q-ID is recorded nowhere.

The capability is deliberately NOT disabled — a genuinely wrong Q-ID must still
be clearable. `test_clear_still_fires_on_positive_contradiction` is what proves
that, and would catch a "fix" that simply stopped clearing.
"""

from __future__ import annotations

from fine_art_archive.enrichment.misresolved_work_qid import (
    QidType,
    decide_repair,
)

META = {
    "work_id": "abc1234-a-work",
    "title": "The Little Street",
    "artist": {"name": "Johannes Vermeer"},
    "stable_identifiers": {"wikidata_q": "Q1234567"},
}


def _qtype(**kw) -> QidType:
    base = {"label": None, "is_artwork": False, "is_human": False, "is_artist": False}
    base.update(kw)
    return QidType(**base)


class TestNoFactsIsNotEvidence:
    def test_factless_row_is_unverifiable_not_cleared(self) -> None:
        """The regression: this returned action='clear' and erased the Q-ID."""
        repair = decide_repair(META, _qtype())
        assert repair is not None
        assert repair.action == "unverifiable"
        assert "did not answer" in repair.note or "no facts" in repair.note

    def test_unverifiable_carries_no_mutation_payload(self) -> None:
        """Nothing downstream can accidentally apply it as an unswap."""
        repair = decide_repair(META, _qtype())
        assert repair.artist_name is None
        assert repair.artist_qid is None
        assert repair.new_title is None


class TestPositiveEvidenceStillClears:
    def test_clear_still_fires_on_positive_contradiction(self) -> None:
        """A labelled non-artwork is real evidence — clearing must still work.

        Without this, 'never clear anything' would pass the guard tests above
        while silently removing the capability.
        """
        repair = decide_repair(META, _qtype(label="Amsterdam"))
        assert repair is not None
        assert repair.action == "clear"
        assert "Amsterdam" in repair.note

    def test_labelled_person_clears_as_person(self) -> None:
        repair = decide_repair(META, _qtype(label="Pierre-Auguste Renoir", is_human=True))
        assert repair.action == "clear"
        assert "person" in repair.note

    def test_a_real_artwork_is_never_touched(self) -> None:
        assert decide_repair(META, _qtype(label="The Little Street", is_artwork=True)) is None


class TestUnverifiableIsDistinctFromEveryOtherOutcome:
    def test_actions_are_disjoint(self) -> None:
        factless = decide_repair(META, _qtype()).action
        contradicted = decide_repair(META, _qtype(label="Amsterdam")).action
        assert factless != contradicted, (
            "an unanswered query and a positive contradiction must not share an "
            "action, or the driver cannot tell them apart"
        )
