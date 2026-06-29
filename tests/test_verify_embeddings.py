"""Embedding and color legs for the identity verification gate."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fine_art_archive.collect.verify import (  # noqa: E402
    check_color_distance,
    check_embedding_similarity,
    check_perceptual_hash,
    verify,
)


def _save(path: Path, image: Image.Image) -> Path:
    image.save(path, quality=95)
    return path


def _reference_work(size: tuple[int, int] = (180, 180)) -> Image.Image:
    image = Image.new("RGB", size, (242, 238, 224))
    draw = ImageDraw.Draw(image)
    w, h = size
    draw.rectangle((w * 0.12, h * 0.18, w * 0.88, h * 0.84), fill=(210, 173, 112))
    draw.ellipse((w * 0.25, h * 0.22, w * 0.68, h * 0.62), fill=(28, 73, 124))
    draw.rectangle((w * 0.44, h * 0.50, w * 0.76, h * 0.78), fill=(146, 58, 48))
    draw.line((w * 0.10, h * 0.86, w * 0.90, h * 0.14), fill=(24, 30, 38), width=5)
    return image


def _different_work(size: tuple[int, int] = (180, 180)) -> Image.Image:
    image = Image.new("RGB", size, (238, 240, 225))
    draw = ImageDraw.Draw(image)
    w, h = size
    draw.rectangle((w * 0.06, h * 0.06, w * 0.26, h * 0.26), fill=(40, 120, 75))
    draw.rectangle((w * 0.72, h * 0.70, w * 0.92, h * 0.92), fill=(190, 70, 170))
    return image


def _crop_and_reframe(image: Image.Image) -> Image.Image:
    cropped = image.crop((24, 12, 168, 156)).resize(image.size)
    overlay = Image.new("RGB", cropped.size, (252, 244, 224))
    return Image.blend(cropped, overlay, 0.08)


def _wrong_color_copy(image: Image.Image) -> Image.Image:
    arr = np.asarray(image.convert("RGB"), dtype=np.uint8).copy()
    mask = np.any(arr < 235, axis=2)
    arr[mask] = np.stack(
        [
            255 - arr[mask, 0],
            np.clip(arr[mask, 1] // 3, 0, 255),
            np.clip(arr[mask, 2] + 90, 0, 255),
        ],
        axis=1,
    )
    return Image.fromarray(arr, "RGB")


def _shape_embedding(image: object) -> list[float]:
    arr = np.asarray(image.convert("RGB").resize((32, 32)), dtype=np.int16)
    background = arr[0, 0]
    mask = (np.abs(arr - background).sum(axis=2) > 35).astype(np.float32)
    features: list[float] = []
    for y in range(0, 32, 8):
        for x in range(0, 32, 8):
            features.append(float(mask[y : y + 8, x : x + 8].mean()))
    return features


def test_embedding_leg_passes_cropped_reframed_work_when_phash_fails(tmp_path):
    reference = _save(tmp_path / "reference.jpg", _reference_work())
    candidate = _save(tmp_path / "candidate.jpg", _crop_and_reframe(_reference_work()))

    phash = check_perceptual_hash(
        candidate_path=candidate,
        reference_path=reference,
        phash_threshold=2,
        dhash_threshold=2,
    )
    assert phash.status == "FAIL"

    report = verify(
        h_cm=20.0,
        w_cm=20.0,
        h_px=180,
        w_px=180,
        candidate_path=candidate,
        reference_path=reference,
        phash_threshold=2,
        dhash_threshold=2,
        enable_clip=True,
        embedding_backend=_shape_embedding,
        clip_threshold=0.80,
    )

    statuses = {check.name: check.status for check in report.checks}
    assert report.overall == "PASS"
    assert statuses["perceptual_hash"] == "FAIL"
    assert statuses["clip_similarity"] == "PASS"
    assert statuses["color_distance"] == "PASS"


def test_embedding_leg_fails_different_artwork(tmp_path):
    reference = _save(tmp_path / "reference.jpg", _reference_work())
    candidate = _save(tmp_path / "different.jpg", _different_work())

    result = check_embedding_similarity(
        candidate_path=candidate,
        reference_path=reference,
        threshold=0.80,
        embedding_backend=_shape_embedding,
    )

    assert result.status == "FAIL"
    assert result.detail["cosine_similarity"] < 0.80


def test_color_check_flags_color_wrong_copy_even_when_embedding_matches(tmp_path):
    reference = _save(tmp_path / "reference.jpg", _reference_work())
    candidate = _save(tmp_path / "wrong-color.jpg", _wrong_color_copy(_reference_work()))

    report = verify(
        h_cm=20.0,
        w_cm=20.0,
        h_px=180,
        w_px=180,
        candidate_path=candidate,
        reference_path=reference,
        enable_clip=True,
        embedding_backend=_shape_embedding,
        clip_threshold=0.80,
    )

    statuses = {check.name: check.status for check in report.checks}
    assert report.overall == "FAIL"
    assert statuses["clip_similarity"] == "PASS"
    assert statuses["color_distance"] == "FAIL"

    color = check_color_distance(candidate_path=candidate, reference_path=reference)
    assert color.status == "FAIL"


def test_embedding_model_absent_skips_without_crashing(tmp_path, monkeypatch):
    reference = _save(tmp_path / "reference.jpg", _reference_work())
    candidate = _save(tmp_path / "candidate.jpg", _reference_work())

    def missing_backend():
        raise ImportError("open_clip")

    monkeypatch.setattr("fine_art_archive.collect.verify._load_open_clip_backend", missing_backend)

    report = verify(
        h_cm=20.0,
        w_cm=20.0,
        h_px=180,
        w_px=180,
        candidate_path=candidate,
        reference_path=reference,
        enable_clip=True,
    )

    statuses = {check.name: check.status for check in report.checks}
    assert statuses["clip_similarity"] == "SKIP"
    assert statuses["color_distance"] == "PASS"
