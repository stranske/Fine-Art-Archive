"""Renditions of a work inherit its identity and may share its work Q-ID."""

from __future__ import annotations

from typing import Any

import pytest

from fine_art_archive.identity.variants import (
    Derivation,
    derivation_of,
    family_root,
    inherit,
    resolved_work_qid,
    violates_identity_invariant,
)
from fine_art_archive.identity.work_qid_uniqueness import WorkQidClaims


def work(work_id: str, **extra: Any) -> dict[str, Any]:
    return {"work_id": work_id, "schema_version": "1.0", **extra}


def detail_of(work_id: str, parent: str, **extra: Any) -> dict[str, Any]:
    return work(
        work_id,
        derived_from={"work_id": parent, "kind": "detail"},
        **extra,
    )


def loader(*metas: dict[str, Any]):
    index = {m["work_id"]: m for m in metas}
    return lambda wid: index.get(wid)


class TestDerivationOf:
    def test_reads_a_well_formed_link(self) -> None:
        meta = work(
            "aaaaaaa-crop",
            derived_from={
                "work_id": "bbbbbbb-master",
                "kind": "detail",
                "region": "with Hell",
            },
        )
        assert derivation_of(meta) == Derivation(
            parent_work_id="bbbbbbb-master",
            kind="detail",
            region="with Hell",
        )

    def test_independent_work_has_no_derivation(self) -> None:
        assert derivation_of(work("aaaaaaa-solo")) is None

    @pytest.mark.parametrize(
        "raw",
        [
            {"kind": "detail"},  # no parent
            {"work_id": "bbbbbbb-master"},  # no kind
            {"work_id": "bbbbbbb-master", "kind": "display-crop"},  # a crop is not a derived item
            {"work_id": "", "kind": "detail"},
            "bbbbbbb-master",  # not an object
        ],
    )
    def test_malformed_links_are_ignored_rather_than_raising(self, raw: Any) -> None:
        assert derivation_of(work("aaaaaaa-crop", derived_from=raw)) is None


class TestFamilyRoot:
    def test_follows_a_chain_to_the_work_itself(self) -> None:
        master = work("ccccccc-master")
        detail = detail_of("bbbbbbb-detail", "ccccccc-master")
        crop = detail_of("aaaaaaa-crop", "bbbbbbb-detail")
        load = loader(master, detail, crop)

        assert family_root("aaaaaaa-crop", load=load) == "ccccccc-master"

    def test_a_missing_parent_degrades_to_the_last_work_reached(self) -> None:
        crop = detail_of("aaaaaaa-crop", "zzzzzzz-gone")
        assert family_root("aaaaaaa-crop", load=loader(crop)) == "zzzzzzz-gone"

    def test_a_cycle_terminates(self) -> None:
        a = detail_of("aaaaaaa-one", "bbbbbbb-two")
        b = detail_of("bbbbbbb-two", "aaaaaaa-one")
        assert family_root("aaaaaaa-one", load=loader(a, b)) in {"aaaaaaa-one", "bbbbbbb-two"}


class TestResolvedWorkQid:
    def test_a_detail_resolves_its_parent_identity(self) -> None:
        master = work("bbbbbbb-master", stable_identifiers={"wikidata_q": "Q10346982"})
        detail = detail_of("aaaaaaa-detail", "bbbbbbb-master")

        assert resolved_work_qid("aaaaaaa-detail", load=loader(master, detail)) == "Q10346982"

    def test_resolution_walks_a_chain(self) -> None:
        master = work("ccccccc-master", stable_identifiers={"wikidata_q": "Q1"})
        mid = detail_of("bbbbbbb-mid", "ccccccc-master")
        leaf = detail_of("aaaaaaa-leaf", "bbbbbbb-mid")

        assert resolved_work_qid("aaaaaaa-leaf", load=loader(master, mid, leaf)) == "Q1"

    def test_none_when_the_parent_has_no_identity_yet(self) -> None:
        master = work("bbbbbbb-master")
        detail = detail_of("aaaaaaa-detail", "bbbbbbb-master")

        assert resolved_work_qid("aaaaaaa-detail", load=loader(master, detail)) is None


