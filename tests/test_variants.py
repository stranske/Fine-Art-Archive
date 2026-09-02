"""A rendition of a work inherits its identity rather than asserting one."""

from __future__ import annotations

from typing import Any

import pytest

from fine_art_archive.identity.variants import (
    Derivation,
    VariantHolding,
    VariantLinks,
    derivation_of,
    family_root,
    inherit,
    resolved_work_qid,
    variant_links,
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
            "aaaaaaa-detail",
            "bbbbbbb-master",
            stable_identifiers={"wikidata_q": "Q10346982"},
        )
        assert violates_identity_invariant(detail)

    def test_a_derived_item_with_a_null_q_id_is_fine(self) -> None:
        detail = detail_of(
            "aaaaaaa-detail",
            "bbbbbbb-master",
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


def owner_of(work_id: str, *held: tuple[str, str], **extra: Any) -> dict[str, Any]:
    """A sidecar declaring ``held`` (work_id, role) pairs to be its variants."""
    return work(
        work_id,
        files={
            "variants": [
                {"rel_path": f"works/{wid}/master.jpg", "role": role} for wid, role in held
            ]
        },
        **extra,
    )


class TestVariantLinks:
    """A sidecar named in another's files.variants[] is a HOLDING of a work, not
    a work, so no resolver may write it a work Q-ID of its own."""

    def test_a_held_crop_may_not_hold_a_work_q_id(self) -> None:
        links = variant_links(
            [
                owner_of("bbbbbbb-master", ("aaaaaaa-crop", "landscape-crop")),
                work("aaaaaaa-crop"),
            ]
        )

        assert links.holdings["aaaaaaa-crop"] == VariantHolding(
            work_id="aaaaaaa-crop",
            owner_work_id="bbbbbbb-master",
            role="landscape-crop",
        )
        assert links.may_hold_work_qid("aaaaaaa-crop") is False
        assert links.exclusion_reason("aaaaaaa-crop") == "variant-holding"

    def test_the_owner_keeps_the_identity_and_stays_resolvable(self) -> None:
        links = variant_links(
            [owner_of("bbbbbbb-master", ("aaaaaaa-crop", "meural-framed")), work("aaaaaaa-crop")]
        )

        assert links.may_hold_work_qid("bbbbbbb-master") is True
        assert links.exclusion_reason("bbbbbbb-master") is None

    def test_a_work_nobody_claims_is_untouched(self) -> None:
        links = variant_links([work("ccccccc-solo")])

        assert links.holdings == {}
        assert links.may_hold_work_qid("ccccccc-solo") is True

    def test_a_mutual_pair_is_ambiguous_and_neither_side_is_resolved(self) -> None:
        # The 2026-08-09 pass wrote entries in the opposite direction, so pairs
        # claim each other. Whoever wrote the entry does not settle which file
        # is the crop; picking a side would strip the Q-ID from the real work.
        links = variant_links(
            [
                owner_of("aaaaaaa-crop", ("bbbbbbb-master", "landscape-crop")),
                owner_of("bbbbbbb-master", ("aaaaaaa-crop", "landscape-crop")),
            ]
        )

        assert links.holdings == {}
        assert links.ambiguous == frozenset({"aaaaaaa-crop", "bbbbbbb-master"})
        assert links.exclusion_reason("aaaaaaa-crop") == "variant-link-ambiguous"
        assert links.exclusion_reason("bbbbbbb-master") == "variant-link-ambiguous"

    def test_a_sidecar_listing_itself_is_a_broken_link_not_a_holding(self) -> None:
        links = variant_links([owner_of("aaaaaaa-solo", ("aaaaaaa-solo", "duplicate-copy"))])

        assert links.holdings == {}
        assert links.self_referential == frozenset({"aaaaaaa-solo"})
        # Nothing can inherit from itself, so the work stays eligible.
        assert links.may_hold_work_qid("aaaaaaa-solo") is True

    @pytest.mark.parametrize(
        "rel_path",
        ["master.jpg", "renders/eink/aaaaaaa-crop.png", "works/", "works/aaaaaaa-crop"],
    )
    def test_a_rel_path_that_names_no_sidecar_is_not_a_holding(self, rel_path: str) -> None:
        # rel_path is relative to <archive_root>/Art/; only works/<work_id>/<file>
        # names another sidecar. A file living beside the master is not a holding.
        links = variant_links(
            [
                work(
                    "bbbbbbb-master",
                    files={"variants": [{"rel_path": rel_path, "role": "unknown"}]},
                )
            ]
        )

        assert links.holdings == {}
        assert links.ambiguous == frozenset()

    def test_malformed_variant_entries_do_not_break_the_scan(self) -> None:
        links = variant_links(
            [
                work("bbbbbbb-master", files={"variants": ["not-a-dict", {}, None]}),
                work("ccccccc-other", files=None),
                work("ddddddd-third"),
                {"schema_version": "1.0"},  # no work_id at all
            ]
        )

        assert links.holdings == {}

    def test_from_sidecars_skips_an_unreadable_sidecar(self) -> None:
        def load(path: str) -> dict[str, Any]:
            if path == "broken":
                raise ValueError("not JSON")
            return owner_of("bbbbbbb-master", ("aaaaaaa-crop", "portrait-crop"))

        links = VariantLinks.from_sidecars(["broken", "ok"], load=load)

        # One parse failure must not disable the guard for everything else.
        assert links.exclusion_reason("aaaaaaa-crop") == "variant-holding"


class TestSelfReferenceIsNotBarred:
    """Pin the behaviour, because the docstring once claimed the opposite.

    Until 2026-08-21 `VariantLinks`'s class docstring said self-referential ids
    were "still barred ... by may_hold_work_qid". `exclusion_reason` has never
    consulted `self_referential`, so a future reader could reasonably have
    "fixed" the code to match the prose. These tests exist to stop that.

    Barring a self-reference protects nothing: the rule keeps a holding out of a
    queue because identity belongs on the OTHER side of the relationship, and a
    self-reference has no other side. It would also be harmful — a sidecar kept
    out of every resolver queue cannot be identified at all.
    """

    @staticmethod
    def _selfref(work_id: str = "aaaaaaa-solo") -> dict:
        return {
            "work_id": work_id,
            "files": {
                "variants": [{"rel_path": f"works/{work_id}/master.jpeg", "role": "landscape-crop"}]
            },
        }

    def test_it_is_recorded_as_self_referential(self) -> None:
        links = variant_links([self._selfref()])
        assert links.self_referential == frozenset({"aaaaaaa-solo"})

    def test_it_is_not_excluded_from_a_work_qid_queue(self) -> None:
        """NOT excluded: this is the assertion the old docstring contradicted."""
        links = variant_links([self._selfref()])
        assert links.exclusion_reason("aaaaaaa-solo") is None
        assert links.may_hold_work_qid("aaaaaaa-solo") is True

    def test_it_is_not_counted_as_a_holding(self) -> None:
        """A self-reference names no owner, so there is nothing to inherit from."""
        links = variant_links([self._selfref()])
        assert "aaaaaaa-solo" not in links.holdings

    def test_a_mutual_pair_is_still_excluded(self) -> None:
        """The contrast that makes the distinction real, not an oversight.

        A mutual pair IS barred, and must stay barred.
        """
        a = {
            "work_id": "aaaaaaa-one",
            "files": {"variants": [{"rel_path": "works/bbbbbbb-two/master.jpeg"}]},
        }
        b = {
            "work_id": "bbbbbbb-two",
            "files": {"variants": [{"rel_path": "works/aaaaaaa-one/master.jpeg"}]},
        }
        links = variant_links([a, b])
        assert links.exclusion_reason("aaaaaaa-one") == "variant-link-ambiguous"
        assert links.may_hold_work_qid("bbbbbbb-two") is False

    def test_the_docstring_no_longer_claims_both_are_barred(self) -> None:
        """The claim this class of bug lived in."""
        doc = VariantLinks.__doc__ or ""
        assert "Both are still barred" not in doc
        assert "``ambiguous`` IS barred by" in doc
        assert "``self_referential`` is NOT barred." in doc


class TestAmbiguityIsAPropertyOfThePair:
    """A mutual pair does not make its members unownable by a third sidecar.

    The real shape, 2026-09-02: two complementary crops list each other (mutual,
    genuinely unsettled between the two of them) and a newly acquired full-frame
    master lists each of them one-way. Before this, one mutual edge discarded
    every other owner, so `holdings` never learned the master owned them — and
    clearing the redundant work Q-ID off a crop would have left it resolvable by
    nothing at all.
    """

    def _meta(self, work_id: str, variants: list[dict]) -> dict:
        return {
            "work_id": work_id,
            "files": {"variants": variants},
        }

    def _crop_of(self, target: str) -> dict:
        return {"rel_path": f"works/{target}/master.jpeg", "role": "partial-crop"}

    def _metas(self) -> list[dict]:
        return [
            self._meta("ccccccc-master", [self._crop_of("aaaaaaa-left"),
                                          self._crop_of("bbbbbbb-right")]),
            self._meta("aaaaaaa-left", [self._crop_of("bbbbbbb-right")]),
            self._meta("bbbbbbb-right", [self._crop_of("aaaaaaa-left")]),
        ]

    def test_the_one_way_owner_wins_over_the_mutual_sibling(self) -> None:
        links = variant_links(self._metas())
        assert links.holdings["aaaaaaa-left"].owner_work_id == "ccccccc-master"
        assert links.holdings["bbbbbbb-right"].owner_work_id == "ccccccc-master"
        assert links.ambiguous == frozenset()

    def test_a_resolved_holding_is_still_barred_from_a_work_qid(self) -> None:
        """Resolving the owner must not make a crop eligible to hold identity."""
        links = variant_links(self._metas())
        for crop in ("aaaaaaa-left", "bbbbbbb-right"):
            assert not links.may_hold_work_qid(crop)
            assert links.exclusion_reason(crop) == "variant-holding"

    def test_a_bare_mutual_pair_is_still_ambiguous(self) -> None:
        """With no third claimant there is still nothing to settle the pair."""
        links = variant_links([
            self._meta("aaaaaaa-left", [self._crop_of("bbbbbbb-right")]),
            self._meta("bbbbbbb-right", [self._crop_of("aaaaaaa-left")]),
        ])
        assert links.ambiguous == frozenset({"aaaaaaa-left", "bbbbbbb-right"})
        assert links.holdings == {}
