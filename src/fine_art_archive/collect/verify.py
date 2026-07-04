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

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

VerifyStatus = Literal["PASS", "FAIL", "SKIP", "UNVERIFIED"]


@dataclass
class CheckResult:
    name: str
    status: VerifyStatus
    detail: dict = field(default_factory=dict)
    message: str = ""
    blocks_overall: bool = True


@dataclass
class VerificationReport:
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def overall(self) -> VerifyStatus:
        blocking_statuses = {c.status for c in self.checks if c.blocks_overall}
        statuses = {c.status for c in self.checks}
        if "FAIL" in blocking_statuses:
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
                    "blocks_overall": c.blocks_overall,
                }
                for c in self.checks
            ],
        }

    def to_source_quality_inputs(self) -> dict[str, bool | None]:
        def match_value(name: str) -> bool | None:
            check = next((c for c in self.checks if c.name == name), None)
            if check is None:
                return None
            if check.status == "PASS":
                return True
            if check.status == "FAIL":
                return False
            return None

        return {
            "verify_match": {"PASS": True, "FAIL": False}.get(self.overall),
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
    blocks_overall: bool = True,
) -> CheckResult:
    """Compare candidate and reference images via perceptual hashes.

    Layer 2 of the verification stack. Both pHash and dHash are computed;
    PASS requires at least one to be under threshold. Empirical calibration
    (Vermeer Little Street vs. Wikidata P18 Commons display, 5190x6344 vs.
    1280x1585): pHash distance 2, dHash distance 0. Negative case (Milkmaid
    bytes vs. Little Street reference): pHash 28, dHash 30. A threshold of
    12 sits in the comfortable middle.

    Uses `imagehash` when installed, with a small PIL/numpy fallback so local
    test runs without optional extras still exercise the layer.
    """
    with (
        _open_exif_transposed_image(candidate_path) as cand_img,
        _open_exif_transposed_image(reference_path) as ref_img,
    ):
        candidate_size = list(cand_img.size)
        reference_size = list(ref_img.size)
        try:
            import imagehash  # imported lazily so the rest of the module loads even

            # if the dep is absent
            p_dist = imagehash.phash(cand_img) - imagehash.phash(ref_img)
            d_dist = imagehash.dhash(cand_img) - imagehash.dhash(ref_img)
            hash_backend = "imagehash"
        except ImportError:
            p_dist = _average_hash_distance(cand_img, ref_img)
            d_dist = _difference_hash_distance(cand_img, ref_img)
            hash_backend = "fallback"

    detail = {
        "phash_distance": int(p_dist),
        "phash_threshold": phash_threshold,
        "dhash_distance": int(d_dist),
        "dhash_threshold": dhash_threshold,
        "candidate_size": candidate_size,
        "reference_size": reference_size,
        "hash_backend": hash_backend,
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
            blocks_overall=blocks_overall,
        )
    return CheckResult(
        name="perceptual_hash",
        status="FAIL",
        detail=detail,
        message=(
            f"both hashes over threshold: pHash {p_dist}>{phash_threshold}, "
            f"dHash {d_dist}>{dhash_threshold}"
        ),
        blocks_overall=blocks_overall,
    )


def _open_exif_transposed_image(path: Path) -> Any:
    from PIL import Image, ImageOps

    with Image.open(path) as image:
        return ImageOps.exif_transpose(image)


def _average_hash_distance(left: Any, right: Any, hash_size: int = 8) -> int:
    import numpy as np

    def bits(image: Any) -> np.ndarray:
        arr = np.asarray(image.convert("L").resize((hash_size, hash_size)), dtype=np.float32)
        return arr > arr.mean()

    return int(np.count_nonzero(bits(left) != bits(right)))


def _difference_hash_distance(left: Any, right: Any, hash_size: int = 8) -> int:
    import numpy as np

    def bits(image: Any) -> np.ndarray:
        arr = np.asarray(image.convert("L").resize((hash_size + 1, hash_size)), dtype=np.float32)
        return arr[:, 1:] > arr[:, :-1]

    return int(np.count_nonzero(bits(left) != bits(right)))


