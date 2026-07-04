"""Tests for the identity verification gate."""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fine_art_archive.collect.verify import (  # noqa: E402
    check_aspect_ratio,
    verify,
)

# -- aspect ratio check ------------------------------------------------------


def test_aspect_passes_when_within_threshold():
    # The Little Street: 54.3 x 44 cm (cm h/w = 1.234)
    # Acquired VWEov master: 5190 x 6344 px (px h/w = 1.222)
    # Difference 0.012 → well under default threshold 0.05.
    r = check_aspect_ratio(h_cm=54.3, w_cm=44.0, h_px=6344, w_px=5190)
    assert r.status == "PASS"
    assert r.name == "aspect_ratio"
    assert r.detail["delta"] < 0.05


def test_aspect_fails_for_milkmaid_bytes_under_little_street_metadata():
    # This is the exact misdirection that caught us in the Rijksmuseum test.
    # Little Street catalogued dimensions (54.3 x 44 cm) vs. Milkmaid bytes
    # (4649 x 5177 px, aspect 1.114). Aspect ratio FAILS instantly.
    r = check_aspect_ratio(h_cm=54.3, w_cm=44.0, h_px=5177, w_px=4649)
    assert r.status == "FAIL"
    assert "aspect mismatch" in r.message
    assert r.detail["rel_delta"] > 0.05


def test_aspect_skips_when_cm_unknown():
    r = check_aspect_ratio(h_cm=None, w_cm=None, h_px=1000, w_px=1000)
    assert r.status == "SKIP"


def test_aspect_handles_zero_dimensions():
    r = check_aspect_ratio(h_cm=10.0, w_cm=10.0, h_px=0, w_px=0)
    assert r.status == "FAIL"


def test_aspect_landscape_orientation_passes():
    # Hopper's Nighthawks: 84.1 x 152.4 cm landscape → h/w = 0.552
    # Hypothetical 4000 x 7250 px → 0.552 — match.
    r = check_aspect_ratio(h_cm=84.1, w_cm=152.4, h_px=4000, w_px=7250)
    assert r.status == "PASS"


def test_aspect_tolerates_small_crop_within_threshold():
    # Catalogued 54.3 x 44 cm but scan slightly cropped to 5100 x 6250 px.
    # rel_delta should still be under 0.05.
    r = check_aspect_ratio(h_cm=54.3, w_cm=44.0, h_px=6250, w_px=5100)
    assert r.status == "PASS"
    assert r.detail["rel_delta"] < 0.05


# -- verify() composer -------------------------------------------------------


def test_verify_only_layer1_today():
    report = verify(h_cm=54.3, w_cm=44.0, h_px=6344, w_px=5190)
    assert report.overall == "PASS"
    assert len(report.checks) == 1
    assert report.checks[0].name == "aspect_ratio"


def test_verify_with_higher_layer_flags_returns_skip_placeholders():
    report = verify(
        h_cm=54.3,
        w_cm=44.0,
        h_px=6344,
        w_px=5190,
        enable_clip=True,
        enable_vlm=True,
    )
    # The aspect check passes; the higher layers are SKIP today.
    statuses = {c.name: c.status for c in report.checks}
    assert statuses["aspect_ratio"] == "PASS"
    assert statuses["clip_similarity"] == "SKIP"
    assert statuses["vlm_inconsistency_check"] == "SKIP"
    # Overall PASS because the only non-SKIP layer passed.
    assert report.overall == "PASS"


# -- Layer 2: perceptual hash -----------------------------------------------


