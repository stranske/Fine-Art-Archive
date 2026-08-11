"""Renditions of a work inherit its identity and may share its work Q-ID."""

from __future__ import annotations

from typing import Any

import pytest

from fine_art_archive.identity.variants import (
    Derivation,
    derivation_of,
    family_root,
    inherit,
    same_object,
)
from fine_art_archive.identity.work_qid_uniqueness import WorkQidClaims


def work(work_id: str, **extra: Any) -> dict[str, Any]:
    return {"work_id": work_id, "schema_version": "1.0", **extra}


def crop_of(work_id: str, parent: str, **extra: Any) -> dict[str, Any]:
    return work(
        work_id,
        derived_from={"work_id": parent, "kind": "display-crop"},
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
                "kind": "display-crop",
                "image_correlation": 0.96,
            },
        )
        assert derivation_of(meta) == Derivation(
            parent_work_id="bbbbbbb-master",
            kind="display-crop",
            image_correlation=0.96,
        )

    def test_independent_work_has_no_derivation(self) -> None:
        assert derivation_of(work("aaaaaaa-solo")) is None

    @pytest.mark.parametrize(
        "raw",
        [
            {"kind": "display-crop"},  # no parent
            {"work_id": "bbbbbbb-master"},  # no kind
            {"work_id": "bbbbbbb-master", "kind": "screenshot"},  # kind not modelled
            {"work_id": "", "kind": "detail"},
            "bbbbbbb-master",  # not an object
        ],
    )
    def test_malformed_links_are_ignored_rather_than_raising(self, raw: Any) -> None:
        assert derivation_of(work("aaaaaaa-crop", derived_from=raw)) is None


class TestFamilyRoot:
    def test_follows_a_chain_to_the_work_itself(self) -> None:
        master = work("ccccccc-master")
        detail = crop_of("bbbbbbb-detail", "ccccccc-master")
        crop = crop_of("aaaaaaa-crop", "bbbbbbb-detail")
        load = loader(master, detail, crop)

        assert family_root("aaaaaaa-crop", load=load) == "ccccccc-master"

    def test_a_missing_parent_degrades_to_the_last_work_reached(self) -> None:
        crop = crop_of("aaaaaaa-crop", "zzzzzzz-gone")
        assert family_root("aaaaaaa-crop", load=loader(crop)) == "zzzzzzz-gone"

    def test_a_cycle_terminates(self) -> None:
        a = crop_of("aaaaaaa-one", "bbbbbbb-two")
        b = crop_of("bbbbbbb-two", "aaaaaaa-one")
        assert family_root("aaaaaaa-one", load=loader(a, b)) in {"aaaaaaa-one", "bbbbbbb-two"}


class TestSameObject:
    def test_crop_and_its_master_are_one_object(self) -> None:
        master = work("bbbbbbb-master")
        crop = crop_of("aaaaaaa-crop", "bbbbbbb-master")
        load = loader(master, crop)

        assert same_object("aaaaaaa-crop", "bbbbbbb-master", load=load)

    def test_two_crops_of_one_master_are_one_object(self) -> None:
        master = work("ccccccc-master")
        wide = crop_of("aaaaaaa-wide", "ccccccc-master")
        tall = crop_of("bbbbbbb-tall", "ccccccc-master")
        load = loader(master, wide, tall)

        assert same_object("aaaaaaa-wide", "bbbbbbb-tall", load=load)

    def test_unrelated_works_are_not(self) -> None:
        load = loader(work("aaaaaaa-one"), work("bbbbbbb-two"))
        assert not same_object("aaaaaaa-one", "bbbbbbb-two", load=load)


class TestInherit:
    def test_fills_only_what_the_rendition_lacks(self) -> None:
        parent = work(
            "bbbbbbb-master",
            title="Rocks at Port-Goulphar",
            year="1886",
            dimensions_original={"h_cm": 66.0, "w_cm": 81.8},
            stable_identifiers={"wikidata_q": "Q10346982"},
        )
        crop = crop_of("aaaaaaa-crop", "bbbbbbb-master", title="Rocks at Port-Goulphar")

        meta, filled, conflicts = inherit(crop, parent)

        assert conflicts == []
        assert meta["year"] == "1886"
        assert meta["dimensions_original"] == {"h_cm": 66.0, "w_cm": 81.8}
        assert meta["stable_identifiers"]["wikidata_q"] == "Q10346982"
        assert "year" in filled and "title" not in filled

    def test_reports_a_disagreement_instead_of_overwriting_it(self) -> None:
        """Four renditions here hold a different Q-ID from their parent; one of
        the two is wrong, and silently replacing it would hide that."""
        parent = work("bbbbbbb-master", stable_identifiers={"wikidata_q": "Q764831"})
        crop = crop_of("aaaaaaa-crop", "bbbbbbb-master",
                       stable_identifiers={"wikidata_q": "Q97377049"})

        meta, filled, conflicts = inherit(crop, parent)

        assert conflicts == ["stable_identifiers.wikidata_q"]
        assert meta["stable_identifiers"]["wikidata_q"] == "Q97377049"
        assert filled == []

    def test_per_file_facts_do_not_travel(self) -> None:
        parent = work(
            "bbbbbbb-master",
            files={"master": {"filename": "master.jpeg", "sha256": "a" * 64}},
            history=[{"op": "ingest"}],
            display_hints={"orientation_natural": "landscape"},
        )
        crop = crop_of("aaaaaaa-crop", "bbbbbbb-master")

        meta, filled, _ = inherit(crop, parent)

        assert "files" not in meta and "history" not in meta
        assert "display_hints" not in meta
        assert filled == []

    def test_image_specific_identifiers_do_not_travel(self) -> None:
        parent = work(
            "bbbbbbb-master",
            stable_identifiers={
                "wikidata_q": "Q10346982",
                "iiif_manifest_url": "https://example.org/master/manifest.json",
            },
        )
        crop = crop_of("aaaaaaa-crop", "bbbbbbb-master")

        meta, _, _ = inherit(crop, parent)

        assert meta["stable_identifiers"]["wikidata_q"] == "Q10346982"
        assert "iiif_manifest_url" not in meta["stable_identifiers"]


class TestUniquenessGuardWithRenditions:
    def test_a_crop_may_share_its_master_q_id(self) -> None:
        master = work("bbbbbbb-master", stable_identifiers={"wikidata_q": "Q10346982"})
        crop = crop_of("aaaaaaa-crop", "bbbbbbb-master")
        load = loader(master, crop)
        claims = WorkQidClaims(
            {"Q10346982": "bbbbbbb-master"},
            same_object=lambda a, b: same_object(a, b, load=load),
        )

        assert claims.collides("Q10346982", "aaaaaaa-crop") is None

    def test_unrelated_works_still_collide(self) -> None:
        load = loader(work("aaaaaaa-one"), work("bbbbbbb-two"))
        claims = WorkQidClaims(
            {"Q10346982": "bbbbbbb-two"},
            same_object=lambda a, b: same_object(a, b, load=load),
        )

        assert claims.collides("Q10346982", "aaaaaaa-one") == "bbbbbbb-two"

    def test_without_the_predicate_behaviour_is_unchanged(self) -> None:
        claims = WorkQidClaims({"Q10346982": "bbbbbbb-master"})
        assert claims.collides("Q10346982", "aaaaaaa-crop") == "bbbbbbb-master"
