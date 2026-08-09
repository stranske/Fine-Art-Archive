"""An artist Q-ID may only be written when it demonstrably denotes that artist.

Near-term item N-M3 — the *preventive* half of decision D1.

The G25 repair fixed the artist-Q-ID corpus. It did not fix what produced it:
`_field_from_entity` returned `_first(_qid_claims(entity, "P170"))` for the
`artist_qid` field, accepting whatever a work item's creator claim pointed at
with no check at all. So the corpus could be re-corrupted by the very next
resolver pass, and the repair was a one-time cleanup rather than a fix.

Two things the audit measured, both reproduced here as tests:

  * **109 sidecars held something that is not an artist at all** — a year, a
    place, a title fragment. The `Q5` (human) condition is what stops that.
  * Same-title works by different hands resolved to one another's creators.
    The name-match condition is what stops that.

The refusal direction is deliberate and is itself asserted: a missing artist
Q-ID leaves the field open for a better pass, while a wrong one propagates into
holder resolution, IIIF and dossiers, and nothing downstream re-checks it.
"""

from __future__ import annotations

from typing import Any

from fine_art_archive.enrichment.source_resolver import WikidataProvider


def _work(creator_qid: str | None) -> dict[str, Any]:
    """A Wikidata work entity whose P170 points at `creator_qid`."""
    if creator_qid is None:
        return {"claims": {}}
    return {
        "claims": {
            "P170": [
                {
                    "mainsnak": {
                        "snaktype": "value",
                        "datavalue": {"value": {"id": creator_qid}, "type": "wikibase-entityid"},
                    }
                }
            ]
        }
    }


def _person(label: str, *, human: bool = True, aliases: list[str] | None = None) -> dict[str, Any]:
    claims: dict[str, Any] = {}
    if human:
        claims["P31"] = [
            {
                "mainsnak": {
                    "snaktype": "value",
                    "datavalue": {"value": {"id": "Q5"}, "type": "wikibase-entityid"},
                }
            }
        ]
    entity: dict[str, Any] = {"labels": {"en": {"value": label}}, "claims": claims}
    if aliases:
        entity["aliases"] = {"en": [{"value": a} for a in aliases]}
    return entity


def _provider(target: dict[str, Any] | None, qid: str = "Q42") -> WikidataProvider:
    p = WikidataProvider(client=object())  # type: ignore[arg-type]
    p._entities = lambda qids: {qid: target} if target is not None else {}  # type: ignore[method-assign]
    return p


def _sidecar(artist_name: str | None) -> dict[str, Any]:
    return {"artist": {"name": artist_name}} if artist_name is not None else {"artist": {}}


class TestItWritesOnlyWhatItCanVerify:
    def test_a_matching_artist_is_written(self) -> None:
        p = _provider(_person("Rembrandt van Rijn"))
        got = p._field_from_entity(_work("Q42"), "artist_qid", _sidecar("Rembrandt van Rijn"))
        assert got == "Q42"

    def test_an_alias_match_is_enough(self) -> None:
        p = _provider(_person("Rembrandt Harmenszoon van Rijn", aliases=["Rembrandt"]))
        got = p._field_from_entity(_work("Q42"), "artist_qid", _sidecar("Rembrandt"))
        assert got == "Q42"

    def test_a_different_person_is_refused(self) -> None:
        """The same-title collision: P170 names someone else entirely."""
        p = _provider(_person("Peter Paul Rubens"))
        got = p._field_from_entity(_work("Q42"), "artist_qid", _sidecar("Rembrandt van Rijn"))
        assert got is None


class TestItRefusesThingsThatAreNotPeople:
    """The 109-sidecar failure: a year, a place, a title fragment."""

    def test_a_place_is_refused(self) -> None:
        p = _provider(_person("Delft", human=False))
        got = p._field_from_entity(_work("Q42"), "artist_qid", _sidecar("Delft"))
        assert got is None, "a place matched by NAME must still fail the human check"

    def test_a_workshop_or_school_is_refused(self) -> None:
        p = _provider(_person("Workshop of Rembrandt", human=False))
        got = p._field_from_entity(_work("Q42"), "artist_qid", _sidecar("Workshop of Rembrandt"))
        assert got is None


class TestUnverifiableIsNeverWritten:
    def test_no_artist_name_on_the_sidecar_means_refuse(self) -> None:
        """Nothing to check against is not the same as checking and passing."""
        p = _provider(_person("Rembrandt van Rijn"))
        assert p._field_from_entity(_work("Q42"), "artist_qid", _sidecar(None)) is None

    def test_no_sidecar_at_all_means_refuse(self) -> None:
        p = _provider(_person("Rembrandt van Rijn"))
        assert p._field_from_entity(_work("Q42"), "artist_qid", None) is None

    def test_an_unresolvable_target_means_refuse(self) -> None:
        p = _provider(None)
        assert p._field_from_entity(_work("Q42"), "artist_qid", _sidecar("Rembrandt")) is None

    def test_a_work_with_no_creator_claim_yields_nothing(self) -> None:
        p = _provider(_person("Rembrandt van Rijn"))
        assert p._field_from_entity(_work(None), "artist_qid", _sidecar("Rembrandt")) is None


class TestTheThresholdIsSharedNotDuplicated:
    def test_it_reuses_the_one_documented_threshold(self) -> None:
        """Two thresholds would let "close enough" mean two different things."""
        assert WikidataProvider.ARTIST_NAME_MATCH_MIN == 0.88

    def test_a_near_miss_below_the_threshold_is_refused(self) -> None:
        p = _provider(_person("Rembrandt van Rijn"))
        got = p._field_from_entity(_work("Q42"), "artist_qid", _sidecar("Rubens"))
        assert got is None


class TestOtherFieldsAreUnaffected:
    def test_year_still_resolves_without_a_sidecar(self) -> None:
        """The guard is scoped to artist_qid; nothing else changes behaviour."""
        p = _provider(None)
        entity = {
            "claims": {
                "P571": [
                    {
                        "mainsnak": {
                            "snaktype": "value",
                            "datavalue": {
                                "value": {"time": "+1642-00-00T00:00:00Z"},
                                "type": "time",
                            },
                        }
                    }
                ]
            }
        }
        assert p._field_from_entity(entity, "year", None) == "1642"
