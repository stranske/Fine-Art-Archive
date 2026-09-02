"""Contract tests for the conservative variant-identity classifier."""

from __future__ import annotations

from fine_art_archive.identity.variant_identity import (
    VariantIdentityVerdict,
    classify_variant_identity,
    classify_variant_links,
)


def _meta(work_id: str, qid: str | None, variants: list[dict[str, str]] | None = None) -> dict:
    stable = {"wikidata_q": qid} if qid else {}
    files: dict[str, object] = {"master": {"filename": "master.jpeg"}}
    if variants is not None:
        files["variants"] = variants
    return {"work_id": work_id, "stable_identifiers": stable, "files": files}


def test_true_crop_is_the_only_identity_case_eligible_for_cleanup() -> None:
    finding = classify_variant_identity(_meta("owner", "Q1"), _meta("holding", "Q1"))

    assert finding.verdict is VariantIdentityVerdict.TRUE_CROP
    assert finding.recommended_action.startswith("eligible:")


def test_owner_without_qid_preserves_the_holding_identity() -> None:
    finding = classify_variant_identity(_meta("owner", None), _meta("holding", "Q2"))

    assert finding.verdict is VariantIdentityVerdict.OWNER_NO_QID
    assert finding.recommended_action.startswith("preserve:")


def test_conflicting_qids_are_not_automatically_called_false_variants() -> None:
    finding = classify_variant_identity(_meta("owner", "Q1"), _meta("holding", "Q2"))

    assert finding.verdict is VariantIdentityVerdict.QID_CONFLICT
    assert "accession-backed evidence" in finding.recommended_action


def test_link_scan_ignores_missing_and_self_referential_targets() -> None:
    findings = classify_variant_links(
        [
            _meta(
                "owner",
                "Q1",
                [
                    {"rel_path": "works/holding/master.jpeg"},
                    {"rel_path": "works/owner/master.jpeg"},
                    {"rel_path": "works/missing/master.jpeg"},
                ],
            ),
            _meta("holding", "Q1"),
        ]
    )

    assert [(item.owner_work_id, item.holding_work_id, item.verdict) for item in findings] == [
        ("owner", "holding", VariantIdentityVerdict.TRUE_CROP)
    ]


def test_complementary_crops_are_never_eligible_for_clearing() -> None:
    """Both sides hold the Q-ID correctly; clearing either leaves a work unidentified.

    Measured on the live archive 2026-09-01: all four TRUE_CROP findings were
    the two directions of two complementary pairs, so acting on the advice
    would have stripped the Q-ID from every member of both.
    """
    from fine_art_archive.identity.variant_identity import (
        VariantIdentityVerdict,
        classify_variant_links,
    )

    def meta(work_id: str, target: str, position: str) -> dict:
        return {
            "work_id": work_id,
            "stable_identifiers": {"wikidata_q": "Q19904859"},
            "files": {
                "variants": [
                    {
                        "rel_path": f"works/{target}/master.jpeg",
                        "role": "partial-crop",
                        "crop_position": position,
                    }
                ]
            },
        }

    findings = classify_variant_links(
        [meta("0777183-loaves", "7c89c9a-loaves", "right"),
         meta("7c89c9a-loaves", "0777183-loaves", "left")]
    )
    assert len(findings) == 2
    assert {f.verdict for f in findings} == {VariantIdentityVerdict.COMPLEMENTARY_CROP}
    assert not any("clear" in f.recommended_action for f in findings)


def test_a_master_and_its_single_crop_is_still_clearable() -> None:
    """The narrowing must not disarm the genuine master-plus-crop cleanup."""
    from fine_art_archive.identity.variant_identity import (
        VariantIdentityVerdict,
        classify_variant_links,
    )

    owner = {
        "work_id": "aaa-master",
        "stable_identifiers": {"wikidata_q": "Q1"},
        "files": {
            "variants": [
                {"rel_path": "works/bbb-crop/master.jpeg", "role": "landscape-crop"}
            ]
        },
    }
    holding = {"work_id": "bbb-crop", "stable_identifiers": {"wikidata_q": "Q1"}}

    findings = classify_variant_links([owner, holding])
    assert [f.verdict for f in findings] == [VariantIdentityVerdict.TRUE_CROP]
