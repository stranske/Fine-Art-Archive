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
