"""Stage 3: title-variant match in the creator's oeuvre (search plan v5).

Every case here is a real pair from the archive's 466 retired works or from the
already-resolved works the strategy was measured against. The declines matter as
much as the matches: this stage exists because 358 of those 466 failed as
`by-creator:below-threshold`, and the repair is to normalize what the two
strings disagree about, NOT to lower the bar -- at 0.83 the field already
contains "Man in a Turban" -> "Young Man in a Turban" (a different Rembrandt,
eighteen years apart).
"""

from __future__ import annotations

from typing import Any

import pytest

from fine_art_archive.enrichment.work_qid_title_variants import (
    OeuvreWork,
    containment,
    creator_work_titles,
    is_derivation_candidate,
    resolve_by_title_variants,
    title_variants,
)

CREATOR = "Q5582"  # van Gogh, the archive's most common creator in this bucket


def work(qid: str, *labels: str, inception: str | None = None) -> OeuvreWork:
    return OeuvreWork(work_qid=qid, labels=labels, inception=inception)


def resolve(title: str, year: int | None, works: list[OeuvreWork]):
    return resolve_by_title_variants(title, year, CREATOR, client=None, works=works)


class TestMatchesTheV4PassCouldNotReach:
    def test_a_non_english_label_is_matched(self) -> None:
        """v4 filters labels to English, so a Dutch-only work scored against ''."""
        oeuvre = [
            work(
                "Q44843793",
                "Portret van jonkvrouwe Maria Francisca Louisa Dommer van Poldersveldt "
                "(Ubbergen 1848 - 1925 's-Hertogenbosch)",
                inception="1888",
            )
        ]
        best, why = resolve(
            "Portrait of Jonkvrouwe Maria Francisca Louisa Dommer van Poldersveldt", 1888, oeuvre
        )
        # The two agree on everything but "Portrait of" / "Portret van" and the
        # label's parenthesised life dates.
        assert why == "match" and best.work_qid == "Q44843793"

    def test_an_archive_copy_number_is_not_part_of_the_title(self) -> None:
        oeuvre = [work("Q19905196", "The Marriage of the Virgin", inception="1479")]
        best, why = resolve("The Marriage of the Virgin 2", 1479, oeuvre)
        assert why == "match" and best.work_qid == "Q19905196"

    def test_a_qualifier_prefix_is_contained(self) -> None:
        """ "Portrait with a Bottle of Wine" for "SELF-Portrait With a Bottle of Wine"."""
        oeuvre = [work("Q18890813", "Self-Portrait With a Bottle of Wine", inception="1906")]
        best, why = resolve("Portrait with a Bottle of Wine", 1906, oeuvre)
        assert why == "match"
        assert (best.work_qid, best.kind) == ("Q18890813", "containment")

    def test_a_label_disambiguator_is_dropped(self) -> None:
        """Wikidata parenthesises life dates; that is not part of the title."""
        oeuvre = [work("Q106865357", "Franklin Delano Roosevelt (1882-1945)", inception="1935")]
        best, why = resolve("Franklin Delano Roosevelt", 1935, oeuvre)
        assert why == "match" and best.work_qid == "Q106865357"


class TestPrecisionGuards:
    def test_a_different_work_by_one_creator_is_declined(self) -> None:
        """Man in a Turban (1632) is not Young Man in a Turban (1650).

        Two guards refuse it independently -- 2/3 containment is below the bar,
        and the years are eighteen apart -- so the reason recorded depends on
        which fires first. What must hold is that nothing is written.
        """
        oeuvre = [work("Q20264458", "Young Man in a Turban", inception="1650")]
        best, why = resolve("Man in a Turban", 1632, oeuvre)
        assert best is None
        assert why in ("no-candidate", "year-mismatch")

        # ... and with the years hidden, the containment bar alone still holds.
        oeuvre = [work("Q20264458", "Young Man in a Turban", inception=None)]
        assert resolve("Man in a Turban", None, oeuvre)[0] is None

    @pytest.mark.parametrize(
        ("title", "label"),
        [
            ("Garden at Arles", "Garden of the Hospital in Arles"),
            ("Flowering Plum Orchard (after Hiroshige)", "The Flowering Orchard"),
            ("The Artist's Son", "The Artist's Son, Paul"),
        ],
    )
    def test_one_dropped_content_word_in_three_is_a_different_painting(
        self, title: str, label: str
    ) -> None:
        """All three sit at 2/3 containment; all three are different works.

        The last one is why a single letter cannot be a content token: folding
        "The Artist's Son" leaves a bare "s", which counted as a word made the
        pair 3/4 and proposed Q20189742 for a sidecar already holding Q22337859.
        """
        oeuvre = [work("Q20189742", label, inception="1885")]
        best, why = resolve(title, 1885, oeuvre)
        assert best is None, f"{title!r} must not resolve to {label!r}"
        assert why in ("no-candidate", "derived-item-candidate")

    def test_one_content_word_is_not_an_identification(self) -> None:
        """Across every language a bare "Mars" finds a same-named work."""
        oeuvre = [work("Q1133875", "Mars", inception="1638")]
        best, why = resolve("Mars", 1640, oeuvre)
        assert best is None and why == "no-candidate"

    def test_a_same_title_cluster_is_ambiguous_not_guessed(self) -> None:
        oeuvre = [
            work("Q1", "Sunflowers Gone to Seed", inception="1887"),
            work("Q2", "Sunflowers gone to seed", inception="1887"),
        ]
        best, why = resolve("Four sunflowers gone to seed", 1887, oeuvre)
        assert best is None and why == "ambiguous"

    def test_containment_without_a_year_on_both_sides_is_declined(self) -> None:
        """The weaker match kind has no second signal left."""
        oeuvre = [work("Q18689514", "Portrait of John Quincy Adams", inception=None)]
        best, why = resolve("John Quincy Adams", 1844, oeuvre)
        assert best is None and why == "containment-needs-year"

    def test_containment_holds_the_year_to_a_tighter_tolerance(self) -> None:
        oeuvre = [work("Q18689514", "Portrait of John Quincy Adams", inception="1849")]
        assert resolve("John Quincy Adams", 1844, oeuvre)[1] == "year-mismatch"
        oeuvre = [work("Q18689514", "Portrait of John Quincy Adams", inception="1845")]
        assert resolve("John Quincy Adams", 1844, oeuvre)[1] == "match"

    def test_an_empty_oeuvre_is_reported_not_matched(self) -> None:
        assert resolve("Anything at all", 1900, [])[1] == "no-works"

    def test_no_creator_means_no_oeuvre_to_search(self) -> None:
        best, why = resolve_by_title_variants("A Title", 1900, None, client=None, works=[])
        assert best is None and why == "no-creator"