EmbeddingBackend = Callable[[Any], Sequence[float]]


@lru_cache(maxsize=1)
def _load_open_clip_backend() -> EmbeddingBackend:
    """Load an optional OpenCLIP backend lazily.

    The project does not require the model dependency for normal CI. When it is
    absent, callers turn the ImportError into a SKIP result instead of crashing.
    """
    import open_clip  # type: ignore[import-not-found]
    import torch  # type: ignore[import-not-found]

    model, _, preprocess = open_clip.create_model_and_transforms(
        "ViT-B-32", pretrained="laion2b_s34b_b79k"
    )
    model.eval()

    def embed(image: Any) -> Sequence[float]:
        with torch.no_grad():
            tensor = preprocess(image).unsqueeze(0)
            vector = model.encode_image(tensor)
            vector = vector / vector.norm(dim=-1, keepdim=True)
        return vector.squeeze(0).detach().cpu().tolist()

    return embed


def _cosine_similarity(left: Sequence[float], right: Sequence[float]) -> float:
    import math

    if len(left) != len(right) or not left:
        raise ValueError("embedding vectors must be non-empty and the same length")
    dot = sum(float(a) * float(b) for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(float(a) * float(a) for a in left))
    right_norm = math.sqrt(sum(float(b) * float(b) for b in right))
    if left_norm == 0 or right_norm == 0:
        raise ValueError("embedding vectors must be non-zero")
    return dot / (left_norm * right_norm)


def check_embedding_similarity(
    *,
    candidate_path: Path,
    reference_path: Path,
    threshold: float = 0.88,
    embedding_backend: EmbeddingBackend | None = None,
) -> CheckResult:
    """Compare candidate/reference identity using an optional image embedding.

    The default backend is OpenCLIP when installed. Tests and offline callers can
    inject a small deterministic backend to avoid network/model downloads.
    """
    if embedding_backend is None:
        try:
            embedding_backend = _load_open_clip_backend()
        except ImportError as exc:
            dependency = exc.name or str(exc) or exc.__class__.__name__
            return CheckResult(
                name="clip_similarity",
                status="SKIP",
                message=f"embedding backend unavailable: {dependency}",
            )
        except (OSError, RuntimeError) as exc:
            return CheckResult(
                name="clip_similarity",
                status="SKIP",
                message=f"embedding backend failed to load: {exc}",
            )

    with (
        _open_exif_transposed_image(candidate_path) as cand_img,
        _open_exif_transposed_image(reference_path) as ref_img,
    ):
        cand_vec = embedding_backend(cand_img.convert("RGB"))
        ref_vec = embedding_backend(ref_img.convert("RGB"))

    try:
        similarity = _cosine_similarity(cand_vec, ref_vec)
    except ValueError as exc:
        return CheckResult(
            name="clip_similarity",
            status="FAIL",
            detail={"threshold": threshold},
            message=str(exc),
        )

    detail = {"cosine_similarity": round(similarity, 4), "threshold": threshold}
    if similarity >= threshold:
        return CheckResult(
            name="clip_similarity",
            status="PASS",
            detail=detail,
            message=f"embedding cosine {similarity:.3f}",
        )
    return CheckResult(
        name="clip_similarity",
        status="FAIL",
        detail=detail,
        message=f"embedding cosine {similarity:.3f} below {threshold}",
    )


