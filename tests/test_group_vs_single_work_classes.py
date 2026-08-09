"""A group Q-ID must never be usable as a single work's identity.

Audit finding 05 / owner decision D2 / near-term item N-M1.

132 work Q-IDs were shared across multiple sidecars, the worst on 50. A >=0.99
visual scan found only ~13 genuinely-duplicate pairs among them, so the rest are
**series members** — Wikidata frequently carries one item for a print suite or
fresco cycle and none for the individual impressions.

Where a series identity BELONGS is `stable_identifiers.part_of_q`, which the
workspace already writes on 162 sidecars and which PR #486 forward-ports into
this repo's schema. This change deliberately does NOT add a second slot for the
same fact.

What #486 does not cover is the class level: `Q15727816` "painting series" sat
in `ALLOWED_P31` with no marker distinguishing it from a single work, so a group
Q-ID could clear every check and be written to `stable_identifiers.wikidata_q`
as if it named one work. Splitting the allowlist closes that at the type level,
independently of which field the data lands in.
"""

from __future__ import annotations

from fine_art_archive.known_works.artwork_classes import (
    ALLOWED_P31,
    GROUP_P31,
    SINGLE_WORK_P31,
    is_group_class,
    is_single_work_class,
)


class TestGroupVersusSingleWorkClasses:
    def test_painting_series_is_an_artwork_class(self) -> None:
        """It genuinely is one — known-works queries should still find it."""
        assert "Q15727816" in ALLOWED_P31

    def test_painting_series_is_not_a_single_work_class(self) -> None:
        """…and that is the distinction whose absence caused the defect."""
        assert is_group_class("Q15727816") is True
        assert is_single_work_class("Q15727816") is False
        assert "Q15727816" not in SINGLE_WORK_P31

    def test_a_painting_is_a_single_work_class(self) -> None:
        assert is_single_work_class("Q3305213") is True

    def test_single_work_set_is_exactly_allowed_minus_group(self) -> None:
        assert SINGLE_WORK_P31 == ALLOWED_P31 - GROUP_P31

    def test_no_group_class_can_serve_as_a_work_identity(self) -> None:
        for qid in GROUP_P31:
            assert is_single_work_class(qid) is False, (
                f"{qid} is a group class and must never be written to stable_identifiers.wikidata_q"
            )