class TestIdentityInvariant:
    def test_a_derived_item_holding_a_q_id_is_a_violation(self) -> None:
        detail = detail_of(
            "aaaaaaa-detail", "bbbbbbb-master",
            stable_identifiers={"wikidata_q": "Q10346982"},
        )
        assert violates_identity_invariant(detail)

    def test_a_derived_item_with_a_null_q_id_is_fine(self) -> None:
        detail = detail_of(
            "aaaaaaa-detail", "bbbbbbb-master",
            stable_identifiers={"wikidata_q": None},
        )
        assert not violates_identity_invariant(detail)

    def test_an_independent_work_may_hold_a_q_id(self) -> None:
        solo = work("aaaaaaa-solo", stable_identifiers={"wikidata_q": "Q10346982"})
        assert not violates_identity_invariant(solo)


class TestInherit:
    def test_fills_only_what_the_rendition_lacks(self) -> None:
        parent = work(
            "bbbbbbb-master",
            title="Rocks at Port-Goulphar",
            year="1886",
            dimensions_original={"h_cm": 66.0, "w_cm": 81.8},
            stable_identifiers={"wikidata_q": "Q10346982"},
        )
        crop = detail_of("aaaaaaa-crop", "bbbbbbb-master", title="Rocks at Port-Goulphar")

        meta, filled, conflicts = inherit(crop, parent)

        assert conflicts == []
        assert meta["year"] == "1886"
        assert meta["dimensions_original"] == {"h_cm": 66.0, "w_cm": 81.8}
        assert "year" in filled and "title" not in filled
        # The identity itself must NOT travel: a derived item holds a null
        # wikidata_q and resolves the parent's on demand.
        assert "wikidata_q" not in meta["stable_identifiers"]
        assert "stable_identifiers.wikidata_q" not in filled

    def test_reports_a_disagreement_instead_of_overwriting_it(self) -> None:
        """Renditions drift from their parent on wording. Replacing the value
        silently would hide the drift; the caller decides which is right."""
        parent = work("bbbbbbb-master", medium="oil paint, canvas", year="1665")
        detail = detail_of("aaaaaaa-detail", "bbbbbbb-master", medium="oil on canvas")

        meta, filled, conflicts = inherit(detail, parent)

        assert conflicts == ["medium"]
        assert meta["medium"] == "oil on canvas"
        assert filled == ["year"]

    def test_per_file_facts_do_not_travel(self) -> None:
        parent = work(
            "bbbbbbb-master",
            files={"master": {"filename": "master.jpeg", "sha256": "a" * 64}},
            history=[{"op": "ingest"}],
            display_hints={"orientation_natural": "landscape"},
        )
        crop = detail_of("aaaaaaa-crop", "bbbbbbb-master")

        meta, filled, _ = inherit(crop, parent)

        assert "files" not in meta and "history" not in meta
        assert "display_hints" not in meta
        assert filled == []

    def test_neither_identity_nor_image_specific_identifiers_travel(self) -> None:
        parent = work(
            "bbbbbbb-master",
            stable_identifiers={
                "wikidata_q": "Q10346982",
                "museum_accession": "1436",
                "iiif_manifest_url": "https://example.org/master/manifest.json",
            },
        )
        detail = detail_of("aaaaaaa-detail", "bbbbbbb-master")

        meta, _, _ = inherit(detail, parent)

        # Describes the parent work -> safe to copy.
        assert meta["stable_identifiers"]["museum_accession"] == "1436"
        # The work's identity -> resolved, never stored.
        assert "wikidata_q" not in meta["stable_identifiers"]
        # Points at one particular image -> not the detail's.
        assert "iiif_manifest_url" not in meta["stable_identifiers"]


class TestUniquenessGuardHasNoRenditionExemption:
    """A derived item cannot reach the guard honestly, so exempting one would
    only let a resolver re-set the Q-ID the invariant repair keeps clearing."""

    def test_any_other_holder_is_a_collision(self) -> None:
        claims = WorkQidClaims({"Q10346982": "bbbbbbb-master"})
        assert claims.collides("Q10346982", "aaaaaaa-detail") == "bbbbbbb-master"

    def test_the_same_work_reclaiming_its_own_q_id_is_not(self) -> None:
        claims = WorkQidClaims({"Q10346982": "bbbbbbb-master"})
        assert claims.collides("Q10346982", "bbbbbbb-master") is None

    def test_an_unclaimed_q_id_is_free(self) -> None:
        claims = WorkQidClaims({"Q10346982": "bbbbbbb-master"})
        assert claims.collides("Q999999", "aaaaaaa-detail") is None
