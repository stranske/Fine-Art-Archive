"""Classify identity claims made across ``files.variants`` links.

The link says that a file is a display variant; it does not prove that both
sidecars describe the same Wikidata work.  This module is deliberately
read-only: only a duplicated Q-ID is a safe candidate for clearing.  Missing
or conflicting identities remain visible for curator-backed remediation.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any

__all__ = [
    "VariantIdentityFinding",
    "VariantIdentityVerdict",
    "classify_variant_identity",
    "classify_variant_links",
    "finding_as_dict",
    "work_qid_of",
]


class VariantIdentityVerdict(StrEnum):
    """The safe disposition for one directed owner-to-holding link."""

    TRUE_CROP = "TRUE_CROP"
    #: Two complementary crops of one work, neither of which is the other's
    #: master. Both correctly hold the Q-ID and neither may be cleared.
    COMPLEMENTARY_CROP = "COMPLEMENTARY_CROP"
    OWNER_NO_QID = "OWNER_NO_QID"
    QID_CONFLICT = "QID_CONFLICT"
    UNRESOLVED = "UNRESOLVED"


@dataclass(frozen=True)
class VariantIdentityFinding:
    """A non-mutating classification of one owner-to-holding relationship."""

    owner_work_id: str
    holding_work_id: str
    owner_qid: str | None
    holding_qid: str | None
    verdict: VariantIdentityVerdict
    recommended_action: str


def work_qid_of(meta: Mapping[str, Any]) -> str | None:
    """Return a non-empty work Q-ID, never coercing malformed metadata."""
    stable = meta.get("stable_identifiers")
    qid = stable.get("wikidata_q") if isinstance(stable, Mapping) else None
    return qid if isinstance(qid, str) and qid else None


def classify_variant_identity(
    owner: Mapping[str, Any],
    holding: Mapping[str, Any],
    *,
    complementary: bool = False,
) -> VariantIdentityFinding:
    """Classify a linked holding without choosing between conflicting Q-IDs.

    A matching Q-ID is the only safe automated cleanup: the holding's value is
    redundant.  A missing owner Q-ID must preserve the holding's sole identity.
    Different Q-IDs are *not* automatically called a false variant: that needs
    the accession- or collection-backed evidence retained by the audit process.

    ``complementary`` marks the pair as two crops that between them cover one
    work, with no master among them -- see
    :func:`~fine_art_archive.identity.crop_siblings.crop_sibling_groups`. The
    matching Q-ID is then correct on BOTH sides and neither is redundant, so
    the TRUE_CROP disposition below must not be reached. It is checked first
    because the shapes are otherwise identical: on 2026-09-01 every TRUE_CROP
    finding in the archive (4 of 4) was one direction of a complementary pair,
    and because such a pair links mutually, the advice was to clear the Q-ID
    from BOTH members -- leaving the work with no identity at all.
    """
    owner_id = str(owner.get("work_id") or "")
    holding_id = str(holding.get("work_id") or "")
    owner_qid = work_qid_of(owner)
    holding_qid = work_qid_of(holding)

    if complementary:
        verdict = VariantIdentityVerdict.COMPLEMENTARY_CROP
        action = (
            "preserve BOTH: complementary crops of one work, no master among "
            "them — each correctly carries the work Q-ID"
        )
    elif holding_qid is None:
        verdict = VariantIdentityVerdict.UNRESOLVED
        action = "preserve: holding has no work Q-ID to evaluate"
    elif owner_qid is None:
        verdict = VariantIdentityVerdict.OWNER_NO_QID
        action = "preserve: holding is the pair's only work identity"
    elif owner_qid == holding_qid:
        verdict = VariantIdentityVerdict.TRUE_CROP
        action = "eligible: clear the redundant holding work Q-ID after review"
    else:
        verdict = VariantIdentityVerdict.QID_CONFLICT
        action = "preserve: require accession-backed evidence before unlinking or clearing"

    return VariantIdentityFinding(
        owner_work_id=owner_id,
        holding_work_id=holding_id,
        owner_qid=owner_qid,
        holding_qid=holding_qid,
        verdict=verdict,
        recommended_action=action,
    )


def classify_variant_links(metas: Iterable[Mapping[str, Any]]) -> list[VariantIdentityFinding]:
    """Classify all resolvable ``files.variants`` links in a sidecar set.

    Missing and malformed links are ignored; an audit report must not invent a
    target or turn an incomplete link into a data-repair instruction.
    """
    by_work_id = {
        work_id: meta
        for meta in metas
        if isinstance((work_id := meta.get("work_id")), str) and work_id
    }
    # Imported here, not at module scope: crop_siblings reads `work_qid_of`
    # from this module, so a top-level import would be circular.
    from fine_art_archive.identity.crop_siblings import (  # noqa: PLC0415
        crop_sibling_work_ids,
    )

    complementary_ids = crop_sibling_work_ids(by_work_id.values())
    findings: list[VariantIdentityFinding] = []
    for owner_id, owner in by_work_id.items():
        files = owner.get("files")
        variants = files.get("variants") if isinstance(files, Mapping) else None
        for variant in variants or []:
            if not isinstance(variant, Mapping):
                continue
            rel_path = variant.get("rel_path")
            if not isinstance(rel_path, str):
                continue
            parts = rel_path.split("/")
            if len(parts) < 3 or parts[0] != "works" or not parts[1] or parts[1] == owner_id:
                continue
            holding = by_work_id.get(parts[1])
            if holding is not None:
                findings.append(
                    classify_variant_identity(
                        owner,
                        holding,
                        complementary=(
                            owner_id in complementary_ids and parts[1] in complementary_ids
                        ),
                    )
                )
    return sorted(findings, key=lambda item: (item.owner_work_id, item.holding_work_id))


def finding_as_dict(finding: VariantIdentityFinding) -> dict[str, str | None]:
    """Serialize a finding for the read-only audit script."""
    data = asdict(finding)
    data["verdict"] = finding.verdict.value
    return data
