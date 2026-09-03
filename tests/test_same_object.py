"""One work Q-ID on two documented objects is correct, not a collision.

A work Q-ID names a WORK; a sidecar describes an OBJECT. For anything held in
multiples those differ, and the archive collects the multiples on purpose --
Hokusai's *South Wind, Clear Sky* as both Cleveland 1930.189 and Indianapolis
60.12, David's *Sacre* as both the Louvre original and the Versailles replica.
"""

from __future__ import annotations

from fine_art_archive.identity.same_object import (
    distinct_object_groups,
    object_key,
)

PRINT = "Q3565037"


def _meta(work_id: str, qid: str | None, holder: str | None, accession: str | None) -> dict:
    return {
        "work_id": work_id,
        "stable_identifiers": ({"wikidata_q": qid} if qid else {})
        | ({"museum_accession": accession} if accession else {}),
        "holder": ({"name": holder} if holder else {}),
    }


class TestTheObjectKey:
    def test_both_halves_are_required(self) -> None:
        """A holder alone cannot separate two impressions in one museum."""
        assert object_key(_meta("a", PRINT, "Cleveland Museum of Art", None)) is None
        assert object_key(_meta("a", PRINT, None, "1930.189")) is None
        assert object_key(_meta("a", PRINT, "Cleveland Museum of Art", "1930.189")) == (
            "Cleveland Museum of Art",
            "1930.189",
        )

    def test_blank_strings_are_not_provenance(self) -> None:
        assert object_key(_meta("a", PRINT, "   ", "1930.189")) is None
        assert object_key(_meta("a", PRINT, "Cleveland", "  ")) is None


class TestWhatIsExcused:
    def test_two_documented_impressions_are_not_a_collision(self) -> None:
        """The real Hokusai pair."""
        metas = [
            _meta("342776b-fuji", PRINT, "Cleveland Museum of Art", "1930.189"),
            _meta("2150e65-fuji", PRINT, "Indianapolis Museum of Art", "60.12"),
        ]
        groups = distinct_object_groups(metas)
        assert len(groups) == 1
        assert groups[0].work_qid == PRINT
        assert groups[0].work_ids == ("2150e65-fuji", "342776b-fuji")

    def test_two_impressions_in_one_museum_are_still_distinct(self) -> None:
        """Same holder, different accession — two sheets, both wanted."""
        metas = [
            _meta("aaa", PRINT, "Cleveland Museum of Art", "1930.189"),
            _meta("bbb", PRINT, "Cleveland Museum of Art", "1930.190"),
        ]
        assert len(distinct_object_groups(metas)) == 1


class TestWhatMustNotBeExcused:
    """Missing provenance must never read as 'a different object'."""

    def test_a_member_without_a_holder_keeps_the_group_actionable(self) -> None:
        metas = [
            _meta("aaa", PRINT, "Cleveland Museum of Art", "1930.189"),
            _meta("bbb", PRINT, None, None),
        ]
        assert distinct_object_groups(metas) == []

    def test_a_member_without_an_accession_keeps_the_group_actionable(self) -> None:
        metas = [
            _meta("aaa", PRINT, "Cleveland Museum of Art", "1930.189"),
            _meta("bbb", PRINT, "Indianapolis Museum of Art", None),
        ]
        assert distinct_object_groups(metas) == []

    def test_two_members_claiming_the_same_object_are_a_real_duplicate(self) -> None:
        """Identical holder AND accession is one object recorded twice."""
        metas = [
            _meta("aaa", PRINT, "Cleveland Museum of Art", "1930.189"),
            _meta("bbb", PRINT, "Cleveland Museum of Art", "1930.189"),
        ]
        assert distinct_object_groups(metas) == []

    def test_a_lone_sidecar_forms_no_group(self) -> None:
        assert (
            distinct_object_groups([_meta("aaa", PRINT, "Cleveland Museum of Art", "1930.189")])
            == []
        )

    def test_sidecars_without_a_qid_form_no_group(self) -> None:
        metas = [
            _meta("aaa", None, "Cleveland Museum of Art", "1930.189"),
            _meta("bbb", None, "Indianapolis Museum of Art", "60.12"),
        ]
        assert distinct_object_groups(metas) == []


class TestTheMeasures:
    def test_the_total_still_counts_it_and_actionable_does_not(self) -> None:
        """#591's regression stays caught; the drainable count reaches zero."""
        from fine_art_archive.identity.work_qid_collision_audit import (
            actionable_offenders,
            measure_work_qid_collisions,
        )

        metas = [
            _meta("342776b-fuji", PRINT, "Cleveland Museum of Art", "1930.189"),
            _meta("2150e65-fuji", PRINT, "Indianapolis Museum of Art", "60.12"),
        ]
        m = measure_work_qid_collisions(metas)
        assert m.qids_on_multiple == 1
        assert m.distinct_object_qids == 1
        assert m.actionable_qids == 0
        assert actionable_offenders(metas) == {}

    def test_an_undocumented_pair_stays_actionable(self) -> None:
        from fine_art_archive.identity.work_qid_collision_audit import (
            measure_work_qid_collisions,
        )

        metas = [_meta("aaa", PRINT, None, None), _meta("bbb", PRINT, None, None)]
        m = measure_work_qid_collisions(metas)
        assert m.distinct_object_qids == 0
        assert m.actionable_qids == 1