def _synthetic_work_image(size: tuple[int, int]) -> Image.Image:
    img = Image.new("RGB", size, "#f7eed6")
    draw = ImageDraw.Draw(img)
    w, h = size
    for x in range(0, w, 12):
        shade = 80 + (x * 7) % 120
        draw.line([(x, 0), (w - x // 2, h)], fill=(shade, 90, 120), width=3)
    draw.rectangle(
        (w * 0.18, h * 0.22, w * 0.78, h * 0.82),
        outline="#2b4b5f",
        width=max(2, w // 50),
    )
    draw.ellipse(
        (w * 0.34, h * 0.28, w * 0.62, h * 0.58),
        fill="#b85c38",
        outline="#1d1d1d",
        width=2,
    )
    draw.polygon(
        [(w * 0.25, h * 0.75), (w * 0.52, h * 0.44), (w * 0.84, h * 0.76)],
        fill="#5a7455",
    )
    return img


def _synthetic_mismatch_image(size: tuple[int, int]) -> Image.Image:
    img = Image.new("RGB", size, "#18212b")
    draw = ImageDraw.Draw(img)
    w, h = size
    for y in range(0, h, 8):
        color = (220, 220, 40) if y // 8 % 2 == 0 else (40, 140, 210)
        draw.rectangle((0, y, w, y + 4), fill=color)
    for x in range(0, w, 16):
        draw.line((x, 0, w - x, h), fill=(240, 80, 80), width=2)
    draw.rectangle((w * 0.1, h * 0.1, w * 0.9, h * 0.9), outline=(255, 255, 255), width=4)
    return img


def _save_synthetic_jpeg(path: Path, image: Image.Image) -> Path:
    image.save(path, quality=92)
    return path


def _save_exif_rotated_jpeg(path: Path, upright: Image.Image) -> Path:
    exif = Image.Exif()
    exif[274] = 6
    stored_landscape = upright.transpose(Image.Transpose.ROTATE_90)
    stored_landscape.save(path, quality=92, exif=exif)
    return path


def test_generated_image_perceptual_hash_passes_for_same_work_at_different_sizes(tmp_path):
    from fine_art_archive.collect.verify import check_perceptual_hash

    reference = _save_synthetic_jpeg(tmp_path / "reference.jpg", _synthetic_work_image((128, 160)))
    candidate = _save_synthetic_jpeg(tmp_path / "candidate.jpg", _synthetic_work_image((256, 320)))

    result = check_perceptual_hash(candidate_path=candidate, reference_path=reference)

    assert result.status == "PASS"
    assert result.detail["phash_distance"] <= 12
    assert result.detail["dhash_distance"] <= 12
    assert result.detail["candidate_size"] == [256, 320]
    assert result.detail["reference_size"] == [128, 160]


def test_generated_image_perceptual_hash_fails_for_different_work_with_same_aspect(tmp_path):
    from fine_art_archive.collect.verify import check_perceptual_hash

    reference = _save_synthetic_jpeg(tmp_path / "reference.jpg", _synthetic_work_image((128, 160)))
    candidate = _save_synthetic_jpeg(
        tmp_path / "candidate.jpg", _synthetic_mismatch_image((256, 320))
    )

    result = check_perceptual_hash(candidate_path=candidate, reference_path=reference)

    assert result.status == "FAIL"
    assert result.detail["phash_distance"] > 12
    assert result.detail["dhash_distance"] > 12
    assert "both hashes over threshold" in result.message


def test_generated_image_verify_layer2_passes_when_aspect_and_hash_match(tmp_path):
    reference = _save_synthetic_jpeg(tmp_path / "reference.jpg", _synthetic_work_image((128, 160)))
    candidate = _save_synthetic_jpeg(tmp_path / "candidate.jpg", _synthetic_work_image((256, 320)))

    report = verify(
        h_cm=20.0,
        w_cm=16.0,
        h_px=320,
        w_px=256,
        candidate_path=candidate,
        reference_path=reference,
    )

    statuses = {c.name: c.status for c in report.checks}
    assert report.overall == "PASS"
    assert statuses["aspect_ratio"] == "PASS"
    assert statuses["perceptual_hash"] == "PASS"


def test_generated_image_verify_layer2_fails_when_hash_mismatches_despite_matching_aspect(tmp_path):
    reference = _save_synthetic_jpeg(tmp_path / "reference.jpg", _synthetic_work_image((128, 160)))
    candidate = _save_synthetic_jpeg(
        tmp_path / "candidate.jpg", _synthetic_mismatch_image((256, 320))
    )

    report = verify(
        h_cm=20.0,
        w_cm=16.0,
        h_px=320,
        w_px=256,
        candidate_path=candidate,
        reference_path=reference,
    )

    statuses = {c.name: c.status for c in report.checks}
    assert report.overall == "FAIL"
    assert statuses["aspect_ratio"] == "PASS"
    assert statuses["perceptual_hash"] == "FAIL"


def test_perceptual_hash_passes_on_real_vermeer_match():
    """Calibration test against the Vermeer Little Street sample.

    Master: 5190x6344 px from Rijksmuseum Micrio VWEov.
    Reference: 1280x1585 px from Wikidata P18 → Commons.
    Expected pHash distance: 2 (well under threshold 12).
    """
    from fine_art_archive.collect.verify import check_perceptual_hash

    base = Path(__file__).resolve().parents[1]
    sample = base / "samples" / "0441b1c-the-little-street-vermeer"
    if not (sample / "master.jpg").exists():
        import pytest

        pytest.skip("sample master.jpg not present")
    r = check_perceptual_hash(
        candidate_path=sample / "master.jpg",
        reference_path=sample / "resources" / "reference_Q586035.jpg",
    )
    assert r.status == "PASS"
    assert r.detail["phash_distance"] <= 4
    assert r.detail["dhash_distance"] <= 4


def test_perceptual_hash_fails_on_milkmaid_substitution():
    """The negative case: Milkmaid bytes (QkOGy) compared to Little Street
    reference. Expected pHash distance: ~28, well above threshold 12.
    """
    from fine_art_archive.collect.verify import check_perceptual_hash

    base = Path(__file__).resolve().parents[1]
    sample = base / "samples" / "0441b1c-the-little-street-vermeer"
    neg = sample / "resources" / "_negative_qkogy_milkmaid.jpg"
    ref = sample / "resources" / "reference_Q586035.jpg"
    if not neg.exists() or not ref.exists():
        import pytest

        pytest.skip("calibration fixtures not present")
    r = check_perceptual_hash(
        candidate_path=neg,
        reference_path=ref,
    )
    assert r.status == "FAIL"
    assert r.detail["phash_distance"] >= 20
    assert r.detail["dhash_distance"] >= 20


def test_verify_layer2_overall_pass_when_both_layers_pass():
    """End-to-end: Vermeer master + Wikidata reference, aspect + pHash both PASS."""
    base = Path(__file__).resolve().parents[1]
    sample = base / "samples" / "0441b1c-the-little-street-vermeer"
    if not (sample / "master.jpg").exists():
        import pytest

        pytest.skip("sample master.jpg not present")
    report = verify(
        h_cm=54.3,
        w_cm=44.0,
        h_px=6344,
        w_px=5190,
        candidate_path=sample / "master.jpg",
        reference_path=sample / "resources" / "reference_Q586035.jpg",
    )
    assert report.overall == "PASS"
    statuses = {c.name: c.status for c in report.checks}
    assert statuses["aspect_ratio"] == "PASS"
    assert statuses["perceptual_hash"] == "PASS"


def test_verify_applies_exif_orientation_before_aspect_and_hash_checks(tmp_path):
    upright = _synthetic_work_image((80, 120))
    reference = _save_synthetic_jpeg(tmp_path / "reference.jpg", upright)
    candidate = _save_exif_rotated_jpeg(tmp_path / "candidate.jpg", upright)

    raw_aspect = check_aspect_ratio(h_cm=30.0, w_cm=20.0, h_px=80, w_px=120)
    report = verify(
        h_cm=30.0,
        w_cm=20.0,
        h_px=80,
        w_px=120,
        candidate_path=candidate,
        reference_path=reference,
    )

    statuses = {c.name: c.status for c in report.checks}
    hash_check = next(c for c in report.checks if c.name == "perceptual_hash")
    assert raw_aspect.status == "FAIL"
    assert report.overall == "PASS"
    assert statuses["aspect_ratio"] == "PASS"
    assert statuses["perceptual_hash"] == "PASS"
    assert hash_check.detail["candidate_size"] == [80, 120]
    assert hash_check.detail["reference_size"] == [80, 120]


def test_verify_layer2_catches_milkmaid_under_little_street_metadata():
    """The full motivating bug: Milkmaid bytes filed under Little Street
    metadata. Both layers FAIL — Layer 1 catches aspect, Layer 2 catches
    the visual identity. Either is a hard fail."""
    base = Path(__file__).resolve().parents[1]
    sample = base / "samples" / "0441b1c-the-little-street-vermeer"
    neg = sample / "resources" / "_negative_qkogy_milkmaid.jpg"
    ref = sample / "resources" / "reference_Q586035.jpg"
    if not (neg.exists() and ref.exists()):
        import pytest

        pytest.skip("calibration fixtures not present")
    # Milkmaid bytes are 4649 x 5177 px; Little Street catalogued 54.3 x 44 cm.
    report = verify(
        h_cm=54.3,
        w_cm=44.0,
        h_px=5177,
        w_px=4649,
        candidate_path=neg,
        reference_path=ref,
    )
    assert report.overall == "FAIL"
    statuses = {c.name: c.status for c in report.checks}
    assert statuses["aspect_ratio"] == "FAIL"
    assert statuses["perceptual_hash"] == "FAIL"


def test_verify_fails_overall_on_aspect_mismatch_even_when_higher_layers_skipped():
    report = verify(
        h_cm=54.3,
        w_cm=44.0,
        h_px=5177,
        w_px=4649,  # Milkmaid-as-Little-Street
        enable_clip=True,
    )
    assert report.overall == "FAIL"