def check_color_distance(
    *,
    candidate_path: Path,
    reference_path: Path,
    threshold: float = 80.0,
    sample_size: int = 48,
) -> CheckResult:
    """Compare downscaled Lab color signatures for candidate/reference images."""
    import numpy as np

    def lab_signature(path: Path) -> np.ndarray:
        with _open_exif_transposed_image(path) as img:
            lab = img.convert("RGB").resize((sample_size, sample_size)).convert("LAB")
        arr = np.asarray(lab, dtype=np.float32)
        return arr.reshape(-1, 3).mean(axis=0)

    cand_sig = lab_signature(candidate_path)
    ref_sig = lab_signature(reference_path)
    distance = float(np.linalg.norm(cand_sig - ref_sig))
    detail = {
        "lab_distance": round(distance, 4),
        "threshold": threshold,
        "candidate_lab_mean": [round(float(v), 3) for v in cand_sig],
        "reference_lab_mean": [round(float(v), 3) for v in ref_sig],
    }
    if distance <= threshold:
        return CheckResult(
            name="color_distance",
            status="PASS",
            detail=detail,
            message=f"Lab distance {distance:.2f}",
        )
    return CheckResult(
        name="color_distance",
        status="FAIL",
        detail=detail,
        message=f"Lab distance {distance:.2f} exceeds {threshold}",
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
    aspect_threshold: float = 0.05,
    phash_threshold: int = 12,
    dhash_threshold: int = 12,
    # Layer 3+ hooks (Phase 5c+); not implemented yet.
    enable_clip: bool = False,
    enable_vlm: bool = False,
    embedding_backend: EmbeddingBackend | None = None,
    clip_threshold: float = 0.88,
    color_threshold: float = 80.0,
) -> VerificationReport:
    """Run all enabled verification layers against an acquired master.

    Layers 1 (aspect ratio) and 2 (perceptual hash vs. reference) are wired.
    When `enable_clip` is set and image paths are supplied, Layer 3 runs an
    embedding similarity check plus a Lab color-distance guard. The VLM layer is
    still a skip-stub.
    """
    candidate_image_path = Path(candidate_path) if candidate_path is not None else None
    reference_image_path = Path(reference_path) if reference_path is not None else None

    aspect_h_px = h_px
    aspect_w_px = w_px
    aspect_result: CheckResult
    should_read_candidate_size = (
        candidate_image_path is not None
        and h_cm is not None
        and w_cm is not None
        and h_cm > 0
        and w_cm > 0
    )
    if should_read_candidate_size:
        assert candidate_image_path is not None
        try:
            with _open_exif_transposed_image(candidate_image_path) as candidate_img:
                aspect_w_px, aspect_h_px = candidate_img.size
            aspect_result = check_aspect_ratio(
                h_cm=h_cm,
                w_cm=w_cm,
                h_px=aspect_h_px,
                w_px=aspect_w_px,
                threshold=aspect_threshold,
            )
        except OSError as exc:
            aspect_result = CheckResult(
                name="aspect_ratio",
                status="FAIL",
                message=f"candidate image unavailable for EXIF-aware aspect check: {exc}",
                detail={"candidate_path": str(candidate_image_path)},
            )
    else:
        aspect_result = check_aspect_ratio(
            h_cm=h_cm,
            w_cm=w_cm,
            h_px=aspect_h_px,
            w_px=aspect_w_px,
            threshold=aspect_threshold,
        )

    report = VerificationReport()
    report.checks.append(aspect_result)

    have_paths = candidate_image_path is not None and reference_image_path is not None
    clip_result: CheckResult | None = None
    if enable_clip and have_paths:
        assert candidate_image_path is not None and reference_image_path is not None
        clip_result = check_embedding_similarity(
            candidate_path=candidate_image_path,
            reference_path=reference_image_path,
            threshold=clip_threshold,
            embedding_backend=embedding_backend,
        )

    embedding_ran = clip_result is not None and clip_result.status != "SKIP"
    if have_paths:
        assert candidate_image_path is not None and reference_image_path is not None
        report.checks.append(
            check_perceptual_hash(
                candidate_path=candidate_image_path,
                reference_path=reference_image_path,
                phash_threshold=phash_threshold,
                dhash_threshold=dhash_threshold,
                blocks_overall=not embedding_ran,
            )
        )

    if enable_clip:
        if not have_paths:
            report.checks.append(
                CheckResult(
                    name="clip_similarity",
                    status="SKIP",
                    message="candidate/reference image paths unavailable",
                )
            )
        else:
            assert (
                clip_result is not None
                and candidate_image_path is not None
                and reference_image_path is not None
            )
            report.checks.append(clip_result)
            report.checks.append(
                check_color_distance(
                    candidate_path=candidate_image_path,
                    reference_path=reference_image_path,
                    threshold=color_threshold,
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
