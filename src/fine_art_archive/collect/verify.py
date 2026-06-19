"""Identity verification gate for acquired masters.

Layer 1 (aspect-ratio) catches misdirection when the wrong painting has
a different shape from the catalogued one. Caught the QkOGy/Milkmaid
substitution for SK-A-2860/Little Street.

Layer 2 (perceptual hash vs. Wikidata P18 reference) catches misdirection
even when aspect ratios coincidentally match. Calibration against the
Vermeer case showed: 2-bit pHash distance for same-work-different-scan vs.
28+ bits for different works. The threshold default of 12 bits puts
a comfortable gap on both sides.

Higher layers (CLIP embedding cosine, VLM cross-check, cross-source
consensus) are documented in `acquisition_quality_design.md`. The
`verify()` function below accepts flags for each so call sites stay
stable when the higher layers land.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

VerifyStatus = Literal["PASS", "FAIL", "SKIP", "UNVERIFIED"]


@dataclass
class CheckResult:
    name: str
    status: VerifyStatus
    detail: dict = field(default_factory=dict)
    message: str = ""


@dataclass
class VerificationReport:
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def overall(self) -> VerifyStatus:
        statuses = {c.status for c in self.checks}
        if "FAIL" in statuses:
            return "FAIL"
        if not statuses or statuses == {"SKIP"}:
            return "UNVERIFIED"
        if "PASS" in statuses:
            return "PASS"
        return "UNVERIFIED"

    def to_dict(self) -> dict:
        return {
            "status": self.overall,
            "checks": [
                {
                    "name": c.name,
                    "status": c.status,
                    "detail": c.detail,
                    "message": c.message,
                }
                for c in self.checks
            ],
        }

    def to_source_quality_inputs(self) -> dict[str, bool | None]:
        def match_value(name: str) -> bool | None:
            status = next((c.status for c in self.checks if c.name == name), None)
            if status == "PASS":
                return True
            if status == "FAIL":
                return False
            return None

        return {
            "phash_match": match_value("perceptual_hash"),
            "aspect_match": match_value("aspect_ratio"),
            "dim_match": None,
        }


def check_aspect_ratio(
    *,
    h_cm: float | None,
    w_cm: float | None,
    h_px: int,
    w_px: int,
    threshold: float = 0.05,
) -> CheckResult:
    """Verify the candidate's pixel aspect ratio matches the catalogued
    physical aspect ratio within `threshold`.

    Returns SKIP when the catalogued dimensions are unknown. Returns FAIL
    when both are known and differ by more than the threshold.
    """
    if h_cm is None or w_cm is None or not (h_cm > 0 and w_cm > 0):
        return CheckResult(
            name="aspect_ratio",
            status="SKIP",
            message="catalogued cm dimensions unavailable",
        )
    if h_px <= 0 or w_px <= 0:
        return CheckResult(
            name="aspect_ratio",
            status="FAIL",
            message="pixel dimensions invalid",
            detail={"h_px": h_px, "w_px": w_px},
        )

    cm_aspect = h_cm / w_cm
    px_aspect = h_px / w_px
    delta = abs(cm_aspect - px_aspect)
    rel_delta = delta / max(cm_aspect, px_aspect)

    detail = {
        "cm_aspect": round(cm_aspect, 4),
        "px_aspect": round(px_aspect, 4),
        "delta": round(delta, 4),
        "rel_delta": round(rel_delta, 4),
        "threshold": threshold,
    }
    if rel_delta <= threshold:
        return CheckResult(name="aspect_ratio", status="PASS", detail=detail)
    return CheckResult(
        name="aspect_ratio",
        status="FAIL",
        detail=detail,
        message=(
            f"aspect mismatch: cm {cm_aspect:.3f} vs px {px_aspect:.3f} "
            f"(rel_delta {rel_delta:.3f} > {threshold})"
        ),
    )


def check_perceptual_hash(
    *,
    candidate_path: Path,
    reference_path: Path,
    phash_threshold: int = 12,
    dhash_threshold: int = 12,
) -> CheckResult:
    """Compare candidate and reference images via perceptual hashes.

    Layer 2 of the verification stack. Both pHash and dHash are computed;
    PASS requires at least one to be under threshold. Empirical calibration
    (Vermeer Little Street vs. Wikidata P18 Commons display, 5190x6344 vs.
    1280x1585): pHash distance 2, dHash distance 0. Negative case (Milkmaid
    bytes vs. Little Street reference): pHash 28, dHash 30. A threshold of
    12 sits in the comfortable middle.

    Raises ImportError if `imagehash` isn't installed.
    """
    import imagehash  # imported lazily so the rest of the module loads even

    # if the dep is absent
    from PIL import Image

    cand_img = Image.open(candidate_path)
    ref_img = Image.open(reference_path)
    p_dist = imagehash.phash(cand_img) - imagehash.phash(ref_img)
    d_dist = imagehash.dhash(cand_img) - imagehash.dhash(ref_img)

    detail = {
        "phash_distance": int(p_dist),
        "phash_threshold": phash_threshold,
        "dhash_distance": int(d_dist),
        "dhash_threshold": dhash_threshold,
        "candidate_size": list(cand_img.size),
        "reference_size": list(ref_img.size),
    }
    # PASS if either hash is comfortably under threshold; that handles
    # rare cases where one variant degrades on a heavily-cropped reference.
    p_pass = p_dist <= phash_threshold
    d_pass = d_dist <= dhash_threshold
    if p_pass or d_pass:
        return CheckResult(
            name="perceptual_hash",
            status="PASS",
            detail=detail,
            message=f"pHash dist {p_dist} / dHash dist {d_dist}",
        )
    return CheckResult(
        name="perceptual_hash",
        status="FAIL",
        detail=detail,
        message=(
            f"both hashes over threshold: pHash {p_dist}>{phash_threshold}, "
            f"dHash {d_dist}>{dhash_threshold}"
        ),
    )


def verify(
    *,
    h_cm: float | None,
    w_cm: float | None,
    h_px: int,
    w_px: int,
    # Layer 2 hook: when a reference image path is supplied, run pHash check.
    candidate_path: Path | None = None,
    reference_path: Path | None = None,
    phash_threshold: int = 12,
    dhash_threshold: int = 12,
    # Layer 3+ hooks (Phase 5c+); not implemented yet.
    enable_clip: bool = False,
    enable_vlm: bool = False,
) -> VerificationReport:
    """Run all enabled verification layers against an acquired master.

    Layers 1 (aspect ratio) and 2 (perceptual hash vs. reference) are
    wired. Layer 2 only runs when both `candidate_path` and `reference_path`
    are supplied. Higher layers are skip-stubs.
    """
    report = VerificationReport()
    report.checks.append(check_aspect_ratio(h_cm=h_cm, w_cm=w_cm, h_px=h_px, w_px=w_px))

    if candidate_path is not None and reference_path is not None:
        report.checks.append(
            check_perceptual_hash(
                candidate_path=Path(candidate_path),
                reference_path=Path(reference_path),
                phash_threshold=phash_threshold,
                dhash_threshold=dhash_threshold,
            )
        )

    if enable_clip:
        report.checks.append(
            CheckResult(
                name="clip_similarity",
                status="SKIP",
                message="Layer 3 not implemented yet; see acquisition_quality_design.md",
            )
        )
    if enable_vlm:
        report.checks.append(
            CheckResult(
                name="vlm_inconsistency_check",
                status="SKIP",
                message="Layer 4 not implemented yet; see acquisition_quality_design.md",
            )
        )

    return report