class TestSectionsAreNotWorks:
    """A title naming a SECTION must not resolve to the whole work: that is how
    one Q-ID came to sit on fifty separate Scrovegni sidecars."""

    @pytest.mark.parametrize(
        "title",
        [
            "The School of Athens (detail)",
            "The Isenheim Altarpiece (detail 2)",
            "Triptych (left panel)",
            "Rembrandt Laughing (framed)",
        ],
    )
    def test_a_derivation_marker_declines_before_any_search(self, title: str) -> None:
        assert is_derivation_candidate(title) is True
        oeuvre = [work("Q591762", title.split(" (")[0], inception="1510")]
        best, why = resolve(title, 1510, oeuvre)
        assert best is None and why == "derived-item-candidate"

    def test_dropping_a_parenthetical_from_the_sidecar_title_needs_review(self) -> None:
        """ "Isenheim Altarpiece (Crucifixion)" is a panel, not the altarpiece."""
        oeuvre = [work("Q591762", "Isenheim Altarpiece", inception="1512")]
        best, why = resolve("Isenheim Altarpiece (Crucifixion)", 1512, oeuvre)
        assert best is None and why == "title-parenthetical-needs-review"

    def test_a_parenthetical_is_never_scored_as_a_title_of_its_own(self) -> None:
        """It matched a print to the Q-ID of the SERIES it belongs to."""
        series = work("Q243248", "The Fifty-three Stations of the Tokaido", inception="1833")
        best, why = resolve(
            "Chiryu, Station 40 (The Fifty-Three Stations of the Tokaido)", 1833, [series]
        )
        assert best is None, "the series is not the print"
        assert why == "no-candidate"


class TestPieces:
    def test_title_variants_reports_how_each_form_was_reached(self) -> None:
        forms = {
            how: form for form, how in reversed(title_variants("The Marriage of the Virgin 2"))
        }
        assert forms["as-written"] == "marriage of the virgin 2"
        assert forms["copy-number"] == "marriage of the virgin"

    def test_containment_is_ordered_not_a_bag_of_words(self) -> None:
        assert containment("portrait bianca ponzoni", "portrait bianca ponzoni anguissola") > 0
        assert containment("ponzoni bianca portrait", "portrait bianca ponzoni anguissola") == 0.0

    def test_creator_work_titles_reads_all_languages(self) -> None:
        class FakeSparql:
            def query(self, sparql: str) -> dict[str, Any]:
                assert 'FILTER(LANG(?lbl) = "en")' not in sparql
                return {
                    "results": {
                        "bindings": [
                            {
                                "w": {"value": "http://www.wikidata.org/entity/Q1"},
                                "labels": {"value": "Zonnebloemen||Sunflowers"},
                                "alts": {"value": "Tournesols"},
                                "inception": {"value": "1888-01-01T00:00:00Z"},
                            }
                        ]
                    }
                }

        works = creator_work_titles(CREATOR, client=FakeSparql())
        assert works[0].labels == ("Zonnebloemen", "Sunflowers", "Tournesols")
        assert works[0].inception.startswith("1888")

    def test_a_dead_endpoint_yields_no_works_rather_than_raising(self) -> None:
        class Dead:
            def query(self, sparql: str) -> None:
                return None

        assert creator_work_titles(CREATOR, client=Dead()) == []
